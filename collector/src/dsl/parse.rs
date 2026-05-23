// SPDX-License-Identifier: MIT
// Copyright (c) 2026 eunomia-bpf org.
//! Hand-rolled parser for the taint DSL concrete syntax (docs/taint-dsl.md §2).

use super::ast::*;

#[derive(Debug, Clone, PartialEq)]
enum Tok {
    Word(String),
    Str(String),
    Colon,
    Eq,
}

fn lex(src: &str) -> Result<Vec<Tok>, String> {
    let b = src.as_bytes();
    let mut i = 0;
    let mut out = Vec::new();
    while i < b.len() {
        let c = b[i] as char;
        if c.is_whitespace() {
            i += 1;
        } else if c == '#' {
            while i < b.len() && b[i] != b'\n' {
                i += 1;
            }
        } else if c == '"' {
            i += 1;
            let start = i;
            while i < b.len() && b[i] != b'"' {
                i += 1;
            }
            if i >= b.len() {
                return Err("unterminated string".into());
            }
            out.push(Tok::Str(src[start..i].to_string()));
            i += 1;
        } else if c == ':' {
            out.push(Tok::Colon);
            i += 1;
        } else if c == '=' {
            out.push(Tok::Eq);
            i += 1;
        } else {
            let start = i;
            while i < b.len() {
                let d = b[i] as char;
                if d.is_whitespace() || d == '"' || d == ':' || d == '=' {
                    break;
                }
                i += 1;
            }
            out.push(Tok::Word(src[start..i].to_string()));
        }
    }
    Ok(out)
}

struct P {
    t: Vec<Tok>,
    i: usize,
}

const STOP: &[&str] = &[
    "and", "or", "unless", "deny", "reason", "label", "source", "rule", "declassify", "endorse",
];

impl P {
    fn peek(&self) -> Option<&Tok> {
        self.t.get(self.i)
    }
    fn next(&mut self) -> Option<Tok> {
        let t = self.t.get(self.i).cloned();
        self.i += 1;
        t
    }
    fn is_word(&self, w: &str) -> bool {
        matches!(self.peek(), Some(Tok::Word(x)) if x == w)
    }
    fn word(&mut self) -> Result<String, String> {
        match self.next() {
            Some(Tok::Word(w)) => Ok(w),
            other => Err(format!("expected word, got {:?}", other)),
        }
    }
    fn string(&mut self) -> Result<String, String> {
        match self.next() {
            Some(Tok::Str(s)) => Ok(s),
            other => Err(format!("expected string, got {:?}", other)),
        }
    }
    fn eat_word(&mut self, w: &str) -> Result<(), String> {
        match self.next() {
            Some(Tok::Word(x)) if x == w => Ok(()),
            other => Err(format!("expected '{}', got {:?}", w, other)),
        }
    }

    fn kind(w: &str) -> Result<Kind, String> {
        match w {
            "file" => Ok(Kind::File),
            "endpoint" => Ok(Kind::Endpoint),
            "exec" => Ok(Kind::Exec),
            _ => Err(format!("unknown node kind '{}'", w)),
        }
    }
    fn op(w: &str) -> Result<Op, String> {
        match w {
            "exec" => Ok(Op::Exec),
            "read" => Ok(Op::Read),
            "write" => Ok(Op::Write),
            "unlink" => Ok(Op::Unlink),
            "connect" => Ok(Op::Connect),
            "recv" => Ok(Op::Recv),
            "open" => Ok(Op::Open),
            _ => Err(format!("unknown op '{}'", w)),
        }
    }

    fn target(&mut self, op: Op) -> Result<Target, String> {
        // exec: pattern follows directly (kind = Exec). others: kind word then pattern.
        let kind = if let Some(Tok::Word(w)) = self.peek() {
            if w == "file" || w == "endpoint" || w == "exec" {
                let w = self.word()?;
                P::kind(&w)?
            } else {
                return Err(format!("expected node kind in target, got '{}'", w));
            }
        } else if op == Op::Exec {
            Kind::Exec
        } else {
            return Err("expected node kind in target".into());
        };
        let pattern = self.string()?;
        let arg = if self.is_word("@arg") {
            self.word()?;
            Some(self.string()?)
        } else {
            None
        };
        Ok(Target { kind, pattern, arg })
    }

