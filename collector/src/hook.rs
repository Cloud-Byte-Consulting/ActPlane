use std::path::{Path, PathBuf};

use crate::Result;
use crate::config::{DEFAULT_FEEDBACK_FILE, DEFAULT_HOOK_STATE_FILE, absolutize};

const HOOK_MAX_CHARS: usize = 8000;

pub(crate) async fn feedback_hook() -> Result<()> {
    let data: serde_json::Value = match serde_json::from_str(&read_stdin()?) {
        Ok(v) => v,
        Err(_) => serde_json::Value::Object(Default::default()),
    };
    let cwd = data
        .get("cwd")
        .and_then(|v| v.as_str())
        .map(PathBuf::from)
        .unwrap_or(std::env::current_dir()?);
    let event = data
        .get("hook_event_name")
        .and_then(|v| v.as_str())
        .unwrap_or("PostToolUse");
    let feedback = env_path_or("ACTPLANE_FEEDBACK_FILE", &cwd, DEFAULT_FEEDBACK_FILE);
    let state = env_path_or(
        "ACTPLANE_HOOK_STATE",
        &cwd,
        feedback
            .parent()
            .map(|p| p.join("feedback-hook.state.json"))
            .unwrap_or_else(|| cwd.join(DEFAULT_HOOK_STATE_FILE))
            .to_string_lossy()
            .as_ref(),
    );
    let feedback_text = new_feedback(&feedback, &state)?;
    if feedback_text.trim().is_empty() {
        return Ok(());
    }
    let context = hook_context(&feedback_text);
    let output = serde_json::json!({
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": context,
        }
    });
    println!("{}", serde_json::to_string(&output)?);
    Ok(())
}

fn read_stdin() -> std::io::Result<String> {
    let mut raw = String::new();
    let mut stdin = std::io::stdin();
    std::io::Read::read_to_string(&mut stdin, &mut raw)?;
    Ok(raw)
}

fn env_path_or(name: &str, cwd: &Path, default: &str) -> PathBuf {
    let path = std::env::var_os(name)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(default));
    absolutize(&path, cwd)
}

fn new_feedback(feedback: &Path, state: &Path) -> Result<String> {
    let size = match std::fs::metadata(feedback) {
        Ok(m) => m.len(),
        Err(_) => return Ok(String::new()),
    };
    let (previous, mut offset) = load_hook_state(state).unwrap_or_default();
    let feedback_name = feedback.to_string_lossy().to_string();
    if previous.as_deref() != Some(feedback_name.as_str()) || offset > size {
        offset = 0;
    }
    if offset == size {
        return Ok(String::new());
    }
    let mut f = std::fs::File::open(feedback)?;
    std::io::Seek::seek(&mut f, std::io::SeekFrom::Start(offset))?;
    let mut buf = Vec::new();
    std::io::Read::read_to_end(&mut f, &mut buf)?;
    save_hook_state(state, feedback, size)?;
    Ok(String::from_utf8_lossy(&buf).trim().to_string())
}

fn load_hook_state(path: &Path) -> Option<(Option<String>, u64)> {
    let value: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(path).ok()?).ok()?;
    Some((
        value
            .get("feedback_file")
            .and_then(|v| v.as_str())
            .map(str::to_string),
        value.get("offset").and_then(|v| v.as_u64()).unwrap_or(0),
    ))
}

fn save_hook_state(state: &Path, feedback: &Path, offset: u64) -> Result<()> {
    if let Some(parent) = state.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let tmp = state.with_extension("tmp");
    let value = serde_json::json!({
        "feedback_file": feedback.to_string_lossy(),
        "offset": offset,
    });
    std::fs::write(&tmp, serde_json::to_string(&value)? + "\n")?;
    std::fs::rename(tmp, state)?;
    Ok(())
}

fn hook_context(feedback: &str) -> String {
    let text = if feedback.chars().count() > HOOK_MAX_CHARS {
        let tail: String = feedback
            .chars()
            .rev()
            .take(HOOK_MAX_CHARS)
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
            .collect();
        format!("... truncated ...\n{tail}")
    } else {
        feedback.to_string()
    };
    format!(
        "ActPlane detected an OS-level harness violation during the previous \
         tool action. Treat this as authoritative feedback from the kernel \
         engine; do not retry the same operation unchanged. Follow the \
         suggested alternative or satisfy the listed precondition.\n\n{text}"
    )
}
