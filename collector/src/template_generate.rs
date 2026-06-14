use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

use crate::{Result, templates};

const MAX_INSTRUCTION_BYTES: usize = 128 * 1024;

#[derive(Debug)]
pub(crate) struct GeneratedTemplate {
    pub(crate) id: &'static str,
    pub(crate) params: Vec<String>,
    pub(crate) reasons: Vec<String>,
}

#[derive(Debug)]
pub(crate) struct GeneratedPolicy {
    pub(crate) root: PathBuf,
    pub(crate) instruction_files: Vec<PathBuf>,
    pub(crate) task: Option<String>,
    pub(crate) templates: Vec<GeneratedTemplate>,
    pub(crate) notes: Vec<String>,
}

pub(crate) fn generate(
    root: &Path,
    instruction_files: &[PathBuf],
    task: Option<&str>,
) -> Result<GeneratedPolicy> {
    let instruction_files = if instruction_files.is_empty() {
        discover_instruction_files(root)
    } else {
        instruction_files.to_vec()
    };
    let mut notes = Vec::new();
    let mut instruction_text = String::new();
    for path in &instruction_files {
        match std::fs::read_to_string(path) {
            Ok(mut text) => {
                if truncate_to_char_boundary(&mut text, MAX_INSTRUCTION_BYTES) {
                    notes.push(format!("truncated {} to 128 KiB", path.display()));
                }
                instruction_text.push_str(&text);
                instruction_text.push('\n');
            }
            Err(e) => {
                return Err(format!("reading instructions {}: {}", path.display(), e).into());
            }
        }
    }
    if let Some(task) = task {
        instruction_text.push_str(task);
        instruction_text.push('\n');
    }
    let lower = instruction_text.to_lowercase();
    let agent_exec = infer_agent_exec(&lower);
    let mut out = Vec::new();

    if mentions_any(
        &lower,
        &["git branch", "git worktree", "no-git-branch", "worktree"],
    ) {
        out.push(GeneratedTemplate {
            id: "no-git-branch",
            params: vec![format!("agent_exec={agent_exec}")],
            reasons: vec![
                "project instructions restrict agent-created git branches/worktrees".into(),
            ],
        });
    }

    if mentions_test_before_commit(&lower) || has_source_tree(root) {
        out.push(GeneratedTemplate {
            id: "test-before-commit",
            params: vec![
                format!("agent_exec={agent_exec}"),
                format!("test_exec={}", infer_test_exec(root, &lower)),
                format!("changed_paths={}", infer_changed_paths(root)),
            ],
            reasons: vec![
                "project appears to have source/test files or instructions about tests before commit"
                    .into(),
            ],
        });
    }

    if mentions_any(
        &lower,
        &[
            "secret",
            "credential",
            "token",
            "api key",
            ".env",
            ".npmrc",
            ".pypirc",
        ],
    ) || root.join(".env").exists()
        || root.join("secrets").exists()
    {
        out.push(GeneratedTemplate {
            id: "no-secret-egress",
            params: vec![
                format!("secret_paths={}", infer_secret_paths(root)),
                "redactor_exec=**/redact".into(),
            ],
            reasons: vec![
                "project contains secret-like files or instructions mention secrets".into(),
            ],
        });
    }

    if mentions_any(&lower, &["no network", "offline", "external network"]) {
        out.push(GeneratedTemplate {
            id: "no-network",
            params: vec![
                format!("agent_exec={agent_exec}"),
                "loopback_endpoint=127.".into(),
            ],
            reasons: vec!["project instructions mention network isolation".into()],
        });
    }

    if mentions_any(&lower, &["read-only", "readonly"])
        && mentions_any(&lower, &["review", "subagent", "sub-agent"])
    {
        out.push(GeneratedTemplate {
            id: "readonly-review",
            params: vec![format!("agent_exec={agent_exec}")],
            reasons: vec!["project instructions mention read-only review work".into()],
        });
    }

    if mentions_any(&lower, &["prod.db", "production database", "migrate"]) {
        out.push(GeneratedTemplate {
            id: "prod-db-via-migrate",
            params: vec![
                "database_path=**/prod.db".into(),
                "mediator_exec=**/migrate".into(),
            ],
            reasons: vec!["project instructions mention production database mediation".into()],
        });
    }

    if out.is_empty() {
        notes.push(
            "no explicit guardrail instructions matched; emitted conservative repository defaults"
                .into(),
        );
        out.push(GeneratedTemplate {
            id: "no-git-branch",
            params: vec![format!("agent_exec={agent_exec}")],
            reasons: vec!["conservative default for agent-managed repositories".into()],
        });
        out.push(GeneratedTemplate {
            id: "test-before-commit",
            params: vec![
                format!("agent_exec={agent_exec}"),
                format!("test_exec={}", infer_test_exec(root, &lower)),
                format!("changed_paths={}", infer_changed_paths(root)),
            ],
            reasons: vec!["conservative default for source repositories".into()],
        });
    }

    Ok(GeneratedPolicy {
        root: root.to_path_buf(),
        instruction_files,
        task: task.map(ToOwned::to_owned),
        templates: out,
        notes,
    })
}

