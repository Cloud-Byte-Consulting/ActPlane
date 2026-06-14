use std::collections::HashMap;
use std::io::Write;
use std::path::Path;

use crate::audit;
use crate::{dsl, feedback};
use serde_json::json;

#[derive(Clone)]
pub(crate) struct RuleFeedbackContext {
    pub(crate) meta: dsl::RuleMeta,
    pub(crate) labels: HashMap<String, u64>,
}

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

impl Violation {
    pub(crate) fn rule_id(&self) -> usize {
        self.rule_id
    }
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
    event_file: Option<&Path>,
) {
    let ctx = meta.get(v.rule_id).map(|m| RuleFeedbackContext {
        meta: m.clone(),
        labels: labels.clone(),
    });
    report_with_context(ctx.as_ref(), v, feedback_file, event_file);
}

pub(crate) fn contexts_from_compiled(compiled: &dsl::Compiled) -> Vec<RuleFeedbackContext> {
    compiled
        .meta
        .iter()
        .cloned()
        .map(|meta| RuleFeedbackContext {
            meta,
            labels: compiled.labels.clone(),
        })
        .collect()
}

pub(crate) fn report_with_context(
    ctx: Option<&RuleFeedbackContext>,
    v: &Violation,
    feedback_file: Option<&Path>,
    event_file: Option<&Path>,
) {
    let verb = if v.killed.unwrap_or(false) {
        "KILLED"
    } else if v.blocked.unwrap_or(false) {
        "BLOCKED"
    } else {
        "VIOLATION"
    };
    let m = ctx.map(|ctx| &ctx.meta);
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
            ctx.map(|ctx| label_name(&ctx.labels, p.label))
                .unwrap_or_else(|| format!("0x{:x}", p.label))
        );
    }

    if let Some(path) = feedback_file {
        append_violation_feedback_context(ctx, v, path);
    }
    if let Some(path) = event_file {
        append_violation_event_context(ctx, v, path);
    }
}

pub(crate) fn append_violation_feedback_context(
    ctx: Option<&RuleFeedbackContext>,
    v: &Violation,
    path: &Path,
) {
    let Some(ctx) = ctx else {
        return;
    };
    let m = &ctx.meta;
    let op = m.ops.first().map(|s| s.as_str()).unwrap_or("op");
    let provenance = v.provenance.as_ref().map(|p| feedback::Provenance {
        label: label_name(&ctx.labels, p.label),
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

pub(crate) fn append_violation_event_context(
    ctx: Option<&RuleFeedbackContext>,
    v: &Violation,
    path: &Path,
) {
    let m = ctx.map(|ctx| &ctx.meta);
    let action = if v.killed.unwrap_or(false) {
        "kill"
    } else if v.blocked.unwrap_or(false) {
        "block"
    } else if m.is_some_and(|m| m.effect == dsl::ast::Effect::Block) {
        "unsupported"
    } else {
        "report"
    };
    let mut record = json!({
        "event": "taint_violation",
        "pid": v.pid,
        "ppid": v.ppid,
        "comm": &v.comm,
        "target": &v.target,
        "rule_id": v.rule_id,
        "effect": v.effect.as_deref().or_else(|| m.map(|m| effect_name(m.effect))).unwrap_or(""),
        "action": action,
        "blocked": v.blocked.unwrap_or(false),
        "killed": v.killed.unwrap_or(false),
        "taint_label": format!("0x{:x}", v.taint_label),
        "matched_label": format!("0x{:x}", v.matched_label),
    });
    if let Some(m) = m {
        record["rule"] = json!({
            "name": &m.name,
            "reason": &m.reason,
            "effect": effect_name(m.effect),
            "ops": &m.ops,
        });
    }
    if let Some(ctx) = ctx {
        record["matched_label_name"] = json!(label_name(&ctx.labels, v.matched_label));
    }
    if let Some(p) = &v.provenance {
        let label = ctx
            .map(|ctx| label_name(&ctx.labels, p.label))
            .unwrap_or_else(|| format!("0x{:x}", p.label));
        record["provenance"] = json!({
            "label": label,
            "label_mask": format!("0x{:x}", p.label),
            "origin_pid": p.pid,
            "origin_op": kernel_op_name(p.op),
            "origin_target": &p.target,
            "origin_timestamp_ns": p.timestamp_ns,
        });
    }
    if let Err(e) = audit::append_with_schema(path, "actplane.violation.v1", &mut record) {
        eprintln!("ActPlane: writing event log {}: {}", path.display(), e);
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::dsl::ast::Effect;

    #[test]
    fn feedback_context_resolves_domain_local_label_names() {
        let path = std::env::temp_dir().join(format!(
            "actplane-report-context-{}.txt",
            std::process::id()
        ));
        let _ = std::fs::remove_file(&path);

        let mut labels = HashMap::new();
        labels.insert("LOCAL_SECRET".to_string(), 1);
        let ctx = RuleFeedbackContext {
            meta: dsl::RuleMeta {
                name: "local-rule".to_string(),
                reason: "local reason".to_string(),
                effect: Effect::Notify,
                ops: vec!["exec".to_string()],
            },
            labels,
        };
        let v = Violation {
            pid: 10,
            ppid: 1,
            comm: "git".to_string(),
            target: "git".to_string(),
            rule_id: 0,
            effect: Some("notify".to_string()),
            blocked: Some(false),
            killed: Some(false),
            taint_label: 1,
            matched_label: 1,
            provenance: Some(ViolationProvenance {
                label: 1,
                timestamp_ns: 42,
                pid: 9,
                op: 1,
                target: "/tmp/local".to_string(),
            }),
        };

        append_violation_feedback_context(Some(&ctx), &v, &path);
        let text = std::fs::read_to_string(&path).expect("feedback file");
        assert!(text.contains("acquired label LOCAL_SECRET"));
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn violation_event_context_writes_structured_jsonl() {
        let path = std::env::temp_dir().join(format!(
            "actplane-event-context-{}.jsonl",
            std::process::id()
        ));
        let _ = std::fs::remove_file(&path);

        let mut labels = HashMap::new();
        labels.insert("LOCAL_SECRET".to_string(), 1);
        let ctx = RuleFeedbackContext {
            meta: dsl::RuleMeta {
                name: "local-rule".to_string(),
                reason: "local reason".to_string(),
                effect: Effect::Kill,
                ops: vec!["exec".to_string()],
            },
            labels,
        };
        let v = Violation {
            pid: 10,
            ppid: 1,
            comm: "git".to_string(),
            target: "git".to_string(),
            rule_id: 7,
            effect: Some("kill".to_string()),
            blocked: Some(false),
            killed: Some(true),
            taint_label: 1,
            matched_label: 1,
            provenance: Some(ViolationProvenance {
                label: 1,
                timestamp_ns: 42,
                pid: 9,
                op: 1,
                target: "/tmp/local".to_string(),
            }),
        };

        append_violation_event_context(Some(&ctx), &v, &path);
        let text = std::fs::read_to_string(&path).expect("event file");
        let value: serde_json::Value = serde_json::from_str(text.trim()).expect("json line");
        assert_eq!(value["schema"], "actplane.violation.v1");
        assert_eq!(value["event"], "taint_violation");
        assert_eq!(value["rule"]["name"], "local-rule");
        assert_eq!(value["rule"]["reason"], "local reason");
        assert_eq!(value["rule_id"], 7);
        assert_eq!(value["action"], "kill");
        assert_eq!(value["matched_label_name"], "LOCAL_SECRET");
        assert_eq!(value["provenance"]["label"], "LOCAL_SECRET");

        let _ = std::fs::remove_file(&path);
    }
}
