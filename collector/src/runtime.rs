use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, RwLock};
use std::time::Duration;

use ebpf_ifc_engine::{DomainHandle, Loader, ReloadHandle};
use serde_json::json;
use tokio::process::{Child, Command};

#[cfg(unix)]
use std::os::unix::ffi::OsStrExt;
#[cfg(unix)]
use std::os::unix::process::{CommandExt, ExitStatusExt};

use crate::config::{FeedbackPaths, feedback_paths, load_policy, policy_source};
use crate::hook::write_hook_state;
use crate::report::{self, report, to_violation};
use crate::{Cli, Result, audit, dsl};

const ATTACH_PID_ENV: &str = "ACTPLANE_ATTACH_PID";

pub(crate) async fn watch_policy(cli: &Cli) -> Result<i32> {
    let attach_pid = attach_pid_from_env_or_parent();
    if attach_pid <= 1 {
        return Err(format!("invalid parent pid for watch attach: {attach_pid}").into());
    }
    require_bpf_caps_or_elevate_with_env(
        cli.internal_elevated,
        &[(ATTACH_PID_ENV, attach_pid.to_string())],
    )?;
    let loaded = load_policy(cli)?;
    let policy = policy_source(&loaded, cli.domain.as_deref())?;
    let compiled = dsl::compile_str(&policy)?;
    let agent_label = runner_label(&compiled)?;
    let feedback = feedback_paths(&loaded);
    prepare_feedback_files(&feedback, target_user(cli.run_as_root))?;

    let stop = Arc::new(AtomicBool::new(false));
    let (ready_tx, ready_rx) = std::sync::mpsc::channel::<std::result::Result<(), String>>();
    let blob = compiled.bytes;
    let meta = compiled.meta;
    let labels = compiled.labels;
    let fb = feedback.feedback.clone();
    let ev = feedback.events.clone();
    let stop_thread = stop.clone();
    let poller = std::thread::spawn(move || {
        let mut loader = match Loader::load(&blob) {
            Ok(l) => l,
            Err(e) => {
                let _ = ready_tx.send(Err(format!("load engine: {e}")));
                return;
            }
        };
        if let Err(e) = loader.seed_label(attach_pid, agent_label) {
            let _ = ready_tx.send(Err(format!("seed watch pid {attach_pid}: {e}")));
            return;
        }
        let _ = ready_tx.send(Ok(()));
        let _ = loader.run(&stop_thread, |v| {
            report(&meta, &labels, &to_violation(&v), Some(&fb), Some(&ev))
        });
    });

    match ready_rx.recv() {
        Ok(Ok(())) => {}
        Ok(Err(e)) => {
            let _ = poller.join();
            return Err(e.into());
        }
        Err(_) => return Err("engine thread exited before readiness".into()),
    }
    eprintln!(
        "ActPlane: watching pid {} under COMMAND label 0x{:x}; feedback {}\n",
        attach_pid,
        agent_label,
        feedback.feedback.display()
    );

    let _ = tokio::signal::ctrl_c().await;
    stop.store(true, Ordering::SeqCst);
    let _ = poller.join();
    Ok(0)
}

pub(crate) struct AttachGuard {
    stop: Arc<AtomicBool>,
    thread: Option<std::thread::JoinHandle<()>>,
    control: Option<Arc<EngineControl>>,
}

#[derive(Clone)]
pub(crate) struct EngineControl {
    pub(crate) reload_handle: Arc<ReloadHandle>,
    pub(crate) domain_handle: Arc<DomainHandle>,
    catalog: Arc<RuntimePolicyCatalog>,
    audit_path: PathBuf,
    pub(crate) parent_pid: i32,
    pub(crate) parent_domain_id: u32,
}

struct RuntimePolicyCatalog {
    inner: RwLock<RuntimePolicyCatalogInner>,
}

struct RuntimePolicyCatalogInner {
    rules: Vec<report::RuleFeedbackContext>,
    domain_labels: HashMap<u32, HashMap<String, u64>>,
}

impl RuntimePolicyCatalog {
    fn from_compiled(compiled: &dsl::Compiled) -> Self {
        let mut domain_labels = HashMap::new();
        domain_labels.insert(0, compiled.labels.clone());
        Self {
            inner: RwLock::new(RuntimePolicyCatalogInner {
                rules: report::contexts_from_compiled(compiled),
                domain_labels,
            }),
        }
    }

