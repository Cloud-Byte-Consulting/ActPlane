// SPDX-License-Identifier: MIT
// Copyright (c) 2026 eunomia-bpf org.

//! ActPlane MCP server — watches `actplane.yaml` for changes, validates the
//! policy on every save, exposes the latest feedback file, and pushes updates
//! to the MCP client via resource updates and logging notifications.

use std::collections::HashMap;
use std::io::{Read, Seek, SeekFrom};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime};

#[cfg(unix)]
use std::os::unix::process::{CommandExt, ExitStatusExt};

use rmcp::model::*;
use rmcp::transport::io::stdio;
use rmcp::{Peer, RoleServer, ServerHandler, ServiceExt};
use serde_json::Value;

use crate::dsl;
use crate::runtime::EngineControl;
use ebpf_ifc_engine::ChildDomainSpec;
use ebpf_ifc_engine::capability::{AUTH_BIND_RULE, TARGET_SELF};

const POLICY_RESOURCE_URI: &str = "actplane:///policy";
const FEEDBACK_RESOURCE_URI: &str = "actplane:///feedback";
const DEFAULT_FEEDBACK_FILE: &str = ".actplane/last-violation.txt";
const WATCH_INTERVAL: Duration = Duration::from_secs(2);

// ── Server state ────────────────────────────────────────────────────

#[derive(Clone)]
pub struct ActPlaneMcp {
    project_dir: PathBuf,
    control: Option<Arc<EngineControl>>,
    children: Arc<Mutex<HashMap<u32, ChildRecord>>>,
}

#[derive(Clone)]
struct ChildRecord {
    launch_id: String,
    pid: i32,
    child_id: u32,
    cmd: Vec<String>,
    stdout: PathBuf,
    stderr: PathBuf,
    meta: PathBuf,
    proc_start_time: Option<u64>,
    status: Arc<Mutex<ChildStatus>>,
}

#[derive(Clone)]
enum ChildStatus {
    Running,
    Exited {
        code: Option<i32>,
        signal: Option<i32>,
    },
    Terminated,
}

impl ActPlaneMcp {
    pub fn new_with_control(control: Option<Arc<EngineControl>>) -> Self {
        let project_dir = std::env::var("ACTPLANE_PROJECT_DIR")
            .or_else(|_| std::env::var("CODEX_PROJECT_DIR"))
            .or_else(|_| std::env::var("CODEX_WORKSPACE"))
            .or_else(|_| std::env::var("CLAUDE_PROJECT_DIR"))
            .map(PathBuf::from)
            .unwrap_or_else(|_| std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")));
        let children = Arc::new(Mutex::new(load_child_records(&project_dir)));
        Self {
            project_dir,
            control,
            children,
        }
    }

    fn discover_policy_file(&self) -> Option<PathBuf> {
        let candidates = ["actplane.yaml", ".actplane/policy.yaml"];
        let mut dir = Some(self.project_dir.as_path());
        while let Some(d) = dir {
            for name in &candidates {
                let p = d.join(name);
                if p.is_file() {
                    return Some(p);
                }
            }
            dir = d.parent();
        }
        None
    }

    fn load_and_validate(&self) -> String {
        let path = match self.discover_policy_file() {
            Some(p) => p,
            None => return "No actplane.yaml found.".into(),
        };
        let src = match std::fs::read_to_string(&path) {
            Ok(s) => s,
            Err(e) => return format!("Cannot read {}: {}", path.display(), e),
        };
        let config: serde_yaml::Value = match serde_yaml::from_str(&src) {
            Ok(v) => v,
            Err(e) => return format!("YAML parse error in {}: {}", path.display(), e),
        };
        let dsl_src = match config.get("policy").and_then(|v| v.as_str()) {
            Some(s) => s,
            None => return format!("{} has no `policy:` field", path.display()),
        };
        match dsl::compile_str(dsl_src) {
            Ok(compiled) => {
                let mut out = format!(
                    "Policy valid ({}, {} rules):\n",
                    path.display(),
                    compiled.meta.len()
                );
                for (i, m) in compiled.meta.iter().enumerate() {
                    let eff = format!("{:?}", m.effect).to_lowercase();
                    let ops = if m.ops.is_empty() {
                        "—".into()
                    } else {
                        m.ops.join("/")
                    };
                    out.push_str(&format!(
                        "  {}. {} — {} {} ({})\n",
                        i + 1,
                        m.name,
                        eff,
                        ops,
                        m.reason
                    ));
                }
                out
            }
            Err(e) => format!("Policy compile error: {}", e),
        }
    }

    fn feedback_file(&self) -> PathBuf {
        if let Ok(path) = std::env::var("ACTPLANE_FEEDBACK_FILE") {
            return PathBuf::from(path);
        }
        let Some(policy) = self.discover_policy_file() else {
            return self.project_dir.join(DEFAULT_FEEDBACK_FILE);
        };
        let root = policy
            .parent()
            .map(PathBuf::from)
            .unwrap_or_else(|| self.project_dir.clone());
        let Ok(src) = std::fs::read_to_string(&policy) else {
            return root.join(DEFAULT_FEEDBACK_FILE);
        };
        let Ok(config) = serde_yaml::from_str::<serde_yaml::Value>(&src) else {
            return root.join(DEFAULT_FEEDBACK_FILE);
        };
        if let Some(path) = latest_run_feedback(&root) {
            return path;
        }
        config
            .get("feedback")
            .and_then(|v| v.get("path"))
            .and_then(|v| v.as_str())
            .map(PathBuf::from)
            .map(|p| if p.is_absolute() { p } else { root.join(p) })
            .unwrap_or_else(|| root.join(DEFAULT_FEEDBACK_FILE))
    }

    fn load_feedback(&self) -> String {
        let path = self.feedback_file();
        match std::fs::read_to_string(&path) {
            Ok(s) if !s.trim().is_empty() => {
                format!("Latest ActPlane feedback ({}):\n{}", path.display(), s)
            }
            Ok(_) => format!(
                "No ActPlane feedback has been written yet ({}).",
                path.display()
            ),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                format!("No ActPlane feedback file yet ({}).", path.display())
            }
            Err(e) => format!("Cannot read {}: {}", path.display(), e),
        }
    }

    fn policy_mtime(&self) -> Option<SystemTime> {
        self.discover_policy_file()
            .and_then(|p| std::fs::metadata(&p).ok())
            .and_then(|m| m.modified().ok())
    }

    fn feedback_mtime(&self) -> Option<SystemTime> {
        std::fs::metadata(self.feedback_file())
            .ok()
            .and_then(|m| m.modified().ok())
    }

