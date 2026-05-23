// SPDX-License-Identifier: MIT
// Copyright (c) 2026 eunomia-bpf org.
//! Parsed form of the ActPlane taint DSL (docs/taint-dsl.md §2).

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    File,
    Endpoint,
    Exec,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Op {
    Exec,
    Read,
    Write,
    Unlink,
    Connect,
    Recv,
    Open,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Source {
    pub label: String,
    pub kind: Kind,
    pub pattern: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Target {
    pub kind: Kind,
    pub pattern: String,
    pub arg: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub enum Expr {
    True,
    Label(String),
    Not(String),
    And(Box<Expr>, Box<Expr>),
    Or(Box<Expr>, Box<Expr>),
}

#[derive(Debug, Clone, PartialEq)]
pub enum Cond {
    Target { negate: bool, pattern: String },
    LineageIncludes { exec: String },
    After { exec: String },
}

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

#[derive(Debug, Clone, PartialEq)]
pub struct Xform {
    pub endorse: bool,
    pub label: String,
    pub gate: String,
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct Policy {
    pub labels: Vec<String>,
    pub sources: Vec<Source>,
    pub rules: Vec<Rule>,
    pub xforms: Vec<Xform>,
}
