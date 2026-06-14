use std::path::{Path, PathBuf};
use std::process::Stdio;

use serde_json::{Value, json};

use crate::config::{
    ResolvedPolicy, domain_summaries, feedback_paths, load_policy, resolve_policy,
};
use crate::dsl::ast::{Effect, Kind, Op, Policy};
use crate::runtime::{have_bpf_caps, passwordless_sudo_available};
use crate::setup::{codex_hook_has_actplane_command, project_mcp_auto_attach_ok};
use crate::{Cli, Result, dsl};

pub(crate) fn check_policy(cli: &Cli, json_output: bool) -> Result<i32> {
    let where_ = policy_ref_for_cli(cli);
    let loaded = match load_policy(cli) {
        Ok(loaded) => loaded,
        Err(e) if json_output => {
            print_check_error_json(&where_, None, &e.to_string())?;
            return Ok(1);
        }
        Err(e) => return Err(e),
    };
    let resolved = match resolve_policy(&loaded, cli.domain.as_deref()) {
        Ok(resolved) => resolved,
        Err(e) if json_output => {
            print_check_error_json(&where_, None, &e.to_string())?;
            return Ok(1);
        }
        Err(e) => return Err(e),
    };
    let where_ = loaded
        .path
        .as_ref()
        .map(|p| p.display().to_string())
        .unwrap_or_else(|| "--rule".into());
    let parsed = match dsl::parse::parse(&resolved.source) {
        Ok(p) => p,
        Err(e) => {
            if json_output {
                print_check_error_json(&where_, Some(&resolved), &e)?;
            } else {
                eprintln!("✗ policy does not compile: {}", e);
            }
            return Ok(1);
        }
    };
    let compiled = match dsl::compile_str(&resolved.source) {
        Ok(c) => c,
        Err(e) => {
            if json_output {
                print_check_error_json(&where_, Some(&resolved), &e)?;
            } else {
                eprintln!("✗ policy does not compile: {}", e);
            }
            return Ok(1);
        }
    };
    let active_lsms = active_lsms().unwrap_or_default();
    let force_tracepoint = std::env::var_os("ACTPLANE_FORCE_TRACEPOINT").is_some();
    let lsm_bpf = lsm_list_has_bpf(&active_lsms) && !force_tracepoint;
    if json_output {
        print_check_json(
            &where_,
            &resolved,
            &parsed,
            &compiled,
            &active_lsms,
            lsm_bpf,
            force_tracepoint,
        )?;
        return Ok(0);
    }

    println!("✓ {}: {} rule(s) compile.\n", where_, compiled.meta.len());
    if let Some(domain) = &resolved.domain {
        println!("domain: {}", domain.name);
        if let Some(parent) = &domain.parent {
            println!("parent: {}", parent);
        }
        println!("locked: {}", format_rule_list(&domain.locked));
        println!("default: {}\n", format_rule_list(&domain.defaults));
    }
    for (i, m) in compiled.meta.iter().enumerate() {
        let eff = format!("{:?}", m.effect).to_lowercase();
        let ops = if m.ops.is_empty() {
            "—".into()
        } else {
            m.ops.join("/")
        };
        println!("  {}. {} — {} {} ({})", i + 1, m.name, eff, ops, m.reason);
    }
    println!("\nbackend support:");
    for line in backend_support_lines(&parsed, lsm_bpf) {
        println!("  - {}", line);
    }
    let warns = backend_support_warnings(&parsed, lsm_bpf);
    if warns.is_empty() {
        println!("\n✓ no warnings.");
    } else {
        println!("\n⚠ {} warning(s):", warns.len());
        for w in &warns {
            println!("  - {}", w.message);
        }
    }
    if unsafe { libc::geteuid() } != 0 {
        println!(
            "\n(note: `check` needs no privileges; applying policies needs `sudo -E actplane run/watch`.)"
        );
    }
    Ok(0)
}

