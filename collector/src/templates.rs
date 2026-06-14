use serde_json::{Value, json};

use crate::Result;

#[derive(Debug)]
pub(crate) struct PolicyTemplate {
    pub(crate) id: &'static str,
    pub(crate) title: &'static str,
    pub(crate) category: &'static str,
    pub(crate) effect: &'static str,
    pub(crate) summary: &'static str,
    pub(crate) notes: &'static [&'static str],
    pub(crate) dsl: &'static str,
}

const TEMPLATES: &[PolicyTemplate] = &[
    PolicyTemplate {
        id: "no-git-branch",
        title: "Prevent agent-created git branches and worktrees",
        category: "process",
        effect: "kill",
        summary: "Terminates git branch/worktree attempts from the protected process tree.",
        notes: &[
            "Uses kill rather than block because argv-sensitive exec predicates are observed after exec.",
            "Good default for repos where branch/worktree management should stay with the human/operator.",
            "With `actplane run` or `watch`, the protected root is also seeded with the COMMAND label. Standalone users can narrow `exec \"**\"` to their agent executable.",
        ],
        dsl: r#"source COMMAND = exec "**"

rule no-git-branch:
  kill exec "git" "branch"   if COMMAND
  kill exec "git" "worktree" if COMMAND
  because "This workspace forbids creating git branches or worktrees. Use other git commands, or ask the user to manage branches."
"#,
    },
    PolicyTemplate {
        id: "no-secret-egress",
        title: "Stop local secret-derived data from reaching the network",
        category: "ifc",
        effect: "block",
        summary: "Labels common secret files and denies network egress after secret-derived reads when BPF-LSM block support is active.",
        notes: &[
            "Endpoint matching is numeric IPv4-oriented in the kernel. Use `actplane check --explain` to review host support.",
            "Edit the source paths and redactor command for the project before enforcing broadly.",
        ],
        dsl: r#"source SECRET = file "**/.env"
source SECRET = file "**/.npmrc"
source SECRET = file "**/.pypirc"
source SECRET = file "**/secrets/**"

rule no-secret-egress:
  block connect endpoint "*" if SECRET
  because "Data derived from local secrets must not leave the host. Redact or declassify first."

declassify SECRET by exec "**/redact"
"#,
    },
    PolicyTemplate {
        id: "test-before-commit",
        title: "Require a fresh test run before git commit",
        category: "causal",
        effect: "kill",
        summary: "Requires pytest to exit 0 after source/test edits before git commit.",
        notes: &[
            "Uses kill for the argv-sensitive git commit predicate.",
            "Replace pytest and path globs with the repo's real test command and source roots.",
            "With `actplane run` or `watch`, the protected root is also seeded with the AGENT label. Standalone users can narrow `exec \"**\"` to their agent executable.",
        ],
        dsl: r#"source AGENT = exec "**"

rule test-before-commit:
  kill exec "git" "commit" if AGENT
    unless after exec "**/pytest" exits 0 since write "src/**" or write "tests/**"
  because "Source or test files changed since the last successful test run. Run pytest before committing."
"#,
    },
    PolicyTemplate {
        id: "workspace-confinement",
        title: "Confine writes to an allowed workspace path",
        category: "sandbox",
        effect: "block",
        summary: "Denies writes and deletes outside /work when BPF-LSM block support is active.",
        notes: &[
            "Change /work/** to the repo or task-specific writable area before use.",
            "Run `actplane check --explain` before rollout. Without BPF-LSM, block rules are reported as unsupported.",
            "With `actplane run` or `watch`, the protected root is also seeded with the AGENT label. Standalone users can narrow `exec \"**\"` to their agent executable.",
        ],
        dsl: r#"source AGENT = exec "**"

rule workspace-confinement:
  block write file "/**"  if AGENT unless target "/work/**"
  block unlink file "/**" if AGENT unless target "/work/**"
  because "Modify only files under /work, or ask the user to approve a different writable path."
"#,
    },
    PolicyTemplate {
        id: "readonly-review",
        title: "Make a review domain read-only",
        category: "sandbox",
        effect: "block",
        summary: "Denies file writes and deletes when BPF-LSM block support is active.",
        notes: &[
            "Useful for review-only subagents or untrusted tool invocations.",
            "Pair with runtime domains when multiple agents share one host workspace.",
            "Run `actplane check --explain` before rollout. Without BPF-LSM, block rules are reported as unsupported.",
            "With `actplane run` or `watch`, the protected root is also seeded with the AGENT label. Standalone users can narrow `exec \"**\"` to their agent executable.",
        ],
        dsl: r#"source AGENT = exec "**"

rule readonly-review:
  block write file "/**"  if AGENT
  block unlink file "/**" if AGENT
  because "This review domain is read-only. Ask the user before modifying files."
"#,
    },
    PolicyTemplate {
        id: "no-network",
        title: "Disable external network egress",
        category: "network",
        effect: "block",
        summary: "Denies outbound connects except loopback numeric IPv4 destinations when BPF-LSM block support is active.",
        notes: &[
            "Loopback is allowed with target prefix 127.; remove the exception for stricter isolation.",
            "Hostname and IPv6 endpoint globs are not kernel-enforced today.",
            "Run `actplane check --explain` before rollout. Without BPF-LSM, block rules are reported as unsupported.",
            "With `actplane run` or `watch`, the protected root is also seeded with the AGENT label. Standalone users can narrow `exec \"**\"` to their agent executable.",
        ],
        dsl: r#"source AGENT = exec "**"

rule no-network:
  block connect endpoint "*" if AGENT unless target "127."
  because "This domain cannot use external network egress."
"#,
    },
    PolicyTemplate {
        id: "prod-db-via-migrate",
        title: "Require a mediation tool for production database access",
        category: "mediation",
        effect: "block",
        summary: "Pre-op blocks prod.db opens unless the lineage includes the migration tool.",
        notes: &[
            "This is intended as a BPF-LSM block policy. Check host support before relying on pre-op denial.",
            "Replace prod.db and migrate with the project's real protected resource and access tool.",
        ],
        dsl: r#"rule prod-db-via-migrate:
  block open file "**/prod.db" if true unless lineage-includes exec "**/migrate"
  because "Access prod.db only through the migration tool."
"#,
    },
];

