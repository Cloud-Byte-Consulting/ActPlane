// SPDX-License-Identifier: MIT
// Copyright (c) 2026 eunomia-bpf org.
//
//! eBPF IFC engine loader (aya).
//!
//! Loads the prebuilt CO-RE object `process.bpf.o` (compiled from the untouched
//! kernel C in this directory), installs the compiled policy into writable BPF
//! array maps, attaches the enforcer, and surfaces `TAINT_VIOLATION` events.
//! Supports hot-reload of policy rules via `ReloadHandle` (user ring buffer).
//!
//! The config blob is exactly the `struct taint_config` the collector's DSL
//! compiler already produces (the same bytes the C loader read from `--config`).

use std::io::{self, Read};
use std::os::fd::{AsFd, AsRawFd, FromRawFd, OwnedFd};
use std::sync::atomic::{AtomicBool, Ordering};

use aya::maps::{Array, HashMap, Map, RingBuf};
use aya::programs::{Lsm, TracePoint};
use aya::{Btf, Ebpf, EbpfLoader};

pub mod capability;
use capability::{
    CapState, DeltaRequest, AUTH_BIND_RULE, AUTH_NARROW_SCOPE, TARGET_CHILD, TARGET_SELF,
};

// ---- prebuilt eBPF object, 8-byte aligned for aya's ELF parser ----
#[repr(align(8))]
struct Aligned<T: ?Sized>(T);
static OBJECT: &Aligned<[u8]> =
    &Aligned(*include_bytes!(concat!(env!("OUT_DIR"), "/process.bpf.o")));
fn object_bytes() -> &'static [u8] {
    &OBJECT.0
}

// ===================== ABI mirrors (must match bpf/taint.h) =====================
// Identical to collector/src/dsl/lower.rs; guarded by abi_size_matches() below.
const PAT: usize = 64;
const ARG: usize = 24;
const MAX_UPDATES: usize = 320;
const MAX_RULES: usize = 128;
const MAX_TAINT_LABELS: usize = 64;
const M_SUFFIX: u8 = 2;
const OP_EXEC: u8 = 0;
const C_TARGET: u8 = 3;

#[repr(C)]
#[derive(Clone, Copy)]
struct CUpdate {
    op: u8,
    m: u8,
    target: [u8; PAT],
    arg: [u8; ARG],
    add: u64,
    del: u64,
    gates: u64,
    invals: u64,
    ipv4: u32,
    ipv4_mask: u32,
    gate_exit_code: i32,
}
#[repr(C)]
#[derive(Clone, Copy)]
struct CRule {
    op: u8,
    m: u8,
    cond_kind: u8,
    cond_neg: u8,
    cond_match: u8,
    effect: u8,
    target: [u8; PAT],
    arg: [u8; ARG],
    cond_pat: [u8; PAT],
    req: u64,
    forbid: u64,
    gate: u64,
    rule_id: u32,
    ipv4: u32,
    ipv4_mask: u32,
    cond_ipv4: u32,
    cond_ipv4_mask: u32,
    gate_idx: u32,
    since_mask: u64,
}
#[repr(C)]
#[derive(Clone, Copy)]
struct CConfig {
    n_updates: u32,
    n_rules: u32,
    updates: [CUpdate; MAX_UPDATES],
    rules: [CRule; MAX_RULES],
}

// proc_state seed (bpf/taint_engine.bpf.h: { u64 labels; u64 lin_gates; }).
#[repr(C)]
#[derive(Clone, Copy)]
struct ProcState {
    labels: u64,
    lin_gates: u64,
}

unsafe impl aya::Pod for CUpdate {}
unsafe impl aya::Pod for CRule {}
unsafe impl aya::Pod for ProcState {}

// ringbuf event (bpf/process.h: struct event).
const EVENT_TYPE_TAINT_VIOLATION: i32 = 3;
const COMM_LEN: usize = 16;
const FILENAME_LEN: usize = 127;

#[repr(C)]
#[derive(Clone, Copy)]
struct Event {
    etype: i32,
    pid: i32,
    ppid: i32,
    blocked: u32,
    killed: u32,
    effect: u32,
    timestamp_ns: u64,
    comm: [u8; COMM_LEN],
    filename: [u8; FILENAME_LEN],
    taint_rule_id: u32,
    conn_ip: u32,
    taint_label: u64,
    matched_label: u64,
    prov_label: u64,
    prov_timestamp_ns: u64,
    prov_pid: i32,
    prov_op: u32,
    prov_ip: u32,
    prov_target: [u8; FILENAME_LEN],
}

/// Provenance for the label that caused a policy violation.
#[derive(Debug, Clone)]
pub struct Provenance {
    pub label: u64,
    pub timestamp_ns: u64,
    pub pid: i32,
    pub op: u32,
    pub target: String,
}