fn policy_ref_for_cli(cli: &Cli) -> String {
    cli.policy
        .as_ref()
        .map(|p| p.display().to_string())
        .unwrap_or_else(|| {
            if cli.rule.is_some() {
                "--rule".to_string()
            } else {
                "auto-discovered policy".to_string()
            }
        })
}

fn print_check_error_json(
    policy_ref: &str,
    resolved: Option<&ResolvedPolicy>,
    error: &str,
) -> Result<()> {
    let record = json!({
        "schema": "actplane.check.v1",
        "ok": false,
        "policy_ref": policy_ref,
        "domain": resolved.map(domain_json).unwrap_or(Value::Null),
        "error": error,
    });
    println!("{}", serde_json::to_string_pretty(&record)?);
    Ok(())
}

fn print_check_json(
    policy_ref: &str,
    resolved: &ResolvedPolicy,
    parsed: &Policy,
    compiled: &dsl::Compiled,
    active_lsms: &str,
    lsm_bpf: bool,
    force_tracepoint: bool,
) -> Result<()> {
    let warnings = backend_support_warnings(parsed, lsm_bpf)
        .into_iter()
        .map(|w| {
            json!({
                "code": w.code,
                "message": w.message,
            })
        })
        .collect::<Vec<_>>();
    let record = json!({
        "schema": "actplane.check.v1",
        "ok": true,
        "policy_ref": policy_ref,
        "domain": domain_json(resolved),
        "host": {
            "active_lsms": active_lsms,
            "bpf_lsm_active": lsm_bpf,
            "force_tracepoint": force_tracepoint,
        },
        "matrix_scope": "static_initial_policy_host_support",
        "matrix_note": "This reports static host/backend support for the selected initial policy. Runtime hook budgets can still reject later deltas that require hooks or matcher classes not reserved when the engine was loaded.",
        "environment": {
            "ACTPLANE_FORCE_TRACEPOINT": std::env::var("ACTPLANE_FORCE_TRACEPOINT").ok(),
            "ACTPLANE_HOOK_PROFILE": std::env::var("ACTPLANE_HOOK_PROFILE").ok(),
            "ACTPLANE_ENABLE_ADVANCED_HOOKS": std::env::var("ACTPLANE_ENABLE_ADVANCED_HOOKS").ok(),
            "ACTPLANE_RESERVE_FILE_FLOW": std::env::var("ACTPLANE_RESERVE_FILE_FLOW").ok(),
        },
        "rule_count": compiled.meta.len(),
        "rules": rule_meta_json(compiled),
        "backend_support": {
            "sources": source_support_json(parsed),
            "clauses": clause_support_json(parsed, lsm_bpf),
        },
        "warnings": warnings,
    });
    println!("{}", serde_json::to_string_pretty(&record)?);
    Ok(())
}

fn domain_json(resolved: &ResolvedPolicy) -> Value {
    match &resolved.domain {
        Some(domain) => json!({
            "name": domain.name,
            "parent": domain.parent,
            "locked": domain.locked,
            "default": domain.defaults,
            "disabled": domain.disabled,
        }),
        None => Value::Null,
    }
}

fn rule_meta_json(compiled: &dsl::Compiled) -> Vec<Value> {
    compiled
        .meta
        .iter()
        .enumerate()
        .map(|(idx, rule)| {
            let mut value = json!({
                "rule_id": idx,
                "name": rule.name,
                "effect": effect_name(rule.effect),
                "ops": rule.ops,
                "clause_op": rule.clause_op,
                "clause_source_index": rule.clause_source_index,
                "kernel_op": rule.kernel_op,
                "target_kind": kind_name(rule.target_kind),
                "target_pattern": rule.target_pattern,
                "target_arg": rule.target_arg,
                "reason": rule.reason,
            });
            if let Some(source) = &rule.source {
                value["source_ref"] = json!(source.source_ref);
                value["source_start_line"] = json!(source.start_line);
                value["source_end_line"] = json!(source.end_line);
                value["source_hash"] = json!(crate::audit::policy_hash(&source.text));
                value["source_text"] = json!(source.text);
                if let Some(line) = source.clause_start_line {
                    value["clause_start_line"] = json!(line);
                }
                if let Some(line) = source.clause_end_line {
                    value["clause_end_line"] = json!(line);
                }
                if let Some(text) = &source.clause_text {
                    value["clause_hash"] = json!(crate::audit::policy_hash(text));
                    value["clause_text"] = json!(text);
                }
                if let Some(mode) = &source.binding_mode {
                    value["binding_mode"] = json!(mode);
                }
                value["immutable"] = json!(source.binding_mode.as_deref() == Some("locked"));
            }
            value
        })
        .collect()
}