    fn do_reload_policy(&self) -> Result<CallToolResult, rmcp::ErrorData> {
        let control = self.control.as_ref().ok_or_else(|| {
            rmcp::ErrorData::new(
                ErrorCode::INTERNAL_ERROR,
                "No eBPF engine attached (MCP not started with --auto-attach-parent)",
                None::<Value>,
            )
        })?;
        let path = self.discover_policy_file().ok_or_else(|| {
            rmcp::ErrorData::new(
                ErrorCode::INVALID_PARAMS,
                "No actplane.yaml found",
                None::<Value>,
            )
        })?;
        let src = std::fs::read_to_string(&path).map_err(|e| {
            rmcp::ErrorData::new(
                ErrorCode::INTERNAL_ERROR,
                format!("Cannot read {}: {e}", path.display()),
                None::<Value>,
            )
        })?;
        let config: serde_yaml::Value = serde_yaml::from_str(&src).map_err(|e| {
            rmcp::ErrorData::new(
                ErrorCode::INTERNAL_ERROR,
                format!("YAML parse error: {e}"),
                None::<Value>,
            )
        })?;
        let dsl_src = config
            .get("policy")
            .and_then(|v| v.as_str())
            .ok_or_else(|| {
                rmcp::ErrorData::new(
                    ErrorCode::INVALID_PARAMS,
                    "No `policy:` field in actplane.yaml",
                    None::<Value>,
                )
            })?;
        let compiled = dsl::compile_str(dsl_src).map_err(|e| {
            rmcp::ErrorData::new(
                ErrorCode::INTERNAL_ERROR,
                format!("Policy compile error: {e}"),
                None::<Value>,
            )
        })?;
        let n_rules = control
            .reload_policy(&compiled, dsl_src, &path.display().to_string())
            .map_err(|e| {
                rmcp::ErrorData::new(
                    ErrorCode::INTERNAL_ERROR,
                    format!("Reload failed: {e}"),
                    None::<Value>,
                )
            })?;

        let msg = format!(
            "Policy hot-reloaded ({} rule metadata entries) from {}",
            n_rules,
            path.display()
        );
        Ok(CallToolResult::success(vec![Content::text(msg)]))
    }

    fn do_bind_child_domain(
        &self,
        args: Option<serde_json::Map<String, Value>>,
    ) -> Result<CallToolResult, rmcp::ErrorData> {
        let control = self.control.as_ref().ok_or_else(|| {
            rmcp::ErrorData::new(
                ErrorCode::INTERNAL_ERROR,
                "No eBPF engine attached (MCP not started with --auto-attach-parent)",
                None::<Value>,
            )
        })?;
        let args = args.unwrap_or_default();
        let pid = json_i32(&args, "pid")?;
        if pid <= 0 {
            return Err(invalid_params("pid must be positive"));
        }
        let child_id = match json_optional_u32(&args, "child_id")? {
            Some(id) => id,
            None => pid as u32,
        };
        let scope_id = json_optional_u32(&args, "scope_id")?.unwrap_or(0);
        control
            .bind_child_domain(ChildDomainSpec {
                parent_pid: control.parent_pid,
                parent_id: control.parent_domain_id,
                child_id,
                pid,
                scope_id,
                authority_mask: AUTH_BIND_RULE,
                target_mask: TARGET_SELF,
                ..ChildDomainSpec::default()
            })
            .map_err(|e| {
                rmcp::ErrorData::new(
                    ErrorCode::INTERNAL_ERROR,
                    format!("Bind child domain failed: {e}"),
                    None::<Value>,
                )
            })?;
        Ok(CallToolResult::success(vec![Content::text(format!(
            "Bound pid {pid} to child domain {child_id} under parent domain {}",
            control.parent_domain_id
        ))]))
    }

    fn do_append_policy_delta(
        &self,
        args: Option<serde_json::Map<String, Value>>,
    ) -> Result<CallToolResult, rmcp::ErrorData> {
        let control = self.control.as_ref().ok_or_else(|| {
            rmcp::ErrorData::new(
                ErrorCode::INTERNAL_ERROR,
                "No eBPF engine attached (MCP not started with --auto-attach-parent)",
                None::<Value>,
            )
        })?;
        let args = args.unwrap_or_default();
        let target_id = match json_optional_u32(&args, "target_id")? {
            Some(id) => id,
            None => json_optional_u32(&args, "domain_id")?.unwrap_or(control.parent_domain_id),
        };
        if target_id == 0 {
            return Err(invalid_params("target_id must be nonzero"));
        }
        let policy = json_string(&args, "policy")?;
        let (base, n_rules) = control
            .append_policy_delta_dsl(target_id, policy)
            .map_err(|e| {
                rmcp::ErrorData::new(
                    ErrorCode::INTERNAL_ERROR,
                    format!("Append policy delta failed: {e}"),
                    None::<Value>,
                )
            })?;
        Ok(CallToolResult::success(vec![Content::text(format!(
            "Appended policy delta to domain {target_id}: {n_rules} rule metadata entries starting at rule_id {base}"
        ))]))
    }