pub(crate) fn render_yaml(generated: &GeneratedPolicy) -> Result<String> {
    let mut out = String::new();
    out.push_str("# ActPlane candidate policy generated by `actplane templates generate`.\n");
    out.push_str("# Review before enforcement. The generator is deterministic and heuristic.\n");
    out.push_str("# Project root: ");
    out.push_str(&generated.root.display().to_string());
    out.push('\n');
    if generated.instruction_files.is_empty() {
        out.push_str("# Instructions considered: none found\n");
    } else {
        out.push_str("# Instructions considered:\n");
        for path in &generated.instruction_files {
            out.push_str("# - ");
            out.push_str(&path.display().to_string());
            out.push('\n');
        }
    }
    if let Some(task) = &generated.task {
        append_comment_block(&mut out, "Task hint", task);
    }
    for note in &generated.notes {
        out.push_str("# Note: ");
        out.push_str(note);
        out.push('\n');
    }
    out.push_str("version: 1\npolicy: |\n");
    for selection in &generated.templates {
        let template = templates::get(selection.id)?;
        out.push_str("  # template: ");
        out.push_str(selection.id);
        out.push('\n');
        for reason in &selection.reasons {
            out.push_str("  # reason: ");
            out.push_str(reason);
            out.push('\n');
        }
        for param in &selection.params {
            out.push_str("  # set: ");
            out.push_str(param);
            out.push('\n');
        }
        let dsl = templates::render_dsl(template, &selection.params)?;
        for line in dsl.trim_end().lines() {
            if !line.is_empty() {
                out.push_str("  ");
                out.push_str(line);
            }
            out.push('\n');
        }
        out.push('\n');
    }
    Ok(out)
}

pub(crate) fn summary(generated: &GeneratedPolicy) -> Vec<String> {
    generated
        .templates
        .iter()
        .map(|selection| {
            format!(
                "{} ({})",
                selection.id,
                selection
                    .reasons
                    .first()
                    .map(String::as_str)
                    .unwrap_or("selected")
            )
        })
        .collect()
}

fn discover_instruction_files(root: &Path) -> Vec<PathBuf> {
    let mut seen = BTreeSet::new();
    let mut out = Vec::new();
    for rel in [
        "AGENTS.md",
        "CLAUDE.md",
        ".agents/AGENTS.md",
        ".agents/instructions.md",
        ".codex/AGENTS.md",
    ] {
        let candidate = root.join(rel);
        if !candidate.is_file() {
            continue;
        }
        let key = candidate
            .canonicalize()
            .unwrap_or_else(|_| candidate.clone());
        if seen.insert(key) {
            out.push(candidate);
        }
    }
    out
}

fn truncate_to_char_boundary(text: &mut String, max_bytes: usize) -> bool {
    if text.len() <= max_bytes {
        return false;
    }
    let mut end = max_bytes;
    while end > 0 && !text.is_char_boundary(end) {
        end -= 1;
    }
    text.truncate(end);
    true
}

fn infer_agent_exec(lower: &str) -> &'static str {
    let mentions_codex = lower.contains("codex");
    let mentions_claude = lower.contains("claude");
    if mentions_codex && !mentions_claude {
        "codex"
    } else if mentions_claude && !mentions_codex {
        "claude"
    } else {
        "**"
    }
}

fn infer_test_exec(root: &Path, lower: &str) -> &'static str {
    if lower.contains("pytest") || root.join("pytest.ini").exists() {
        "**/pytest"
    } else if lower.contains("pnpm test") {
        "**/pnpm"
    } else if lower.contains("npm test") {
        "**/npm"
    } else if lower.contains("cargo test") {
        "**/cargo"
    } else if lower.contains("go test") {
        "**/go"
    } else {
        "**/pytest"
    }
}

fn infer_changed_paths(root: &Path) -> String {
    let mut paths = Vec::new();
    for rel in [
        "src/**",
        "tests/**",
        "collector/src/**",
        "collector/tests/**",
        "bpf/src/**",
        "bpf/tests/**",
        "cmd/**",
        "pkg/**",
    ] {
        let dir = rel.trim_end_matches("/**");
        if root.join(dir).is_dir() {
            paths.push(rel);
        }
    }
    if paths.is_empty() {
        "src/**,tests/**".into()
    } else {
        paths.join(",")
    }
}

fn infer_secret_paths(root: &Path) -> String {
    let mut paths = vec!["**/.env", "**/.npmrc", "**/.pypirc"];
    if root.join("secrets").exists() {
        paths.push("**/secrets/**");
    }
    paths.join(",")
}