fn source_support_json(policy: &Policy) -> Vec<Value> {
    policy
        .sources
        .iter()
        .map(|source| {
            let (supported, reason, limitations) =
                source_support_detail(source.kind, &source.pattern);
            json!({
                "label": source.label,
                "kind": kind_name(source.kind),
                "pattern": source.pattern,
                "supported": supported,
                "reason": reason,
                "limitations": limitations,
            })
        })
        .collect()
}

fn clause_support_json(policy: &Policy, lsm_bpf: bool) -> Vec<Value> {
    let mut out = Vec::new();
    for rule in &policy.rules {
        for (clause_index, clause) in rule.clauses.iter().enumerate() {
            let support = clause_support_detail(
                clause.effect,
                clause.op,
                clause.target.kind,
                &clause.target.pattern,
                clause.target.arg.as_deref(),
                lsm_bpf,
            );
            out.push(json!({
                "rule": rule.name,
                "clause_index": clause_index,
                "effect": effect_name(clause.effect),
                "op": op_name(clause.op),
                "target_kind": kind_name(clause.target.kind),
                "target_pattern": clause.target.pattern,
                "target_arg": clause.target.arg,
                "supported": support.supported,
                "status": support.status,
                "mode": support.mode,
                "pre_op": support.pre_op,
                "reason": support.reason,
                "limitations": support.limitations,
            }));
        }
    }
    out
}

fn source_support_detail(kind: Kind, pattern: &str) -> (bool, &'static str, Vec<&'static str>) {
    match kind {
        Kind::Exec => (
            true,
            "exec source labels are applied on process exec",
            vec![],
        ),
        Kind::File => (
            true,
            "file source labels are applied through file open/read flow",
            vec!["open-time file source handling is conservative"],
        ),
        Kind::Endpoint if endpoint_pattern_is_numeric_ipv4(pattern) => (
            true,
            "endpoint source labels match numeric IPv4 connect and recv paths",
            vec!["IPv6 and hostname patterns are not enforced in-kernel"],
        ),
        Kind::Endpoint => (
            false,
            "endpoint source pattern is not numeric IPv4",
            vec!["IPv6 and hostname patterns are not enforced in-kernel"],
        ),
    }
}

struct SupportDetail {
    supported: bool,
    status: &'static str,
    mode: &'static str,
    pre_op: bool,
    reason: String,
    limitations: Vec<&'static str>,
}

#[derive(Clone)]
struct BackendWarning {
    code: &'static str,
    message: String,
}

