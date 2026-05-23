// SPDX-License-Identifier: MIT
// Copyright (c) 2026 eunomia-bpf org.
//! Taint engine: provenance state, fixed propagation, and rule evaluation over
//! an event trace (docs/taint-dsl.md §1, §5). This is the userspace reference
//! implementation of the DSL semantics; the in-kernel POC (bpf/) is its
//! Process/exec/open special case.

use super::ast::*;
use std::collections::{HashMap, HashSet};

/// Glob match where `*`/`**` both match any run of characters (`**` collapses
/// to `*`). Sufficient for the path/host/exe patterns in the DSL.
pub fn glob_match(pat: &str, text: &str) -> bool {
    let p: Vec<char> = pat.chars().collect();
    let t: Vec<char> = text.chars().collect();
    let (mut pi, mut ti) = (0usize, 0usize);
    let (mut star, mut mark) = (None, 0usize);
    while ti < t.len() {
        if pi < p.len() && (p[pi] == '?' || p[pi] == t[ti]) {
            pi += 1;
            ti += 1;
        } else if pi < p.len() && p[pi] == '*' {
            while pi < p.len() && p[pi] == '*' {
                pi += 1;
            }
            if pi == p.len() {
                return true;
            }
            star = Some(pi);
            mark = ti;
        } else if let Some(sp) = star {
            pi = sp;
            mark += 1;
            ti = mark;
        } else {
            return false;
        }
    }
    while pi < p.len() && p[pi] == '*' {
        pi += 1;
    }
    pi == p.len()
}

/// One observed operation. Subject is always a process (pid).
#[derive(Debug, Clone)]
pub enum Event {
    Fork { ppid: u32, pid: u32 },
    Exec { pid: u32, exe: String, args: Vec<String> },
    Read { pid: u32, path: String },
    Write { pid: u32, path: String },
    Unlink { pid: u32, path: String },
    Connect { pid: u32, host: String },
    Recv { pid: u32, host: String },
}

#[derive(Debug, Clone, PartialEq)]
pub struct Violation {
    pub rule: String,
    pub reason: String,
    pub pid: u32,
    pub op: Op,
    pub target: String,
}

pub struct Engine<'a> {
    pol: &'a Policy,
    proc: HashMap<u32, HashSet<String>>,    // pid -> labels
    file: HashMap<String, HashSet<String>>, // path -> labels
    endp: HashMap<String, HashSet<String>>, // host -> labels
    lin_gates: HashMap<u32, HashSet<String>>, // pid -> gate patterns in ANCESTOR chain (incl self)
    sess_gates: HashMap<u32, HashSet<String>>, // root pid -> gate patterns anywhere in subtree
    root: HashMap<u32, u32>,                // pid -> session root
    gate_pats: Vec<String>,                 // all exec-gate patterns referenced by conds
}

impl<'a> Engine<'a> {
    pub fn new(pol: &'a Policy) -> Self {
        let mut gate_pats = Vec::new();
        for r in &pol.rules {
            for c in &r.clauses {
                if let Some(cond) = &c.unless {
                    match cond {
                        Cond::LineageIncludes { exec } | Cond::After { exec } => {
                            gate_pats.push(exec.clone())
                        }
                        Cond::Target { .. } => {}
                    }
                }
            }
        }
        Engine {
            pol,
            proc: HashMap::new(),
            file: HashMap::new(),
            endp: HashMap::new(),
            lin_gates: HashMap::new(),
            sess_gates: HashMap::new(),
            root: HashMap::new(),
            gate_pats,
        }
    }

    pub fn run(pol: &'a Policy, trace: &[Event]) -> Vec<Violation> {
        let mut e = Engine::new(pol);
        let mut v = Vec::new();
        for ev in trace {
            e.step(ev, &mut v);
        }
        v
    }

    fn root_of(&self, pid: u32) -> u32 {
        self.root.get(&pid).copied().unwrap_or(pid)
    }

    fn intrinsic(&self, kind: Kind, ident: &str) -> HashSet<String> {
        let mut s = HashSet::new();
        for src in &self.pol.sources {
            if src.kind == kind && glob_match(&src.pattern, ident) {
                s.insert(src.label.clone());
            }
        }
        s
    }

