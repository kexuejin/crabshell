use aes_gcm::{
    aead::{Aead, KeyInit},
    Aes256Gcm, Nonce,
};
use clap::Parser;
use rand::Rng;
use std::collections::HashSet;
use std::fs::File;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use zip::{write::FileOptions, CompressionMethod, ZipArchive, ZipWriter};

mod config;
use config::AES_KEY;

#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Args {
    #[arg(short, long)]
    target: PathBuf,

    #[arg(short, long)]
    output: PathBuf,

    #[arg(long)]
    bootstrap_apk: PathBuf,

    #[arg(long)]
    bootstrap_lib_dir: PathBuf,

    #[arg(long)]
    patched_manifest: Option<PathBuf>,

    #[arg(long = "keep-class")]
    keep_class: Vec<String>,

    #[arg(long = "keep-prefix")]
    keep_prefix: Vec<String>,

    #[arg(long = "keep-lib")]
    keep_lib: Vec<String>,

    #[arg(long)]
    resources: Option<PathBuf>,
}

fn main() -> anyhow::Result<()> {
    let args = Args::parse();

    println!(
        "Packing target {} -> {}",
        args.target.display(),
        args.output.display()
    );

    let keep_descriptors: Vec<String> = args
        .keep_class
        .iter()
        .map(|class_name| to_dex_descriptor(class_name))
        .collect();

    let keep_prefixes: Vec<String> = args
        .keep_prefix
        .iter()
        .map(|prefix| {
            let trimmed = prefix.trim().trim_matches('.');
            format!("L{}/", trimmed.replace('.', "/"))
        })
        .collect();

    let keep_libs: Vec<String> = args.keep_lib.clone();

    println!("Keep descriptors: {:?}", keep_descriptors);
    println!("Keep prefixes: {:?}", keep_prefixes);
    println!("Keep libs: {:?}", keep_libs);

    let payload_entries = collect_and_encrypt_payload_entries(&args.target, &keep_descriptors, &keep_prefixes, &keep_libs)?;
    let encrypted_entry_names: HashSet<String> = payload_entries
        .iter()
        .map(|(name, _, _)| name.clone())
        .collect();
    if payload_entries.is_empty() {
        anyhow::bail!("No classes*.dex or lib/**/*.so found in target APK");
    }

    let payload_blob = build_payload_blob(&payload_entries);
    repack_target_with_bootstrap(
        &args.target,
        &args.bootstrap_apk,
        &args.bootstrap_lib_dir,
        args.patched_manifest.as_deref(),
        args.resources.as_deref(),
        &encrypted_entry_names,
        &args.output,
        &payload_blob,
    )?;

    println!("Success! Output written to {}", args.output.display());
    Ok(())
}

fn is_payload_entry(name: &str) -> bool {
    let is_dex = name.starts_with("classes") && name.ends_with(".dex");
    let is_lib = name.starts_with("lib/") && name.ends_with(".so");
    is_dex || is_lib
}

fn to_dex_descriptor(class_name: &str) -> String {
    let trimmed = class_name.trim();
    if trimmed.starts_with('L') && trimmed.ends_with(';') {
        return trimmed.to_string();
    }
    format!("L{};", trimmed.replace('.', "/"))
}

fn class_index(name: &str) -> Option<usize> {
    if name == "classes.dex" {
        return Some(1);
    }
    if name.starts_with("classes") && name.ends_with(".dex") {
        let middle = &name[7..name.len() - 4];
        if middle.is_empty() {
            return Some(1);
        }
        return middle.parse::<usize>().ok();
    }
    None
}

fn dex_name_for_index(index: usize) -> String {
    if index == 1 {
        "classes.dex".to_string()
    } else {
        format!("classes{}.dex", index)
    }
}

fn should_keep_dex(_name: &str, dex_bytes: &[u8], keep_descriptors: &[String]) -> bool {
    for descriptor in keep_descriptors {
        if dex_bytes.windows(descriptor.len()).any(|window| window == descriptor.as_bytes()) {
            return true;
        }
    }
    false
}

fn matches_keep_prefix(dex_bytes: &[u8], keep_prefixes: &[String]) -> bool {
    for prefix in keep_prefixes {
        if dex_bytes.windows(prefix.len()).any(|window| window == prefix.as_bytes()) {
            return true;
        }
    }

    false
}

fn should_keep_lib(name: &str, keep_libs: &[String]) -> bool {
    let filename = Path::new(name).file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("");
    
    for kept in keep_libs {
        if filename == kept || filename == format!("lib{}.so", kept) || filename == format!("{}.so", kept) {
            return true;
        }
    }
    false
}