    fn append_outputs(&self, v: &report::Violation, feedback_file: &Path, event_file: &Path) {
        match self.inner.read() {
            Ok(inner) => {
                report::append_violation_feedback_context(
                    inner.rules.get(v.rule_id()),
                    v,
                    feedback_file,
                );
                report::append_violation_event_context(inner.rules.get(v.rule_id()), v, event_file);
            }
            Err(e) => eprintln!("ActPlane: policy metadata lock poisoned: {e}"),
        }
    }
}

impl EngineControl {
    pub(crate) fn reload_policy(
        &self,
        compiled: &dsl::Compiled,
        policy_source: &str,
        policy_ref: &str,
    ) -> Result<usize> {
        let outcome: Result<usize> = (|| {
            let mut inner = self
                .catalog
                .inner
                .write()
                .map_err(|e| format!("policy metadata lock poisoned: {e}"))?;
            self.reload_handle.reload_policy(&compiled.bytes)?;
            inner.rules = report::contexts_from_compiled(compiled);
            inner.domain_labels.insert(0, compiled.labels.clone());
            Ok(compiled.meta.len())
        })();
        match outcome {
            Ok(n_rules) => {
                self.audit(json!({
                    "event": "reload_policy",
                    "status": "accepted",
                    "actor_pid": self.parent_pid,
                    "domain_id": 0,
                    "rule_count": n_rules,
                    "policy_ref": policy_ref,
                    "policy_hash": audit::policy_hash(policy_source),
                }))?;
                Ok(n_rules)
            }
            Err(e) => {
                let msg = e.to_string();
                self.audit(json!({
                    "event": "reload_policy",
                    "status": "rejected",
                    "actor_pid": self.parent_pid,
                    "domain_id": 0,
                    "policy_ref": policy_ref,
                    "policy_hash": audit::policy_hash(policy_source),
                    "error": msg,
                }))
                .map_err(|audit_err| format!("{e}; audit write failed: {audit_err}"))?;
                Err(e)
            }
        }
    }

    pub(crate) fn bind_child_domain(&self, spec: ebpf_ifc_engine::ChildDomainSpec) -> Result<()> {
        let outcome = self.domain_handle.bind_child_domain(spec);
        match outcome {
            Ok(()) => {
                self.audit(json!({
                    "event": "bind_child_domain",
                    "status": "accepted",
                    "actor_pid": self.parent_pid,
                    "parent_pid": spec.parent_pid,
                    "parent_domain_id": spec.parent_id,
                    "child_domain_id": spec.child_id,
                    "pid": spec.pid,
                    "scope_id": spec.scope_id,
                    "authority_mask": format!("0x{:x}", spec.authority_mask),
                    "target_mask": format!("0x{:x}", spec.target_mask),
                    "label_mask": format!("0x{:x}", spec.label_mask),
                }))?;
                Ok(())
            }
            Err(e) => {
                let msg = e.to_string();
                self.audit(json!({
                    "event": "bind_child_domain",
                    "status": "rejected",
                    "actor_pid": self.parent_pid,
                    "parent_pid": spec.parent_pid,
                    "parent_domain_id": spec.parent_id,
                    "child_domain_id": spec.child_id,
                    "pid": spec.pid,
                    "scope_id": spec.scope_id,
                    "error": msg,
                }))
                .map_err(|audit_err| format!("{e}; audit write failed: {audit_err}"))?;
                Err(e.into())
            }
        }
    }

    pub(crate) fn append_policy_delta_dsl(
        &self,
        target_id: u32,
        dsl_src: &str,
    ) -> Result<(usize, usize)> {
        let outcome = self.append_policy_delta_dsl_inner(target_id, dsl_src);
        match outcome {
            Ok((base, n_rules)) => {
                self.audit(json!({
                    "event": "append_policy_delta",
                    "status": "accepted",
                    "actor_pid": self.parent_pid,
                    "target_id": target_id,
                    "rule_id_base": base,
                    "rule_count": n_rules,
                    "policy_hash": audit::policy_hash(dsl_src),
                }))?;
                Ok((base, n_rules))
            }
            Err(e) => {
                let msg = e.to_string();
                self.audit(json!({
                    "event": "append_policy_delta",
                    "status": "rejected",
                    "actor_pid": self.parent_pid,
                    "target_id": target_id,
                    "policy_hash": audit::policy_hash(dsl_src),
                    "error": msg,
                }))
                .map_err(|audit_err| format!("{e}; audit write failed: {audit_err}"))?;
                Err(e)
            }
        }
    }