/// A policy violation reported by the kernel.
#[derive(Debug, Clone)]
pub struct Violation {
    pub effect: u32, // 0 notify, 1 block, 2 kill
    pub blocked: bool,
    pub killed: bool,
    pub comm: String,
    pub pid: i32,
    pub ppid: i32,
    pub target: String, // exe/path, or "a.b.c.d" for connect
    pub rule_id: u32,
    pub label: u64,
    pub matched_label: u64,
    pub provenance: Option<Provenance>,
    pub timestamp_ns: u64,
}

/// Tracepoint programs: (fn name, category, event). Always attached.
const TRACEPOINTS: &[(&str, &str, &str)] = &[
    ("handle_fork", "sched", "sched_process_fork"),
    ("handle_exec", "sched", "sched_process_exec"),
    ("handle_exit", "sched", "sched_process_exit"),
    ("trace_openat", "syscalls", "sys_enter_openat"),
    ("trace_openat_exit", "syscalls", "sys_exit_openat"),
    ("trace_open", "syscalls", "sys_enter_open"),
    ("trace_open_exit", "syscalls", "sys_exit_open"),
    ("trace_openat2", "syscalls", "sys_enter_openat2"),
    ("trace_openat2_exit", "syscalls", "sys_exit_openat2"),
    ("trace_creat", "syscalls", "sys_enter_creat"),
    ("trace_creat_exit", "syscalls", "sys_exit_creat"),
    ("trace_truncate", "syscalls", "sys_enter_truncate"),
    ("trace_truncate_exit", "syscalls", "sys_exit_truncate"),
    ("trace_unlink", "syscalls", "sys_enter_unlink"),
    ("trace_unlinkat", "syscalls", "sys_enter_unlinkat"),
    ("trace_rename", "syscalls", "sys_enter_rename"),
    ("trace_renameat", "syscalls", "sys_enter_renameat"),
    ("trace_renameat2", "syscalls", "sys_enter_renameat2"),
    ("trace_connect", "syscalls", "sys_enter_connect"),
    ("trace_read", "syscalls", "sys_enter_read"),
    ("trace_write", "syscalls", "sys_enter_write"),
    ("cap_drain_tick", "syscalls", "sys_enter_getpid"),
];

/// LSM programs: (fn name, hook). Attached only when BPF LSM is active.
const LSM_PROGS: &[(&str, &str)] = &[
    ("enforce_bprm_check_security", "bprm_check_security"),
    ("enforce_file_open", "file_open"),
    ("enforce_file_permission", "file_permission"),
    ("enforce_file_truncate", "file_truncate"),
    ("enforce_path_truncate", "path_truncate"),
    ("enforce_path_unlink", "path_unlink"),
    ("enforce_path_rename", "path_rename"),
    ("enforce_socket_connect", "socket_connect"),
];

/// True if `bpf` appears in the active LSM list (enables pre-op `block`).
pub fn bpf_lsm_active() -> bool {
    if std::env::var_os("ACTPLANE_FORCE_TRACEPOINT").is_some() {
        return false;
    }
    let mut s = String::new();
    if let Ok(mut f) = std::fs::File::open("/sys/kernel/security/lsm") {
        let _ = f.read_to_string(&mut s);
    }
    s.split(',').any(|x| x.trim() == "bpf")
}

fn err(msg: impl Into<String>) -> io::Error {
    io::Error::new(io::ErrorKind::Other, msg.into())
}

fn validate_config(cfg: &CConfig) -> io::Result<()> {
    for (i, u) in cfg
        .updates
        .iter()
        .take((cfg.n_updates as usize).min(MAX_UPDATES))
        .enumerate()
    {
        if u.op == OP_EXEC && u.m == M_SUFFIX {
            return Err(err(format!("config update[{i}]: suffix exec matches are unsupported; use DSL exec patterns that lower to exact/prefix")));
        }
    }
    for (i, r) in cfg
        .rules
        .iter()
        .take((cfg.n_rules as usize).min(MAX_RULES))
        .enumerate()
    {
        if r.op == OP_EXEC && r.m == M_SUFFIX {
            return Err(err(format!("config rule[{i}]: suffix exec matches are unsupported; use DSL exec patterns that lower to exact/prefix")));
        }
        if r.op == OP_EXEC && r.cond_kind == C_TARGET && r.cond_match == M_SUFFIX {
            return Err(err(format!("config rule[{i}]: suffix exec target conditions are unsupported; use exact/prefix exec patterns")));
        }
    }
    Ok(())
}

pub struct Loader {
    bpf: Ebpf,
    enforce: bool,
}