    fn step(&mut self, ev: &Event, out: &mut Vec<Violation>) {
        match ev {
            Event::Fork { ppid, pid } => {
                let r = self.root_of(*ppid);
                self.root.insert(*pid, r);
                let pl = self.proc.get(ppid).cloned().unwrap_or_default();
                self.proc.entry(*pid).or_default().extend(pl);
                let pg = self.lin_gates.get(ppid).cloned().unwrap_or_default();
                self.lin_gates.entry(*pid).or_default().extend(pg);
            }
            Event::Exec { pid, exe, args } => {
                // exec(p,f): σ(p) ∪= σ(f) ∪ srcExec(f)
                let mut add = self.intrinsic(Kind::File, exe); // exe's intrinsic file labels
                add.extend(self.file.get(exe).cloned().unwrap_or_default());
                add.extend(self.intrinsic(Kind::Exec, exe)); // exec sources
                self.proc.entry(*pid).or_default().extend(add);
                // declassify / endorse on gate exec
                for x in &self.pol.xforms {
                    if glob_match(&x.gate, exe) {
                        let s = self.proc.entry(*pid).or_default();
                        if x.endorse {
                            s.insert(x.label.clone());
                        } else {
                            s.remove(&x.label);
                        }
                    }
                }
                // record lineage + session gates
                for gp in &self.gate_pats {
                    if glob_match(gp, exe) {
                        self.lin_gates.entry(*pid).or_default().insert(gp.clone());
                        let r = self.root_of(*pid);
                        self.sess_gates.entry(r).or_default().insert(gp.clone());
                    }
                }
                self.check(*pid, Op::Exec, Kind::Exec, exe, args, out);
            }
            Event::Read { pid, path } => {
                let mut add = self.intrinsic(Kind::File, path);
                add.extend(self.file.get(path).cloned().unwrap_or_default());
                self.proc.entry(*pid).or_default().extend(add);
                self.check(*pid, Op::Read, Kind::File, path, &[], out);
            }
            Event::Write { pid, path } => {
                let pl = self.proc.get(pid).cloned().unwrap_or_default();
                self.file.entry(path.clone()).or_default().extend(pl);
                self.check(*pid, Op::Write, Kind::File, path, &[], out);
            }
            Event::Unlink { pid, path } => {
                self.check(*pid, Op::Unlink, Kind::File, path, &[], out);
            }
            Event::Connect { pid, host } => {
                let pl = self.proc.get(pid).cloned().unwrap_or_default();
                self.endp.entry(host.clone()).or_default().extend(pl);
                self.check(*pid, Op::Connect, Kind::Endpoint, host, &[], out);
            }
            Event::Recv { pid, host } => {
                let mut add = self.intrinsic(Kind::Endpoint, host);
                add.extend(self.endp.get(host).cloned().unwrap_or_default());
                self.proc.entry(*pid).or_default().extend(add);
                self.check(*pid, Op::Recv, Kind::Endpoint, host, &[], out);
            }
        }
    }

    fn op_matches(clause: Op, ev: Op) -> bool {
        clause == ev || (clause == Op::Open && (ev == Op::Read || ev == Op::Write))
    }

    fn eval(&self, e: &Expr, labels: &HashSet<String>) -> bool {
        match e {
            Expr::True => true,
            Expr::Label(l) => labels.contains(l),
            Expr::Not(l) => !labels.contains(l),
            Expr::And(a, b) => self.eval(a, labels) && self.eval(b, labels),
            Expr::Or(a, b) => self.eval(a, labels) || self.eval(b, labels),
        }
    }

    /// Returns true if the `unless` condition is satisfied (i.e. the op is allowed).
    fn cond_ok(&self, cond: &Cond, subject: u32, obj: &str) -> bool {
        match cond {
            Cond::Target { negate, pattern } => {
                let m = glob_match(pattern, obj);
                if *negate {
                    !m
                } else {
                    m
                }
            }
            Cond::LineageIncludes { exec } => self
                .lin_gates
                .get(&subject)
                .map(|g| g.contains(exec))
                .unwrap_or(false),
            Cond::After { exec } => self
                .sess_gates
                .get(&self.root_of(subject))
                .map(|g| g.contains(exec))
                .unwrap_or(false),
        }
    }

