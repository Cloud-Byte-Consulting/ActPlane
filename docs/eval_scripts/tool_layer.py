#!/usr/bin/env python3
"""Tool-call-layer baselines for ActPlane evaluation.

Three modes (--mode):
  per-call   : stateless per-call pattern matching (AgentSpec/Progent)
  sequence   : sliding-window temporal awareness (sequence-aware AgentSpec)
  ifc        : label tracking across tool calls (FIDES/CaMeL)
"""
import argparse, json, re, sys, yaml
from dataclasses import dataclass, field
from typing import Optional

# -- DSL AST ---------------------------------------------------------------
@dataclass
class Source:
    label: str; kind: str; pattern: str  # kind: exec|file
@dataclass
class SinceClause:
    events: list  # [(op, pattern), ...]
@dataclass
class Condition:
    kind: str  # after | target | target_not
    exec_pattern: str = ""; since: Optional[SinceClause] = None
    target_pattern: str = ""
@dataclass
class Clause:
    effect: str; op: str; target: str; args: list
    label_expr: str; condition: Optional[Condition] = None
@dataclass
class Rule:
    name: str; clauses: list; because: str = ""
@dataclass
class Policy:
    sources: list; rules: list

# -- DSL Parser -------------------------------------------------------------
_Q = re.compile(r'"([^"]*)"')

def parse_dsl(text: str) -> Policy:
    sources, rules = [], []
    lines = [l.rstrip() for l in text.splitlines()]
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith('#'):
            i += 1; continue
        m = re.match(r'source\s+(\w+)\s*=\s*(exec|file|endpoint)\s+"([^"]*)"', line)
        if m:
            sources.append(Source(m[1], m[2], m[3])); i += 1; continue
        m = re.match(r'rule\s+([\w-]+)\s*:', line)
        if m:
            name, clauses, because = m[1], [], ""
            i += 1
            while i < len(lines):
                cl = lines[i].strip()
                if not cl or cl.startswith('#'):
                    i += 1; continue
                if cl.startswith('because '):
                    qs = _Q.findall(cl); because = qs[0] if qs else ""
                    i += 1; continue
                cm = re.match(r'(kill|block|notify)\s+(exec|write|unlink|connect|open)\s+', cl)
                if not cm: break
                effect, op = cm[1], cm[2]
                rest = cl[cm.end():]
                if rest.startswith('file '): rest = rest[5:]
                all_q = _Q.findall(rest); tgt = all_q[0] if all_q else ""
                if_idx = rest.find(' if ')
                if if_idx >= 0:
                    args = _Q.findall(rest[:if_idx])[1:]
                    after_if = rest[if_idx+4:]
                    ui = after_if.find(' unless ')
                    if ui >= 0:
                        lbl, cond_t = after_if[:ui].strip(), after_if[ui+8:].strip()
                    else:
                        lbl, cond_t = after_if.strip(), ""
                else:
                    args, lbl, cond_t = (all_q[1:] if len(all_q)>1 else []), "", ""
                cond = _parse_cond(cond_t) if cond_t else None
                clauses.append(Clause(effect, op, tgt, args, lbl, cond))
                i += 1; continue
            rules.append(Rule(name, clauses, because)); continue
        i += 1
    return Policy(sources, rules)

def _parse_cond(t: str) -> Condition:
    m = re.match(r'after\s+exec\s+"([^"]*)"', t)
    if m:
        ep = m[1]; since = None
        si = t.find(' since ')
        if si >= 0:
            evts = []
            for p in re.split(r'\s+or\s+', t[si+7:]):
                pm = re.match(r'(write|exec|read)\s+"([^"]*)"', p.strip())
                if pm: evts.append((pm[1], pm[2]))
            since = SinceClause(evts)
        return Condition("after", exec_pattern=ep, since=since)
    m = re.match(r'target\s+not\s+"([^"]*)"', t)
    if m: return Condition("target_not", target_pattern=m[1])
    m = re.match(r'target\s+"([^"]*)"', t)
    if m: return Condition("target", target_pattern=m[1])
    return Condition("target", target_pattern=t.strip('"'))

# -- Glob matching ----------------------------------------------------------
def glob_match(pat: str, val: str) -> bool:
    if not val: return pat in ("**", "*")
    if pat == "**": return True
    if '*' not in pat and '?' not in pat: return pat == val
    return bool(re.fullmatch(_glob_re(pat), val))

def _glob_re(pat: str) -> str:
    out, i = [], 0
    while i < len(pat):
        c = pat[i]
        if c == '*':
            if i+1 < len(pat) and pat[i+1] == '*':
                out.append('.*'); i += 2
                if i < len(pat) and pat[i] == '/': i += 1
                continue
            else: out.append('[^/]*')
        elif c in r'.+^${}|()[]\!': out.append('\\' + c)
        else: out.append(c)
        i += 1
    return ''.join(out)