    fn do_launch_child_domain(
        &self,
        args: Option<serde_json::Map<String, Value>>,
    ) -> Result<CallToolResult, rmcp::ErrorData> {
        let control = self.control.as_ref().ok_or_else(|| {
            rmcp::ErrorData::new(
                ErrorCode::INTERNAL_ERROR,
                "No eBPF engine attached (MCP not started with --auto-attach-parent)",
                None::<Value>,
            )
        })?;
        let args = args.unwrap_or_default();
        let cmd = json_string_vec(&args, "cmd")?;
        if cmd.is_empty() {
            return Err(invalid_params("cmd must not be empty"));
        }
        let launch_id = child_launch_id();
        let log_dir = self
            .project_dir
            .join(".actplane")
            .join("children")
            .join(&launch_id);
        let mut child = spawn_stopped_child(&cmd, &self.project_dir, &log_dir)?;
        let pid = child.id() as i32;
        let child_id = match json_optional_u32(&args, "child_id")? {
            Some(id) => id,
            None => pid as u32,
        };
        let scope_id = json_optional_u32(&args, "scope_id")?.unwrap_or(0);
        let policy = json_optional_string(&args, "policy")?;
        let policy_attached = policy.is_some();

        if let Err(e) = control.bind_child_domain(ChildDomainSpec {
            parent_pid: control.parent_pid,
            parent_id: control.parent_domain_id,
            child_id,
            pid,
            scope_id,
            authority_mask: AUTH_BIND_RULE,
            target_mask: TARGET_SELF,
            ..ChildDomainSpec::default()
        }) {
            kill_and_wait(child);
            let _ = control.audit_child_launch(
                pid,
                child_id,
                &cmd,
                policy_attached,
                "rejected",
                Some(&e.to_string()),
            );
            return Err(rmcp::ErrorData::new(
                ErrorCode::INTERNAL_ERROR,
                format!("Bind launched child domain failed: {e}"),
                None::<Value>,
            ));
        }

        if let Some(policy) = policy {
            if let Err(e) = control.append_policy_delta_dsl(child_id, policy) {
                kill_and_wait(child);
                let _ = control.audit_child_launch(
                    pid,
                    child_id,
                    &cmd,
                    policy_attached,
                    "rejected",
                    Some(&e.to_string()),
                );
                return Err(rmcp::ErrorData::new(
                    ErrorCode::INTERNAL_ERROR,
                    format!("Append launched child policy failed: {e}"),
                    None::<Value>,
                ));
            }
        }

        if let Err(e) = send_signal(pid, libc::SIGCONT) {
            kill_and_wait(child);
            let _ = control.audit_child_launch(
                pid,
                child_id,
                &cmd,
                policy_attached,
                "rejected",
                Some(&e.to_string()),
            );
            return Err(rmcp::ErrorData::new(
                ErrorCode::INTERNAL_ERROR,
                format!("Resume launched child failed: {e}"),
                None::<Value>,
            ));
        }
        let status = Arc::new(Mutex::new(ChildStatus::Running));
        let record = ChildRecord {
            launch_id,
            pid,
            child_id,
            cmd: cmd.clone(),
            stdout: log_dir.join("stdout.log"),
            stderr: log_dir.join("stderr.log"),
            meta: log_dir.join("meta.json"),
            proc_start_time: proc_start_time(pid),
            status: status.clone(),
        };
        persist_child_record(&record).map_err(|e| {
            rmcp::ErrorData::new(
                ErrorCode::INTERNAL_ERROR,
                format!("Persist child registry failed: {e}"),
                None::<Value>,
            )
        })?;
        self.children
            .lock()
            .map_err(|e| {
                rmcp::ErrorData::new(
                    ErrorCode::INTERNAL_ERROR,
                    format!("Child registry lock poisoned: {e}"),
                    None::<Value>,
                )
            })?
            .insert(child_id, record.clone());
        control
            .audit_child_launch(pid, child_id, &cmd, policy_attached, "accepted", None)
            .map_err(|e| {
                rmcp::ErrorData::new(
                    ErrorCode::INTERNAL_ERROR,
                    format!("Launch succeeded but audit write failed: {e}"),
                    None::<Value>,
                )
            })?;
        std::thread::spawn(move || match child.wait() {
            Ok(exit) => {
                if let Ok(mut st) = status.lock() {
                    *st = ChildStatus::Exited {
                        code: exit.code(),
                        signal: exit.signal(),
                    };
                }
                let _ = persist_child_record(&record);
            }
            Err(_) => {
                if let Ok(mut st) = status.lock() {
                    *st = ChildStatus::Terminated;
                }
                let _ = persist_child_record(&record);
            }
        });

        Ok(CallToolResult::success(vec![Content::text(format!(
            "Launched pid {pid} in child domain {child_id}"
        ))]))
    }

    fn do_list_child_domains(&self) -> Result<CallToolResult, rmcp::ErrorData> {
        let mut children = self.children.lock().map_err(|e| {
            rmcp::ErrorData::new(
                ErrorCode::INTERNAL_ERROR,
                format!("Child registry lock poisoned: {e}"),
                None::<Value>,
            )
        })?;
        for record in children.values_mut() {
            refresh_child_record_status(record);
        }
        let mut rows: Vec<serde_json::Value> = children.values().map(child_record_json).collect();
        rows.sort_by_key(|v| v["child_id"].as_u64().unwrap_or(0));
        Ok(CallToolResult::success(vec![Content::text(
            serde_json::to_string_pretty(&rows).unwrap_or_else(|_| "[]".to_string()),
        )]))
    }

    fn do_read_child_domain_logs(
        &self,
        args: Option<serde_json::Map<String, Value>>,
    ) -> Result<CallToolResult, rmcp::ErrorData> {
        let args = args.unwrap_or_default();
        let child_id = child_id_arg(&args)?;
        let stream = json_optional_string(&args, "stream")?.unwrap_or("both");
        if !matches!(stream, "stdout" | "stderr" | "both") {
            return Err(invalid_params(
                "`stream` must be one of stdout, stderr, or both",
            ));
        }
        let max_bytes = json_optional_usize(&args, "max_bytes")?
            .unwrap_or(8192)
            .clamp(1, 65536);
        let record = {
            let mut children = self.children.lock().map_err(|e| {
                rmcp::ErrorData::new(
                    ErrorCode::INTERNAL_ERROR,
                    format!("Child registry lock poisoned: {e}"),
                    None::<Value>,
                )
            })?;
            let record = children
                .get_mut(&child_id)
                .ok_or_else(|| invalid_params(format!("unknown child domain {child_id}")))?;
            refresh_child_record_status(record);
            record.clone()
        };
        let mut value = serde_json::json!({
            "pid": record.pid,
            "child_id": record.child_id,
            "status": record.status.lock().map(|s| child_status_json(&s)).unwrap_or_else(|_| serde_json::json!({ "state": "unknown" })),
            "max_bytes": max_bytes,
        });
        if stream == "stdout" || stream == "both" {
            value["stdout"] = read_log_json(&record.stdout, max_bytes)?;
        }
        if stream == "stderr" || stream == "both" {
            value["stderr"] = read_log_json(&record.stderr, max_bytes)?;
        }
        Ok(CallToolResult::success(vec![Content::text(
            serde_json::to_string_pretty(&value).unwrap_or_else(|_| "{}".to_string()),
        )]))
    }