    fn audit(&self, record: serde_json::Value) -> Result<()> {
        audit::append(&self.audit_path, record)
    }

    pub(crate) fn audit_child_launch(
        &self,
        pid: i32,
        child_id: u32,
        cmd: &[String],
        policy_attached: bool,
        status: &str,
        error: Option<&str>,
    ) -> Result<()> {
        let mut record = json!({
            "event": "launch_child_domain",
            "status": status,
            "actor_pid": self.parent_pid,
            "pid": pid,
            "child_domain_id": child_id,
            "cmd": cmd,
            "policy_attached": policy_attached,
        });
        if let Some(error) = error {
            record["error"] = json!(error);
        }
        self.audit(record)
    }

    fn append_policy_delta_dsl_inner(
        &self,
        target_id: u32,
        dsl_src: &str,
    ) -> Result<(usize, usize)> {
        if target_id == 0 {
            return Err("runtime policy deltas must target a nonzero domain".into());
        }
        let mut inner = self
            .catalog
            .inner
            .write()
            .map_err(|e| format!("policy metadata lock poisoned: {e}"))?;
        let existing_labels = inner
            .domain_labels
            .get(&target_id)
            .cloned()
            .unwrap_or_default();
        let compiled = dsl::compile_str_with_labels(dsl_src, &existing_labels)?;
        let rule_id_base = inner.rules.len();
        self.reload_handle.append_policy_delta_with_rule_id_base(
            self.parent_pid,
            target_id,
            rule_id_base as u32,
            &compiled.bytes,
        )?;
        inner
            .domain_labels
            .insert(target_id, compiled.labels.clone());
        inner
            .rules
            .extend(report::contexts_from_compiled(&compiled));
        Ok((rule_id_base, compiled.meta.len()))
    }
}

impl AttachGuard {
    pub(crate) fn engine_control(&self) -> Option<Arc<EngineControl>> {
        self.control.clone()
    }
}

impl Drop for AttachGuard {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::SeqCst);
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}

pub(crate) fn start_mcp_auto_attach(cli: &Cli) -> Result<AttachGuard> {
    let attach_pid = attach_pid_from_env_or_parent();
    if attach_pid <= 1 {
        return Err(format!("invalid parent pid for auto-attach: {attach_pid}").into());
    }

    require_bpf_caps_or_elevate_with_env(
        cli.internal_elevated,
        &[(ATTACH_PID_ENV, attach_pid.to_string())],
    )?;

    let loaded = load_policy(cli)?;
    let policy = policy_source(&loaded, cli.domain.as_deref())?;
    let compiled = dsl::compile_str(&policy)?;
    let agent_label = runner_label(&compiled)?;
    let catalog = Arc::new(RuntimePolicyCatalog::from_compiled(&compiled));
    let feedback = scoped_feedback_paths(&feedback_paths(&loaded), "mcp");
    prepare_feedback_files(&feedback, target_user(cli.run_as_root))?;
    write_hook_state(&feedback.state, &feedback.feedback, attach_pid)?;
    if let Some((uid, gid)) = target_user(cli.run_as_root) {
        chown_path(&feedback.state, uid, gid)?;
    }

    let stop = Arc::new(AtomicBool::new(false));
    type ReadyResult = std::result::Result<(ReloadHandle, DomainHandle), String>;
    let (ready_tx, ready_rx) = std::sync::mpsc::channel::<ReadyResult>();
    let blob = compiled.bytes;
    let fb = feedback.feedback.clone();
    let ev = feedback.events.clone();
    let run_catalog = catalog.clone();
    let stop_thread = stop.clone();
    let thread = std::thread::spawn(move || {
        let mut loader = match Loader::load(&blob) {
            Ok(l) => l,
            Err(e) => {
                let _ = ready_tx.send(Err(format!("load engine: {e}")));
                return;
            }
        };
        if let Err(e) = loader.seed_label(attach_pid, agent_label) {
            let _ = ready_tx.send(Err(format!("seed parent pid {attach_pid}: {e}")));
            return;
        }
        let rh = match loader.reload_handle() {
            Ok(h) => h,
            Err(e) => {
                let _ = ready_tx.send(Err(format!("create reload handle: {e}")));
                return;
            }
        };
        let dh = match loader.domain_handle() {
            Ok(h) => h,
            Err(e) => {
                let _ = ready_tx.send(Err(format!("create domain handle: {e}")));
                return;
            }
        };
        let _ = ready_tx.send(Ok((rh, dh)));
        let _ = loader.run(&stop_thread, |v| {
            run_catalog.append_outputs(&to_violation(&v), &fb, &ev);
        });
    });

    match ready_rx.recv() {
        Ok(Ok((reload_handle, domain_handle))) => {
            eprintln!(
                "ActPlane: MCP auto-attached pid {} under COMMAND label 0x{:x}; feedback {}",
                attach_pid,
                agent_label,
                feedback.feedback.display()
            );
            Ok(AttachGuard {
                stop,
                thread: Some(thread),
                control: Some(Arc::new(EngineControl {
                    reload_handle: Arc::new(reload_handle),
                    domain_handle: Arc::new(domain_handle),
                    catalog,
                    audit_path: feedback.audit.clone(),
                    parent_pid: attach_pid,
                    parent_domain_id: attach_pid as u32,
                })),
            })
        }
        Ok(Err(e)) => {
            stop.store(true, Ordering::SeqCst);
            let _ = thread.join();
            Err(e.into())
        }
        Err(_) => {
            stop.store(true, Ordering::SeqCst);
            let _ = thread.join();
            Err("engine thread exited before readiness".into())
        }
    }
}