fn clause_support_detail(
    effect: Effect,
    op: Op,
    kind: Kind,
    pattern: &str,
    arg: Option<&str>,
    lsm_bpf: bool,
) -> SupportDetail {
    if matches!(op, Op::Connect | Op::Recv)
        && kind == Kind::Endpoint
        && !endpoint_pattern_is_numeric_ipv4(pattern)
    {
        return SupportDetail {
            supported: false,
            status: "unsupported",
            mode: "none",
            pre_op: false,
            reason: "endpoint target pattern is not numeric IPv4".into(),
            limitations: vec!["IPv6 and hostname patterns are not enforced in-kernel"],
        };
    }

    match effect {
        Effect::Block => {
            if op == Op::Exec && arg.is_some() {
                SupportDetail {
                    supported: false,
                    status: "unsupported",
                    mode: "none",
                    pre_op: false,
                    reason: "argv is only available after exec, so this cannot block pre-exec"
                        .into(),
                    limitations: vec!["use kill exec for post-exec termination"],
                }
            } else if !lsm_bpf {
                SupportDetail {
                    supported: false,
                    status: "unsupported",
                    mode: "none",
                    pre_op: false,
                    reason: "BPF-LSM is not active on this host".into(),
                    limitations: vec!["notify and kill still use tracepoint paths where available"],
                }
            } else {
                let (reason, limitations) = match op {
                    Op::Exec => ("pre-op block via BPF-LSM bprm_check_security", vec![]),
                    Op::Read | Op::Open | Op::Write | Op::Unlink => {
                        ("pre-op block via BPF-LSM file/path hooks", vec![])
                    }
                    Op::Connect => (
                        "pre-op block via BPF-LSM socket_connect",
                        vec!["numeric IPv4 only"],
                    ),
                    Op::Recv => (
                        "pre-op block via BPF-LSM socket_recvmsg",
                        vec!["connected numeric IPv4 only"],
                    ),
                };
                SupportDetail {
                    supported: true,
                    status: "supported",
                    mode: "bpf-lsm",
                    pre_op: true,
                    reason: reason.into(),
                    limitations,
                }
            }
        }
        Effect::Notify => {
            let (reason, limitations) = match op {
                Op::Recv => (
                    "tracepoint report after recv",
                    vec!["numeric IPv4 only", "post-receive in tracepoint mode"],
                ),
                Op::Exec => ("post-exec tracepoint report", vec![]),
                Op::Read | Op::Open | Op::Write | Op::Unlink => ("tracepoint report", vec![]),
                Op::Connect => ("connect tracepoint report", vec!["numeric IPv4 only"]),
            };
            SupportDetail {
                supported: true,
                status: "supported",
                mode: "tracepoint",
                pre_op: false,
                reason: reason.into(),
                limitations,
            }
        }
        Effect::Kill => {
            let (reason, limitations) = match op {
                Op::Recv => (
                    "tracepoint kill after recv",
                    vec!["numeric IPv4 only", "post-receive in tracepoint mode"],
                ),
                Op::Exec => ("post-exec tracepoint kill", vec![]),
                Op::Read | Op::Open | Op::Write | Op::Unlink => ("tracepoint kill", vec![]),
                Op::Connect => ("connect tracepoint kill", vec!["numeric IPv4 only"]),
            };
            SupportDetail {
                supported: true,
                status: "supported",
                mode: "tracepoint",
                pre_op: false,
                reason: reason.into(),
                limitations,
            }
        }
    }
}

fn kind_name(kind: Kind) -> &'static str {
    match kind {
        Kind::File => "file",
        Kind::Endpoint => "endpoint",
        Kind::Exec => "exec",
    }
}

fn backend_support_lines(policy: &Policy, lsm_bpf: bool) -> Vec<String> {
    let mut lines = Vec::new();
    for rule in &policy.rules {
        for clause in &rule.clauses {
            lines.push(format!(
                "{}: {} {} -> {}",
                rule.name,
                effect_name(clause.effect),
                op_name(clause.op),
                clause_support(
                    clause.effect,
                    clause.op,
                    clause.target.kind,
                    &clause.target.pattern,
                    clause.target.arg.as_deref(),
                    lsm_bpf
                )
            ));
        }
    }
    lines
}