    fn do_terminate_child_domain(
        &self,
        args: Option<serde_json::Map<String, Value>>,
    ) -> Result<CallToolResult, rmcp::ErrorData> {
        let args = args.unwrap_or_default();
        let child_id = child_id_arg(&args)?;
        let record = {
            let mut children = self.children.lock().map_err(|e| {
                rmcp::ErrorData::new(
                    ErrorCode::INTERNAL_ERROR,
                    format!("Child registry lock poisoned: {e}"),
                    None::<Value>,
                )
            })?;
            let record = children
                .get_mut(&child_id)
                .ok_or_else(|| invalid_params(format!("unknown child domain {child_id}")))?;
            refresh_child_record_status(record);
            record.clone()
        };
        if let Ok(status) = record.status.lock() {
            match &*status {
                ChildStatus::Exited { .. } => {
                    return Ok(CallToolResult::success(vec![Content::text(format!(
                        "Child domain {child_id} already exited"
                    ))]));
                }
                ChildStatus::Terminated => {
                    return Ok(CallToolResult::success(vec![Content::text(format!(
                        "Child domain {child_id} was already terminated"
                    ))]));
                }
                ChildStatus::Running => {}
            }
        }
        let next_status = match terminate_process_group(record.pid) {
            Ok(()) => ChildStatus::Terminated,
            Err(e) if e.raw_os_error() == Some(libc::ESRCH) => ChildStatus::Exited {
                code: None,
                signal: None,
            },
            Err(e) => {
                return Err(rmcp::ErrorData::new(
                    ErrorCode::INTERNAL_ERROR,
                    format!("Terminate child domain failed: {e}"),
                    None::<Value>,
                ));
            }
        };
        let terminated = matches!(next_status, ChildStatus::Terminated);
        if let Ok(mut status) = record.status.lock() {
            *status = next_status;
        }
        persist_child_record(&record).map_err(|e| {
            rmcp::ErrorData::new(
                ErrorCode::INTERNAL_ERROR,
                format!("Persist child registry failed: {e}"),
                None::<Value>,
            )
        })?;
        let msg = if terminated {
            format!("Terminated child domain {child_id} (pid {})", record.pid)
        } else {
            format!("Child domain {child_id} already exited")
        };
        Ok(CallToolResult::success(vec![Content::text(msg)]))
    }
}

fn invalid_params(msg: impl Into<String>) -> rmcp::ErrorData {
    rmcp::ErrorData::new(ErrorCode::INVALID_PARAMS, msg.into(), None::<Value>)
}

fn json_i32(args: &serde_json::Map<String, Value>, key: &str) -> Result<i32, rmcp::ErrorData> {
    let value = args
        .get(key)
        .ok_or_else(|| invalid_params(format!("missing `{key}`")))?;
    let n = value
        .as_i64()
        .ok_or_else(|| invalid_params(format!("`{key}` must be an integer")))?;
    i32::try_from(n).map_err(|_| invalid_params(format!("`{key}` is out of range")))
}

fn json_string<'a>(
    args: &'a serde_json::Map<String, Value>,
    key: &str,
) -> Result<&'a str, rmcp::ErrorData> {
    args.get(key)
        .and_then(|v| v.as_str())
        .ok_or_else(|| invalid_params(format!("missing string `{key}`")))
}

fn json_optional_string<'a>(
    args: &'a serde_json::Map<String, Value>,
    key: &str,
) -> Result<Option<&'a str>, rmcp::ErrorData> {
    let Some(value) = args.get(key) else {
        return Ok(None);
    };
    value
        .as_str()
        .map(Some)
        .ok_or_else(|| invalid_params(format!("`{key}` must be a string")))
}

fn json_string_vec(
    args: &serde_json::Map<String, Value>,
    key: &str,
) -> Result<Vec<String>, rmcp::ErrorData> {
    let value = args
        .get(key)
        .ok_or_else(|| invalid_params(format!("missing `{key}`")))?;
    let arr = value
        .as_array()
        .ok_or_else(|| invalid_params(format!("`{key}` must be an array of strings")))?;
    arr.iter()
        .map(|v| {
            v.as_str()
                .map(ToString::to_string)
                .ok_or_else(|| invalid_params(format!("`{key}` must be an array of strings")))
        })
        .collect()
}

fn json_optional_u32(
    args: &serde_json::Map<String, Value>,
    key: &str,
) -> Result<Option<u32>, rmcp::ErrorData> {
    let Some(value) = args.get(key) else {
        return Ok(None);
    };
    let n = value
        .as_u64()
        .ok_or_else(|| invalid_params(format!("`{key}` must be a non-negative integer")))?;
    Ok(Some(u32::try_from(n).map_err(|_| {
        invalid_params(format!("`{key}` is out of range"))
    })?))
}

fn json_optional_usize(
    args: &serde_json::Map<String, Value>,
    key: &str,
) -> Result<Option<usize>, rmcp::ErrorData> {
    let Some(value) = args.get(key) else {
        return Ok(None);
    };
    let n = value
        .as_u64()
        .ok_or_else(|| invalid_params(format!("`{key}` must be a non-negative integer")))?;
    Ok(Some(usize::try_from(n).map_err(|_| {
        invalid_params(format!("`{key}` is out of range"))
    })?))
}

fn child_id_arg(args: &serde_json::Map<String, Value>) -> Result<u32, rmcp::ErrorData> {
    match json_optional_u32(args, "child_id")? {
        Some(id) => Ok(id),
        None => json_optional_u32(args, "domain_id")?
            .ok_or_else(|| invalid_params("missing `child_id`")),
    }
}

fn latest_run_feedback(root: &std::path::Path) -> Option<PathBuf> {
    let runs = root.join(".actplane").join("runs");
    let mut candidates = Vec::new();
    for entry in std::fs::read_dir(runs).ok()?.flatten() {
        let path = entry.path().join("feedback.txt");
        let modified = std::fs::metadata(&path).ok()?.modified().ok()?;
        candidates.push((modified, path));
    }
    candidates.sort_by_key(|(modified, _)| *modified);
    candidates.pop().map(|(_, path)| path)
}

fn child_launch_id() -> String {
    let now = SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    format!("child-{}-{now}", std::process::id())
}

fn child_record_json(record: &ChildRecord) -> serde_json::Value {
    let status = record
        .status
        .lock()
        .map(|s| child_status_json(&s))
        .unwrap_or_else(|_| serde_json::json!({ "state": "unknown" }));
    serde_json::json!({
        "launch_id": record.launch_id,
        "pid": record.pid,
        "child_id": record.child_id,
        "cmd": &record.cmd,
        "stdout": record.stdout.display().to_string(),
        "stderr": record.stderr.display().to_string(),
        "meta": record.meta.display().to_string(),
        "proc_start_time": record.proc_start_time,
        "status": status,
    })
}

fn child_status_json(status: &ChildStatus) -> serde_json::Value {
    match status {
        ChildStatus::Running => serde_json::json!({ "state": "running" }),
        ChildStatus::Exited { code, signal } => serde_json::json!({
            "state": "exited",
            "code": code,
            "signal": signal,
        }),
        ChildStatus::Terminated => serde_json::json!({ "state": "terminated" }),
    }
}

