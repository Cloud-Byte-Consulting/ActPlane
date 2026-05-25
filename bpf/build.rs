// Builds the eBPF CO-RE object via the existing C/libbpf Makefile and copies it
// into OUT_DIR so lib.rs can embed it with include_bytes!. The kernel eBPF is
// not touched; this only produces bpf/.output/process.bpf.o.
//
// (Once the prebuilt object is committed for `cargo install`, this build.rs can
// be reduced to just the copy — see lib.rs OBJECT.)
use std::env;
use std::path::PathBuf;
use std::process::Command;

fn main() {
    let manifest = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let out = PathBuf::from(env::var("OUT_DIR").unwrap());
    let obj = manifest.join(".output/process.bpf.o");

    for f in [
        "process.bpf.c",
        "process.h",
        "taint.h",
        "taint_engine.bpf.h",
        "Makefile",
    ] {
        println!("cargo:rerun-if-changed={}", manifest.join(f).display());
    }

    let status = Command::new("make")
        .arg("-C")
        .arg(&manifest)
        .arg("process")
        .status()
        .expect("run make -C bpf process");
    assert!(status.success(), "make -C bpf process failed");

    std::fs::copy(&obj, out.join("process.bpf.o"))
        .unwrap_or_else(|e| panic!("copy {} -> OUT_DIR: {e}", obj.display()));
}
