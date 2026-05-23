// SPDX-License-Identifier: MIT
// Copyright (c) 2026 eunomia-bpf org.
//! AST for the ActPlane taint DSL (see docs/taint-dsl.md §2).

/// Node kind named in a `source` declaration or a sink `target`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    File,
    Endpoint,
    Exec,
}

/// Operation an event/clause refers to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Op {
    Exec,
    Read,
    Write,
    Unlink,
    Connect,
    Recv,
    Open, // sugar: matches Read or Write
}

/// `source L = <kind> "PATTERN"`
#[derive(Debug, Clone, PartialEq)]
pub struct Source {
    pub label: String,
    pub kind: Kind,
    pub pattern: String,
}

/// `<kind> "PATTERN" [@arg "TOKEN"]`
#[derive(Debug, Clone, PartialEq)]
pub struct Target {
    pub kind: Kind,
    pub pattern: String,
    pub arg: Option<String>,
}

/// Boolean over the subject's labels.
#[derive(Debug, Clone, PartialEq)]
pub enum Expr {
    True,
    Label(String),
    Not(String),
    And(Box<Expr>, Box<Expr>),
    Or(Box<Expr>, Box<Expr>),
}

/// Optional `unless` condition that relaxes a deny.
#[derive(Debug, Clone, PartialEq)]
pub enum Cond {
    /// allowed when object matches (negate => when it does NOT match)
    Target { negate: bool, pattern: String },
    /// allowed when an ancestor (incl. self) exec'd a gate matching `exec`
    LineageIncludes { exec: String },
    /// allowed when `exec` happened earlier in this lineage
    After { exec: String },
}

/// One `deny OP TARGET [if EXPR] [unless COND]` clause.
#[derive(Debug, Clone, PartialEq)]
pub struct Clause {
    pub op: Op,
    pub target: Target,
    pub when: Expr,
    pub unless: Option<Cond>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Rule {
    pub name: String,
    pub clauses: Vec<Clause>,
    pub reason: String,
}

/// `declassify L by exec G` / `endorse L by exec G`
#[derive(Debug, Clone, PartialEq)]
pub struct Xform {
    pub endorse: bool, // false = declassify (remove), true = endorse (add)
    pub label: String,
    pub gate: String, // exec pattern
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct Policy {
    pub labels: Vec<String>,
    pub sources: Vec<Source>,
    pub rules: Vec<Rule>,
    pub xforms: Vec<Xform>,
}
