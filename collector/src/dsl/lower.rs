// SPDX-License-Identifier: MIT
// Copyright (c) 2026 eunomia-bpf org.
//! Lower a parsed Policy to the kernel ABI (struct taint_config, see
//! bpf/taint.h): assign label/gate bits, compile boolean exprs to req/forbid
//! masks (via DNF), and lower globs to the kernel's exact/prefix/suffix/any
//! match kinds.

use super::ast::*;
use std::collections::HashMap;

// must match bpf/taint.h
const PAT: usize = 64;
const ARG: usize = 24;
// Must match bpf/taint.h MAX_TAINT_* exactly (ABI). Sized for 100+ rules/policy.
const MAX_UPDATES: usize = 320;
const MAX_RULES: usize = 128;
const MAX_GATES: usize = 64;
const MAX_INVALS: usize = 64;

const M_EXACT: u8 = 0;
const M_PREFIX: u8 = 1;
const M_SUFFIX: u8 = 2;
const M_ANY: u8 = 3;
const M_CONTAINS: u8 = 4;
const OP_EXEC: u8 = 0;
const OP_OPEN: u8 = 1;
const OP_WRITE: u8 = 2;
const OP_CONNECT: u8 = 3;
const OP_RECV: u8 = 4;
const C_NONE: u8 = 0;
const C_LINEAGE: u8 = 1;
const C_AFTER: u8 = 2;
const C_TARGET: u8 = 3;
const EFFECT_NOTIFY: u8 = 0;
const EFFECT_BLOCK: u8 = 1;
const EFFECT_KILL: u8 = 2;

#[repr(C)]
#[derive(Clone, Copy)]
struct CUpdate {
    op: u8,
    m: u8,
    target: [u8; PAT],
    add: u64,
    del: u64,
    gates: u64,
    invals: u64,
    ipv4: u32,
    ipv4_mask: u32,
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

fn set_pat(dst: &mut [u8], s: &str) {
    let b = s.as_bytes();
    let n = b.len().min(dst.len() - 1);
    dst[..n].copy_from_slice(&b[..n]);
    dst[n] = 0;
}

/// (match, literal) lowering for exec-side patterns (matched on comm).
fn lower_exec(pat: &str) -> (u8, String) {
    let base = pat.rsplit('/').next().unwrap_or(pat);
    if let Some(stripped) = base.strip_suffix('*') {
        (M_PREFIX, stripped.to_string())
    } else {
        (M_EXACT, base.to_string())
    }
}

/// (match, literal) lowering for path patterns.
fn lower_path(pat: &str) -> (u8, String) {
    if pat == "*" || pat == "**" {
        return (M_ANY, String::new());
    }
    // **/middle/** → contains "/middle/" (substring search)
    if let Some(inner) = pat.strip_prefix("**/").and_then(|r| r.strip_suffix("/**")) {
        if !inner.contains('*') {
            return (M_CONTAINS, format!("/{inner}/"));
        }
    }
    // **/middle/* → contains "/middle/" (files directly inside)
    if let Some(inner) = pat.strip_prefix("**/").and_then(|r| r.strip_suffix("/*")) {
        if !inner.contains('*') {
            return (M_CONTAINS, format!("/{inner}/"));
        }
    }
    if let Some(p) = pat.strip_suffix("/**") {
        return (M_PREFIX, format!("{}/", p));
    }
    if let Some(p) = pat.strip_suffix("**") {
        return (M_PREFIX, p.to_string());
    }
    if let Some(p) = pat.strip_suffix("/*") {
        return (M_PREFIX, format!("{}/", p));
    }
    if let Some(p) = pat.strip_prefix("**/") {
        return (M_SUFFIX, p.to_string());
    }
    if let Some(p) = pat.strip_prefix('*') {
        return (M_SUFFIX, p.to_string());
    }
    if let Some(idx) = pat.find('*') {
        return (M_PREFIX, pat[..idx].to_string());
    }
    (M_EXACT, pat.to_string())
}

/// Lower an IPv4 prefix/host pattern to (net, mask) in the same byte order as
/// the kernel's `sin_addr.s_addr` (octet k at bit 8*k). "*" -> match-any (0,0).
/// "10.0.0." -> /24, "10.0.0.5" -> /32. Non-IP hostnames -> (0, !0) = match-none
/// (hostname rules need userspace DNS; not matched numerically).
fn lower_ipv4(pat: &str) -> (u32, u32) {
    if pat == "*" {
        return (0, 0);
    }
    let body = pat.strip_suffix('.').unwrap_or(pat);
    let mut net: u32 = 0;
    let mut mask: u32 = 0;
    let mut k = 0u32;
    for tok in body.split('.') {
        if k >= 4 {
            break;
        }
        match tok.parse::<u8>() {
            Ok(o) => {
                net |= (o as u32) << (8 * k);
                mask |= 0xffu32 << (8 * k);
                k += 1;
            }
            Err(_) => return (0, u32::MAX), // not an IP -> matches nothing in-kernel
        }
    }
    (net, mask)
}

struct Ctx {
    labels: HashMap<String, u64>,
    next_label: u32,
    updates: Vec<CUpdate>,
    gate_bits: HashMap<(u8, String), (u64, u32)>,
    next_gate: u32,
    inval_slots: HashMap<(u8, u8, String), u32>,
    next_inval: u32,
}
impl Ctx {
    fn add_update(&mut self, spec: UpdateSpec<'_>) -> Result<(), String> {
        for u in &mut self.updates {
            if u.op == spec.op
                && u.m == spec.m
                && u.ipv4 == spec.ipv4
                && u.ipv4_mask == spec.ipv4_mask
                && pat_eq(&u.target, spec.target)
            {
                u.add |= spec.add;
                u.del |= spec.del;
                u.gates |= spec.gates;
                u.invals |= spec.invals;
                return Ok(());
            }
        }
        if self.updates.len() >= MAX_UPDATES {
            return Err(format!(
                "too many event updates ({} > {})",
                self.updates.len() + 1,
                MAX_UPDATES
            ));
        }
        let mut u = CUpdate {
            op: spec.op,
            m: spec.m,
            target: [0; PAT],
            add: spec.add,
            del: spec.del,
            gates: spec.gates,
            invals: spec.invals,
            ipv4: spec.ipv4,
            ipv4_mask: spec.ipv4_mask,
        };
        set_pat(&mut u.target, spec.target);
        self.updates.push(u);
        Ok(())
    }