    fn check(&self, pid: u32, op: Op, kind: Kind, obj: &str, args: &[String], out: &mut Vec<Violation>) {
        let labels = self.proc.get(&pid).cloned().unwrap_or_default();
        for rule in &self.pol.rules {
            for c in &rule.clauses {
                if !Self::op_matches(c.op, op) {
                    continue;
                }
                if c.target.kind != kind {
                    continue;
                }
                if !glob_match(&c.target.pattern, obj) {
                    continue;
                }
                if let Some(a) = &c.target.arg {
                    if !args.iter().any(|x| x == a) {
                        continue;
                    }
                }
                if !self.eval(&c.when, &labels) {
                    continue;
                }
                if let Some(cond) = &c.unless {
                    if self.cond_ok(cond, pid, obj) {
                        continue; // allowed by escape condition
                    }
                }
                out.push(Violation {
                    rule: rule.name.clone(),
                    reason: rule.reason.clone(),
                    pid,
                    op,
                    target: obj.to_string(),
                });
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::dsl::parse::parse;

    // helpers
    fn ex(pid: u32, exe: &str, args: &[&str]) -> Event {
        Event::Exec { pid, exe: exe.into(), args: args.iter().map(|s| s.to_string()).collect() }
    }
    fn fork(ppid: u32, pid: u32) -> Event { Event::Fork { ppid, pid } }
    fn rd(pid: u32, p: &str) -> Event { Event::Read { pid, path: p.into() } }
    fn wr(pid: u32, p: &str) -> Event { Event::Write { pid, path: p.into() } }
    fn un(pid: u32, p: &str) -> Event { Event::Unlink { pid, path: p.into() } }
    fn cn(pid: u32, h: &str) -> Event { Event::Connect { pid, host: h.into() } }
    fn rv(pid: u32, h: &str) -> Event { Event::Recv { pid, host: h.into() } }

    fn names(v: &[Violation]) -> Vec<String> { v.iter().map(|x| x.rule.clone()).collect() }
    fn run(src: &str, trace: &[Event]) -> Vec<Violation> {
        Engine::run(&parse(src).expect("parse"), trace)
    }

    const E1: &str = r#"
        source SECRET = file "**/.env"
        source SECRET = file "/etc/secrets/**"
        rule no-exfil:
          deny connect endpoint "*"      if SECRET
          deny write   file "/shared/**" if SECRET
          reason "secret data must not leave the host; redact first"
        declassify SECRET by exec "**/redact"
    "#;

    #[test]
    fn e1_secret_no_exfil() {
        // reads .env then connects -> violation; benign reader does not
        let v = run(E1, &[rd(1, "/app/.env"), cn(1, "api.x.com")]);
        assert_eq!(names(&v), vec!["no-exfil"]);
        // writing to /shared after reading a secret also violates
        let v = run(E1, &[rd(1, "/etc/secrets/k"), wr(1, "/shared/o")]);
        assert_eq!(names(&v), vec!["no-exfil"]);
        // a process that never touched a secret may connect
        let v = run(E1, &[rd(1, "/app/readme"), cn(1, "api.x.com")]);
        assert!(v.is_empty());
    }

    #[test]
    fn e2_prompt_injection_no_priv() {
        let src = r#"
            source UNTRUST = endpoint "*"
            source UNTRUST = file "**/downloads/**"
            rule no-injected-priv:
              deny exec "**/git" @arg "push" if UNTRUST and not REVIEWED
              deny exec "**/deploy*"         if UNTRUST and not REVIEWED
              reason "action derived from untrusted input; needs human review"
            endorse REVIEWED by exec "**/human-approve"
        "#;
        // recv from net taints; git push -> violation
        let v = run(src, &[rv(1, "evil.com"), ex(1, "/usr/bin/git", &["git", "push"])]);
        assert_eq!(names(&v), vec!["no-injected-priv"]);
        // after human-approve endorsement, allowed
        let v = run(
            src,
            &[rv(1, "evil.com"), ex(1, "/opt/human-approve", &["human-approve"]), ex(1, "/usr/bin/git", &["git", "push"])],
        );
        assert!(v.is_empty());
    }

    #[test]
    fn e3_mandatory_mediation() {
        let src = r#"
            rule mediate-proddb:
              deny open file "**/prod.db" unless lineage-includes exec "**/migrate"
              reason "prod.db is reachable only through the migration tool"
        "#;
        // agent opens prod.db directly -> violation
        let v = run(src, &[ex(1, "/bin/codex", &["codex"]), rd(1, "/db/prod.db")]);
        assert_eq!(names(&v), vec!["mediate-proddb"]);
        // the migrate tool (execs migrate, then opens) is allowed
        let v = run(src, &[ex(2, "/bin/migrate", &["migrate"]), rd(2, "/db/prod.db")]);
        assert!(v.is_empty());
    }

    #[test]
    fn e4_workspace_confinement() {
        let src = r#"
            source AGENT = exec "**/codex"
            rule confine-writes:
              deny write  file "/**" if AGENT unless target "/work/**"
              deny unlink file "/**" if AGENT unless target "/work/**"
              reason "agent may only modify its workspace /work/**"
        "#;
        let v = run(src, &[ex(1, "/bin/codex", &["codex"]), wr(1, "/etc/passwd")]);
        assert_eq!(names(&v), vec!["confine-writes"]);
        let v = run(src, &[ex(1, "/bin/codex", &["codex"]), wr(1, "/work/t/f"), un(1, "/work/t/f")]);
        assert!(v.is_empty());
        // unlink outside workspace also caught
        let v = run(src, &[ex(1, "/bin/codex", &["codex"]), un(1, "/data/x")]);
        assert_eq!(names(&v), vec!["confine-writes"]);
    }

    #[test]
    fn e5_test_before_commit() {
        let src = r#"
            source AGENT = exec "**/codex"
            rule test-before-commit:
              deny exec "**/git" @arg "commit" if AGENT unless after exec "**/pytest"
              reason "run the test suite before committing"
        "#;
        // agent forks a git child and commits without testing -> violation
        let t = [ex(1, "/bin/codex", &["codex"]), fork(1, 2), ex(2, "/usr/bin/git", &["git", "commit"])];
        assert_eq!(names(&run(src, &t)), vec!["test-before-commit"]);
        // agent ran pytest (a child) earlier in the session -> commit allowed
        let t = [
            ex(1, "/bin/codex", &["codex"]),
            fork(1, 2),
            ex(2, "/usr/bin/pytest", &["pytest"]),
            fork(1, 3),
            ex(3, "/usr/bin/git", &["git", "commit"]),
        ];
        assert!(run(src, &t).is_empty());
    }

    #[test]
    fn e6_research_readonly() {
        let src = r#"
            source RESEARCH = exec "**/research-agent"
            rule research-readonly:
              deny write   file "/**"   if RESEARCH
              deny connect endpoint "*" if RESEARCH
              deny exec    "**/git"     if RESEARCH
              reason "research sub-agent is read-only"
        "#;
        // descendant of research-agent inherits RESEARCH and is fully read-only
        let t = [
            ex(1, "/bin/research-agent", &["research-agent"]),
            fork(1, 2),
            wr(2, "/tmp/x"),
            cn(2, "api"),
            ex(2, "/usr/bin/git", &["git", "status"]),
        ];
        assert_eq!(names(&run(src, &t)), vec!["research-readonly", "research-readonly", "research-readonly"]);
    }

    #[test]
    fn e7_transitive_secret_derivation() {
        // A reads secret, writes /tmp/out.json (file becomes SECRET);
        // B reads out.json (B becomes SECRET), then connect -> violation, though
        // B never touched .env.
        let t = [
            rd(1, "/app/.env"),
            wr(1, "/tmp/out.json"),
            rd(2, "/tmp/out.json"),
            cn(2, "exfil.com"),
        ];
        let v = run(E1, &t);
        assert_eq!(names(&v), vec!["no-exfil"]);
        assert_eq!(v[0].pid, 2); // the *uploader* is caught
    }

    #[test]
    fn e8_declassification() {
        // send WITHOUT redact -> blocked; redact in lineage clears SECRET -> allowed
        let blocked = run(E1, &[rd(1, "/app/.env"), cn(1, "mail.x")]);
        assert_eq!(names(&blocked), vec!["no-exfil"]);
        let allowed = run(E1, &[rd(1, "/app/.env"), ex(1, "/opt/redact", &["redact"]), cn(1, "mail.x")]);
        assert!(allowed.is_empty());
    }

    #[test]
    fn e9_cross_tool_unbypassable() {
        let src = r#"
            source AGENT = exec "**/codex"
            rule no-git:
              deny exec "**/git" if AGENT
              reason "this agent must not invoke git on any path"
        "#;
        // (a) via the git tool directly (agent execs git)
        let a = [ex(1, "/bin/codex", &["codex"]), fork(1, 2), ex(2, "/usr/bin/git", &["git", "log"])];
        // (b) via bash -c 'git ...'
        let b = [
            ex(1, "/bin/codex", &["codex"]),
            fork(1, 2),
            ex(2, "/bin/bash", &["bash", "-c", "git log"]),
            fork(2, 3),
            ex(3, "/usr/bin/git", &["git", "log"]),
        ];
        // (c) via python subprocess
        let c = [
            ex(1, "/bin/codex", &["codex"]),
            fork(1, 2),
            ex(2, "/usr/bin/python3", &["python3", "-c", "..."]),
            fork(2, 3),
            ex(3, "/usr/bin/git", &["git", "log"]),
        ];
        for t in [a.as_slice(), b.as_slice(), c.as_slice()] {
            assert_eq!(names(&run(src, t)), vec!["no-git"], "all three paths must be caught");
        }
    }

    #[test]
    fn e10_pii_egress_allowlist() {
        let src = r#"
            source PII = file "/data/customers/**"
            rule pii-egress:
              deny connect endpoint "*" if PII unless target "*.internal"
              reason "PII-handling process may only reach *.internal"
        "#;
        // after reading PII, external host blocked, internal allowed
        let v = run(src, &[rd(1, "/data/customers/c1"), cn(1, "api.evil.com")]);
        assert_eq!(names(&v), vec!["pii-egress"]);
        let v = run(src, &[rd(1, "/data/customers/c1"), cn(1, "db.internal")]);
        assert!(v.is_empty());
    }

    #[test]
    fn e11_destructive_needs_confirm() {
        let src = r#"
            source AGENT = exec "**/codex"
            rule confirm-destructive:
              deny exec "**/git" @arg "--force" if AGENT unless after exec "**/confirm"
              deny unlink file "/data/**"        if AGENT unless after exec "**/confirm"
              reason "destructive action needs an explicit confirm step"
        "#;
        let t = [ex(1, "/bin/codex", &["codex"]), fork(1, 2), ex(2, "/usr/bin/git", &["git", "push", "--force"])];
        assert_eq!(names(&run(src, &t)), vec!["confirm-destructive"]);
        let t = [
            ex(1, "/bin/codex", &["codex"]),
            fork(1, 2),
            ex(2, "/opt/confirm", &["confirm"]),
            fork(1, 3),
            ex(3, "/usr/bin/git", &["git", "push", "--force"]),
        ];
        assert!(run(src, &t).is_empty());
    }

    #[test]
    fn e12_task_non_interference() {
        let src = r#"
            source TASK_A = exec "**/task-a"
            source TASK_B = exec "**/task-b"
            rule no-cross-task-commit:
              deny exec "**/git" @arg "commit" if TASK_A and TASK_B
              reason "a commit must not mix data from task A and task B"
        "#;
        // a process tainted by both tasks committing -> violation
        let t = [
            ex(1, "/bin/task-a", &["task-a"]),
            rd(1, "/x"),                 // (carries TASK_A)
            ex(1, "/bin/task-b", &["task-b"]), // now also TASK_B (exec adds)
            ex(1, "/usr/bin/git", &["git", "commit"]),
        ];
        assert_eq!(names(&run(src, &t)), vec!["no-cross-task-commit"]);
        // a process with only one task label is fine
        let t = [ex(1, "/bin/task-a", &["task-a"]), ex(1, "/usr/bin/git", &["git", "commit"])];
        assert!(run(src, &t).is_empty());
    }

    #[test]
    fn glob_basics() {
        assert!(glob_match("**/git", "/usr/bin/git"));
        assert!(glob_match("/work/**", "/work/a/b"));
        assert!(!glob_match("/work/**", "/etc/x"));
        assert!(glob_match("*.internal", "db.internal"));
        assert!(!glob_match("*.internal", "evil.com"));
        assert!(glob_match("*", "anything"));
    }
}