fn backend_support_warnings(policy: &Policy, lsm_bpf: bool) -> Vec<BackendWarning> {
    let mut warnings = Vec::new();
    for source in &policy.sources {
        if source.kind == Kind::Endpoint && !endpoint_pattern_is_numeric_ipv4(&source.pattern) {
            warnings.push(BackendWarning {
                code: "endpoint_source_non_numeric_ipv4",
                message: format!(
                    "source {} = endpoint \"{}\" uses a hostname or IPv6 pattern; endpoint sources currently match numeric IPv4 only.",
                    source.label, source.pattern
                ),
            });
        }
    }
    for rule in &policy.rules {
        for clause in &rule.clauses {
            if matches!(clause.op, Op::Connect | Op::Recv)
                && clause.target.kind == Kind::Endpoint
                && !endpoint_pattern_is_numeric_ipv4(&clause.target.pattern)
            {
                warnings.push(BackendWarning {
                    code: "endpoint_target_non_numeric_ipv4",
                    message: format!(
                        "{} {} endpoint \"{}\" uses a hostname or IPv6 pattern; the kernel matches numeric IPv4 only, so this rule will not fire.",
                        effect_name(clause.effect),
                        op_name(clause.op),
                        clause.target.pattern
                    ),
                });
            }
            if clause.effect == Effect::Block
                && clause.op == Op::Exec
                && clause.target.arg.is_some()
            {
                warnings.push(BackendWarning {
                    code: "argv_block_exec_post_exec_only",
                    message: format!(
                        "{}: `block exec` with an argv token cannot block pre-exec because argv is only available after exec; use `kill exec` if termination after exec is acceptable.",
                        rule.name
                    ),
                });
            }
            if clause.effect == Effect::Block && !lsm_bpf {
                warnings.push(BackendWarning {
                    code: "bpf_lsm_inactive_for_block",
                    message: format!(
                        "{}: `block {}` is unsupported on this host until BPF-LSM is active.",
                        rule.name,
                        op_name(clause.op)
                    ),
                });
            }
        }
    }
    warnings
}

fn clause_support(
    effect: Effect,
    op: Op,
    kind: Kind,
    pattern: &str,
    arg: Option<&str>,
    lsm_bpf: bool,
) -> String {
    let detail = clause_support_detail(effect, op, kind, pattern, arg, lsm_bpf);
    if detail.limitations.is_empty() {
        detail.reason
    } else {
        format!("{}, {}", detail.reason, detail.limitations.join(", "))
    }
}

fn effect_name(effect: Effect) -> &'static str {
    match effect {
        Effect::Notify => "notify",
        Effect::Block => "block",
        Effect::Kill => "kill",
    }
}

fn op_name(op: Op) -> &'static str {
    match op {
        Op::Exec => "exec",
        Op::Read => "read",
        Op::Write => "write",
        Op::Unlink => "unlink",
        Op::Connect => "connect",
        Op::Recv => "recv",
        Op::Open => "open",
    }
}

fn endpoint_pattern_is_numeric_ipv4(pat: &str) -> bool {
    if pat == "*" {
        return true;
    }
    let body = pat.trim_end_matches('.');
    let mut count = 0usize;
    for octet in body.split('.') {
        if octet.is_empty() || octet.parse::<u8>().is_err() {
            return false;
        }
        count += 1;
    }
    (1..=4).contains(&count)
}