impl Loader {
    /// `config_blob` is the raw `struct taint_config` produced by the collector.
    pub fn load(config_blob: &[u8]) -> io::Result<Self> {
        if config_blob.len() != std::mem::size_of::<CConfig>() {
            return Err(err(format!(
                "config size mismatch: got {}, expected {}",
                config_blob.len(),
                std::mem::size_of::<CConfig>()
            )));
        }
        // Owned, aligned copy so we can borrow fields for set_global.
        let cfg: Box<CConfig> =
            Box::new(unsafe { std::ptr::read_unaligned(config_blob.as_ptr() as *const CConfig) });
        validate_config(&cfg)?;

        let enforce = bpf_lsm_active();
        let enforce_mode: u32 = if enforce { 1 } else { 0 };

        let mut loader = EbpfLoader::new();
        loader
            .allow_unsupported_maps()
            .set_global("enforce_mode", &enforce_mode, true);

        let mut bpf = loader
            .load(object_bytes())
            .map_err(|e| err(format!("Ebpf::load: {e}")))?;

        // Populate writable array maps for updates and rules.
        populate_update_map(&mut bpf, &cfg)?;
        populate_rule_map(&mut bpf, &cfg)?;

        // Loop counts in a (non-frozen) map so the verifier analyzes each
        // bpf_loop callback once. Slots: 0=rules 1=updates 5=labels.
        {
            let mut counts: Array<_, u32> = Array::try_from(
                bpf.map_mut("ts_counts")
                    .ok_or_else(|| err("map ts_counts missing"))?,
            )
            .map_err(|e| err(format!("ts_counts: {e}")))?;
            let vals = [cfg.n_rules, cfg.n_updates, 0, 0, 0, MAX_TAINT_LABELS as u32];
            for (i, v) in vals.iter().enumerate() {
                counts
                    .set(i as u32, *v, 0)
                    .map_err(|e| err(format!("ts_counts[{i}]: {e}")))?;
            }
        }

        let has_connect =
            (0..cfg.n_rules as usize).any(|i| cfg.rules.get(i).map_or(false, |r| r.op == 3));

        // Attach tracepoints (always) then LSM programs (only with BPF LSM).
        for (name, cat, event) in TRACEPOINTS {
            if !has_connect && *name == "trace_connect" {
                continue;
            }
            let p: &mut TracePoint = bpf
                .program_mut(name)
                .ok_or_else(|| err(format!("program {name} missing")))?
                .try_into()
                .map_err(|e| err(format!("{name} not a tracepoint: {e}")))?;
            p.load().map_err(|e| err(format!("{name}.load: {e}")))?;
            p.attach(cat, event)
                .map_err(|e| err(format!("{name}.attach: {e}")))?;
        }
        if enforce {
            let btf = Btf::from_sys_fs().map_err(|e| err(format!("btf: {e}")))?;
            for (name, hook) in LSM_PROGS {
                if !has_connect && *name == "enforce_socket_connect" {
                    continue;
                }
                let p: &mut Lsm = bpf
                    .program_mut(name)
                    .ok_or_else(|| err(format!("program {name} missing")))?
                    .try_into()
                    .map_err(|e| err(format!("{name} not an lsm: {e}")))?;
                p.load(hook, &btf)
                    .map_err(|e| err(format!("{name}.load: {e}")))?;
                p.attach().map_err(|e| err(format!("{name}.attach: {e}")))?;
            }
        }

        Ok(Loader { bpf, enforce })
    }

    pub fn enforce_mode(&self) -> bool {
        self.enforce
    }

    /// Create a `ReloadHandle` that can hot-reload policy into this engine.
    pub fn reload_handle(&self) -> io::Result<ReloadHandle> {
        let map = self
            .bpf
            .map("cap_req")
            .ok_or_else(|| err("cap_req missing"))?;
        let map_data = match map {
            Map::Unsupported(data) => data,
            _ => return Err(err("cap_req is not a user ringbuf map")),
        };
        let raw = map_data.fd().as_fd().as_raw_fd();
        let dup = unsafe { libc::dup(raw) };
        if dup < 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(ReloadHandle {
            cap_req_fd: unsafe { OwnedFd::from_raw_fd(dup) },
        })
    }

    /// Seed `pid` and its future descendants with an initial label.
    pub fn seed_label(&mut self, pid: i32, label: u64) -> io::Result<()> {
        if pid <= 0 || label == 0 {
            return Err(err("pid and label must both be set"));
        }
        {
            let mut proc: HashMap<_, i32, ProcState> = HashMap::try_from(
                self.bpf
                    .map_mut("ts_proc")
                    .ok_or_else(|| err("ts_proc missing"))?,
            )
            .map_err(|e| err(format!("ts_proc: {e}")))?;
            proc.insert(
                pid,
                ProcState {
                    labels: label,
                    lin_gates: 0,
                },
                0,
            )
            .map_err(|e| err(format!("seed ts_proc: {e}")))?;
        }
        {
            let mut root: HashMap<_, i32, i32> = HashMap::try_from(
                self.bpf
                    .map_mut("ts_root")
                    .ok_or_else(|| err("ts_root missing"))?,
            )
            .map_err(|e| err(format!("ts_root: {e}")))?;
            root.insert(pid, pid, 0)
                .map_err(|e| err(format!("seed ts_root: {e}")))?;
        }
        self.bind_state(
            pid,
            pid as u32,
            CapState {
                scope_id: 1,
                labels: label,
                authority_mask: AUTH_BIND_RULE | AUTH_NARROW_SCOPE,
                target_mask: TARGET_SELF | TARGET_CHILD,
                ..CapState::default()
            },
        )?;
        Ok(())
    }