fn persist_child_record(record: &ChildRecord) -> std::io::Result<()> {
    if let Some(parent) = record.meta.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let text =
        serde_json::to_string_pretty(&child_record_json(record)).map_err(std::io::Error::other)?;
    std::fs::write(&record.meta, text)
}

fn load_child_records(project_dir: &std::path::Path) -> HashMap<u32, ChildRecord> {
    let root = project_dir.join(".actplane").join("children");
    let mut records = HashMap::new();
    let Ok(entries) = std::fs::read_dir(root) else {
        return records;
    };
    for entry in entries.flatten() {
        let log_dir = entry.path();
        let meta = log_dir.join("meta.json");
        let Ok(text) = std::fs::read_to_string(&meta) else {
            continue;
        };
        let Ok(value) = serde_json::from_str::<Value>(&text) else {
            continue;
        };
        let Some(mut record) = child_record_from_meta(&value, log_dir) else {
            continue;
        };
        refresh_child_record_status(&mut record);
        records.insert(record.child_id, record);
    }
    records
}

fn child_record_from_meta(value: &Value, log_dir: PathBuf) -> Option<ChildRecord> {
    let pid = i32::try_from(value.get("pid")?.as_i64()?).ok()?;
    let child_id = u32::try_from(value.get("child_id")?.as_u64()?).ok()?;
    let launch_id = value
        .get("launch_id")
        .and_then(Value::as_str)
        .map(ToString::to_string)
        .or_else(|| {
            log_dir
                .file_name()
                .and_then(|s| s.to_str())
                .map(ToString::to_string)
        })?;
    let cmd = value
        .get("cmd")
        .and_then(Value::as_array)?
        .iter()
        .map(|v| v.as_str().map(ToString::to_string))
        .collect::<Option<Vec<_>>>()?;
    let stdout = value
        .get("stdout")
        .and_then(Value::as_str)
        .map(PathBuf::from)
        .unwrap_or_else(|| log_dir.join("stdout.log"));
    let stderr = value
        .get("stderr")
        .and_then(Value::as_str)
        .map(PathBuf::from)
        .unwrap_or_else(|| log_dir.join("stderr.log"));
    let meta = value
        .get("meta")
        .and_then(Value::as_str)
        .map(PathBuf::from)
        .unwrap_or_else(|| log_dir.join("meta.json"));
    let proc_start_time = value.get("proc_start_time").and_then(Value::as_u64);
    let status = value
        .get("status")
        .and_then(child_status_from_json)
        .unwrap_or(ChildStatus::Running);
    Some(ChildRecord {
        launch_id,
        pid,
        child_id,
        cmd,
        stdout,
        stderr,
        meta,
        proc_start_time,
        status: Arc::new(Mutex::new(status)),
    })
}

fn child_status_from_json(value: &Value) -> Option<ChildStatus> {
    match value.get("state")?.as_str()? {
        "running" => Some(ChildStatus::Running),
        "exited" => Some(ChildStatus::Exited {
            code: value
                .get("code")
                .and_then(Value::as_i64)
                .and_then(|n| i32::try_from(n).ok()),
            signal: value
                .get("signal")
                .and_then(Value::as_i64)
                .and_then(|n| i32::try_from(n).ok()),
        }),
        "terminated" => Some(ChildStatus::Terminated),
        _ => None,
    }
}

fn refresh_child_record_status(record: &mut ChildRecord) {
    let Ok(mut status) = record.status.lock() else {
        return;
    };
    if !matches!(*status, ChildStatus::Running) {
        return;
    }
    if process_identity_matches(record) {
        return;
    }
    *status = ChildStatus::Exited {
        code: None,
        signal: None,
    };
    drop(status);
    let _ = persist_child_record(record);
}

fn process_identity_matches(record: &ChildRecord) -> bool {
    if record.pid <= 0 {
        return false;
    }
    match (record.proc_start_time, proc_start_time(record.pid)) {
        (Some(expected), Some(actual)) => expected == actual,
        (Some(_), None) => false,
        (None, _) => process_exists(record.pid),
    }
}

fn process_exists(pid: i32) -> bool {
    let rc = unsafe { libc::kill(pid, 0) };
    if rc == 0 {
        return true;
    }
    let err = std::io::Error::last_os_error();
    err.raw_os_error() != Some(libc::ESRCH)
}

fn proc_start_time(pid: i32) -> Option<u64> {
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat")).ok()?;
    let (_, rest) = stat.rsplit_once(") ")?;
    rest.split_whitespace().nth(19)?.parse().ok()
}

fn read_log_json(path: &std::path::Path, max_bytes: usize) -> Result<Value, rmcp::ErrorData> {
    let mut file = match std::fs::File::open(path) {
        Ok(file) => file,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            return Ok(serde_json::json!({
                "path": path.display().to_string(),
                "content": "",
                "truncated": false,
                "missing": true,
            }));
        }
        Err(e) => {
            return Err(rmcp::ErrorData::new(
                ErrorCode::INTERNAL_ERROR,
                format!("Read child log failed: {e}"),
                None::<Value>,
            ));
        }
    };
    let len = file
        .metadata()
        .map_err(|e| {
            rmcp::ErrorData::new(
                ErrorCode::INTERNAL_ERROR,
                format!("Read child log metadata failed: {e}"),
                None::<Value>,
            )
        })?
        .len();
    let start = len.saturating_sub(max_bytes as u64);
    file.seek(SeekFrom::Start(start)).map_err(|e| {
        rmcp::ErrorData::new(
            ErrorCode::INTERNAL_ERROR,
            format!("Seek child log failed: {e}"),
            None::<Value>,
        )
    })?;
    let mut buf = Vec::new();
    file.read_to_end(&mut buf).map_err(|e| {
        rmcp::ErrorData::new(
            ErrorCode::INTERNAL_ERROR,
            format!("Read child log failed: {e}"),
            None::<Value>,
        )
    })?;
    Ok(serde_json::json!({
        "path": path.display().to_string(),
        "content": String::from_utf8_lossy(&buf),
        "truncated": start > 0,
        "missing": false,
    }))
}