    fn expr(&mut self) -> Result<Expr, String> {
        let mut lhs = self.term()?;
        loop {
            match self.peek() {
                Some(Tok::Word(w)) if w == "and" => {
                    self.next();
                    let rhs = self.term()?;
                    lhs = Expr::And(Box::new(lhs), Box::new(rhs));
                }
                Some(Tok::Word(w)) if w == "or" => {
                    self.next();
                    let rhs = self.term()?;
                    lhs = Expr::Or(Box::new(lhs), Box::new(rhs));
                }
                _ => break,
            }
        }
        Ok(lhs)
    }

    fn term(&mut self) -> Result<Expr, String> {
        if self.is_word("not") {
            self.next();
            Ok(Expr::Not(self.word()?))
        } else if self.is_word("true") {
            self.next();
            Ok(Expr::True)
        } else {
            Ok(Expr::Label(self.word()?))
        }
    }

    fn cond(&mut self) -> Result<Cond, String> {
        let w = self.word()?;
        match w.as_str() {
            "target" => {
                let negate = self.is_word("not");
                if negate {
                    self.next();
                }
                Ok(Cond::Target {
                    negate,
                    pattern: self.string()?,
                })
            }
            "lineage-includes" => {
                self.eat_word("exec")?;
                Ok(Cond::LineageIncludes { exec: self.string()? })
            }
            "after" => {
                self.eat_word("exec")?;
                Ok(Cond::After { exec: self.string()? })
            }
            _ => Err(format!("unknown unless condition '{}'", w)),
        }
    }

    fn clause(&mut self) -> Result<Clause, String> {
        self.eat_word("deny")?;
        let op = P::op(&self.word()?)?;
        let target = self.target(op)?;
        let when = if self.is_word("if") {
            self.next();
            self.expr()?
        } else {
            Expr::True
        };
        let unless = if self.is_word("unless") {
            self.next();
            Some(self.cond()?)
        } else {
            None
        };
        Ok(Clause {
            op,
            target,
            when,
            unless,
        })
    }
}

pub fn parse(src: &str) -> Result<Policy, String> {
    let mut p = P { t: lex(src)?, i: 0 };
    let mut pol = Policy::default();

    while let Some(tok) = p.peek().cloned() {
        let kw = match tok {
            Tok::Word(w) => w,
            other => return Err(format!("expected declaration keyword, got {:?}", other)),
        };
        match kw.as_str() {
            "label" => {
                p.next();
                pol.labels.push(p.word()?);
            }
            "source" => {
                p.next();
                let label = p.word()?;
                match p.next() {
                    Some(Tok::Eq) => {}
                    other => return Err(format!("expected '=' in source, got {:?}", other)),
                }
                let kind = P::kind(&p.word()?)?;
                let pattern = p.string()?;
                pol.sources.push(Source { label, kind, pattern });
            }
            "declassify" | "endorse" => {
                let endorse = kw == "endorse";
                p.next();
                let label = p.word()?;
                p.eat_word("by")?;
                p.eat_word("exec")?;
                let gate = p.string()?;
                pol.xforms.push(Xform { endorse, label, gate });
            }
            "rule" => {
                p.next();
                let name = p.word()?;
                match p.next() {
                    Some(Tok::Colon) => {}
                    other => return Err(format!("expected ':' after rule name, got {:?}", other)),
                }
                let mut clauses = Vec::new();
                let mut reason = String::new();
                loop {
                    if p.is_word("deny") {
                        clauses.push(p.clause()?);
                    } else if p.is_word("reason") {
                        p.next();
                        reason = p.string()?;
                        break;
                    } else {
                        break; // next top-level decl or EOF
                    }
                }
                pol.rules.push(Rule { name, clauses, reason });
            }
            other => return Err(format!("unknown declaration '{}'", other)),
        }
    }
    let _ = STOP; // documented stop-set; expr/term use explicit checks above
    Ok(pol)
}
