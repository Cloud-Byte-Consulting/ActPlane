// SPDX-License-Identifier: MIT
// Copyright (c) 2026 eunomia-bpf org.
//! ActPlane taint DSL: parser + reference taint engine (docs/taint-dsl.md).

pub mod ast;
pub mod engine;
pub mod parse;

// Re-exported as the module's public API; not all are used by the binary yet.
#[allow(unused_imports)]
pub use ast::Policy;
#[allow(unused_imports)]
pub use engine::{Engine, Event, Violation};
#[allow(unused_imports)]
pub use parse::parse;