fn spawn_stopped_child(
    cmd: &[String],
    cwd: &std::path::Path,
    log_dir: &std::path::Path,
) -> Result<Child, rmcp::ErrorData> {
    std::fs::create_dir_all(log_dir).map_err(|e| {
        rmcp::ErrorData::new(
            ErrorCode::INTERNAL_ERROR,
            format!("Create child log dir failed: {e}"),
            None::<Value>,
        )
    })?;
    let stdout = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_dir.join("stdout.log"))
        .map_err(|e| {
            rmcp::ErrorData::new(
                ErrorCode::INTERNAL_ERROR,
                format!("Open child stdout log failed: {e}"),
                None::<Value>,
            )
        })?;
    let stderr = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_dir.join("stderr.log"))
        .map_err(|e| {
            rmcp::ErrorData::new(
                ErrorCode::INTERNAL_ERROR,
                format!("Open child stderr log failed: {e}"),
                None::<Value>,
            )
        })?;
    let mut child = Command::new("/bin/sh");
    child.arg("-c");
    child.arg("kill -STOP $$; exec \"$@\"");
    child.arg("actplane-child");
    child.args(cmd);
    if cwd.is_dir() {
        child.current_dir(cwd);
    }
    child.stdin(Stdio::null());
    child.stdout(Stdio::from(stdout));
    child.stderr(Stdio::from(stderr));
    #[cfg(unix)]
    unsafe {
        child.pre_exec(|| {
            if libc::setpgid(0, 0) != 0 {
                return Err(std::io::Error::last_os_error());
            }
            Ok(())
        });
    }
    child.spawn().map_err(|e| {
        rmcp::ErrorData::new(
            ErrorCode::INTERNAL_ERROR,
            format!("Spawn child failed: {e}"),
            None::<Value>,
        )
    })
}

fn kill_and_wait(mut child: Child) {
    let _ = terminate_process_group_with(child.id() as i32, libc::SIGKILL);
    let _ = child.wait();
}

fn send_signal(pid: i32, sig: i32) -> std::io::Result<()> {
    let rc = unsafe { libc::kill(pid, sig) };
    if rc == 0 {
        Ok(())
    } else {
        Err(std::io::Error::last_os_error())
    }
}

fn terminate_process_group(pid: i32) -> std::io::Result<()> {
    terminate_process_group_with(pid, libc::SIGTERM)
}

fn terminate_process_group_with(pid: i32, sig: i32) -> std::io::Result<()> {
    let rc = unsafe { libc::kill(-pid, sig) };
    if rc == 0 {
        Ok(())
    } else {
        Err(std::io::Error::last_os_error())
    }
}

// ── ServerHandler ───────────────────────────────────────────────────

impl ServerHandler for ActPlaneMcp {
    fn get_info(&self) -> ServerInfo {
        ServerInfo::new(
            ServerCapabilities::builder()
                .enable_resources()
                .enable_tools()
                .build(),
        )
        .with_instructions(
            "ActPlane: OS-level agent harness. This server exposes policy \
                 validation and the latest corrective feedback from the kernel \
                 enforcer.",
        )
    }

    fn list_tools(
        &self,
        _request: Option<PaginatedRequestParams>,
        _context: rmcp::service::RequestContext<rmcp::service::RoleServer>,
    ) -> impl std::future::Future<Output = Result<ListToolsResult, rmcp::ErrorData>> + Send + '_
    {
        let empty_schema: serde_json::Map<String, Value> =
            serde_json::from_value(serde_json::json!({
                "type": "object",
                "properties": {},
            }))
            .unwrap();
        let bind_schema: serde_json::Map<String, Value> = serde_json::from_value(serde_json::json!({
            "type": "object",
            "properties": {
                "pid": {
                    "type": "integer",
                    "description": "Linux pid of the already-started subagent root process to bind."
                },
                "child_id": {
                    "type": "integer",
                    "description": "Optional runtime domain id. Defaults to pid."
                },
                "scope_id": {
                    "type": "integer",
                    "description": "Optional narrower scope id. Defaults to the parent scope."
                }
            },
            "required": ["pid"]
        }))
        .unwrap();
        let append_schema: serde_json::Map<String, Value> =
            serde_json::from_value(serde_json::json!({
                "type": "object",
                "properties": {
                    "target_id": {
                        "type": "integer",
                        "description": "Runtime domain id to receive the delta. Defaults to the auto-attached parent domain."
                    },
                    "policy": {
                        "type": "string",
                        "description": "Append-only ActPlane DSL fragment to compile and submit to the target domain."
                    }
                },
                "required": ["policy"]
            }))
            .unwrap();
        let launch_schema: serde_json::Map<String, Value> =
            serde_json::from_value(serde_json::json!({
                "type": "object",
                "properties": {
                    "cmd": {
                        "type": "array",
                        "items": { "type": "string" },
                        "description": "Command argv to launch as the child-domain root process."
                    },
                    "child_id": {
                        "type": "integer",
                        "description": "Optional runtime domain id. Defaults to the launched pid."
                    },
                    "scope_id": {
                        "type": "integer",
                        "description": "Optional narrower scope id. Defaults to the parent scope."
                    },
                    "policy": {
                        "type": "string",
                        "description": "Optional append-only ActPlane DSL fragment installed into the child domain before resume."
                    }
                },
                "required": ["cmd"]
            }))
            .unwrap();
        let child_id_schema: serde_json::Map<String, Value> =
            serde_json::from_value(serde_json::json!({
                "type": "object",
                "properties": {
                    "child_id": {
                        "type": "integer",
                        "description": "Child runtime domain id returned by launch_child_domain."
                    },
                    "domain_id": {
                        "type": "integer",
                        "description": "Alias for child_id."
                    }
                },
                "oneOf": [
                    { "required": ["child_id"] },
                    { "required": ["domain_id"] }
                ]
            }))
            .unwrap();
        let read_logs_schema: serde_json::Map<String, Value> =
            serde_json::from_value(serde_json::json!({
                "type": "object",
                "properties": {
                    "child_id": {
                        "type": "integer",
                        "description": "Child runtime domain id returned by launch_child_domain."
                    },
                    "domain_id": {
                        "type": "integer",
                        "description": "Alias for child_id."
                    },
                    "stream": {
                        "type": "string",
                        "enum": ["stdout", "stderr", "both"],
                        "description": "Which detached log stream to read. Defaults to both."
                    },
                    "max_bytes": {
                        "type": "integer",
                        "description": "Maximum bytes to return per stream, clamped to 65536. Defaults to 8192."
                    }
                },
                "oneOf": [
                    { "required": ["child_id"] },
                    { "required": ["domain_id"] }
                ]
            }))
            .unwrap();
        let tools = vec![
            Tool::new(
                "reload_policy",
                "Hot-reload the policy from actplane.yaml into the running \
                 eBPF engine without restarting. Accumulated state (process \
                 labels, file labels, session gates) is preserved.",
                empty_schema.clone(),
            ),
            Tool::new(
                "bind_child_domain",
                "Bind a subagent root pid to a child runtime policy domain under \
                 the auto-attached repo agent. The child can bind rules for its \
                 own domain but does not receive label-creation authority.",
                bind_schema,
            ),
            Tool::new(
                "append_policy_delta",
                "Append a scoped DSL policy delta to a runtime domain through \
                 the kernel-admitted path. The server preserves rule metadata \
                 so future kernel violations report the appended rule reason.",
                append_schema,
            ),
            Tool::new(
                "launch_child_domain",
                "Launch a subagent command stopped, bind it to a child runtime \
                 policy domain, optionally append its local policy, then resume \
                 it. Child stdout/stderr are detached from MCP stdio.",
                launch_schema,
            ),
            Tool::new(
                "list_child_domains",
                "List subagents launched by this MCP server, including child \
                 domain id, root pid, detached log paths, command argv, and \
                 current exit status.",
                empty_schema,
            ),
            Tool::new(
                "read_child_domain_logs",
                "Read bounded stdout/stderr logs for a subagent launched by \
                 launch_child_domain.",
                read_logs_schema,
            ),
            Tool::new(
                "terminate_child_domain",
                "Terminate the process group for a subagent launched by \
                 launch_child_domain and mark it in the local lifecycle \
                 registry.",
                child_id_schema,
            ),
        ];
        std::future::ready(Ok(ListToolsResult {
            tools,
            ..Default::default()
        }))
    }