    fn label_bit(&mut self, name: &str) -> Result<u64, String> {
        if let Some(b) = self.labels.get(name) {
            return Ok(*b);
        }
        if self.next_label >= 64 {
            return Err("too many labels (max 64)".into());
        }
        let b = 1u64 << self.next_label;
        self.next_label += 1;
        self.labels.insert(name.to_string(), b);
        Ok(b)
    }
    /// Returns (gate bit, gate slot index). The index is what the engine uses to
    /// look up the gate's epoch for staleness; the bit is the v1 latching mask.
    fn gate_bit(&mut self, exec_pat: &str) -> Result<(u64, u32), String> {
        let (m, lit) = lower_exec(exec_pat);
        let key = (m, lit.clone());
        if let Some(b) = self.gate_bits.get(&key) {
            return Ok(*b);
        }
        if self.next_gate >= 64 || self.next_gate as usize >= MAX_GATES {
            return Err("too many gates".into());
        }
        let idx = self.next_gate;
        let b = 1u64 << idx;
        self.next_gate += 1;
        self.add_update(UpdateSpec {
            op: OP_EXEC,
            m,
            target: &lit,
            add: 0,
            del: 0,
            gates: b,
            invals: 0,
            ipv4: 0,
            ipv4_mask: 0,
        })?;
        self.gate_bits.insert(key, (b, idx));
        Ok((b, idx))
    }
    /// Allocate (or reuse) a `since` invalidator slot, returning its bit in the
    /// rule's `since_mask`. `op` is the lowered taint_op; the pattern is matched
    /// like a sink target (exec on comm, others on path).
    fn inval_slot(&mut self, op: u8, kind: Kind, pat: &str) -> Result<u64, String> {
        let (m, lit) = if op == OP_EXEC {
            lower_exec(pat)
        } else {
            lower_target(op, kind, pat)
        };
        let key = (op, m, lit.clone());
        if let Some(i) = self.inval_slots.get(&key) {
            return Ok(1u64 << *i);
        }
        if self.next_inval >= 64 || self.next_inval as usize >= MAX_INVALS {
            return Err("too many `since` invalidators (max 64)".into());
        }
        let idx = self.next_inval;
        self.next_inval += 1;
        let bit = 1u64 << idx;
        self.add_update(UpdateSpec {
            op,
            m,
            target: &lit,
            add: 0,
            del: 0,
            gates: 0,
            invals: bit,
            ipv4: 0,
            ipv4_mask: 0,
        })?;
        self.inval_slots.insert(key, idx);
        Ok(bit)
    }
}

struct UpdateSpec<'a> {
    op: u8,
    m: u8,
    target: &'a str,
    add: u64,
    del: u64,
    gates: u64,
    invals: u64,
    ipv4: u32,
    ipv4_mask: u32,
}

fn pat_eq(buf: &[u8; PAT], s: &str) -> bool {
    let mut pat = [0u8; PAT];
    set_pat(&mut pat, s);
    *buf == pat
}

