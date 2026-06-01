use std::path::{Path, PathBuf};

use crate::{Cli, Result};

const DEFAULT_POLICY_FILES: &[&str] = &["actplane.yaml", ".actplane/policy.yaml"];
pub(crate) const DEFAULT_FEEDBACK_FILE: &str = ".actplane/last-violation.txt";
pub(crate) const DEFAULT_HOOK_STATE_FILE: &str = ".actplane/feedback-hook.state.json";

#[derive(Debug, Default, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct FileConfig {
    #[serde(default, rename = "version")]
    _version: Option<u32>,
    pub(crate) policy: String,
    #[serde(default)]
    feedback: FeedbackConfig,
}

#[derive(Debug, Default, serde::Deserialize)]
struct FeedbackConfig {
    path: Option<PathBuf>,
}

pub(crate) struct LoadedPolicy {
    pub(crate) config: FileConfig,
    pub(crate) root: PathBuf,
    pub(crate) path: Option<PathBuf>,
}

#[derive(Clone)]
pub(crate) struct FeedbackPaths {
    pub(crate) feedback: PathBuf,
    pub(crate) state: PathBuf,
}

pub(crate) fn load_policy(cli: &Cli) -> Result<LoadedPolicy> {
    if let Some(rule) = &cli.rule {
        return Ok(LoadedPolicy {
            config: FileConfig {
                policy: rule.clone(),
                ..FileConfig::default()
            },
            root: std::env::current_dir()?,
            path: None,
        });
    }

    let cwd = std::env::current_dir()?;
    let explicit_policy = cli.policy.is_some();
    let path = match &cli.policy {
        Some(path) => absolutize(path, &cwd),
        None => discover_policy(&cwd)
            .ok_or("no actplane.yaml found; pass --policy <file> or --rule <dsl>")?,
    };
    if path.extension().is_some_and(|ext| ext == "dsl") {
        return Err(format!(
            "{} is a raw DSL file; policy files must be YAML with `policy: |`. Use `--rule` for one-off inline DSL.",
            path.display()
        )
        .into());
    }
    let src =
        std::fs::read_to_string(&path).map_err(|e| format!("reading {}: {}", path.display(), e))?;
    let config: FileConfig =
        serde_yaml::from_str(&src).map_err(|e| format!("parsing {}: {}", path.display(), e))?;
    if config.policy.trim().is_empty() {
        return Err(format!(
            "{} must contain a non-empty `policy: |` block",
            path.display()
        )
        .into());
    }
    let root = if explicit_policy {
        cwd
    } else {
        path.parent().map(Path::to_path_buf).unwrap_or(cwd)
    };
    Ok(LoadedPolicy {
        config,
        root,
        path: Some(path),
    })
}

pub(crate) fn discover_policy(start: &Path) -> Option<PathBuf> {
    let mut dir = Some(start);
    while let Some(d) = dir {
        for name in DEFAULT_POLICY_FILES {
            let candidate = d.join(name);
            if candidate.is_file() {
                return Some(candidate);
            }
        }
        dir = d.parent();
    }
    None
}

pub(crate) fn feedback_paths(loaded: &LoadedPolicy) -> FeedbackPaths {
    let feedback = loaded
        .config
        .feedback
        .path
        .as_ref()
        .map(|p| absolutize(p, &loaded.root))
        .unwrap_or_else(|| loaded.root.join(DEFAULT_FEEDBACK_FILE));
    let state = feedback
        .parent()
        .map(|p| p.join("feedback-hook.state.json"))
        .unwrap_or_else(|| loaded.root.join(DEFAULT_HOOK_STATE_FILE));
    FeedbackPaths { feedback, state }
}

pub(crate) fn absolutize(path: &Path, base: &Path) -> PathBuf {
    if path.is_absolute() {
        path.to_path_buf()
    } else {
        base.join(path)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn policy_yaml_rejects_removed_fallback_config() {
        let err = serde_yaml::from_str::<FileConfig>(
            r#"
policy: |
  source AGENT = exec "**/claude"
fallback:
  kill_on_violation: true
"#,
        )
        .unwrap_err();
        assert!(err.to_string().contains("unknown field `fallback`"));
    }
}