    /// Bind a Linux pid to an engine state id.
    pub fn bind_state(&mut self, pid: i32, target_id: u32, state: CapState) -> io::Result<()> {
        if pid <= 0 || target_id == 0 {
            return Err(err("pid and target id must both be set"));
        }
        {
            let mut pid_map: HashMap<_, i32, u32> = HashMap::try_from(
                self.bpf
                    .map_mut("cap_task")
                    .ok_or_else(|| err("cap_task missing"))?,
            )
            .map_err(|e| err(format!("cap_task: {e}")))?;
            pid_map
                .insert(pid, target_id, 0)
                .map_err(|e| err(format!("seed cap_task: {e}")))?;
        }
        {
            let mut states: HashMap<_, u32, CapState> = HashMap::try_from(
                self.bpf
                    .map_mut("cap_state")
                    .ok_or_else(|| err("cap_state missing"))?,
            )
            .map_err(|e| err(format!("cap_state: {e}")))?;
            states
                .insert(target_id, state, 0)
                .map_err(|e| err(format!("seed cap_state: {e}")))?;
        }
        Ok(())
    }

    /// Submit a runtime policy delta through the user-to-kernel ring buffer.
    ///
    /// The BPF side admits the request only if `caller_pid` maps to a state with
    /// the needed authority masks, and then applies a monotonic delta to
    /// `cap_state`. The caller normally sets `caller_pid` to its own pid; this
    /// method triggers a `getpid` syscall so the BPF drain hook runs.
    pub fn submit_delta(&self, req: DeltaRequest) -> io::Result<()> {
        let map = self
            .bpf
            .map("cap_req")
            .ok_or_else(|| err("cap_req missing"))?;
        let map_data = match map {
            Map::Unsupported(data) => data,
            _ => return Err(err("cap_req is not a user ringbuf map")),
        };
        let fd = map_data.fd().as_fd().as_raw_fd();
        unsafe {
            let rb = libbpf_sys::user_ring_buffer__new(fd, std::ptr::null());
            if rb.is_null() {
                return Err(io::Error::last_os_error());
            }
            let sample = libbpf_sys::user_ring_buffer__reserve(
                rb,
                std::mem::size_of::<DeltaRequest>() as u32,
            );
            if sample.is_null() {
                let e = io::Error::last_os_error();
                libbpf_sys::user_ring_buffer__free(rb);
                return Err(e);
            }
            std::ptr::copy_nonoverlapping(
                &req as *const DeltaRequest as *const u8,
                sample as *mut u8,
                std::mem::size_of::<DeltaRequest>(),
            );
            libbpf_sys::user_ring_buffer__submit(rb, sample);
            libbpf_sys::user_ring_buffer__free(rb);
            libc::syscall(libc::SYS_getpid);
        }
        Ok(())
    }

    /// Poll the ring buffer until `stop` is set, delivering each violation.
    pub fn run(&mut self, stop: &AtomicBool, mut on: impl FnMut(Violation)) -> io::Result<()> {
        let mut ring = RingBuf::try_from(self.bpf.map_mut("rb").ok_or_else(|| err("rb missing"))?)
            .map_err(|e| err(format!("rb: {e}")))?;
        let fd = ring.as_raw_fd();

        while !stop.load(Ordering::Relaxed) {
            let mut pfd = libc::pollfd {
                fd,
                events: libc::POLLIN,
                revents: 0,
            };
            let r = unsafe { libc::poll(&mut pfd, 1, 100) };
            if r < 0 {
                let e = io::Error::last_os_error();
                if e.kind() == io::ErrorKind::Interrupted {
                    continue;
                }
                return Err(e);
            }
            while let Some(item) = ring.next() {
                let bytes: &[u8] = &item;
                if bytes.len() < std::mem::size_of::<Event>() {
                    continue;
                }
                let e: Event = unsafe { std::ptr::read_unaligned(bytes.as_ptr() as *const Event) };
                if e.etype != EVENT_TYPE_TAINT_VIOLATION {
                    continue;
                }
                on(decode(&e));
            }
        }
        Ok(())
    }
}

// ── Map population helpers ──────────────────────────────────────────