def _exec_pat_match(pat: str, tc) -> bool:
    """Check exec pattern against command name and all tokens."""
    cmd = tc.target.split('/')[-1]
    if glob_match(pat, cmd) or glob_match(pat, tc.target): return True
    for tok in tc.raw_input.get("command", "").split():
        if glob_match(pat, tok) or glob_match(pat, tok.split('/')[-1]): return True
    return False

# -- Tool call extraction ---------------------------------------------------
@dataclass
class ToolCall:
    tool_name: str; raw_input: dict; op: str; target: str
    args: list; file_path: str = ""

def extract_tool_calls(entry: dict) -> list:
    if entry.get("type") != "assistant": return []
    content = entry.get("content", [])
    if not isinstance(content, list): return []
    out = []
    for it in content:
        if isinstance(it, dict) and it.get("type") == "tool_use":
            tc = _parse_tool(it)
            if tc: out.append(tc)
    return out

def _parse_tool(it: dict):
    n, inp = it.get("name",""), it.get("input",{})
    if n == "Bash":
        cmd = inp.get("command","")
        parts = re.split(r'\s*&&\s*|\s*;\s*', cmd)
        pri = parts[-1].strip() if parts else cmd
        if '|' in pri: pri = pri.split('|')[0].strip()
        toks = pri.split()
        if not toks: return ToolCall("Bash", inp, "exec", cmd, [], "")
        return ToolCall("Bash", inp, "exec", toks[0], toks[1:], "")
    elif n == "Read":
        fp = inp.get("file_path",""); return ToolCall(n, inp, "read", fp, [], fp)
    elif n == "Write":
        fp = inp.get("file_path",""); return ToolCall(n, inp, "write", fp, [], fp)
    elif n == "Edit":
        fp = inp.get("file_path","")
        if inp.get("new_string","") == "" and inp.get("old_string","") != "":
            return ToolCall(n, inp, "unlink", fp, [], fp)
        return ToolCall(n, inp, "write", fp, [], fp)
    return None

def _decompose_bash(cmd: str) -> list:
    out = []
    for part in re.split(r'\s*&&\s*|\s*;\s*', cmd):
        part = part.strip()
        if not part: continue
        if '|' in part: part = part.split('|')[0].strip()
        toks = part.split()
        if toks: out.append(ToolCall("Bash", {"command": part}, "exec", toks[0], toks[1:], ""))
    return out

# -- Label expression evaluation --------------------------------------------
def eval_labels(expr: str, labels: set) -> bool:
    if not expr.strip(): return True
    return any(all(_atom(a.strip(), labels) for a in p.split(' and '))
               for p in re.split(r'\s+or\s+', expr))
def _atom(e: str, L: set) -> bool:
    if e.startswith('not '): return e[4:].strip() not in L
    if e == 'true': return True
    return e in L

# -- After gate check -------------------------------------------------------
def _check_after(cond: Condition, history: list, tracker: dict = None) -> bool:
    if tracker and cond.exec_pattern in tracker: return tracker[cond.exec_pattern]
    gate, stale = False, False
    for tc in reversed(history):
        if not gate and cond.since:
            for eo, ep in cond.since.events:
                if tc.op == eo and glob_match(ep, tc.file_path): stale = True
        if tc.op == "exec" and _exec_pat_match(cond.exec_pattern, tc):
            gate = True; break
    return gate and not stale

# -- Unified clause matching ------------------------------------------------
def _clause_match(clause: Clause, tc: ToolCall, *,
                  skip_labels=False, history=None, labels=None, tracker=None) -> bool:
    if clause.op != tc.op: return False
    # Target / exec match
    if clause.op == "exec":
        if not _exec_pat_match(clause.target, tc): return False
        for a in clause.args:
            if not any(glob_match(a, x) for x in tc.args):
                if a not in tc.raw_input.get("command",""): return False
    elif clause.op in ("write","read","unlink","open"):
        if not glob_match(clause.target, tc.file_path): return False
    else: return False
    # Labels
    if not skip_labels:
        if labels is not None and not eval_labels(clause.label_expr, labels): return False
    # Conditions (unless = rule does NOT fire when condition is true)
    if clause.condition:
        c = clause.condition
        if c.kind == "target":
            if glob_match(c.target_pattern, tc.file_path): return False
        elif c.kind == "target_not":
            if not glob_match(c.target_pattern, tc.file_path): return False
        elif c.kind == "after":
            if history is not None:
                if _check_after(c, history, tracker): return False
            # no history -> assume gate not satisfied -> rule fires
    return True