fn has_source_tree(root: &Path) -> bool {
    [
        "src",
        "tests",
        "collector/src",
        "collector/tests",
        "bpf/src",
        "bpf/tests",
        "cmd",
        "pkg",
    ]
    .iter()
    .any(|rel| root.join(rel).is_dir())
}

fn mentions_test_before_commit(lower: &str) -> bool {
    (mentions_any(lower, &["before commit", "before committing", "git commit"])
        && mentions_any(
            lower,
            &["test", "pytest", "cargo test", "pnpm test", "npm test"],
        ))
        || lower.contains("test-before-commit")
}

fn mentions_any(haystack: &str, needles: &[&str]) -> bool {
    needles.iter().any(|needle| haystack.contains(needle))
}

fn append_comment_block(out: &mut String, label: &str, text: &str) {
    let mut lines = text.lines();
    if let Some(first) = lines.next() {
        out.push_str("# ");
        out.push_str(label);
        out.push_str(": ");
        out.push_str(first);
        out.push('\n');
    } else {
        out.push_str("# ");
        out.push_str(label);
        out.push_str(": \n");
        return;
    }
    for line in lines {
        out.push_str("# ");
        out.push_str(label);
        out.push_str(": ");
        out.push_str(line);
        out.push('\n');
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn generator_selects_templates_from_instructions_and_manifests() {
        let tmp = tempfile::tempdir().unwrap();
        std::fs::write(
            tmp.path().join("AGENTS.md"),
            "Do not run git branch. Run pytest before committing. Keep secrets safe.",
        )
        .unwrap();
        std::fs::create_dir(tmp.path().join("src")).unwrap();
        let generated = generate(tmp.path(), &[], None).unwrap();
        let ids = generated
            .templates
            .iter()
            .map(|selection| selection.id)
            .collect::<Vec<_>>();
        assert!(ids.contains(&"no-git-branch"));
        assert!(ids.contains(&"test-before-commit"));
        assert!(ids.contains(&"no-secret-egress"));
        let yaml = render_yaml(&generated).unwrap();
        assert!(yaml.contains("rule no-git-branch:"));
        assert!(yaml.contains("rule test-before-commit:"));
        assert!(yaml.contains("source SECRET = file"));
    }

    #[test]
    fn generator_uses_task_hint_without_instruction_files() {
        let tmp = tempfile::tempdir().unwrap();
        let generated = generate(tmp.path(), &[], Some("offline readonly review")).unwrap();
        let ids = generated
            .templates
            .iter()
            .map(|selection| selection.id)
            .collect::<Vec<_>>();
        assert!(ids.contains(&"no-network"));
        assert!(ids.contains(&"readonly-review"));
    }

    #[test]
    fn generator_task_comment_handles_multiline_text() {
        let tmp = tempfile::tempdir().unwrap();
        let generated = generate(tmp.path(), &[], Some("offline\nreadonly review")).unwrap();
        let yaml = render_yaml(&generated).unwrap();
        assert!(yaml.contains("# Task hint: offline\n# Task hint: readonly review"));
        let config: crate::config::FileConfig = serde_yaml::from_str(&yaml).unwrap();
        let loaded = crate::config::LoadedPolicy {
            config,
            root: PathBuf::new(),
            path: None,
        };
        let source = crate::config::policy_source(&loaded, None).unwrap();
        crate::dsl::compile_str(&source).unwrap();
    }

    #[test]
    fn generator_does_not_infer_broad_package_manager_as_test_without_test_phrase() {
        let tmp = tempfile::tempdir().unwrap();
        std::fs::write(tmp.path().join("Cargo.toml"), "[workspace]\n").unwrap();
        let generated = generate(tmp.path(), &[], None).unwrap();
        let test_before_commit = generated
            .templates
            .iter()
            .find(|selection| selection.id == "test-before-commit")
            .unwrap();
        assert!(
            test_before_commit
                .params
                .iter()
                .any(|param| param == "test_exec=**/pytest")
        );

        let generated =
            generate(tmp.path(), &[], Some("run cargo test before committing")).unwrap();
        let test_before_commit = generated
            .templates
            .iter()
            .find(|selection| selection.id == "test-before-commit")
            .unwrap();
        assert!(
            test_before_commit
                .params
                .iter()
                .any(|param| param == "test_exec=**/cargo")
        );
    }

    #[test]
    fn generator_truncates_large_unicode_instruction_on_char_boundary() {
        let tmp = tempfile::tempdir().unwrap();
        let prefix = "Do not run git branch.\n";
        let mut text = String::from(prefix);
        text.push_str(&"a".repeat(MAX_INSTRUCTION_BYTES - prefix.len() - 1));
        text.push('é');
        std::fs::write(tmp.path().join("AGENTS.md"), text).unwrap();

        let generated = generate(tmp.path(), &[], None).unwrap();

        assert!(
            generated
                .notes
                .iter()
                .any(|note| note.contains("truncated"))
        );
        assert!(
            generated
                .templates
                .iter()
                .any(|selection| selection.id == "no-git-branch")
        );
    }
}
