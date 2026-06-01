use std::collections::HashMap;
use std::io::Write;
use std::path::Path;

use crate::{dsl, feedback};

#[derive(serde::Deserialize)]
pub(crate) struct Violation {
    pid: i32,
    ppid: i32,
    comm: String,
    target: String,
    rule_id: usize,
    #[allow(dead_code)]
    effect: Option<String>,
    blocked: Option<bool>,
    killed: Option<bool>,
    #[allow(dead_code)]
    taint_label: u64,
    #[allow(dead_code)]
    matched_label: u64,
    provenance: Option<ViolationProvenance>,
}

#[derive(Clone, serde::Deserialize)]
struct ViolationProvenance {
    label: u64,
    timestamp_ns: u64,
    pid: i32,
    op: u32,
    target: String,
}

/// Map the eBPF crate's violation into the collector's reporting struct.
pub(crate) fn to_violation(v: &ebpf_ifc_engine::Violation) -> Violation {
    Violation {
        pid: v.pid,
        ppid: v.ppid,
        comm: v.comm.clone(),
        target: v.target.clone(),
        rule_id: v.rule_id as usize,
        effect: Some(
            match v.effect {
                0 => "notify",
                1 => "block",
                2 => "kill",
                _ => "unknown",
            }
            .to_string(),
        ),
        blocked: Some(v.blocked),
        killed: Some(v.killed),
        taint_label: v.label,
        matched_label: v.matched_label,
        provenance: v.provenance.as_ref().map(|p| ViolationProvenance {
            label: p.label,
            timestamp_ns: p.timestamp_ns,
            pid: p.pid,
            op: p.op,
            target: p.target.clone(),
        }),
    }
}

/// Report a violation: a human one-liner to stdout, plus the structured
/// corrective-feedback payload appended to the reason file.
pub(crate) fn report(
    meta: &[dsl::RuleMeta],
    labels: &HashMap<String, u64>,
    v: &Violation,
    feedback_file: Option<&Path>,
) {
    let verb = if v.killed.unwrap_or(false) {
        "KILLED"
    } else if v.blocked.unwrap_or(false) {
        "BLOCKED"
    } else {
        "VIOLATION"
    };
    let m = meta.get(v.rule_id);
    let reason = m.map(|m| m.reason.as_str()).unwrap_or("");
    let effect = v
        .effect
        .as_deref()
        .or_else(|| m.map(|m| effect_name(m.effect)))
        .unwrap_or("");
    println!(
        "🚫 {}: process '{}' (pid {}, ppid {}) — {}",
        verb, v.comm, v.pid, v.ppid, v.target
    );
    if !effect.is_empty() {
        println!("   effect: {}", effect);
    }
    if !reason.is_empty() {
        println!("   reason: {}", reason);
    }
    if let Some(p) = &v.provenance {
        println!(
            "   provenance: pid {} {} {} -> label {}",
            p.pid,
            kernel_op_name(p.op),
            p.target,
            label_name(labels, p.label)
        );
    }

    if let Some(path) = feedback_file {
        append_violation_feedback(meta, labels, v, path);
    }
}

pub(crate) fn append_violation_feedback(
    meta: &[dsl::RuleMeta],
    labels: &HashMap<String, u64>,
    v: &Violation,
    path: &Path,
) {
    let Some(m) = meta.get(v.rule_id) else {
        return;
    };
    let op = m.ops.first().map(|s| s.as_str()).unwrap_or("op");
    let provenance = v.provenance.as_ref().map(|p| feedback::Provenance {
        label: label_name(labels, p.label),
        origin_pid: p.pid,
        origin_op: kernel_op_name(p.op).to_string(),
        origin_target: if p.target.is_empty() {
            "<unknown>".to_string()
        } else {
            p.target.clone()
        },
        origin_timestamp_ns: p.timestamp_ns,
    });
    let payload = feedback::format_payload(feedback::PayloadInput {
        name: &m.name,
        op,
        target: &v.target,
        reason: &m.reason,
        effect: m.effect,
        blocked: v.blocked.unwrap_or(false),
        killed: v.killed.unwrap_or(false),
        provenance: provenance.as_ref(),
    });
    if let Err(e) = append_feedback(path, &payload) {
        eprintln!("ActPlane: writing feedback file {}: {}", path.display(), e);
    }
}

fn label_name(labels: &HashMap<String, u64>, label: u64) -> String {
    labels
        .iter()
        .find_map(|(name, bit)| (*bit == label).then(|| name.clone()))
        .unwrap_or_else(|| format!("0x{label:x}"))
}

fn kernel_op_name(op: u32) -> &'static str {
    match op {
        0 => "exec",
        1 => "read",
        2 => "write",
        3 => "connect",
        _ => "op",
    }
}

fn append_feedback(path: &Path, payload: &str) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let mut f = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)?;
    writeln!(f, "{}\n----", payload)
}

fn effect_name(effect: dsl::ast::Effect) -> &'static str {
    match effect {
        dsl::ast::Effect::Notify => "notify",
        dsl::ast::Effect::Block => "block",
        dsl::ast::Effect::Kill => "kill",
    }
}
