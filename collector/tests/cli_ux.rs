use std::fs;
use std::process::{Command, Output};

#[cfg(unix)]
use std::io::{BufRead, Write};
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
