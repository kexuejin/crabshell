use clap::Parser;
use std::fs::{self, File};
use std::io::{Read, Write};
use std::path::PathBuf;
use aes_gcm::{
    aead::{Aead, KeyInit},
    Aes256Gcm, Nonce // Or `Aes128Gcm`
};
use rand::Rng;
use zip::ZipArchive;

// Shared constants with shell
mod config;
use config::AES_KEY;

#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Args {
    #[arg(short, long)]
    shell: PathBuf,

    #[arg(short, long)]
    target: PathBuf,

    #[arg(short, long)]
    output: PathBuf,
}

fn main() -> anyhow::Result<()> {
    let args = Args::parse();

    println!("Packing {} into shell {} -> {}", args.target.display(), args.shell.display(), args.output.display());

    // 1. Read Target APK as Zip
    let target_file = File::open(&args.target)?;
    let mut zip = ZipArchive::new(target_file)?;

    // 2. Extract and Encrypt
    // Entry: (Path, EncryptedData, IV)
    let mut entries: Vec<(String, Vec<u8>, [u8; 12])> = Vec::new();
    
    for i in 0..zip.len() {
        let file = zip.by_index(i)?;
        let name = file.name().to_string();
        
        let is_dex = name.starts_with("classes") && name.ends_with(".dex");
        let is_lib = name.starts_with("lib/") && name.ends_with(".so");

        if is_dex || is_lib {
            println!("Processing {}...", name);
            // Re-open because by_index borrows zip
            drop(file);
            let mut file = zip.by_index(i)?;
            
            let mut buffer = Vec::new();
            file.read_to_end(&mut buffer)?;
            
            let (encrypted, nonce) = encrypt_payload(&buffer)?;
            entries.push((name, encrypted, nonce));
        }
    }

    if entries.is_empty() {
        anyhow::bail!("No classes*.dex or lib/**/*.so found in target APK");
    }

    println!("Found {} files to pack.", entries.len());

    // 3. Read Shell APK
    let mut shell_apk = Vec::new();
    File::open(&args.shell)?.read_to_end(&mut shell_apk)?;

    // 4. Construct Output
    let mut final_apk = shell_apk.clone();

    // Append Encrypted Data
    for (_, enc_data, _) in &entries {
        final_apk.extend_from_slice(enc_data);
    }

    // Construct Metadata Block
    // Format: [N (4)] + [ [NameLen(2)] [Name] [Size(4)] [IV(12)] ] * N
    let mut metadata = Vec::new();
    metadata.extend_from_slice(&(entries.len() as u32).to_le_bytes()); // N

    for (name, enc_data, nonce) in &entries {
        let name_bytes = name.as_bytes();
        metadata.extend_from_slice(&(name_bytes.len() as u16).to_le_bytes());
        metadata.extend_from_slice(name_bytes);
        metadata.extend_from_slice(&(enc_data.len() as u32).to_le_bytes());
        metadata.extend_from_slice(nonce);
    }

    final_apk.extend_from_slice(&metadata);

    // Footer: [Metadata Size (4)] [Magic (5)]
    final_apk.extend_from_slice(&(metadata.len() as u32).to_le_bytes());
    final_apk.extend_from_slice(b"SHELL");

    // 5. Write Output
    fs::write(&args.output, final_apk)?;

    println!("Success! Output written to {}", args.output.display());
    
    Ok(())
}

fn encrypt_payload(data: &[u8]) -> anyhow::Result<(Vec<u8>, [u8; 12])> {
    let key = *AES_KEY;
    let cipher = Aes256Gcm::new(&key.into());
    
    let mut nonce_bytes = [0u8; 12];
    rand::thread_rng().fill(&mut nonce_bytes);
    let nonce = Nonce::from_slice(&nonce_bytes);

    let ciphertext = cipher.encrypt(nonce, data)
        .map_err(|e| anyhow::anyhow!("Encryption failure: {:?}", e))?;
    
    Ok((ciphertext, nonce_bytes))
}
