use std::env;
use std::fs;
use std::path::Path;
use std::path::PathBuf;

fn ensure_generated_file(src_dir: &Path, generated_name: &str, defaults_name: &str) {
    let generated_path = src_dir.join(generated_name);
    if generated_path.exists() {
        println!("cargo:rerun-if-changed={}", generated_path.display());
        return;
    }

    let defaults_path = src_dir.join(defaults_name);
    if !defaults_path.exists() {
        panic!(
            "Missing fallback template for {}: {}",
            generated_name,
            defaults_path.display()
        );
    }

    fs::copy(&defaults_path, &generated_path).unwrap_or_else(|error| {
        panic!(
            "Failed to bootstrap {} from {}: {}",
            generated_path.display(),
            defaults_path.display(),
            error
        )
    });

    println!(
        "cargo:warning=Bootstrapped {} from {}",
        generated_name, defaults_name
    );
    println!("cargo:rerun-if-changed={}", generated_path.display());
}

fn main() {
    let manifest_dir = env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR missing");
    let src_dir = PathBuf::from(manifest_dir).join("src");

    println!("cargo:rerun-if-changed=build.rs");
    println!(
        "cargo:rerun-if-changed={}",
        src_dir.join("config.defaults.rs").display()
    );
    println!(
        "cargo:rerun-if-changed={}",
        src_dir.join("strings_config.defaults.rs").display()
    );

    ensure_generated_file(&src_dir, "config.rs", "config.defaults.rs");
    ensure_generated_file(&src_dir, "strings_config.rs", "strings_config.defaults.rs");
}