    fn call_tool(
        &self,
        request: CallToolRequestParams,
        _context: rmcp::service::RequestContext<rmcp::service::RoleServer>,
    ) -> impl std::future::Future<Output = Result<CallToolResult, rmcp::ErrorData>> + Send + '_
    {
        let result = match request.name.as_ref() {
            "reload_policy" => self.do_reload_policy(),
            "bind_child_domain" => self.do_bind_child_domain(request.arguments),
            "append_policy_delta" => self.do_append_policy_delta(request.arguments),
            "launch_child_domain" => self.do_launch_child_domain(request.arguments),
            "list_child_domains" => self.do_list_child_domains(),
            "read_child_domain_logs" => self.do_read_child_domain_logs(request.arguments),
            "terminate_child_domain" => self.do_terminate_child_domain(request.arguments),
            _ => Err(rmcp::ErrorData::new(
                ErrorCode::METHOD_NOT_FOUND,
                format!("Unknown tool: {}", request.name),
                None::<Value>,
            )),
        };
        std::future::ready(result)
    }

    fn list_resources(
        &self,
        _request: Option<PaginatedRequestParams>,
        _context: rmcp::service::RequestContext<rmcp::service::RoleServer>,
    ) -> impl std::future::Future<Output = Result<ListResourcesResult, rmcp::ErrorData>> + Send + '_
    {
        let resources = vec![
            Annotated::new(
                RawResource {
                    uri: POLICY_RESOURCE_URI.into(),
                    name: "actplane-policy".into(),
                    title: Some("ActPlane Policy Status".into()),
                    description: Some("Current policy validation result from actplane.yaml".into()),
                    mime_type: Some("text/plain".into()),
                    size: None,
                    icons: None,
                    meta: None,
                },
                None,
            ),
            Annotated::new(
                RawResource {
                    uri: FEEDBACK_RESOURCE_URI.into(),
                    name: "actplane-feedback".into(),
                    title: Some("ActPlane Feedback".into()),
                    description: Some(
                        "Latest corrective feedback from .actplane/last-violation.txt".into(),
                    ),
                    mime_type: Some("text/plain".into()),
                    size: None,
                    icons: None,
                    meta: None,
                },
                None,
            ),
        ];
        std::future::ready(Ok(ListResourcesResult {
            resources,
            ..Default::default()
        }))
    }

    fn read_resource(
        &self,
        request: ReadResourceRequestParams,
        _context: rmcp::service::RequestContext<rmcp::service::RoleServer>,
    ) -> impl std::future::Future<Output = Result<ReadResourceResult, rmcp::ErrorData>> + Send + '_
    {
        let result = if request.uri == POLICY_RESOURCE_URI {
            let text = self.load_and_validate();
            Ok(ReadResourceResult::new(vec![
                ResourceContents::TextResourceContents {
                    uri: POLICY_RESOURCE_URI.into(),
                    mime_type: Some("text/plain".into()),
                    text,
                    meta: None,
                },
            ]))
        } else if request.uri == FEEDBACK_RESOURCE_URI {
            let text = self.load_feedback();
            Ok(ReadResourceResult::new(vec![
                ResourceContents::TextResourceContents {
                    uri: FEEDBACK_RESOURCE_URI.into(),
                    mime_type: Some("text/plain".into()),
                    text,
                    meta: None,
                },
            ]))
        } else {
            Err(rmcp::ErrorData::new(
                ErrorCode::INVALID_PARAMS,
                format!("Unknown resource: {}", request.uri),
                None::<Value>,
            ))
        };
        std::future::ready(result)
    }
}

// ── File watcher ────────────────────────────────────────────────────

async fn watch_policy_file(server: Arc<ActPlaneMcp>, peer: Peer<RoleServer>) {
    let mut last_policy_mtime = server.policy_mtime();
    let mut last_feedback_mtime = server.feedback_mtime();

    // Send initial validation on startup.
    let initial = server.load_and_validate();
    let _ = peer
        .notify_logging_message(LoggingMessageNotificationParam::new(
            LoggingLevel::Info,
            Value::String(initial),
        ))
        .await;

    loop {
        tokio::time::sleep(WATCH_INTERVAL).await;

        let current_policy_mtime = server.policy_mtime();
        if current_policy_mtime != last_policy_mtime {
            last_policy_mtime = current_policy_mtime;

            let result = server.load_and_validate();
            let level = if result.contains("error") || result.contains("No actplane") {
                LoggingLevel::Error
            } else {
                LoggingLevel::Info
            };

            let _ = peer
                .notify_logging_message(LoggingMessageNotificationParam::new(
                    level,
                    Value::String(result),
                ))
                .await;

            let _ = peer
                .notify_resource_updated(ResourceUpdatedNotificationParam::new(POLICY_RESOURCE_URI))
                .await;
        }

        let current_feedback_mtime = server.feedback_mtime();
        if current_feedback_mtime != last_feedback_mtime {
            last_feedback_mtime = current_feedback_mtime;
            let result = server.load_feedback();

            let _ = peer
                .notify_logging_message(LoggingMessageNotificationParam::new(
                    LoggingLevel::Info,
                    Value::String(result),
                ))
                .await;

            let _ = peer
                .notify_resource_updated(ResourceUpdatedNotificationParam::new(
                    FEEDBACK_RESOURCE_URI,
                ))
                .await;
        }
    }
}