/// expr -> disjunction of (req_mask, forbid_mask)
fn dnf(e: &Expr, ctx: &mut Ctx) -> Result<Vec<(u64, u64)>, String> {
    Ok(match e {
        Expr::True => vec![(0, 0)],
        Expr::Label(l) => vec![(ctx.label_bit(l)?, 0)],
        Expr::Not(l) => vec![(0, ctx.label_bit(l)?)],
        Expr::Or(a, b) => {
            let mut v = dnf(a, ctx)?;
            v.extend(dnf(b, ctx)?);
            v
        }
        Expr::And(a, b) => {
            let (da, db) = (dnf(a, ctx)?, dnf(b, ctx)?);
            let mut v = Vec::new();
            for (ra, fa) in &da {
                for (rb, fb) in &db {
                    v.push((ra | rb, fa | fb));
                }
            }
            v
        }
    })
}

/// Human-readable verb for a DSL op, used in the feedback payload.
fn op_name(op: Op) -> &'static str {
    match op {
        Op::Exec => "exec",
        Op::Read => "read",
        Op::Open => "open",
        Op::Write => "write",
        Op::Unlink => "unlink",
        Op::Connect => "connect",
        Op::Recv => "recv",
    }
}

fn op_lowers(op: Op) -> Result<&'static [u8], String> {
    match op {
        Op::Exec => Ok(&[OP_EXEC]),
        Op::Read => Ok(&[OP_OPEN]),
        Op::Open => Ok(&[OP_OPEN]),
        Op::Write | Op::Unlink => Ok(&[OP_WRITE]),
        Op::Connect => Ok(&[OP_CONNECT]),
        Op::Recv => Ok(&[OP_RECV]),
    }
}

/// Lower a `since` event op to the single taint_op the engine stamps on. Only
/// read/write/exec can invalidate a gate.
fn inval_op(op: Op) -> Result<u8, String> {
    match op {
        Op::Read => Ok(OP_OPEN),
        Op::Write => Ok(OP_WRITE),
        Op::Exec => Ok(OP_EXEC),
        other => Err(format!(
            "`since {}` is not a valid invalidator (use read/write/exec)",
            op_name(other)
        )),
    }
}

fn lower_target(op: u8, kind: Kind, pat: &str) -> (u8, String) {
    let _ = kind;
    match op {
        OP_EXEC => lower_exec(pat),
        OP_CONNECT => (M_ANY, String::new()), // connect matches numerically (ipv4/mask)
        _ => lower_path(pat),
    }
}

fn lower_effect(effect: Effect) -> u8 {
    match effect {
        Effect::Notify => EFFECT_NOTIFY,
        Effect::Block => EFFECT_BLOCK,
        Effect::Kill => EFFECT_KILL,
    }
}

/// Per-rule metadata, indexed by `rule_id`, kept Rust-side for building the
/// corrective-feedback payload (docs/feedback-design.md §6).
#[derive(Clone)]
pub struct RuleMeta {
    pub name: String,
    pub reason: String,
    pub effect: Effect,
    /// Operations the rule denies (e.g. "exec", "write"), de-duplicated.
    pub ops: Vec<String>,
}

pub struct Compiled {
    pub bytes: Vec<u8>,
    pub reasons: Vec<String>, // indexed by rule_id
    pub meta: Vec<RuleMeta>,  // indexed by rule_id
    pub labels: HashMap<String, u64>,
}