fn populate_update_map(bpf: &mut Ebpf, cfg: &CConfig) -> io::Result<()> {
    let mut updates_map: Array<_, CUpdate> = Array::try_from(
        bpf.map_mut("ts_updates")
            .ok_or_else(|| err("map ts_updates missing"))?,
    )
    .map_err(|e| err(format!("ts_updates: {e}")))?;
    for i in 0..cfg.n_updates as usize {
        updates_map
            .set(i as u32, cfg.updates[i], 0)
            .map_err(|e| err(format!("ts_updates[{i}]: {e}")))?;
    }
    Ok(())
}

fn populate_rule_map(bpf: &mut Ebpf, cfg: &CConfig) -> io::Result<()> {
    let mut rules_map: Array<_, CRule> = Array::try_from(
        bpf.map_mut("ts_rules")
            .ok_or_else(|| err("map ts_rules missing"))?,
    )
    .map_err(|e| err(format!("ts_rules: {e}")))?;
    for i in 0..cfg.n_rules as usize {
        rules_map
            .set(i as u32, cfg.rules[i], 0)
            .map_err(|e| err(format!("ts_rules[{i}]: {e}")))?;
    }
    Ok(())
}

// ── Hot-reload via cap_req ring buffer ─────────────────────────────

const CAP_REQ_RELOAD_UPDATE: i32 = -1;
const CAP_REQ_RELOAD_RULE: i32 = -2;
const CAP_REQ_RELOAD_COUNTS: i32 = -3;
const CAP_REQ_APPEND_UPDATE: i32 = -4;
const CAP_REQ_APPEND_RULE: i32 = -5;

#[repr(C)]
#[derive(Clone, Copy)]
struct ReloadUpdate {
    tag: i32,
    index: u32,
    entry: CUpdate,
}

#[repr(C)]
#[derive(Clone, Copy)]
struct ReloadRule {
    tag: i32,
    index: u32,
    entry: CRule,
}

#[repr(C)]
#[derive(Clone, Copy)]
struct ReloadCounts {
    tag: i32,
    n_rules: u32,
    n_updates: u32,
    _pad: u32,
}

#[repr(C)]
#[derive(Clone, Copy)]
struct AppendUpdate {
    tag: i32,
    caller_pid: i32,
    target_id: u32,
    new_scope_id: u32,
    required_mask: u64,
    entry: CUpdate,
}

#[repr(C)]
#[derive(Clone, Copy)]
struct AppendRule {
    tag: i32,
    caller_pid: i32,
    target_id: u32,
    new_scope_id: u32,
    required_mask: u64,
    entry: CRule,
}

/// A handle for hot-reloading policy rules into a running eBPF engine.
///
/// Holds only the `cap_req` user ring buffer fd (via a dup'd `OwnedFd`).
/// `Send + Sync` — safe to share across threads and the async MCP server.
pub struct ReloadHandle {
    cap_req_fd: std::os::fd::OwnedFd,
}

unsafe impl Send for ReloadHandle {}
unsafe impl Sync for ReloadHandle {}

impl ReloadHandle {
    fn submit_raw(&self, data: &[u8]) -> io::Result<()> {
        let fd = self.cap_req_fd.as_raw_fd();
        unsafe {
            let rb = libbpf_sys::user_ring_buffer__new(fd, std::ptr::null());
            if rb.is_null() {
                return Err(io::Error::last_os_error());
            }
            let sample = libbpf_sys::user_ring_buffer__reserve(rb, data.len() as u32);
            if sample.is_null() {
                let e = io::Error::last_os_error();
                libbpf_sys::user_ring_buffer__free(rb);
                return Err(e);
            }
            std::ptr::copy_nonoverlapping(data.as_ptr(), sample as *mut u8, data.len());
            libbpf_sys::user_ring_buffer__submit(rb, sample);
            libbpf_sys::user_ring_buffer__free(rb);
            libc::syscall(libc::SYS_getpid);
        }
        Ok(())
    }

    fn submit<T: Copy>(&self, val: &T) -> io::Result<()> {
        let bytes = unsafe {
            std::slice::from_raw_parts(val as *const T as *const u8, std::mem::size_of::<T>())
        };
        self.submit_raw(bytes)
    }

    /// Hot-reload a new compiled policy blob without restarting the engine.
    ///
    /// Sequence: quiesce (counts→0) → write updates → write rules → activate.
    /// Accumulated state (process labels, file labels, session gates) is preserved.
    pub fn reload_policy(&self, new_blob: &[u8]) -> io::Result<()> {
        if new_blob.len() != std::mem::size_of::<CConfig>() {
            return Err(err(format!(
                "reload config size mismatch: got {}, expected {}",
                new_blob.len(),
                std::mem::size_of::<CConfig>()
            )));
        }
        let cfg: Box<CConfig> =
            Box::new(unsafe { std::ptr::read_unaligned(new_blob.as_ptr() as *const CConfig) });
        validate_config(&cfg)?;

        // Phase 1: quiesce — set counts to 0 so the engine skips all rules.
        self.submit(&ReloadCounts {
            tag: CAP_REQ_RELOAD_COUNTS,
            n_rules: 0,
            n_updates: 0,
            _pad: 0,
        })?;

        // Phase 2: submit all update entries.
        for i in 0..cfg.n_updates {
            self.submit(&ReloadUpdate {
                tag: CAP_REQ_RELOAD_UPDATE,
                index: i,
                entry: cfg.updates[i as usize],
            })?;
        }

        // Phase 3: submit all rule entries.
        for i in 0..cfg.n_rules {
            self.submit(&ReloadRule {
                tag: CAP_REQ_RELOAD_RULE,
                index: i,
                entry: cfg.rules[i as usize],
            })?;
        }

        // Phase 4: activate — set real counts.
        self.submit(&ReloadCounts {
            tag: CAP_REQ_RELOAD_COUNTS,
            n_rules: cfg.n_rules,
            n_updates: cfg.n_updates,
            _pad: 0,
        })?;

        Ok(())
    }