fn parent_pid() -> i32 {
    unsafe { libc::getppid() as i32 }
}

fn attach_pid_from_env_or_parent() -> i32 {
    std::env::var(ATTACH_PID_ENV)
        .ok()
        .and_then(|s| s.parse::<i32>().ok())
        .unwrap_or_else(parent_pid)
}

/// Check whether we have BPF capabilities (root or CAP_BPF + CAP_SYS_ADMIN).
pub(crate) fn have_bpf_caps() -> bool {
    if unsafe { libc::geteuid() } == 0 {
        return true;
    }
    let eff = std::fs::read_to_string("/proc/self/status")
        .ok()
        .and_then(|s| {
            s.lines()
                .find_map(|l| l.strip_prefix("CapEff:"))
                .and_then(|h| u64::from_str_radix(h.trim(), 16).ok())
        })
        .unwrap_or(0);
    let has = |bit: u32| eff & (1u64 << bit) != 0;
    has(39) && has(21)
}

pub(crate) fn passwordless_sudo_available() -> bool {
    std::process::Command::new("sudo")
        .args(["-n", "true"])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

/// If we lack BPF caps, try passwordless sudo to re-exec ourselves elevated.
/// Returns Ok(()) if we already have caps; otherwise re-execs or exits with an error.
fn require_bpf_caps_or_elevate(already_elevated: bool) -> Result<()> {
    require_bpf_caps_or_elevate_with_env(already_elevated, &[])
}

fn require_bpf_caps_or_elevate_with_env(
    already_elevated: bool,
    extra_env: &[(&str, String)],
) -> Result<()> {
    if have_bpf_caps() {
        return Ok(());
    }
    if already_elevated {
        eprintln!("actplane: still lacks BPF caps after elevation attempt");
        std::process::exit(1);
    }
    if passwordless_sudo_available() {
        let exe = std::env::current_exe().unwrap_or_else(|_| PathBuf::from("actplane"));
        let args: Vec<String> = std::env::args().collect();
        let mut cmd = std::process::Command::new("sudo");
        cmd.arg("-E").arg(&exe).arg("--internal-elevated");
        for (name, value) in extra_env {
            cmd.env(name, value);
        }
        for arg in &args[1..] {
            cmd.arg(arg);
        }
        eprintln!("actplane: auto-elevating via passwordless sudo ...");
        #[cfg(unix)]
        {
            let e = cmd.exec();
            Err(format!("sudo exec: {e}").into())
        }
        #[cfg(not(unix))]
        {
            let status = cmd.status().map_err(|e| format!("sudo re-exec: {e}"))?;
            std::process::exit(status.code().unwrap_or(1));
        }
    } else {
        eprintln!(
            "actplane: this command loads an eBPF engine, which needs root \
                 (or CAP_BPF + CAP_SYS_ADMIN).\n\
                 \n  Re-run with sudo, e.g.:   sudo -E actplane <same args>\n\
                 \n  (sudo-launched ActPlane drops the target command back to your user automatically.)"
        );
        std::process::exit(1);
    }
}

pub(crate) async fn run_command(cli: &Cli, cmd: &[String]) -> Result<i32> {
    require_bpf_caps_or_elevate(cli.internal_elevated)?;
    let loaded = load_policy(cli)?;
    let policy = policy_source(&loaded, cli.domain.as_deref())?;
    let compiled = dsl::compile_str(&policy)?;
    let agent_label = runner_label(&compiled)?;
    let feedback = scoped_feedback_paths(&feedback_paths(&loaded), "run");
    let target_owner = target_user(cli.run_as_root);
    prepare_feedback_files(&feedback, target_owner)?;

    let mut target = spawn_stopped_target(cmd, &feedback, loaded.path.as_deref(), cli.run_as_root)?;
    let target_pid = target.id().ok_or("target process has no pid")?;
    write_hook_state(&feedback.state, &feedback.feedback, target_pid as i32)?;
    if let Some((uid, gid)) = target_owner {
        chown_path(&feedback.state, uid, gid)?;
    }

    let stop = Arc::new(AtomicBool::new(false));
    let (ready_tx, ready_rx) = std::sync::mpsc::channel::<std::result::Result<(), String>>();
    let blob = compiled.bytes;
    let meta = compiled.meta;
    let labels = compiled.labels;
    let fb = feedback.feedback.clone();
    let ev = feedback.events.clone();
    let stop_thread = stop.clone();
    let poller = std::thread::spawn(move || {
        let mut loader = match Loader::load(&blob) {
            Ok(l) => l,
            Err(e) => {
                let _ = ready_tx.send(Err(format!("load engine: {e}")));
                return;
            }
        };
        if let Err(e) = loader.seed_label(target_pid as i32, agent_label) {
            let _ = ready_tx.send(Err(format!("seed pid: {e}")));
            return;
        }
        let _ = ready_tx.send(Ok(()));
        let _ = loader.run(&stop_thread, |v| {
            report(&meta, &labels, &to_violation(&v), Some(&fb), Some(&ev))
        });
    });

    match ready_rx.recv() {
        Ok(Ok(())) => {}
        Ok(Err(e)) => {
            let _ = send_signal(target_pid, libc::SIGKILL);
            let _ = target.wait().await;
            let _ = poller.join();
            return Err(e.into());
        }
        Err(_) => {
            let _ = send_signal(target_pid, libc::SIGKILL);
            let _ = target.wait().await;
            return Err("engine thread exited before readiness".into());
        }
    }

    eprintln!(
        "ActPlane: running pid {} under COMMAND label 0x{:x}; feedback {}\n",
        target_pid,
        agent_label,
        feedback.feedback.display()
    );
    send_signal(target_pid, libc::SIGCONT)?;

    let status = target.wait().await?;
    std::thread::sleep(Duration::from_millis(200));
    stop.store(true, Ordering::SeqCst);
    let _ = poller.join();
    Ok(exit_code(status))
}

fn runner_label(compiled: &dsl::Compiled) -> Result<u64> {
    compiled
        .labels
        .get("COMMAND")
        .or_else(|| compiled.labels.get("AGENT"))
        .copied()
        .ok_or_else(|| {
            "run/auto-attach mode requires the policy to declare or reference label COMMAND \
             (or AGENT for backward compatibility)"
                .into()
        })
}

fn prepare_feedback_files(
    paths: &FeedbackPaths,
    owner: Option<(libc::uid_t, libc::gid_t)>,
) -> Result<()> {
    if let Some(parent) = paths.feedback.parent() {
        std::fs::create_dir_all(parent)?;
        if let Some((uid, gid)) = owner {
            chown_path(parent, uid, gid)?;
        }
    }
    std::fs::write(&paths.feedback, "")?;
    if let Some((uid, gid)) = owner {
        chown_path(&paths.feedback, uid, gid)?;
    }
    if let Some(parent) = paths.audit.parent() {
        std::fs::create_dir_all(parent)?;
        if let Some((uid, gid)) = owner {
            chown_path(parent, uid, gid)?;
        }
    }
    std::fs::write(&paths.audit, "")?;
    if let Some((uid, gid)) = owner {
        chown_path(&paths.audit, uid, gid)?;
    }
    if let Some(parent) = paths.events.parent() {
        std::fs::create_dir_all(parent)?;
        if let Some((uid, gid)) = owner {
            chown_path(parent, uid, gid)?;
        }
    }
    std::fs::write(&paths.events, "")?;
    if let Some((uid, gid)) = owner {
        chown_path(&paths.events, uid, gid)?;
    }
    match std::fs::remove_file(&paths.state) {
        Ok(()) => {}
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        Err(e) => return Err(e.into()),
    }
    Ok(())
}

fn scoped_feedback_paths(base: &FeedbackPaths, prefix: &str) -> FeedbackPaths {
    let root = base
        .feedback
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from("."));
    let run_dir = root.join("runs").join(run_id(prefix));
    FeedbackPaths {
        feedback: run_dir.join("feedback.txt"),
        state: run_dir.join("hook-state.json"),
        audit: run_dir.join("audit.jsonl"),
        events: run_dir.join("events.jsonl"),
    }
}

