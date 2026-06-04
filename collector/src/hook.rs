use std::path::{Path, PathBuf};
use std::thread;
use std::time::Duration;

use crate::Result;
use crate::config::{DEFAULT_FEEDBACK_FILE, DEFAULT_HOOK_STATE_FILE, absolutize};

const HOOK_MAX_CHARS: usize = 8000;
const FEEDBACK_SEPARATOR: &str = "\n----\n";

#[derive(Default, serde::Deserialize, serde::Serialize)]
struct HookState {
    feedback_file: Option<String>,
    root_pid: Option<i32>,
}

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
    let default_feedback = env_path_or("ACTPLANE_FEEDBACK_FILE", &cwd, DEFAULT_FEEDBACK_FILE);
    let default_state = env_path_or(
        "ACTPLANE_HOOK_STATE",
        &cwd,
        default_feedback
            .parent()
            .map(|p| p.join("feedback-hook.state.json"))
            .unwrap_or_else(|| cwd.join(DEFAULT_HOOK_STATE_FILE))
            .to_string_lossy()
            .as_ref(),
    );

    let Some(feedback) = select_feedback_file(&cwd, &default_feedback, &default_state) else {
        return Ok(());
    };

    let feedback_text = consume_one_feedback(&feedback)?;
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

pub(crate) fn write_hook_state(state: &Path, feedback: &Path, root_pid: i32) -> Result<()> {
    if let Some(parent) = state.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let tmp = state.with_extension("tmp");
    let value = HookState {
        feedback_file: Some(feedback.to_string_lossy().to_string()),
        root_pid: Some(root_pid),
    };
    std::fs::write(&tmp, serde_json::to_string(&value)? + "\n")?;
    std::fs::rename(tmp, state)?;
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

fn load_hook_state(path: &Path) -> Option<HookState> {
    serde_json::from_str(&std::fs::read_to_string(path).ok()?).ok()
}

fn select_feedback_file(cwd: &Path, default_feedback: &Path, default_state: &Path) -> Option<PathBuf> {
    if let Some(state) = load_hook_state(default_state) {
        if hook_matches_agent(&state) {
            return state
                .feedback_file
                .map(PathBuf::from)
                .or_else(|| Some(default_feedback.to_path_buf()));
        }
        return discover_matching_feedback(cwd);
    }
    discover_matching_feedback(cwd).or_else(|| {
        if default_feedback.exists() {
            Some(default_feedback.to_path_buf())
        } else {
            None
        }
    })
}

fn discover_matching_feedback(cwd: &Path) -> Option<PathBuf> {
    let runs = cwd.join(".actplane").join("runs");
    let entries = std::fs::read_dir(runs).ok()?;
    let mut matches = Vec::new();
    for entry in entries.flatten() {
        let state_path = entry.path().join("hook-state.json");
        let Some(state) = load_hook_state(&state_path) else {
            continue;
        };
        if hook_matches_agent(&state) {
            if let Some(path) = state.feedback_file {
                matches.push(PathBuf::from(path));
            }
        }
    }
    matches.sort();
    matches.pop()
}

fn hook_matches_agent(state: &HookState) -> bool {
    let Some(root_pid) = state.root_pid else {
        return true;
    };
    root_pid > 1 && is_descendant_of(std::process::id() as i32, root_pid)
}

fn is_descendant_of(mut pid: i32, root_pid: i32) -> bool {
    for _ in 0..128 {
        if pid == root_pid {
            return true;
        }
        if pid <= 1 {
            return false;
        }
        let Some(ppid) = parent_pid(pid) else {
            return false;
        };
        pid = ppid;
    }
    false
}

fn parent_pid(pid: i32) -> Option<i32> {
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat")).ok()?;
    let rparen = stat.rfind(')')?;
    let after = stat.get(rparen + 2..)?;
    let mut fields = after.split_whitespace();
    let _state = fields.next()?;
    fields.next()?.parse().ok()
}

fn consume_one_feedback(feedback: &Path) -> Result<String> {
    let Some(parent) = feedback.parent() else {
        return consume_one_feedback_locked(feedback);
    };
    std::fs::create_dir_all(parent)?;
    let lock = parent.join(".feedback.lock");
    let _guard = match FeedbackLock::acquire(&lock)? {
        Some(guard) => guard,
        None => return Ok(String::new()),
    };
    consume_one_feedback_locked(feedback)
}

fn consume_one_feedback_locked(feedback: &Path) -> Result<String> {
    let raw = match std::fs::read_to_string(feedback) {
        Ok(s) => s,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(String::new()),
        Err(e) => return Err(e.into()),
    };
    if raw.trim().is_empty() {
        return Ok(String::new());
    }
    let (next, rest) = split_first_feedback(&raw);
    std::fs::write(feedback, rest)?;
    Ok(next.trim().to_string())
}

fn split_first_feedback(raw: &str) -> (String, String) {
    if let Some(idx) = raw.find(FEEDBACK_SEPARATOR) {
        let next = raw[..idx].to_string();
        let rest = raw[idx + FEEDBACK_SEPARATOR.len()..].to_string();
        return (next, rest);
    }
    (raw.to_string(), String::new())
}

struct FeedbackLock {
    path: PathBuf,
}

impl FeedbackLock {
    fn acquire(path: &Path) -> Result<Option<Self>> {
        for _ in 0..20 {
            match std::fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(path)
            {
                Ok(_) => {
                    return Ok(Some(Self {
                        path: path.to_path_buf(),
                    }));
                }
                Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
                    thread::sleep(Duration::from_millis(10));
                }
                Err(e) => return Err(e.into()),
            }
        }
        Ok(None)
    }
}

impl Drop for FeedbackLock {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.path);
    }
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn split_consumes_one_feedback() {
        let raw = "one\n----\ntwo\n----\n";
        let (next, rest) = split_first_feedback(raw);
        assert_eq!(next, "one");
        assert_eq!(rest, "two\n----\n");
    }

    #[test]
    fn split_consumes_unsuffixed_feedback() {
        let (next, rest) = split_first_feedback("one");
        assert_eq!(next, "one");
        assert_eq!(rest, "");
    }
}