pub(crate) fn doctor(cli: &Cli) -> Result<i32> {
    println!("ActPlane doctor\n");
    let mut problems = 0;

    doctor_path_actplane(&mut problems);

    match load_policy(cli) {
        Ok(loaded) => {
            let where_ = loaded
                .path
                .as_ref()
                .map(|p| p.display().to_string())
                .unwrap_or_else(|| "--rule".into());
            let resolved = resolve_policy(&loaded, cli.domain.as_deref())?;
            match dsl::compile_str(&resolved.source) {
                Ok(compiled) => {
                    if let Some(domain) = &resolved.domain {
                        println!(
                            "✓ policy: {} domain `{}` ({} rule(s))",
                            where_,
                            domain.name,
                            compiled.meta.len()
                        );
                    } else {
                        println!("✓ policy: {} ({} rule(s))", where_, compiled.meta.len());
                    }
                    let feedback = feedback_paths(&loaded);
                    println!("✓ feedback file: {}", feedback.feedback.display());
                    println!("✓ audit log: {}", feedback.audit.display());
                    println!("✓ event log: {}", feedback.events.display());
                }
                Err(e) => {
                    problems += 1;
                    println!("✗ policy: {} does not compile: {}", where_, e);
                }
            }
            doctor_agent_files(&loaded.root, &mut problems);
        }
        Err(e) => {
            problems += 1;
            println!("✗ policy: {}", e);
            let cwd = std::env::current_dir()?;
            doctor_agent_files(&cwd, &mut problems);
        }
    }

    if std::path::Path::new("/sys/kernel/btf/vmlinux").exists() {
        println!("✓ kernel BTF: /sys/kernel/btf/vmlinux");
    } else {
        problems += 1;
        println!("✗ kernel BTF: missing /sys/kernel/btf/vmlinux");
    }

    if have_bpf_caps() {
        println!("✓ eBPF privilege: current process has root/CAP_BPF+CAP_SYS_ADMIN");
    } else if passwordless_sudo_available() {
        println!("✓ eBPF privilege: passwordless sudo is available");
    } else {
        problems += 1;
        println!("✗ eBPF privilege: run/watch needs sudo or CAP_BPF+CAP_SYS_ADMIN");
    }

    let lsm = active_lsms().unwrap_or_default();
    if lsm_list_has_bpf(&lsm) {
        println!("✓ BPF-LSM: active ({})", lsm.trim());
    } else if let Some(source) = bpf_lsm_configured_for_next_boot() {
        println!(
            "⚠ BPF-LSM: configured for next boot in {}; reboot pending ({})",
            source.display(),
            lsm.trim()
        );
    } else {
        println!(
            "⚠ BPF-LSM: not active; `block` rules will not fire ({})",
            lsm.trim()
        );
    }

    println!("\nNext commands:");
    println!("  actplane check");
    println!("  codex");
    println!("  sudo -E actplane run -- <agent-or-command>");

    if problems == 0 {
        println!("\n✓ setup looks usable.");
        Ok(0)
    } else {
        println!("\n✗ setup has {} problem(s).", problems);
        Ok(1)
    }
}

pub(crate) fn list_domains(cli: &Cli) -> Result<i32> {
    let loaded = load_policy(cli)?;
    let where_ = loaded
        .path
        .as_ref()
        .map(|p| p.display().to_string())
        .unwrap_or_else(|| "--rule".into());
    if loaded.config.policy.is_some() {
        println!(
            "{} uses legacy `policy: |`; no domains are defined.",
            where_
        );
        return Ok(0);
    }

    let selected = resolve_policy(&loaded, cli.domain.as_deref())?
        .domain
        .map(|d| d.name);
    println!("Domains in {}", where_);
    for domain in domain_summaries(&loaded.config)? {
        let mark = if Some(domain.name.as_str()) == selected.as_deref() {
            "*"
        } else {
            " "
        };
        println!("{} {}", mark, domain.name);
        if let Some(parent) = &domain.parent {
            println!("    parent: {}", parent);
        }
        if !domain.disabled.is_empty() {
            println!("    disables: {}", format_rule_list(&domain.disabled));
        }
        println!("    locked: {}", format_rule_list(&domain.locked));
        println!("    default: {}", format_rule_list(&domain.defaults));
    }
    Ok(0)
}

fn format_rule_list(rules: &[String]) -> String {
    if rules.is_empty() {
        "none".into()
    } else {
        rules.join(", ")
    }
}

fn doctor_path_actplane(problems: &mut usize) {
    match find_executable_on_path("actplane") {
        Some(path) => {
            let version = command_version(&path).unwrap_or_else(|| "version unknown".into());
            println!("✓ PATH actplane: {} ({})", path.display(), version);
        }
        None => {
            *problems += 1;
            println!("✗ PATH actplane: not found; install or add the release binary to PATH");
        }
    }
}

