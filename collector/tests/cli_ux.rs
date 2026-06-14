use std::fs;
use std::process::{Command, Output};

#[cfg(unix)]
use std::io::{BufRead, Write};
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
#[cfg(unix)]
use std::os::unix::net::UnixListener;
#[cfg(unix)]
use std::time::Duration;

fn actplane() -> &'static str {
    env!("CARGO_BIN_EXE_actplane")
}

fn fixture(name: &str) -> String {
    format!("{}/test/policies/{}", env!("CARGO_MANIFEST_DIR"), name)
}

fn run(args: &[&str]) -> Output {
    Command::new(actplane())
        .args(args)
        .output()
        .unwrap_or_else(|e| panic!("run actplane {args:?}: {e}"))
}

#[test]
fn check_prints_domain_summary() {
    let policy = fixture("15_domain_bindings.yaml");
    let output = run(&["--policy", &policy, "--domain", "review", "check"]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let stdout = stdout(&output);
    assert!(stdout.contains("domain: review"));
    assert!(stdout.contains("parent: session"));
    assert!(stdout.contains("locked: no-git-branch, readonly"));
    assert!(stdout.contains("default: none"));
    assert!(!stdout.contains("no-network —"));
}

#[test]
fn check_prints_backend_support_matrix_and_static_warnings() {
    let policy = r#"
source NET = endpoint "source.example.com"

rule recv-soft:
  notify recv endpoint "*" if true
  because "recv notify"

rule host-connect:
  block connect endpoint "api.example.com" if true
  because "hostname connect"
"#;
    let output = run(&["--rule", policy, "check"]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let stdout = stdout(&output);
    assert!(stdout.contains("backend support:"));
    assert!(stdout.contains("recv-soft: notify recv -> tracepoint report after recv"));
    assert!(stdout.contains("host-connect: block connect ->"));
    assert!(stdout.contains("connect endpoint \"api.example.com\" uses a hostname"));
    assert!(stdout.contains("source NET = endpoint \"source.example.com\" uses a hostname"));
}

#[test]
fn check_json_reports_backend_support_and_static_warnings() {
    let policy = r#"
source NET = endpoint "source.example.com"

rule recv-soft:
  notify recv endpoint "*" if true
  because "recv notify"

rule host-connect:
  notify connect endpoint "api.example.com" if true
  because "hostname connect"
"#;
    let output = run(&["--rule", policy, "check", "--json"]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let value: serde_json::Value =
        serde_json::from_slice(&output.stdout).expect("check --json stdout");

    assert_eq!(value["schema"], "actplane.check.v1");
    assert_eq!(value["ok"], true);
    assert_eq!(value["matrix_scope"], "static_initial_policy_host_support");
    assert_eq!(value["rule_count"], 2);
    assert_eq!(value["backend_support"]["sources"][0]["label"], "NET");
    assert_eq!(value["backend_support"]["sources"][0]["supported"], false);

    let clauses = value["backend_support"]["clauses"].as_array().unwrap();
    assert!(clauses.iter().any(|clause| {
        clause["rule"] == "recv-soft" && clause["op"] == "recv" && clause["supported"] == true
    }));
    assert!(clauses.iter().any(|clause| {
        clause["rule"] == "host-connect"
            && clause["op"] == "connect"
            && clause["supported"] == false
            && clause["reason"] == "endpoint target pattern is not numeric IPv4"
    }));

    let warning_codes: Vec<&str> = value["warnings"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|warning| warning["code"].as_str())
        .collect();
    assert!(warning_codes.contains(&"endpoint_source_non_numeric_ipv4"));
    assert!(warning_codes.contains(&"endpoint_target_non_numeric_ipv4"));
}

#[test]
fn check_json_reports_policy_load_errors_as_json() {
    let missing = "/tmp/actplane-definitely-missing-policy.yaml";
    let output = run(&["--policy", missing, "check", "--json"]);
    assert!(!output.status.success());
    let value: serde_json::Value =
        serde_json::from_slice(&output.stdout).expect("check --json error stdout");
    assert_eq!(value["schema"], "actplane.check.v1");
    assert_eq!(value["ok"], false);
    assert_eq!(value["policy_ref"], missing);
    assert!(
        value["error"]
            .as_str()
            .unwrap_or("")
            .contains("reading /tmp/actplane-definitely-missing-policy.yaml")
    );
}

#[test]
fn check_json_treats_invalid_ipv4_octets_as_unsupported() {
    let policy = r#"
source BAD = endpoint "999.1.1.1"

rule bad-connect:
  notify connect endpoint "999.1.1.1" if true
  because "bad endpoint"
"#;
    let output = run(&["--rule", policy, "check", "--json"]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let value: serde_json::Value =
        serde_json::from_slice(&output.stdout).expect("check --json stdout");
    assert_eq!(value["backend_support"]["sources"][0]["supported"], false);
    assert_eq!(value["backend_support"]["clauses"][0]["supported"], false);
}

#[test]
fn check_json_reports_force_tracepoint_override_for_block_rules() {
    let policy = r#"
rule block-git:
  block exec "git" if true
  because "block git"
"#;
    let output = Command::new(actplane())
        .env("ACTPLANE_FORCE_TRACEPOINT", "1")
        .args(["--rule", policy, "check", "--json"])
        .output()
        .expect("run check --json");
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let value: serde_json::Value =
        serde_json::from_slice(&output.stdout).expect("check --json stdout");
    assert_eq!(value["host"]["force_tracepoint"], true);
    assert_eq!(value["host"]["bpf_lsm_active"], false);
    assert_eq!(value["backend_support"]["clauses"][0]["supported"], false);
}

#[test]
fn check_reports_endpoint_target_condition_hostname_warning() {
    let policy = r#"
source AGENT = exec "**"

rule host-exception:
  notify connect endpoint "*" if AGENT unless target "api.example.com"
  because "hostname exception"
"#;
    let output = run(&["--rule", policy, "check", "--json"]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let value: serde_json::Value =
        serde_json::from_slice(&output.stdout).expect("check --json stdout");
    let clause = &value["backend_support"]["clauses"][0];
    assert_eq!(clause["supported"], true);
    assert_eq!(
        clause["condition_warnings"][0]["code"],
        "endpoint_target_condition_non_numeric_ipv4"
    );
    let warning_codes: Vec<&str> = value["warnings"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|warning| warning["code"].as_str())
        .collect();
    assert!(warning_codes.contains(&"endpoint_target_condition_non_numeric_ipv4"));

    let output = run(&["--rule", policy, "check", "--explain"]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let stdout = stdout(&output);
    assert!(stdout.contains("condition warning:"));
    assert!(stdout.contains("unless target \"api.example.com\" uses a hostname"));
}

#[test]
fn check_help_exposes_explain_output() {
    let output = run(&["check", "--help"]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let stdout = stdout(&output);
    assert!(stdout.contains("--json"));
    assert!(stdout.contains("--explain"));
    assert!(stdout.contains("--out"));
    assert!(stdout.contains("--force"));
}

#[test]
fn check_explain_emits_policy_review_artifact() {
    let tmp = tempfile::tempdir().unwrap();
    let policy = tmp.path().join("actplane.yaml");
    fs::write(
        &policy,
        r#"
version: 1
runtime:
  approval:
    append_delta:
      required: true
      require_approval_ref: true
      require_generated_by: true
      allowed_approvers:
        - repo-supervisor
policy: |
  source SECRET = file "secrets/**"
  source NET = endpoint "source.example.com"

  rule argv-block:
    block exec "git" "push" if SECRET
    because "no secret push"

  rule hostname-connect:
    notify connect endpoint "api.example.com" if true
    because "hostname connect"
"#,
    )
    .unwrap();

    let output = run(&["--policy", policy.to_str().unwrap(), "check", "--explain"]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let stdout = stdout(&output);
    assert!(stdout.contains("ActPlane policy review"));
    assert!(stdout.contains("append-delta approval: required"));
    assert!(stdout.contains("allowed approvers: repo-supervisor"));
    assert!(stdout.contains("admission model: static_metadata_allowlist"));
    assert!(stdout.contains("external_verified=false, signature=null"));
    assert!(stdout.contains("source SECRET = file \"secrets/**\""));
    assert!(stdout.contains("source NET = endpoint \"source.example.com\""));
    assert!(stdout.contains("clause 1: block exec \"**/git\" \"push\" if SECRET"));
    assert!(stdout.contains("argv is only available after exec"));
    assert!(stdout.contains("not enforceable by the current backend selection"));
    assert!(stdout.contains("endpoint target pattern is not numeric IPv4"));
    assert!(stdout.contains("positive required label bits for the selected lowered matcher"));
    assert!(stdout.contains("causal_chain is a reported single-hop origin"));
    assert!(stdout.contains("shared memory, IPv6, hostname endpoint globs"));
    assert!(stdout.contains("lowered:"));
}

#[test]
fn check_explain_writes_policy_review_artifact_file() {
    let tmp = tempfile::tempdir().unwrap();
    let out = tmp.path().join("review.txt");
    let policy = r#"
source AGENT = exec "**"

rule no-network:
  notify connect endpoint "*" if AGENT unless target "127."
  because "network review"
"#;
    let output = run(&[
        "--rule",
        policy,
        "check",
        "--explain",
        "--out",
        out.to_str().unwrap(),
    ]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    assert!(
        output.stdout.is_empty(),
        "stdout should be empty when writing --out: {}",
        stdout(&output)
    );
    assert!(stderr(&output).contains("wrote policy review"));
    let artifact = fs::read_to_string(&out).unwrap();
    assert!(artifact.contains("ActPlane policy review"));
    assert!(artifact.contains("rule no-network"));
    assert!(artifact.contains("review scope: selected initial policy"));
}

#[test]
fn check_explain_out_refuses_existing_file_without_force() {
    let tmp = tempfile::tempdir().unwrap();
    let out = tmp.path().join("review.txt");
    fs::write(&out, "keep me").unwrap();
    let policy = r#"
rule noop:
  notify exec "git" if true
  because "noop"
"#;

    let output = run(&[
        "--rule",
        policy,
        "check",
        "--explain",
        "--out",
        out.to_str().unwrap(),
    ]);
    assert!(!output.status.success());
    assert!(stderr(&output).contains("already exists"));
    assert_eq!(fs::read_to_string(&out).unwrap(), "keep me");

    let output = run(&[
        "--rule",
        policy,
        "check",
        "--explain",
        "--out",
        out.to_str().unwrap(),
        "--force",
    ]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let artifact = fs::read_to_string(&out).unwrap();
    assert!(artifact.contains("ActPlane policy review"));
    assert!(artifact.contains("rule noop"));
}

#[test]
fn check_out_requires_explain() {
    let tmp = tempfile::tempdir().unwrap();
    let out = tmp.path().join("review.txt");
    let policy = r#"
rule noop:
  notify exec "git" if true
  because "noop"
"#;
    let output = run(&["--rule", policy, "check", "--out", out.to_str().unwrap()]);
    assert!(!output.status.success());
    assert!(stderr(&output).contains("required"));
}

#[test]
fn check_json_and_explain_are_mutually_exclusive() {
    let policy = r#"
rule noop:
  notify exec "git" if true
  because "noop"
"#;
    let output = run(&["--rule", policy, "check", "--json", "--explain"]);
    assert!(!output.status.success());
    assert!(stderr(&output).contains("cannot be used with"));
}

#[test]
fn check_explain_reports_force_tracepoint_block_limit() {
    let policy = r#"
rule block-git:
  block exec "git" if true
  because "block git"
"#;
    let output = Command::new(actplane())
        .env("ACTPLANE_FORCE_TRACEPOINT", "1")
        .args(["--rule", policy, "check", "--explain"])
        .output()
        .expect("run check --explain");
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let stdout = stdout(&output);
    assert!(stdout.contains("ACTPLANE_FORCE_TRACEPOINT: set"));
    assert!(stdout.contains("BPF-LSM pre-op block: unavailable"));
    assert!(stdout.contains("not enforceable by the current backend selection"));
    assert!(stdout.contains("bpf_lsm_inactive_for_block"));
}

#[test]
fn rollout_prints_plan_and_writes_observe_policy() {
    let tmp = tempfile::tempdir().unwrap();
    let observe = tmp.path().join("observe.yaml");
    let policy = r#"
source AGENT = exec "**"

rule no-network:
  block connect endpoint "*" if AGENT unless target "127."
  because "network rollout"

rule no-branch:
  kill exec "git" "branch" if AGENT
  because "branch rollout"
"#;
    let output = run(&[
        "--rule",
        policy,
        "rollout",
        "--observe-policy-out",
        observe.to_str().unwrap(),
    ]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    assert!(stderr(&output).contains("wrote observe-first policy"));
    let stdout = stdout(&output);
    assert!(stdout.contains("ActPlane rollout plan"));
    assert!(stdout.contains("recommended rollout sequence"));
    assert!(stdout.contains("rule no-network"));
    assert!(stdout.contains("observe stage: use notify-only observe policy"));
    assert!(stdout.contains("promotion: eligible for block"));
    assert!(stdout.contains("rule no-branch"));
    assert!(stdout.contains("promote to kill only after manual review"));

    let observe_policy = fs::read_to_string(&observe).unwrap();
    assert!(observe_policy.contains("ActPlane observe-first policy"));
    assert!(observe_policy.contains("notify connect endpoint \"*\""));
    assert!(observe_policy.contains("notify exec \"**/git\" \"branch\""));
    assert!(!observe_policy.contains("block connect"));
    assert!(!observe_policy.contains("kill exec"));

    let check = run(&["--policy", observe.to_str().unwrap(), "check"]);
    assert!(check.status.success(), "stderr: {}", stderr(&check));
}

#[test]
fn rollout_writes_plan_and_observe_policy_atomically() {
    let tmp = tempfile::tempdir().unwrap();
    let plan = tmp.path().join("rollout.txt");
    let observe = tmp.path().join("observe.yaml");
    let policy = r#"
rule block-git:
  block exec "git" if true
  because "block git"
"#;
    let output = run(&[
        "--rule",
        policy,
        "rollout",
        "--out",
        plan.to_str().unwrap(),
        "--observe-policy-out",
        observe.to_str().unwrap(),
    ]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    assert!(output.stdout.is_empty());
    assert!(
        fs::read_to_string(&plan)
            .unwrap()
            .contains("ActPlane rollout plan")
    );
    assert!(
        fs::read_to_string(&observe)
            .unwrap()
            .contains("notify exec \"**/git\"")
    );

    let output = run(&[
        "--rule",
        policy,
        "rollout",
        "--out",
        plan.to_str().unwrap(),
        "--observe-policy-out",
        plan.to_str().unwrap(),
        "--force",
    ]);
    assert!(!output.status.success());
    assert!(stderr(&output).contains("--out and --observe-policy-out must be different"));
}

#[test]
fn rollout_reports_unsupported_block_before_promotion() {
    let policy = r#"
source AGENT = exec "**"

rule argv-block:
  block exec "git" "push" if AGENT
  because "argv block"
"#;
    let output = run(&["--rule", policy, "rollout"]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let stdout = stdout(&output);
    assert!(stdout.contains("do not deploy as block yet"));
    assert!(stdout.contains("argv is only available after exec"));
    assert!(stdout.contains("static warnings to resolve before promotion"));
}

#[test]
fn templates_list_and_json_expose_catalog() {
    let output = run(&["templates", "list"]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let stdout = stdout(&output);
    assert!(stdout.contains("ActPlane policy templates"));
    assert!(stdout.contains("no-secret-egress"));
    assert!(stdout.contains("test-before-commit"));
    assert!(stdout.contains("prod-db-via-migrate"));

    let output = run(&["templates", "list", "--json"]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let value: serde_json::Value =
        serde_json::from_slice(&output.stdout).expect("templates list --json stdout");
    assert_eq!(value["schema"], "actplane.templates.v1");
    let ids: Vec<&str> = value["templates"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|template| template["id"].as_str())
        .collect();
    assert!(ids.contains(&"no-network"));
    assert!(ids.contains(&"readonly-review"));
}

#[test]
fn templates_show_prints_dsl_and_yaml() {
    let output = run(&["templates", "show", "no-secret-egress"]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let dsl_stdout = stdout(&output);
    assert!(dsl_stdout.contains("source SECRET = file"));
    assert!(dsl_stdout.contains("rule no-secret-egress:"));
    assert!(!dsl_stdout.contains("version: 1"));

    let output = run(&["templates", "show", "no-network", "--format", "yaml"]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let yaml_stdout = stdout(&output);
    assert!(yaml_stdout.contains("version: 1"));
    assert!(yaml_stdout.contains("policy: |"));
    assert!(yaml_stdout.contains("rule no-network:"));
}

#[test]
fn templates_show_and_json_expose_parameters() {
    let output = run(&[
        "templates",
        "show",
        "test-before-commit",
        "--set",
        "test_exec=**/pnpm",
        "--set",
        "changed_paths=packages/**,src/**",
    ]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let stdout = stdout(&output);
    assert!(stdout.contains("after exec \"**/pnpm\""));
    assert!(stdout.contains("write \"packages/**\" or write \"src/**\""));

    let output = run(&["templates", "list", "--json"]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let value: serde_json::Value =
        serde_json::from_slice(&output.stdout).expect("templates list --json stdout");
    let templates = value["templates"].as_array().unwrap();
    let no_network = templates
        .iter()
        .find(|template| template["id"] == "no-network")
        .expect("no-network template");
    let params: Vec<&str> = no_network["params"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|param| param["name"].as_str())
        .collect();
    assert!(params.contains(&"agent_exec"));
    assert!(params.contains(&"loopback_endpoint"));
}

#[test]
fn templates_reject_policy_selection_globals() {
    let tmp = tempfile::tempdir().unwrap();
    let out = tmp.path().join("actplane.yaml");
    let review = tmp.path().join("review.txt");
    let output = run(&[
        "--domain",
        "review",
        "templates",
        "review",
        "no-network",
        "--policy-out",
        out.to_str().unwrap(),
        "--review-out",
        review.to_str().unwrap(),
    ]);
    assert!(!output.status.success());
    assert!(stderr(&output).contains("does not read --policy, --rule, or --domain"));
    assert!(!out.exists());
    assert!(!review.exists());

    let policy = tmp.path().join("existing.yaml");
    fs::write(&policy, "version: 1\npolicy: |\n").unwrap();
    let output = run(&[
        "--policy",
        policy.to_str().unwrap(),
        "templates",
        "show",
        "no-network",
    ]);
    assert!(!output.status.success());
    assert!(stderr(&output).contains("does not read --policy, --rule, or --domain"));
}

#[test]
fn templates_write_outputs_checkable_yaml_and_respects_force() {
    let tmp = tempfile::tempdir().unwrap();
    let out = tmp.path().join("actplane.yaml");
    let output = run(&[
        "templates",
        "write",
        "no-network",
        "--out",
        out.to_str().unwrap(),
    ]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let written = fs::read_to_string(&out).unwrap();
    assert!(written.contains("ActPlane policy generated from template `no-network`"));
    assert!(written.contains("rule no-network:"));

    let check = run(&["--policy", out.to_str().unwrap(), "check", "--explain"]);
    assert!(check.status.success(), "stderr: {}", stderr(&check));
    assert!(stdout(&check).contains("rule no-network"));

    let output = run(&[
        "templates",
        "write",
        "no-network",
        "--out",
        out.to_str().unwrap(),
    ]);
    assert!(!output.status.success());
    assert!(stderr(&output).contains("already exists"));

    let output = run(&[
        "templates",
        "write",
        "no-network",
        "--out",
        out.to_str().unwrap(),
        "--force",
    ]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
}

#[test]
fn templates_write_applies_parameters_and_rejects_bad_parameters() {
    let tmp = tempfile::tempdir().unwrap();
    let out = tmp.path().join("actplane.yaml");
    let output = run(&[
        "templates",
        "write",
        "workspace-confinement",
        "--set",
        "agent_exec=codex",
        "--set",
        "writable_path=/repo/**",
        "--out",
        out.to_str().unwrap(),
    ]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let written = fs::read_to_string(&out).unwrap();
    assert!(written.contains("# Parameter writable_path: /repo/**"));
    assert!(written.contains("source AGENT = exec \"codex\""));
    assert!(written.contains("unless target \"/repo/**\""));

    let bad = tmp.path().join("bad.yaml");
    let output = run(&[
        "templates",
        "write",
        "workspace-confinement",
        "--set",
        "missing=value",
        "--out",
        bad.to_str().unwrap(),
    ]);
    assert!(!output.status.success());
    assert!(stderr(&output).contains("unknown parameter `missing`"));
    assert!(!bad.exists());

    let output = run(&[
        "templates",
        "write",
        "workspace-confinement",
        "--set",
        "writable_path=bad\"quote",
        "--out",
        bad.to_str().unwrap(),
    ]);
    assert!(!output.status.success());
    assert!(stderr(&output).contains("unsupported by the current DSL string syntax"));
    assert!(!bad.exists());
}

#[test]
fn templates_review_writes_policy_and_review_artifact() {
    let tmp = tempfile::tempdir().unwrap();
    let policy = tmp.path().join("actplane.yaml");
    let review = tmp.path().join("review.txt");
    let output = run(&[
        "templates",
        "review",
        "no-secret-egress",
        "--policy-out",
        policy.to_str().unwrap(),
        "--review-out",
        review.to_str().unwrap(),
    ]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    assert!(stderr(&output).contains("wrote template `no-secret-egress`"));
    assert!(stderr(&output).contains("wrote policy review"));

    let written_policy = fs::read_to_string(&policy).unwrap();
    assert!(written_policy.contains("version: 1"));
    assert!(written_policy.contains("rule no-secret-egress:"));

    let artifact = fs::read_to_string(&review).unwrap();
    assert!(artifact.contains("ActPlane policy review"));
    assert!(artifact.contains(&format!("policy: {}", policy.display())));
    assert!(artifact.contains("rule no-secret-egress"));
    assert!(artifact.contains("review scope: selected initial policy"));
}

#[test]
fn templates_review_applies_parameters_to_policy_and_review() {
    let tmp = tempfile::tempdir().unwrap();
    let policy = tmp.path().join("actplane.yaml");
    let review = tmp.path().join("review.txt");
    let output = run(&[
        "templates",
        "review",
        "no-network",
        "--set",
        "agent_exec=codex",
        "--set",
        "loopback_endpoint=10.",
        "--policy-out",
        policy.to_str().unwrap(),
        "--review-out",
        review.to_str().unwrap(),
    ]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let written_policy = fs::read_to_string(&policy).unwrap();
    assert!(written_policy.contains("# Parameter agent_exec: codex"));
    assert!(written_policy.contains("source AGENT = exec \"codex\""));
    assert!(written_policy.contains("unless target \"10.\""));

    let artifact = fs::read_to_string(&review).unwrap();
    assert!(artifact.contains("source AGENT = exec \"codex\""));
    assert!(artifact.contains("unless target \"10.\""));
}

#[test]
fn templates_review_refuses_existing_outputs_without_partial_write() {
    let tmp = tempfile::tempdir().unwrap();
    let policy = tmp.path().join("actplane.yaml");
    let review = tmp.path().join("review.txt");
    fs::write(&review, "keep review").unwrap();

    let output = run(&[
        "templates",
        "review",
        "no-network",
        "--policy-out",
        policy.to_str().unwrap(),
        "--review-out",
        review.to_str().unwrap(),
    ]);
    assert!(!output.status.success());
    assert!(stderr(&output).contains("already exists"));
    assert!(
        !policy.exists(),
        "policy should not be written after preflight failure"
    );
    assert_eq!(fs::read_to_string(&review).unwrap(), "keep review");

    let output = run(&[
        "templates",
        "review",
        "no-network",
        "--policy-out",
        policy.to_str().unwrap(),
        "--review-out",
        review.to_str().unwrap(),
        "--force",
    ]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    assert!(
        fs::read_to_string(&policy)
            .unwrap()
            .contains("rule no-network:")
    );
    assert!(
        fs::read_to_string(&review)
            .unwrap()
            .contains("rule no-network")
    );
}

#[test]
fn templates_review_preflights_parent_dirs_before_writing() {
    let tmp = tempfile::tempdir().unwrap();
    let policy = tmp.path().join("actplane.yaml");
    let review = tmp.path().join("missing").join("review.txt");

    let output = run(&[
        "templates",
        "review",
        "no-network",
        "--policy-out",
        policy.to_str().unwrap(),
        "--review-out",
        review.to_str().unwrap(),
    ]);
    assert!(!output.status.success());
    assert!(stderr(&output).contains("parent directory"));
    assert!(
        !policy.exists(),
        "policy should not be written after preflight failure"
    );
}

#[cfg(unix)]
#[test]
fn templates_review_does_not_write_policy_when_review_temp_fails() {
    if unsafe { libc::geteuid() } == 0 {
        return;
    }

    let tmp = tempfile::tempdir().unwrap();
    let policy_dir = tmp.path().join("policy");
    let review_dir = tmp.path().join("review");
    fs::create_dir(&policy_dir).unwrap();
    fs::create_dir(&review_dir).unwrap();
    let policy = policy_dir.join("actplane.yaml");
    let review = review_dir.join("review.txt");

    let mut perms = fs::metadata(&review_dir).unwrap().permissions();
    perms.set_mode(0o500);
    fs::set_permissions(&review_dir, perms).unwrap();

    let output = run(&[
        "templates",
        "review",
        "no-network",
        "--policy-out",
        policy.to_str().unwrap(),
        "--review-out",
        review.to_str().unwrap(),
    ]);

    let mut perms = fs::metadata(&review_dir).unwrap().permissions();
    perms.set_mode(0o700);
    fs::set_permissions(&review_dir, perms).unwrap();

    assert!(!output.status.success());
    assert!(
        !policy.exists(),
        "policy should not be written when review temp creation fails"
    );
    assert!(!review.exists());
}

#[test]
fn templates_review_requires_distinct_output_paths() {
    let tmp = tempfile::tempdir().unwrap();
    let out = tmp.path().join("actplane.yaml");
    let output = run(&[
        "templates",
        "review",
        "no-network",
        "--policy-out",
        out.to_str().unwrap(),
        "--review-out",
        out.to_str().unwrap(),
    ]);
    assert!(!output.status.success());
    assert!(stderr(&output).contains("--policy-out and --review-out must be different"));
    assert!(!out.exists());
}

#[test]
fn templates_review_rejects_same_output_file_with_different_path_syntax() {
    let tmp = tempfile::tempdir().unwrap();
    let out = tmp.path().join("actplane.yaml");
    let output = Command::new(actplane())
        .current_dir(tmp.path())
        .args([
            "templates",
            "review",
            "no-network",
            "--policy-out",
            "actplane.yaml",
            "--review-out",
            out.to_str().unwrap(),
        ])
        .output()
        .expect("run templates review");
    assert!(!output.status.success());
    assert!(stderr(&output).contains("--policy-out and --review-out must be different"));
    assert!(!out.exists());
}

#[test]
fn templates_review_rejects_directory_targets_even_with_force() {
    let tmp = tempfile::tempdir().unwrap();
    let policy = tmp.path().join("actplane.yaml");
    let review_dir = tmp.path().join("review-dir");
    fs::create_dir(&review_dir).unwrap();
    let output = run(&[
        "templates",
        "review",
        "no-network",
        "--policy-out",
        policy.to_str().unwrap(),
        "--review-out",
        review_dir.to_str().unwrap(),
        "--force",
    ]);
    assert!(!output.status.success());
    assert!(stderr(&output).contains("is a directory"));
    assert!(
        !policy.exists(),
        "policy should not be written after preflight failure"
    );
}

#[cfg(unix)]
#[test]
fn templates_review_rejects_symlink_output_paths() {
    let tmp = tempfile::tempdir().unwrap();
    let target = tmp.path().join("target.yaml");
    let symlink = tmp.path().join("policy.yaml");
    std::os::unix::fs::symlink(&target, &symlink).unwrap();

    let output = run(&[
        "templates",
        "review",
        "no-network",
        "--policy-out",
        symlink.to_str().unwrap(),
        "--review-out",
        target.to_str().unwrap(),
    ]);
    assert!(!output.status.success());
    assert!(stderr(&output).contains("is a symlink"));
    assert!(!target.exists());
}

#[cfg(unix)]
#[test]
fn templates_review_rejects_hardlinked_existing_outputs() {
    let tmp = tempfile::tempdir().unwrap();
    let policy = tmp.path().join("policy.yaml");
    let review = tmp.path().join("review.txt");
    fs::write(&policy, "old").unwrap();
    std::fs::hard_link(&policy, &review).unwrap();

    let output = run(&[
        "templates",
        "review",
        "no-network",
        "--policy-out",
        policy.to_str().unwrap(),
        "--review-out",
        review.to_str().unwrap(),
        "--force",
    ]);
    assert!(!output.status.success());
    assert!(stderr(&output).contains("--policy-out and --review-out must be different"));
    assert_eq!(fs::read_to_string(&policy).unwrap(), "old");
}

#[test]
fn templates_generate_writes_candidate_policy_and_review() {
    let tmp = tempfile::tempdir().unwrap();
    fs::write(
        tmp.path().join("AGENTS.md"),
        "Do not run git branch or git worktree. Run pytest before committing. Keep secrets safe.",
    )
    .unwrap();
    fs::create_dir(tmp.path().join("src")).unwrap();
    fs::create_dir(tmp.path().join("tests")).unwrap();
    let policy = tmp.path().join("candidate.yaml");
    let review = tmp.path().join("candidate-review.txt");

    let output = Command::new(actplane())
        .current_dir(tmp.path())
        .args([
            "templates",
            "generate",
            "--policy-out",
            policy.to_str().unwrap(),
            "--review-out",
            review.to_str().unwrap(),
        ])
        .output()
        .expect("run templates generate");
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    assert!(stderr(&output).contains("selected no-git-branch"));
    assert!(stderr(&output).contains("selected test-before-commit"));
    assert!(stderr(&output).contains("selected no-secret-egress"));

    let written = fs::read_to_string(&policy).unwrap();
    assert!(written.contains("ActPlane candidate policy generated"));
    assert!(written.contains("# template: no-git-branch"));
    assert!(written.contains("rule no-git-branch:"));
    assert!(written.contains("rule test-before-commit:"));
    assert!(written.contains("source SECRET = file"));

    let artifact = fs::read_to_string(&review).unwrap();
    assert!(artifact.contains("ActPlane policy review"));
    assert!(artifact.contains("rule no-git-branch"));
    assert!(artifact.contains("rule test-before-commit"));
}

#[test]
fn templates_generate_uses_task_hint_without_instruction_files() {
    let tmp = tempfile::tempdir().unwrap();
    let policy = tmp.path().join("candidate.yaml");
    let review = tmp.path().join("candidate-review.txt");
    let output = Command::new(actplane())
        .current_dir(tmp.path())
        .args([
            "templates",
            "generate",
            "--task",
            "offline read-only review",
            "--policy-out",
            policy.to_str().unwrap(),
            "--review-out",
            review.to_str().unwrap(),
        ])
        .output()
        .expect("run templates generate");
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let written = fs::read_to_string(&policy).unwrap();
    assert!(written.contains("# template: no-network"));
    assert!(written.contains("rule no-network:"));
    assert!(written.contains("# template: readonly-review"));
    assert!(written.contains("rule readonly-review:"));
}

#[test]
fn templates_generate_discovers_project_root_from_subdirectory() {
    let tmp = tempfile::tempdir().unwrap();
    fs::write(tmp.path().join("actplane.yaml"), "version: 1\npolicy: |\n").unwrap();
    fs::write(tmp.path().join("AGENTS.md"), "Do not run git branch.").unwrap();
    let subdir = tmp.path().join("nested");
    fs::create_dir(&subdir).unwrap();
    let policy = subdir.join("candidate.yaml");
    let review = subdir.join("candidate-review.txt");
    let output = Command::new(actplane())
        .current_dir(&subdir)
        .args([
            "templates",
            "generate",
            "--policy-out",
            policy.to_str().unwrap(),
            "--review-out",
            review.to_str().unwrap(),
        ])
        .output()
        .expect("run templates generate");
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let written = fs::read_to_string(&policy).unwrap();
    assert!(written.contains("# Project root: "));
    assert!(written.contains(tmp.path().to_str().unwrap()));
    assert!(written.contains("# Instructions considered:"));
    assert!(written.contains("AGENTS.md"));
    assert!(written.contains("rule no-git-branch:"));
}

#[test]
fn domains_lists_effective_bindings_and_default_selection() {
    let policy = fixture("15_domain_bindings.yaml");
    let output = run(&["--policy", &policy, "domains"]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let stdout = stdout(&output);
    assert!(stdout.contains("* review"));
    assert!(stdout.contains("  session"));
    assert!(stdout.contains("disables: no-network"));
    assert!(stdout.contains("locked: no-git-branch, readonly"));
    assert!(stdout.contains("default: no-network"));
}

#[test]
fn compile_prints_selected_domain_before_output_path() {
    let tmp = tempfile::tempdir().unwrap();
    let out = tmp.path().join("review.bin");
    let policy = fixture("15_domain_bindings.yaml");
    let output = run(&[
        "--policy",
        &policy,
        "--domain",
        "review",
        "compile",
        "--out",
        out.to_str().unwrap(),
    ]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    assert!(out.is_file());
    let stderr = stderr(&output);
    assert!(stderr.contains("domain `review`"));
    assert!(stderr.contains("locked: no-git-branch, readonly"));
    assert!(stderr.contains("compiled 2 rule(s)"));
}

#[test]
fn ambiguous_domains_error_tells_user_how_to_select() {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("actplane.yaml");
    fs::write(
        &path,
        r#"
version: 1
rules:
  r:
    ifc: |
      rule r:
        kill exec "git"
        because "r"
domains:
  alpha:
    bind:
      - rule: r
        mode: default
  beta:
    bind:
      - rule: r
        mode: default
"#,
    )
    .unwrap();
    let output = run(&["--policy", path.to_str().unwrap(), "check"]);
    assert!(!output.status.success());
    let stderr = stderr(&output);
    assert!(stderr.contains("policy defines multiple domains"));
    assert!(stderr.contains("alpha, beta"));
    assert!(stderr.contains("--domain"));
}

#[test]
fn child_run_help_exposes_domain_lifecycle_flags() {
    let output = run(&["child-run", "--help"]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let stdout = stdout(&output);
    assert!(stdout.contains("--child-id"));
    assert!(stdout.contains("--scope-id"));
    assert!(stdout.contains("--delta"));
    assert!(stdout.contains("--delta-text"));
    assert!(stdout.contains("--approved-by"));
    assert!(stdout.contains("--approval-ref"));
    assert!(stdout.contains("--generated-by"));
}

#[test]
fn control_help_exposes_already_running_engine_commands() {
    let output = run(&["control", "--help"]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let stdout = stdout(&output);
    assert!(stdout.contains("status"));
    assert!(stdout.contains("reload-policy"));
    assert!(stdout.contains("bind-child"));
    assert!(stdout.contains("append-delta"));
    assert!(stdout.contains("launch-child"));
    assert!(stdout.contains("list-children"));
    assert!(stdout.contains("terminate-child"));
    assert!(stdout.contains("restart-child"));
    assert!(stdout.contains("reconcile-children"));
}

#[test]
fn control_append_delta_help_exposes_delta_inputs() {
    let output = run(&["control", "append-delta", "--help"]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let stdout = stdout(&output);
    assert!(stdout.contains("--target-id"));
    assert!(stdout.contains("--domain-id"));
    assert!(stdout.contains("--delta"));
    assert!(stdout.contains("--delta-text"));
    assert!(stdout.contains("--approved-by"));
    assert!(stdout.contains("--approval-ref"));
    assert!(stdout.contains("--generated-by"));
}

#[test]
fn delta_add_help_exposes_public_append_inputs() {
    let output = run(&["delta", "add", "--help"]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let stdout = stdout(&output);
    assert!(stdout.contains("--target-id"));
    assert!(stdout.contains("--domain-id"));
    assert!(stdout.contains("--delta"));
    assert!(stdout.contains("--delta-text"));
    assert!(stdout.contains("--approved-by"));
    assert!(stdout.contains("--approval-ref"));
    assert!(stdout.contains("--generated-by"));
}

#[cfg(unix)]
#[test]
fn delta_add_sends_append_delta_over_repo_control_socket() {
    let tmp = tempfile::tempdir().unwrap();
    let policy = tmp.path().join("actplane.yaml");
    fs::write(
        &policy,
        r#"
version: 1
policy: |
  source COMMAND = exec "**"
  rule noop:
    notify exec "__actplane_never__" if COMMAND
    because "noop"
"#,
    )
    .unwrap();

    let socket_path = tmp.path().join("control.sock");
    let listener = UnixListener::bind(&socket_path).unwrap();
    let state_dir = tmp.path().join(".actplane");
    fs::create_dir_all(&state_dir).unwrap();
    fs::write(
        state_dir.join("control.json"),
        serde_json::to_string_pretty(&serde_json::json!({
            "schema": "actplane.control.v1",
            "pid": std::process::id() as i32,
            "proc_start_time": null,
            "socket_path": socket_path,
            "project_dir": tmp.path(),
            "parent_pid": 1111,
            "parent_domain_id": 2222,
        }))
        .unwrap(),
    )
    .unwrap();

    let (tx, rx) = std::sync::mpsc::channel();
    let handle = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().expect("accept control client");
        let mut line = String::new();
        std::io::BufReader::new(stream.try_clone().expect("clone stream"))
            .read_line(&mut line)
            .expect("read request");
        let request: serde_json::Value = serde_json::from_str(&line).expect("request JSON");
        tx.send(request).expect("send request");
        serde_json::to_writer(
            &mut stream,
            &serde_json::json!({ "ok": true, "text": "delta accepted" }),
        )
        .expect("write response");
        writeln!(stream).expect("write response newline");
    });

    let output = Command::new(actplane())
        .current_dir(tmp.path())
        .args([
            "--policy",
            policy.to_str().unwrap(),
            "delta",
            "add",
            "--target-id",
            "4242",
            "--delta-text",
            "rule added:\n  notify exec \"git\" if true\n  because \"added\"",
            "--approved-by",
            "reviewer",
            "--approval-ref",
            "ticket-7",
            "--generated-by",
            "cli-test",
        ])
        .output()
        .expect("run delta add");
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    assert!(stdout(&output).contains("delta accepted"));

    let request = rx
        .recv_timeout(Duration::from_secs(5))
        .expect("control request");
    assert_eq!(request["op"], "append_policy_delta");
    assert_eq!(request["target_id"], 4242);
    assert!(request["policy"].as_str().unwrap().contains("rule added"));
    assert_eq!(request["policy_ref"], "--delta-text[0]");
    assert_eq!(request["approved_by"], "reviewer");
    assert_eq!(request["approval_ref"], "ticket-7");
    assert_eq!(request["generated_by"], "cli-test");
    handle.join().expect("control server thread");
}

#[cfg(unix)]
#[test]
fn control_launch_child_sends_policy_approval_over_repo_control_socket() {
    let tmp = tempfile::tempdir().unwrap();
    let policy = tmp.path().join("actplane.yaml");
    fs::write(
        &policy,
        r#"
version: 1
policy: |
  source COMMAND = exec "**"
  rule noop:
    notify exec "__actplane_never__" if COMMAND
    because "noop"
"#,
    )
    .unwrap();

    let socket_path = tmp.path().join("control.sock");
    let listener = UnixListener::bind(&socket_path).unwrap();
    let state_dir = tmp.path().join(".actplane");
    fs::create_dir_all(&state_dir).unwrap();
    fs::write(
        state_dir.join("control.json"),
        serde_json::to_string_pretty(&serde_json::json!({
            "schema": "actplane.control.v1",
            "pid": std::process::id() as i32,
            "proc_start_time": null,
            "socket_path": socket_path,
            "project_dir": tmp.path(),
            "parent_pid": 1111,
            "parent_domain_id": 2222,
        }))
        .unwrap(),
    )
    .unwrap();

    let (tx, rx) = std::sync::mpsc::channel();
    let handle = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().expect("accept control client");
        let mut line = String::new();
        std::io::BufReader::new(stream.try_clone().expect("clone stream"))
            .read_line(&mut line)
            .expect("read request");
        let request: serde_json::Value = serde_json::from_str(&line).expect("request JSON");
        tx.send(request).expect("send request");
        serde_json::to_writer(
            &mut stream,
            &serde_json::json!({ "ok": true, "text": "launch accepted" }),
        )
        .expect("write response");
        writeln!(stream).expect("write response newline");
    });

    let output = Command::new(actplane())
        .current_dir(tmp.path())
        .args([
            "--policy",
            policy.to_str().unwrap(),
            "control",
            "launch-child",
            "--child-id",
            "5252",
            "--delta-text",
            "rule child:\n  notify exec \"git\" if true\n  because \"child\"",
            "--approved-by",
            "repo-supervisor",
            "--approval-ref",
            "ticket-8",
            "--generated-by",
            "cli-test",
            "/bin/true",
        ])
        .output()
        .expect("run control launch-child");
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    assert!(stdout(&output).contains("launch accepted"));

    let request = rx
        .recv_timeout(Duration::from_secs(5))
        .expect("control request");
    assert_eq!(request["op"], "launch_child_domain");
    assert_eq!(request["child_id"], 5252);
    assert!(request["policy"].as_str().unwrap().contains("rule child"));
    assert_eq!(request["approved_by"], "repo-supervisor");
    assert_eq!(request["approval_ref"], "ticket-8");
    assert_eq!(request["generated_by"], "cli-test");
    assert_eq!(request["cmd"][0], "/bin/true");
    handle.join().expect("control server thread");
}

#[test]
fn control_launch_child_help_exposes_supervisor_flags() {
    let output = run(&["control", "launch-child", "--help"]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let stdout = stdout(&output);
    assert!(stdout.contains("--child-id"));
    assert!(stdout.contains("--scope-id"));
    assert!(stdout.contains("--restart-policy"));
    assert!(stdout.contains("--restart-limit"));
    assert!(stdout.contains("--restart-backoff-ms"));
    assert!(stdout.contains("--approved-by"));
    assert!(stdout.contains("--approval-ref"));
    assert!(stdout.contains("--generated-by"));
}

#[test]
fn control_restart_child_help_exposes_fresh_domain_flags() {
    let output = run(&["control", "restart-child", "--help"]);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let stdout = stdout(&output);
    assert!(stdout.contains("--child-id"));
    assert!(stdout.contains("--domain-id"));
    assert!(stdout.contains("--new-child-id"));
    assert!(stdout.contains("--terminate-existing"));
}

fn stdout(output: &Output) -> String {
    String::from_utf8_lossy(&output.stdout).to_string()
}

fn stderr(output: &Output) -> String {
    String::from_utf8_lossy(&output.stderr).to_string()
}