pub(crate) fn all() -> &'static [PolicyTemplate] {
    TEMPLATES
}

pub(crate) fn get(id: &str) -> Result<&'static PolicyTemplate> {
    TEMPLATES
        .iter()
        .find(|template| template.id == id)
        .ok_or_else(|| {
            format!(
                "unknown template `{}` (available: {})",
                id,
                TEMPLATES
                    .iter()
                    .map(|template| template.id)
                    .collect::<Vec<_>>()
                    .join(", ")
            )
            .into()
        })
}

pub(crate) fn json() -> Value {
    json!({
        "schema": "actplane.templates.v1",
        "templates": TEMPLATES.iter().map(template_json).collect::<Vec<_>>(),
    })
}

fn template_json(template: &PolicyTemplate) -> Value {
    json!({
        "id": template.id,
        "title": template.title,
        "category": template.category,
        "effect": template.effect,
        "summary": template.summary,
        "notes": template.notes,
    })
}

pub(crate) fn render_dsl(template: &PolicyTemplate) -> &str {
    template.dsl
}

pub(crate) fn render_yaml(template: &PolicyTemplate) -> String {
    let mut out = String::new();
    out.push_str("# ActPlane policy generated from template `");
    out.push_str(template.id);
    out.push_str("`.\n");
    out.push_str("# ");
    out.push_str(template.summary);
    out.push('\n');
    for note in template.notes {
        out.push_str("# Note: ");
        out.push_str(note);
        out.push('\n');
    }
    out.push_str("version: 1\npolicy: |\n");
    for line in template.dsl.trim_end().lines() {
        if !line.is_empty() {
            out.push_str("  ");
            out.push_str(line);
        }
        out.push('\n');
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::{FileConfig, LoadedPolicy, policy_source};
    use crate::dsl;
    use std::path::PathBuf;

    #[test]
    fn all_templates_compile_as_dsl_and_yaml() {
        assert!(all().len() >= 6);
        for template in all() {
            dsl::compile_str(template.dsl)
                .unwrap_or_else(|e| panic!("template {} DSL compile: {e}", template.id));

            let yaml = render_yaml(template);
            let config: FileConfig = serde_yaml::from_str(&yaml)
                .unwrap_or_else(|e| panic!("template {} YAML parse: {e}", template.id));
            let loaded = LoadedPolicy {
                config,
                root: PathBuf::new(),
                path: None,
            };
            let source = policy_source(&loaded, None)
                .unwrap_or_else(|e| panic!("template {} policy source: {e}", template.id));
            dsl::compile_str(&source)
                .unwrap_or_else(|e| panic!("template {} YAML compile: {e}", template.id));
        }
    }

    #[test]
    fn unknown_template_lists_available_ids() {
        let err = get("missing-template").unwrap_err().to_string();
        assert!(err.contains("unknown template `missing-template`"));
        assert!(err.contains("no-secret-egress"));
    }
}