fn collect_and_encrypt_payload_entries(
    target_apk: &Path,
    keep_descriptors: &[String],
    keep_prefixes: &[String],
    keep_libs: &[String],
) -> anyhow::Result<Vec<(String, Vec<u8>, [u8; 12])>> {
    let target_file = File::open(target_apk)?;
    let mut zip = ZipArchive::new(target_file)?;

    let mut entries: Vec<(String, Vec<u8>, [u8; 12])> = Vec::new();

    for i in 0..zip.len() {
        let file = zip.by_index(i)?;
        let name = file.name().to_string();

        if is_payload_entry(&name) {
            drop(file);
            let mut file = zip.by_index(i)?;
            let mut buffer = Vec::new();
            file.read_to_end(&mut buffer)?;

            if name.ends_with(".dex")
                && (should_keep_dex(&name, &buffer, keep_descriptors)
                    || matches_keep_prefix(&buffer, keep_prefixes))
            {
                println!("Keeping {} in plaintext for startup compatibility", name);
                continue;
            }

            if name.ends_with(".so") && should_keep_lib(&name, keep_libs) {
                println!("Keeping {} in plaintext for startup compatibility", name);
                continue;
            }

            println!("Encrypting {}...", name);
            let (encrypted, nonce) = encrypt_payload(&buffer)?;
            entries.push((name, encrypted, nonce));
        }
    }

    println!("Encrypted {} entries total", entries.len());
    Ok(entries)
}

fn build_payload_blob(entries: &[(String, Vec<u8>, [u8; 12])]) -> Vec<u8> {
    let mut payload_blob = Vec::new();

    for (_, enc_data, _) in entries {
        payload_blob.extend_from_slice(enc_data);
    }

    let mut metadata = Vec::new();
    metadata.extend_from_slice(&(entries.len() as u32).to_le_bytes());

    for (name, enc_data, nonce) in entries {
        let name_bytes = name.as_bytes();
        metadata.extend_from_slice(&(name_bytes.len() as u16).to_le_bytes());
        metadata.extend_from_slice(name_bytes);
        metadata.extend_from_slice(&(enc_data.len() as u32).to_le_bytes());
        metadata.extend_from_slice(nonce);
    }

    payload_blob.extend_from_slice(&metadata);
    payload_blob.extend_from_slice(&(metadata.len() as u32).to_le_bytes());
    payload_blob.extend_from_slice(b"SHELL");

    payload_blob
}

fn repack_target_with_bootstrap(
    target_apk: &Path,
    bootstrap_apk: &Path,
    bootstrap_lib_dir: &Path,
    patched_manifest: Option<&Path>,
    resources_arsc: Option<&Path>,
    encrypted_entry_names: &HashSet<String>,
    output_apk: &Path,
    payload_blob: &[u8],
) -> anyhow::Result<()> {
    let target_file = File::open(target_apk)?;
    let mut target_zip = ZipArchive::new(target_file)?;

    let output_file = File::create(output_apk)?;
    let mut writer = ZipWriter::new(output_file);

    let patched_manifest_bytes = if let Some(path) = patched_manifest {
        let mut bytes = Vec::new();
        File::open(path)?.read_to_end(&mut bytes)?;
        Some(bytes)
    } else {
        None
    };

    let resources_arsc_bytes = if let Some(path) = resources_arsc {
        let mut bytes = Vec::new();
        File::open(path)?.read_to_end(&mut bytes)?;
        Some(bytes)
    } else {
        None
    };

    let mut retained_dex_entries: Vec<(usize, Vec<u8>)> = Vec::new();

    for i in 0..target_zip.len() {
        let mut file = target_zip.by_index(i)?;
        let name = file.name().to_string();

        if name == "assets/kapp_payload.bin" || encrypted_entry_names.contains(&name) {
            continue;
        }

        if name == "AndroidManifest.xml" {
            if let Some(bytes) = &patched_manifest_bytes {
                let options = FileOptions::default().compression_method(file.compression());
                writer.start_file(name, options)?;
                writer.write_all(bytes)?;
                continue;
            }
        }

        if name == "resources.arsc" {
            if let Some(bytes) = &resources_arsc_bytes {
                let options = FileOptions::default().compression_method(file.compression());
                writer.start_file(name, options)?;
                writer.write_all(bytes)?;
                continue;
            }
        }

        let options = FileOptions::default().compression_method(file.compression());
        if file.is_dir() {
            writer.add_directory(name, options)?;
        } else {
            if let Some(index) = class_index(&name) {
                let mut dex_bytes = Vec::new();
                file.read_to_end(&mut dex_bytes)?;
                retained_dex_entries.push((index, dex_bytes));
                continue;
            }
            writer.start_file(name, options)?;
            std::io::copy(&mut file, &mut writer)?;
        }
    }

    retained_dex_entries.sort_by_key(|(index, _)| *index);

    // 1. Inject Bootstrap DEX as the FIRST dex file(s)
    let bootstrap_dex_entries = get_bootstrap_dex_entries(bootstrap_apk)?;
    let num_bootstrap_dexes = bootstrap_dex_entries.len();
    
    let dex_options = FileOptions::default().compression_method(CompressionMethod::Stored);
    for (i, dex_bytes) in bootstrap_dex_entries.into_iter().enumerate() {
        let dex_name = dex_name_for_index(i + 1);
        writer.start_file(dex_name, dex_options)?;
        writer.write_all(&dex_bytes)?;
    }

    // 2. Write Retained DEXs starting from the next index
    for (i, (_, dex_bytes)) in retained_dex_entries.iter().enumerate() {
        let dex_name = dex_name_for_index(num_bootstrap_dexes + i + 1);
        writer.start_file(dex_name, dex_options)?;
        writer.write_all(dex_bytes)?;
    }

    inject_bootstrap_libs(bootstrap_lib_dir, &mut writer)?;

    writer.start_file(
        "assets/kapp_payload.bin",
        FileOptions::default().compression_method(CompressionMethod::Stored),
    )?;
    writer.write_all(payload_blob)?;

    writer.finish()?;
    Ok(())
}