    /// Append a precompiled policy delta through the kernel-admitted runtime path.
    ///
    /// Unlike `reload_policy`, this does not replace existing rules. Each update
    /// and rule is admitted by the BPF capability checker using the submitting
    /// pid's bound state. Updates that delete labels are rejected because a
    /// runtime self-policy delta must not declassify inherited state.
    pub fn append_policy_delta(
        &self,
        caller_pid: i32,
        target_id: u32,
        delta_blob: &[u8],
    ) -> io::Result<()> {
        self.append_policy_delta_with_rule_id_base(caller_pid, target_id, 0, delta_blob)
    }

    /// Same as `append_policy_delta`, but offsets appended rule ids before
    /// submission so userspace metadata can remain aligned with kernel events.
    pub fn append_policy_delta_with_rule_id_base(
        &self,
        caller_pid: i32,
        target_id: u32,
        rule_id_base: u32,
        delta_blob: &[u8],
    ) -> io::Result<()> {
        if caller_pid <= 0 || target_id == 0 {
            return Err(err("caller_pid and target_id must both be set"));
        }
        if delta_blob.len() != std::mem::size_of::<CConfig>() {
            return Err(err(format!(
                "delta config size mismatch: got {}, expected {}",
                delta_blob.len(),
                std::mem::size_of::<CConfig>()
            )));
        }
        let cfg: Box<CConfig> =
            Box::new(unsafe { std::ptr::read_unaligned(delta_blob.as_ptr() as *const CConfig) });
        validate_config(&cfg)?;

        for i in 0..cfg.n_updates {
            let entry = cfg.updates[i as usize];
            if entry.del != 0 {
                return Err(err(format!(
                    "runtime policy delta update[{i}] deletes labels; declassification is not allowed"
                )));
            }
            self.submit(&AppendUpdate {
                tag: CAP_REQ_APPEND_UPDATE,
                caller_pid,
                target_id,
                new_scope_id: 0,
                required_mask: 0,
                entry,
            })?;
        }

        for i in 0..cfg.n_rules {
            let mut entry = cfg.rules[i as usize];
            entry.rule_id = entry.rule_id.saturating_add(rule_id_base);
            self.submit(&AppendRule {
                tag: CAP_REQ_APPEND_RULE,
                caller_pid,
                target_id,
                new_scope_id: 0,
                required_mask: AUTH_BIND_RULE,
                entry,
            })?;
        }

        Ok(())
    }
}

fn cstr(buf: &[u8]) -> String {
    let end = buf.iter().position(|&b| b == 0).unwrap_or(buf.len());
    String::from_utf8_lossy(&buf[..end]).into_owned()
}