fn doctor_agent_files(root: &Path, problems: &mut usize) {
    let codex_hooks = root.join(".codex/hooks.json");
    if codex_hooks.is_file() {
        let hooks = std::fs::read_to_string(&codex_hooks).unwrap_or_default();
        if codex_hook_has_actplane_command(&hooks) {
            println!("✓ Codex hook: {}", codex_hooks.display());
        } else {
            *problems += 1;
            println!(
                "✗ Codex hook: {} exists but is not wired to `actplane feedback-hook`; run `actplane setup --force`",
                codex_hooks.display()
            );
        }
    } else {
        *problems += 1;
        println!(
            "✗ Codex hook: missing {}; add `actplane feedback-hook` as PostToolUse",
            codex_hooks.display()
        );
    }

    let agents = root.join("AGENTS.md");
    if agents.is_symlink() {
        println!(
            "✓ Codex instructions: {} -> {:?}",
            agents.display(),
            std::fs::read_link(&agents).ok()
        );
    } else if agents.is_file() {
        println!("✓ Codex instructions: {}", agents.display());
    } else {
        println!("⚠ Codex instructions: AGENTS.md missing");
    }

    let mcp = root.join(".mcp.json");
    let mut project_mcp_ok = false;
    if mcp.is_file() {
        let text = std::fs::read_to_string(&mcp).unwrap_or_default();
        if project_mcp_auto_attach_ok(&text) {
            project_mcp_ok = true;
            println!("✓ project MCP config: {}", mcp.display());
        } else {
            *problems += 1;
            println!(
                "✗ project MCP config: {} does not auto-attach with PATH `actplane`; run `actplane setup`",
                mcp.display()
            );
        }
    } else {
        println!("⚠ project MCP config: .mcp.json missing");
    }
    if project_mcp_ok && let Some(global) = codex_global_mcp_actplane_config() {
        println!(
            "⚠ Codex global MCP also defines actplane ({}); keep either global or project config, not both",
            global.display()
        );
    }
}

fn codex_global_mcp_actplane_config() -> Option<PathBuf> {
    let path = std::env::var_os("HOME")
        .map(PathBuf::from)?
        .join(".codex/config.toml");
    let text = std::fs::read_to_string(&path).ok()?;
    text.lines()
        .any(|line| line.trim() == "[mcp_servers.actplane]")
        .then_some(path)
}

fn find_executable_on_path(name: &str) -> Option<PathBuf> {
    let path_var = std::env::var_os("PATH")?;
    std::env::split_paths(&path_var)
        .map(|dir| dir.join(name))
        .find(|candidate| is_executable(candidate))
}

fn is_executable(path: &Path) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        path.metadata()
            .map(|m| m.is_file() && m.permissions().mode() & 0o111 != 0)
            .unwrap_or(false)
    }
    #[cfg(not(unix))]
    {
        path.is_file()
    }
}

fn command_version(path: &Path) -> Option<String> {
    let output = std::process::Command::new(path)
        .arg("--version")
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let version = String::from_utf8_lossy(&output.stdout).trim().to_string();
    (!version.is_empty()).then_some(version)
}

fn active_lsms() -> Option<String> {
    std::fs::read_to_string("/sys/kernel/security/lsm").ok()
}

fn lsm_list_has_bpf(lsms: &str) -> bool {
    lsms.split(',').any(|name| name.trim() == "bpf")
}

fn bpf_lsm_configured_for_next_boot() -> Option<PathBuf> {
    [
        "/proc/cmdline",
        "/etc/default/grub.d/99-actplane-bpf-lsm.cfg",
        "/boot/grub/grub.cfg",
    ]
    .iter()
    .map(PathBuf::from)
    .find(|path| {
        std::fs::read_to_string(path)
            .map(|text| text_has_bpf_lsm_arg(&text))
            .unwrap_or(false)
    })
}

fn text_has_bpf_lsm_arg(text: &str) -> bool {
    text.split(|c: char| c.is_whitespace() || c == '"' || c == '\'')
        .filter_map(|token| token.strip_prefix("lsm="))
        .any(lsm_list_has_bpf)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lsm_parser_requires_exact_bpf_token() {
        assert!(lsm_list_has_bpf("lockdown,capability,bpf"));
        assert!(text_has_bpf_lsm_arg(
            r#"GRUB_CMDLINE_LINUX="${GRUB_CMDLINE_LINUX} lsm=landlock,lockdown,yama,bpf""#
        ));
        assert!(!lsm_list_has_bpf("lockdown,capability,bpfish"));
        assert!(!text_has_bpf_lsm_arg(
            "BOOT_IMAGE=/vmlinuz lsm=landlock,lockdown,yama,bpfish"
        ));
    }
}