fn run_id(prefix: &str) -> String {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    format!("{prefix}-{}-{now}", std::process::id())
}

fn chown_path(path: &Path, uid: libc::uid_t, gid: libc::gid_t) -> std::io::Result<()> {
    let c_path = std::ffi::CString::new(path.as_os_str().as_bytes())
        .map_err(|_| std::io::Error::new(std::io::ErrorKind::InvalidInput, "path contains NUL"))?;
    let rc = unsafe { libc::chown(c_path.as_ptr(), uid, gid) };
    if rc == 0 {
        Ok(())
    } else {
        Err(std::io::Error::last_os_error())
    }
}

fn spawn_stopped_target(
    cmd: &[String],
    feedback: &FeedbackPaths,
    policy_path: Option<&Path>,
    run_as_root: bool,
) -> Result<Child> {
    if cmd.is_empty() {
        return Err("run requires a command after `--`".into());
    }
    let drop_to = target_user(run_as_root);
    let mut target = Command::new("/bin/sh");
    target.arg("-c");
    target.arg("kill -STOP $$; exec \"$@\"");
    target.arg("actplane-target");
    target.args(cmd);
    target.stdin(Stdio::inherit());
    target.stdout(Stdio::inherit());
    target.stderr(Stdio::inherit());
    target.env("ACTPLANE_FEEDBACK_FILE", &feedback.feedback);
    target.env("ACTPLANE_HOOK_STATE", &feedback.state);
    if let Some(policy_path) = policy_path {
        target.env("ACTPLANE_POLICY_FILE", policy_path);
    }

    unsafe {
        target.pre_exec(move || {
            if let Some((uid, gid)) = drop_to {
                if libc::setgid(gid) != 0 {
                    return Err(std::io::Error::last_os_error());
                }
                if libc::setuid(uid) != 0 {
                    return Err(std::io::Error::last_os_error());
                }
            }
            Ok(())
        });
    }
    Ok(target.spawn()?)
}

fn target_user(run_as_root: bool) -> Option<(libc::uid_t, libc::gid_t)> {
    if run_as_root || unsafe { libc::geteuid() } != 0 {
        return None;
    }
    let uid = std::env::var("SUDO_UID")
        .ok()?
        .parse::<libc::uid_t>()
        .ok()?;
    let gid = std::env::var("SUDO_GID")
        .ok()?
        .parse::<libc::gid_t>()
        .ok()?;
    Some((uid, gid))
}

fn send_signal(pid: u32, sig: i32) -> std::io::Result<()> {
    let rc = unsafe { libc::kill(pid as libc::pid_t, sig) };
    if rc == 0 {
        Ok(())
    } else {
        Err(std::io::Error::last_os_error())
    }
}

fn exit_code(status: std::process::ExitStatus) -> i32 {
    if let Some(code) = status.code() {
        return code;
    }
    #[cfg(unix)]
    if let Some(sig) = status.signal() {
        return 128 + sig;
    }
    1
}