# -- IFC state (mode=ifc) ---------------------------------------------------
@dataclass
class IFCState:
    agent_labels: set = field(default_factory=set)
    file_labels: dict = field(default_factory=dict)
    since_tracker: dict = field(default_factory=dict)

    def propagate(self, policy: Policy, tc: ToolCall):
        for s in policy.sources:
            if s.kind == "exec" and tc.op == "exec" and _exec_pat_match(s.pattern, tc):
                self.agent_labels.add(s.label)
            elif s.kind == "file":
                if tc.op == "read" and glob_match(s.pattern, tc.file_path):
                    self.agent_labels.add(s.label)
                    self.file_labels.setdefault(tc.file_path, set()).add(s.label)
                elif tc.op == "write" and glob_match(s.pattern, tc.file_path):
                    self.file_labels.setdefault(tc.file_path, set()).add(s.label)
        # Data flow
        if tc.op == "read":
            self.agent_labels.update(self.file_labels.get(tc.file_path, set()))
        elif tc.op == "write":
            self.file_labels.setdefault(tc.file_path, set()).update(self.agent_labels)
        # Since trackers
        for r in policy.rules:
            for cl in r.clauses:
                co = cl.condition
                if co and co.kind == "after" and co.since:
                    if tc.op == "exec" and _exec_pat_match(co.exec_pattern, tc):
                        self.since_tracker[co.exec_pattern] = True
                    for eo, ep in co.since.events:
                        if tc.op == eo and glob_match(ep, tc.file_path):
                            self.since_tracker[co.exec_pattern] = False

# -- Main processing --------------------------------------------------------
WINDOW = 20

def process_trace(policy: Policy, trace: list, mode: str) -> dict:
    ctx, fb_list, fired = [], [], False
    history, ifc = [], IFCState()
    # Seed AGENT label for ifc
    if mode == "ifc":
        for s in policy.sources:
            if s.kind == "exec" and ("claude" in s.pattern or "agent" in s.pattern):
                ifc.agent_labels.add(s.label)

    for entry in trace:
        if entry.get("type") == "ground_truth": continue
        tool_calls = extract_tool_calls(entry)
        if not tool_calls:
            ctx.append(entry); continue

        # IFC: decompose compound bash into sub-commands
        calls = []
        for tc in tool_calls:
            if mode == "ifc" and tc.tool_name == "Bash":
                d = _decompose_bash(tc.raw_input.get("command",""))
                calls.extend(d if len(d) > 1 else [tc])
            else:
                calls.append(tc)

        entry_fb, seen = [], set()
        for tc in calls:
            if mode == "ifc": ifc.propagate(policy, tc)
            matches = []
            for r in policy.rules:
                for cl in r.clauses:
                    if mode == "per-call":
                        ok = _clause_match(cl, tc, skip_labels=True)
                    elif mode == "sequence":
                        ok = _clause_match(cl, tc, skip_labels=True, history=history[-WINDOW:])
                    else:  # ifc
                        ok = _clause_match(cl, tc, labels=ifc.agent_labels,
                                           history=history, tracker=ifc.since_tracker)
                    if ok: matches.append((cl, r))
            for cl, r in matches:
                key = (r.name, cl.effect, cl.op, cl.target)
                if key in seen: continue
                seen.add(key); fired = True
                entry_fb.append({"rule":r.name, "effect":cl.effect,
                                 "because":r.because, "tool":tc.tool_name,
                                 "op":tc.op, "target":tc.target})
                if r.because: fb_list.append(r.because)
            history.append(tc)

        ctx.append(entry)
        for fb in entry_fb:
            if fb["effect"] in ("kill","block"):
                ctx.append({"type":"tool_result","name":fb["tool"],
                            "content":{"returncode":-1,"stdout":"",
                                       "stderr":"blocked by tool-layer guard"}})
            ctx.append({"type":"actplane_feedback","content":fb["because"],
                        "rule":fb["rule"],"effect":fb["effect"]})

    return {"mode":mode, "context":ctx,
            "feedback":list(dict.fromkeys(fb_list)), "fired":fired}

# -- Entry point -------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Tool-call-layer baselines")
    ap.add_argument("--mode", required=True, choices=["per-call","sequence","ifc"])
    ap.add_argument("--rule", required=True)
    ap.add_argument("--trace", required=True)
    a = ap.parse_args()
    with open(a.rule) as f: dsl = yaml.safe_load(f).get("policy","")
    policy = parse_dsl(dsl)
    trace = []
    with open(a.trace) as f:
        for ln in f:
            ln = ln.strip()
            if ln: trace.append(json.loads(ln))
    json.dump(process_trace(policy, trace, a.mode), sys.stdout, indent=2)
    print()

if __name__ == "__main__":
    main()
