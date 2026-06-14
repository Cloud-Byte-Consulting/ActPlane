use std::io::Write;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{Value, json};

use crate::Result;

pub(crate) fn policy_hash(src: &str) -> String {
    let mut h = 0xcbf29ce484222325u64;
    for b in src.as_bytes() {
        h ^= u64::from(*b);
        h = h.wrapping_mul(0x100000001b3);
    }
    format!("fnv1a64:{h:016x}")
}

pub(crate) fn append(path: &Path, mut record: Value) -> Result<()> {
    append_with_schema(path, "actplane.audit.v1", &mut record)
}

pub(crate) fn append_with_schema(path: &Path, schema: &str, record: &mut Value) -> Result<()> {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let Some(obj) = record.as_object_mut() else {
        return Err("JSONL record must be a JSON object".into());
    };
    obj.entry("timestamp_unix_ns")
        .or_insert_with(|| json!(now.to_string()));
    obj.entry("schema").or_insert_with(|| json!(schema));
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let mut f = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)?;
    serde_json::to_writer(&mut f, &record)?;
    writeln!(f)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn audit_appends_jsonl_with_schema_and_timestamp() {
        let path =
            std::env::temp_dir().join(format!("actplane-audit-test-{}.jsonl", std::process::id()));
        let _ = std::fs::remove_file(&path);

        append(
            &path,
            json!({
                "event": "append_policy_delta",
                "status": "accepted",
                "target_id": 42
            }),
        )
        .expect("append audit");

        let text = std::fs::read_to_string(&path).expect("read audit");
        let value: Value = serde_json::from_str(text.trim()).expect("json line");
        assert_eq!(value["schema"], "actplane.audit.v1");
        assert_eq!(value["event"], "append_policy_delta");
        assert_eq!(value["status"], "accepted");
        assert_eq!(value["target_id"], 42);
        assert!(value["timestamp_unix_ns"].as_str().is_some());

        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn policy_hash_is_stable_and_content_sensitive() {
        assert_eq!(policy_hash("abc"), policy_hash("abc"));
        assert_ne!(policy_hash("abc"), policy_hash("abcd"));
        assert!(policy_hash("abc").starts_with("fnv1a64:"));
    }
}
