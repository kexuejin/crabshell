use std::env;
use std::fs;
use std::path::PathBuf;

fn main() {
    let manifest_dir = env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR missing");
    let src_dir = PathBuf::from(manifest_dir).join("src");
    let generated = src_dir.join("config.rs");
    let defaults = src_dir.join("config.defaults.rs");

    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-changed={}", defaults.display());
    println!("cargo:rerun-if-changed={}", generated.display());

    if generated.exists() {
        return;
    }

    if !defaults.exists() {
        panic!(
            "Missing fallback template for config.rs: {}",
            defaults.display()
        );
    }

    fs::copy(&defaults, &generated).unwrap_or_else(|error| {
        panic!(
            "Failed to bootstrap {} from {}: {}",
            generated.display(),
            defaults.display(),
            error
        )
    });

    println!("cargo:warning=Bootstrapped config.rs from config.defaults.rs");
}