fn decode(e: &Event) -> Violation {
    let target = if e.conn_ip != 0 {
        let ip = e.conn_ip; // network order: bytes are a.b.c.d in memory
        format!(
            "{}.{}.{}.{}",
            ip & 0xff,
            (ip >> 8) & 0xff,
            (ip >> 16) & 0xff,
            (ip >> 24) & 0xff
        )
    } else {
        cstr(&e.filename)
    };
    let provenance = if e.prov_label != 0 {
        let target = if e.prov_ip != 0 {
            let ip = e.prov_ip;
            format!(
                "{}.{}.{}.{}",
                ip & 0xff,
                (ip >> 8) & 0xff,
                (ip >> 16) & 0xff,
                (ip >> 24) & 0xff
            )
        } else {
            cstr(&e.prov_target)
        };
        Some(Provenance {
            label: e.prov_label,
            timestamp_ns: e.prov_timestamp_ns,
            pid: e.prov_pid,
            op: e.prov_op,
            target,
        })
    } else {
        None
    };
    Violation {
        effect: e.effect,
        blocked: e.blocked != 0,
        killed: e.killed != 0,
        comm: cstr(&e.comm),
        pid: e.pid,
        ppid: e.ppid,
        target,
        rule_id: e.taint_rule_id,
        label: e.taint_label,
        matched_label: e.matched_label,
        provenance,
        timestamp_ns: e.timestamp_ns,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // The Rust ABI mirror must match the C struct sizes the object was built
    // with. These are the documented sizes from bpf/taint.h.
    #[test]
    fn abi_sizes() {
        assert_eq!(std::mem::size_of::<ProcState>(), 16);
        assert_eq!(std::mem::size_of::<CapState>(), 56);
        assert_eq!(std::mem::size_of::<DeltaRequest>(), 48);
        // CConfig = 5 u32 (+pad) + the five arrays; just assert it is non-trivial
        // and 8-aligned so set_global offsets line up.
        assert_eq!(std::mem::align_of::<CConfig>(), 8);
        assert!(std::mem::size_of::<CConfig>() > 0);
    }

    #[test]
    fn object_is_aligned_elf() {
        let b = object_bytes();
        assert_eq!(b.as_ptr() as usize % 8, 0, "object must be 8-aligned");
        assert_eq!(&b[..4], b"\x7fELF");
    }

    #[test]
    fn object_has_capability_user_ringbuf_path() {
        let b = object_bytes();
        for name in [
            b"cap_req".as_slice(),
            b"cap_state".as_slice(),
            b"cap_task".as_slice(),
            b"cap_drain_tick".as_slice(),
            b"trace_read".as_slice(),
            b"trace_write".as_slice(),
            b"stdio:stdin".as_slice(),
            b"stdio:stdout".as_slice(),
            b"ts_updates".as_slice(),
            b"ts_rules".as_slice(),
            b"ts_exit_gates".as_slice(),
        ] {
            assert!(
                b.windows(name.len()).any(|w| w == name),
                "object should contain {}",
                String::from_utf8_lossy(name)
            );
        }
    }

    #[test]
    fn reload_struct_layout() {
        assert_eq!(
            std::mem::size_of::<ReloadUpdate>(),
            8 + std::mem::size_of::<CUpdate>()
        );
        assert_eq!(
            std::mem::size_of::<ReloadRule>(),
            8 + std::mem::size_of::<CRule>()
        );
        assert_eq!(std::mem::size_of::<ReloadCounts>(), 16);
        assert_eq!(
            std::mem::size_of::<AppendUpdate>(),
            24 + std::mem::size_of::<CUpdate>()
        );
        assert_eq!(
            std::mem::size_of::<AppendRule>(),
            24 + std::mem::size_of::<CRule>()
        );
    }

    fn set_cstr<const N: usize>(dst: &mut [u8; N], s: &str) {
        let bytes = s.as_bytes();
        let n = bytes.len().min(N.saturating_sub(1));
        dst[..n].copy_from_slice(&bytes[..n]);
    }

    fn config_blob(cfg: &CConfig) -> Vec<u8> {
        unsafe {
            std::slice::from_raw_parts(
                cfg as *const CConfig as *const u8,
                std::mem::size_of::<CConfig>(),
            )
            .to_vec()
        }
    }

    fn empty_config_blob() -> Vec<u8> {
        let cfg: CConfig = unsafe { std::mem::zeroed() };
        config_blob(&cfg)
    }

    fn notify_exec_config_blob(name: &str) -> Vec<u8> {
        let mut cfg: CConfig = unsafe { std::mem::zeroed() };
        cfg.n_rules = 1;
        cfg.rules[0].op = OP_EXEC;
        cfg.rules[0].m = 0; // TAINT_MATCH_EXACT
        cfg.rules[0].effect = 0; // notify
        cfg.rules[0].rule_id = 0;
        set_cstr(&mut cfg.rules[0].target, name);
        config_blob(&cfg)
    }

    fn percentile(sorted: &[std::time::Duration], pct: f64) -> std::time::Duration {
        assert!(!sorted.is_empty());
        let idx = ((sorted.len() - 1) as f64 * pct).round() as usize;
        sorted[idx.min(sorted.len() - 1)]
    }

    fn summarize_durations(name: &str, durs: &[std::time::Duration]) {
        let mut sorted = durs.to_vec();
        sorted.sort_unstable();
        let total_ns: u128 = durs.iter().map(|d| d.as_nanos()).sum();
        let mean_us = total_ns as f64 / durs.len() as f64 / 1000.0;
        println!(
            "{name}: n={} mean={:.2}us p50={:.2}us p90={:.2}us p99={:.2}us min={:.2}us max={:.2}us",
            durs.len(),
            mean_us,
            percentile(&sorted, 0.50).as_secs_f64() * 1_000_000.0,
            percentile(&sorted, 0.90).as_secs_f64() * 1_000_000.0,
            percentile(&sorted, 0.99).as_secs_f64() * 1_000_000.0,
            sorted[0].as_secs_f64() * 1_000_000.0,
            sorted[sorted.len() - 1].as_secs_f64() * 1_000_000.0,
        );
    }

    #[test]
    #[ignore = "requires root/CAP_BPF and loads live eBPF programs"]
    fn reload_policy_latency_smoke() {
        let empty = empty_config_blob();
        let policy_a = notify_exec_config_blob("aprl_a");
        let policy_b = notify_exec_config_blob("aprl_b");
        let policy_hit = notify_exec_config_blob("aprlhit");

        let mut loader = Loader::load(&empty).expect("load eBPF engine");
        let handle = loader.reload_handle().expect("reload handle");
        let stop = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
        let (tx, rx) = std::sync::mpsc::channel();
        let run_stop = std::sync::Arc::clone(&stop);
        let run_thread = std::thread::spawn(move || {
            loader.run(&run_stop, |v| {
                let _ = tx.send((std::time::Instant::now(), v));
            })
        });

        std::thread::sleep(std::time::Duration::from_millis(50));
        for i in 0..10 {
            let blob = if i % 2 == 0 { &policy_a } else { &policy_b };
            handle.reload_policy(blob).expect("warm reload");
        }

        let mut reload_durs = Vec::new();
        for i in 0..200 {
            let blob = if i % 2 == 0 { &policy_a } else { &policy_b };
            let start = std::time::Instant::now();
            handle.reload_policy(blob).expect("measured reload");
            reload_durs.push(start.elapsed());
        }

        let tmp =
            std::env::temp_dir().join(format!("actplane-reload-bench-{}", std::process::id()));
        std::fs::create_dir_all(&tmp).expect("create temp dir");
        let hit_path = tmp.join("aprlhit");
        std::fs::copy("/bin/true", &hit_path).expect("copy /bin/true");

        let mut effect_durs = Vec::new();
        let mut reload_only_durs = Vec::new();
        for _ in 0..50 {
            let start = std::time::Instant::now();
            handle
                .reload_policy(&policy_hit)
                .expect("reload hit policy");
            reload_only_durs.push(start.elapsed());
            let status = std::process::Command::new(&hit_path)
                .status()
                .expect("run matching executable");
            assert!(status.success());
            let (event_at, v) = rx
                .recv_timeout(std::time::Duration::from_secs(2))
                .expect("violation after reload");
            assert!(v.target.ends_with("aprlhit"), "target was {}", v.target);
            effect_durs.push(event_at.duration_since(start));
        }

        stop.store(true, std::sync::atomic::Ordering::Relaxed);
        run_thread
            .join()
            .expect("join ring thread")
            .expect("run loop");
        let _ = std::fs::remove_dir_all(&tmp);

        println!("reload path: 1 rule, 0 updates, counts quiesce + rule + counts activate");
        summarize_durations("reload_policy_submit_to_drain", &reload_durs);
        summarize_durations("reload_policy_before_effect_samples", &reload_only_durs);
        summarize_durations("reload_to_observed_exec_violation", &effect_durs);
    }

    #[test]
    #[ignore = "requires root/CAP_BPF and loads live eBPF programs"]
    fn append_policy_delta_admits_self_rule_smoke() {
        let empty = empty_config_blob();
        let policy = notify_exec_config_blob("aprladd");
        let caller_pid = std::process::id() as i32;
        let target_id = 42;

        let mut loader = Loader::load(&empty).expect("load eBPF engine");
        loader
            .bind_state(
                caller_pid,
                target_id,
                CapState {
                    scope_id: 1,
                    authority_mask: AUTH_BIND_RULE,
                    target_mask: TARGET_SELF,
                    ..CapState::default()
                },
            )
            .expect("bind caller domain");
        let handle = loader.reload_handle().expect("reload handle");

        let stop = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
        let (tx, rx) = std::sync::mpsc::channel();
        let run_stop = std::sync::Arc::clone(&stop);
        let run_thread = std::thread::spawn(move || {
            loader.run(&run_stop, |v| {
                let _ = tx.send(v);
            })
        });
        std::thread::sleep(std::time::Duration::from_millis(50));

        handle
            .append_policy_delta(caller_pid, target_id, &policy)
            .expect("append admitted rule");

        let tmp =
            std::env::temp_dir().join(format!("actplane-append-smoke-{}", std::process::id()));
        std::fs::create_dir_all(&tmp).expect("create temp dir");
        let hit_path = tmp.join("aprladd");
        std::fs::copy("/bin/true", &hit_path).expect("copy /bin/true");
        let status = std::process::Command::new(&hit_path)
            .status()
            .expect("run matching executable");
        assert!(status.success());

        let v = rx
            .recv_timeout(std::time::Duration::from_secs(2))
            .expect("violation from appended rule");
        assert!(v.target.ends_with("aprladd"), "target was {}", v.target);
        assert_eq!(v.rule_id, 0);

        stop.store(true, std::sync::atomic::Ordering::Relaxed);
        run_thread
            .join()
            .expect("join ring thread")
            .expect("run loop");
        let _ = std::fs::remove_dir_all(&tmp);
    }
}