fn get_bootstrap_dex_entries(bootstrap_apk: &Path) -> anyhow::Result<Vec<Vec<u8>>> {
    let bootstrap_file = File::open(bootstrap_apk)?;
    let mut bootstrap_zip = ZipArchive::new(bootstrap_file)?;

    let mut dex_entries: Vec<(usize, Vec<u8>)> = Vec::new();
    for i in 0..bootstrap_zip.len() {
        let file = bootstrap_zip.by_index(i)?;
        let name = file.name().to_string();
        if let Some(index) = class_index(&name) {
            drop(file);
            let mut file = bootstrap_zip.by_index(i)?;
            let mut dex_bytes = Vec::new();
            file.read_to_end(&mut dex_bytes)?;
            dex_entries.push((index, dex_bytes));
        }
    }

    dex_entries.sort_by_key(|(index, _)| *index);

    if dex_entries.is_empty() {
        anyhow::bail!("No classes*.dex found in bootstrap APK");
    }

    Ok(dex_entries.into_iter().map(|(_, bytes)| bytes).collect())
}

fn inject_bootstrap_libs(bootstrap_lib_dir: &Path, writer: &mut ZipWriter<File>) -> anyhow::Result<()> {
    let options = FileOptions::default().compression_method(CompressionMethod::Stored);

    let abi_dirs = std::fs::read_dir(bootstrap_lib_dir)?;
    let mut injected_count = 0usize;

    for abi_entry in abi_dirs {
        let abi_entry = abi_entry?;
        let abi_path = abi_entry.path();
        if !abi_path.is_dir() {
            continue;
        }

        let abi_name = abi_entry.file_name().to_string_lossy().to_string();
        let libshell_path = abi_path.join("libshell.so");
        if !libshell_path.exists() {
            continue;
        }

        let mut file = File::open(&libshell_path)?;
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes)?;

        let zip_path = format!("lib/{}/libshell.so", abi_name);
        writer.start_file(zip_path, options)?;
        writer.write_all(&bytes)?;
        injected_count += 1;
    }

    if injected_count == 0 {
        anyhow::bail!(
            "No libshell.so found under bootstrap_lib_dir: {}",
            bootstrap_lib_dir.display()
        );
    }

    Ok(())
}

fn encrypt_payload(data: &[u8]) -> anyhow::Result<(Vec<u8>, [u8; 12])> {
    let key = *AES_KEY;
    let cipher = Aes256Gcm::new(&key.into());

    let mut nonce_bytes = [0u8; 12];
    rand::thread_rng().fill(&mut nonce_bytes);
    let nonce = Nonce::from_slice(&nonce_bytes);

    let ciphertext = cipher
        .encrypt(nonce, data)
        .map_err(|e| anyhow::anyhow!("Encryption failure: {:?}", e))?;

    Ok((ciphertext, nonce_bytes))
}