pub async fn run_mcp_server_with_control(
    control: Option<Arc<EngineControl>>,
) -> std::result::Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let server = ActPlaneMcp::new_with_control(control);
    let server_arc = Arc::new(server.clone());
    let transport = stdio();
    let service = server.serve(transport).await?;

    let peer = service.peer().clone();
    tokio::spawn(watch_policy_file(server_arc, peer));

    service.waiting().await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bind_child_domain_args_parse_required_and_optional_fields() {
        let args = serde_json::json!({
            "pid": 1234,
            "child_id": 5678,
            "scope_id": 9,
            "cmd": ["/bin/true", "--flag"],
            "policy": "rule r:\n  notify exec \"git\"\n  because \"test\""
        })
        .as_object()
        .expect("object")
        .clone();

        assert_eq!(json_i32(&args, "pid").expect("pid"), 1234);
        assert_eq!(
            json_optional_u32(&args, "child_id").expect("child_id"),
            Some(5678)
        );
        assert_eq!(
            json_optional_u32(&args, "scope_id").expect("scope_id"),
            Some(9)
        );
        assert_eq!(json_optional_u32(&args, "missing").expect("missing"), None);
        assert_eq!(
            json_string(&args, "policy").expect("policy"),
            "rule r:\n  notify exec \"git\"\n  because \"test\""
        );
        assert_eq!(
            json_optional_string(&args, "policy").expect("optional policy"),
            Some("rule r:\n  notify exec \"git\"\n  because \"test\"")
        );
        assert_eq!(
            json_string_vec(&args, "cmd").expect("cmd"),
            vec!["/bin/true".to_string(), "--flag".to_string()]
        );
    }

    #[test]
    fn bind_child_domain_args_reject_bad_types_and_ranges() {
        let string_pid = serde_json::json!({ "pid": "1234" })
            .as_object()
            .expect("object")
            .clone();
        assert!(json_i32(&string_pid, "pid").is_err());

        let negative_child = serde_json::json!({ "child_id": -1 })
            .as_object()
            .expect("object")
            .clone();
        assert!(json_optional_u32(&negative_child, "child_id").is_err());

        let huge_scope = serde_json::json!({ "scope_id": u64::MAX })
            .as_object()
            .expect("object")
            .clone();
        assert!(json_optional_u32(&huge_scope, "scope_id").is_err());

        let numeric_policy = serde_json::json!({ "policy": 7 })
            .as_object()
            .expect("object")
            .clone();
        assert!(json_string(&numeric_policy, "policy").is_err());
        assert!(json_optional_string(&numeric_policy, "policy").is_err());

        let bad_cmd = serde_json::json!({ "cmd": ["/bin/true", 7] })
            .as_object()
            .expect("object")
            .clone();
        assert!(json_string_vec(&bad_cmd, "cmd").is_err());
    }

    #[test]
    fn spawn_stopped_child_can_be_killed_without_stdio_inheritance() {
        let cmd = vec!["/bin/true".to_string()];
        let log_dir = std::env::temp_dir().join(child_launch_id());
        let mut child = spawn_stopped_child(&cmd, &std::env::current_dir().expect("cwd"), &log_dir)
            .expect("spawn child");
        terminate_process_group_with(child.id() as i32, libc::SIGKILL).expect("kill child group");
        let _ = child.wait().expect("wait child");
        assert!(log_dir.join("stdout.log").is_file());
        assert!(log_dir.join("stderr.log").is_file());
        let _ = std::fs::remove_dir_all(log_dir);
    }

    #[test]
    fn child_record_json_includes_status_and_log_paths() {
        let status = Arc::new(Mutex::new(ChildStatus::Exited {
            code: Some(7),
            signal: None,
        }));
        let record = ChildRecord {
            launch_id: "child-test".to_string(),
            pid: 123,
            child_id: 456,
            cmd: vec!["/bin/echo".to_string(), "hello".to_string()],
            stdout: PathBuf::from("/tmp/stdout.log"),
            stderr: PathBuf::from("/tmp/stderr.log"),
            meta: PathBuf::from("/tmp/meta.json"),
            proc_start_time: Some(99),
            status,
        };
        let value = child_record_json(&record);
        assert_eq!(value["launch_id"], "child-test");
        assert_eq!(value["pid"], 123);
        assert_eq!(value["child_id"], 456);
        assert_eq!(value["cmd"][1], "hello");
        assert_eq!(value["stdout"], "/tmp/stdout.log");
        assert_eq!(value["proc_start_time"], 99);
        assert_eq!(value["status"]["state"], "exited");
        assert_eq!(value["status"]["code"], 7);
    }

    #[test]
    fn read_log_json_returns_bounded_tail() {
        let path = std::env::temp_dir().join(format!(
            "actplane-mcp-log-test-{}-{}.log",
            std::process::id(),
            child_launch_id()
        ));
        std::fs::write(&path, "0123456789").expect("write log");
        let value = read_log_json(&path, 4).expect("read log");
        assert_eq!(value["content"], "6789");
        assert_eq!(value["truncated"], true);
        assert_eq!(value["missing"], false);
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn child_registry_persists_and_loads_records() {
        let project_dir = std::env::temp_dir().join(format!(
            "actplane-mcp-registry-test-{}-{}",
            std::process::id(),
            child_launch_id()
        ));
        let log_dir = project_dir
            .join(".actplane")
            .join("children")
            .join("child-persist-test");
        let status = Arc::new(Mutex::new(ChildStatus::Running));
        let record = ChildRecord {
            launch_id: "child-persist-test".to_string(),
            pid: std::process::id() as i32,
            child_id: 777,
            cmd: vec!["/bin/true".to_string()],
            stdout: log_dir.join("stdout.log"),
            stderr: log_dir.join("stderr.log"),
            meta: log_dir.join("meta.json"),
            proc_start_time: proc_start_time(std::process::id() as i32),
            status,
        };
        persist_child_record(&record).expect("persist record");

        let loaded = load_child_records(&project_dir);
        let loaded_record = loaded.get(&777).expect("loaded child record");
        assert_eq!(loaded_record.launch_id, "child-persist-test");
        assert_eq!(loaded_record.cmd, vec!["/bin/true".to_string()]);
        assert_eq!(loaded_record.stdout, log_dir.join("stdout.log"));
        assert!(matches!(
            *loaded_record.status.lock().expect("status"),
            ChildStatus::Running
        ));
        let _ = std::fs::remove_dir_all(project_dir);
    }
}