pub fn compile(pol: &Policy) -> Result<Compiled, String> {
    let mut ctx = Ctx {
        labels: HashMap::new(),
        next_label: 0,
        updates: Vec::new(),
        gate_bits: HashMap::new(),
        next_gate: 0,
        inval_slots: HashMap::new(),
        next_inval: 0,
    };
    let mut rules: Vec<CRule> = Vec::new();
    let mut reasons: Vec<String> = Vec::new();
    let mut meta: Vec<RuleMeta> = Vec::new();

    for s in &pol.sources {
        let bit = ctx.label_bit(&s.label)?;
        let (op, m, lit, ipv4, ipv4_mask) = match s.kind {
            Kind::Exec => {
                let (m, lit) = lower_exec(&s.pattern);
                (OP_EXEC, m, lit, 0, 0)
            }
            Kind::File => {
                let (m, lit) = lower_path(&s.pattern);
                (OP_OPEN, m, lit, 0, 0)
            }
            Kind::Endpoint => {
                let (n, mk) = lower_ipv4(&s.pattern);
                (OP_CONNECT, M_ANY, String::new(), n, mk)
            }
        };
        ctx.add_update(UpdateSpec {
            op,
            m,
            target: &lit,
            add: bit,
            del: 0,
            gates: 0,
            invals: 0,
            ipv4,
            ipv4_mask,
        })?;
    }
    for x in &pol.xforms {
        let bit = ctx.label_bit(&x.label)?;
        let (m, lit) = lower_exec(&x.gate);
        ctx.add_update(UpdateSpec {
            op: OP_EXEC,
            m,
            target: &lit,
            add: if x.endorse { bit } else { 0 },
            del: if x.endorse { 0 } else { bit },
            gates: 0,
            invals: 0,
            ipv4: 0,
            ipv4_mask: 0,
        })?;
    }
    for (rid, rule) in pol.rules.iter().enumerate() {
        reasons.push(rule.reason.clone());
        let mut ops: Vec<String> = Vec::new();
        for cl in &rule.clauses {
            let s = op_name(cl.op).to_string();
            if !ops.contains(&s) {
                ops.push(s);
            }
        }
        meta.push(RuleMeta {
            name: rule.name.clone(),
            reason: rule.reason.clone(),
            effect: rule.effect(),
            ops,
        });
        for cl in &rule.clauses {
            for op in op_lowers(cl.op)? {
                let op = *op;
                let (tm, tlit) = lower_target(op, cl.target.kind, &cl.target.pattern);
                // connect: numeric IPv4 target
                let (ipv4, ipv4_mask) = if op == OP_CONNECT {
                    lower_ipv4(&cl.target.pattern)
                } else {
                    (0, 0)
                };
                // condition
                let (mut ck, mut cneg, mut cm, mut clit, mut gate) =
                    (C_NONE, 0u8, M_EXACT, String::new(), 0u64);
                let (mut cipv4, mut cipv4_mask) = (0u32, 0u32);
                let mut gate_idx = 0u32;
                let mut since_mask = 0u64;
                match &cl.unless {
                    None => {}
                    Some(Cond::Target { negate, pattern }) => {
                        ck = C_TARGET;
                        cneg = *negate as u8;
                        if op == OP_CONNECT {
                            let (n, mk) = lower_ipv4(pattern);
                            cipv4 = n;
                            cipv4_mask = mk;
                        } else {
                            let (m, l) = lower_target(op, cl.target.kind, pattern);
                            cm = m;
                            clit = l;
                        }
                    }
                    Some(Cond::LineageIncludes { exec }) => {
                        ck = C_LINEAGE;
                        let (b, _idx) = ctx.gate_bit(exec)?;
                        gate = b;
                    }
                    Some(Cond::After { exec, since }) => {
                        ck = C_AFTER;
                        let (b, idx) = ctx.gate_bit(exec)?;
                        gate = b;
                        gate_idx = idx;
                        for (op, pat) in since {
                            let iop = inval_op(*op)?;
                            since_mask |= ctx.inval_slot(iop, cl.target.kind, pat)?;
                        }
                    }
                }
                for (req, forbid) in dnf(&cl.when, &mut ctx)? {
                    let mut cr = CRule {
                        op,
                        m: tm,
                        cond_kind: ck,
                        cond_neg: cneg,
                        cond_match: cm,
                        effect: lower_effect(cl.effect),
                        target: [0; PAT],
                        arg: [0; ARG],
                        cond_pat: [0; PAT],
                        req,
                        forbid,
                        gate,
                        rule_id: rid as u32,
                        ipv4,
                        ipv4_mask,
                        cond_ipv4: cipv4,
                        cond_ipv4_mask: cipv4_mask,
                        gate_idx,
                        since_mask,
                    };
                    set_pat(&mut cr.target, &tlit);
                    if let Some(a) = &cl.target.arg {
                        set_pat(&mut cr.arg, a);
                    }
                    set_pat(&mut cr.cond_pat, &clit);
                    rules.push(cr);
                }
            }
        }
    }

    if rules.len() > MAX_RULES {
        return Err(format!(
            "too many compiled rules ({} > {})",
            rules.len(),
            MAX_RULES
        ));
    }

    // build the repr(C) config
    let mut cfg: CConfig = unsafe { std::mem::zeroed() };
    cfg.n_updates = ctx.updates.len() as u32;
    cfg.n_rules = rules.len() as u32;
    for (i, u) in ctx.updates.iter().enumerate() {
        cfg.updates[i] = *u;
    }
    for (i, r) in rules.iter().enumerate() {
        cfg.rules[i] = *r;
    }

    let bytes = unsafe {
        std::slice::from_raw_parts(
            &cfg as *const CConfig as *const u8,
            std::mem::size_of::<CConfig>(),
        )
    }
    .to_vec();
    Ok(Compiled {
        bytes,
        reasons,
        meta,
        labels: ctx.labels,
    })
}
