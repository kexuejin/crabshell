use rfd::FileDialog;
use serde::{Deserialize, Serialize};
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;
use tauri::{AppHandle, Emitter, Manager, State};

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct HardeningConfig {
    input_file: String,
    output_file: String,
    output_format: String,
    advanced: AdvancedConfig,
    signing: SigningConfig,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AdvancedConfig {
    keep_classes: Vec<String>,
    keep_prefixes: Vec<String>,
    keep_libs: Vec<String>,
    encrypt_assets: Vec<String>,
    skip_build: bool,
    skip_sign: bool,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SigningConfig {
    use_debug: bool,
    keystore: Option<String>,
    password: Option<String>,
    alias: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct HardeningProgress {
    stage: String,
    progress: u8,
    message: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct LogEntry {
    timestamp: String,
    level: String,
    message: String,
}

#[derive(Default)]
struct HardeningState {
    process: Arc<Mutex<Option<Child>>>,
}

#[tauri::command]
fn select_file() -> Option<String> {
    FileDialog::new()
        .add_filter("Android Files", &["apk", "aab"])
        .pick_file()
        .map(|path| path.to_string_lossy().to_string())
}

#[tauri::command]
fn select_keystore() -> Option<String> {
    FileDialog::new()
        .add_filter("Keystore Files", &["keystore", "jks"])
        .pick_file()
        .map(|path| path.to_string_lossy().to_string())
}

#[tauri::command]
fn select_output(default_path: String) -> Option<String> {
    let mut dialog = FileDialog::new().add_filter("Android Files", &["apk", "aab"]);
    if !default_path.trim().is_empty() {
        dialog = dialog.set_file_name(&default_path);
    }

    dialog
        .save_file()
        .map(|path| path.to_string_lossy().to_string())
}

#[tauri::command]
fn start_hardening(
    app: AppHandle,
    state: State<HardeningState>,
    config: HardeningConfig,
) -> Result<(), String> {
    {
        let lock = state.process.lock().map_err(|_| "State lock failed")?;
        if lock.is_some() {
            return Err("Hardening process already running".to_string());
        }
    }

    let pack_py_path = resolve_pack_py_path(&app).ok_or_else(|| {
        "Cannot locate pack.py. Set CRABSHELL_ROOT to repository path or place pack.py next to app resources."
            .to_string()
    })?;

    let mut args = vec![
        pack_py_path.to_string_lossy().to_string(),
        "--target".to_string(),
        config.input_file.clone(),
        "--output".to_string(),
        config.output_file.clone(),
        "--output-format".to_string(),
        config.output_format.clone(),
    ];

    if !config.signing.use_debug {
        if let Some(keystore) = config.signing.keystore {
            args.push("--keystore".to_string());
            args.push(keystore);
        }
        if let Some(password) = config.signing.password {
            args.push("--ks-pass".to_string());
            args.push(password);
        }
        if let Some(alias) = config.signing.alias {
            args.push("--key-alias".to_string());
            args.push(alias);
        }
    }

    for class_name in config.advanced.keep_classes {
        args.push("--keep-class".to_string());
        args.push(class_name);
    }

    for keep_prefix in config.advanced.keep_prefixes {
        args.push("--keep-prefix".to_string());
        args.push(keep_prefix);
    }

    for keep_lib in config.advanced.keep_libs {
        args.push("--keep-lib".to_string());
        args.push(keep_lib);
    }

    for encrypt_asset in config.advanced.encrypt_assets {
        args.push("--encrypt-asset".to_string());
        args.push(encrypt_asset);
    }

    if config.advanced.skip_build {
        args.push("--skip-build".to_string());
    }

    if config.advanced.skip_sign {
        args.push("--no-sign".to_string());
    }

    let working_dir = pack_py_path
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from("."));

    emit_log(
        &app,
        "info",
        &format!("Running: python3 {}", args.join(" ")),
    );

    let mut cmd = Command::new("python3");
    cmd.args(args)
        .current_dir(working_dir)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    apply_java_env_fallbacks(&mut cmd);

    let mut process = cmd
        .spawn()
        .map_err(|error| format!("Failed to start process: {error}"))?;

    let stdout = process
        .stdout
        .take()
        .ok_or_else(|| "Failed to capture stdout".to_string())?;
    let stderr = process
        .stderr
        .take()
        .ok_or_else(|| "Failed to capture stderr".to_string())?;

    {
        let mut lock = state.process.lock().map_err(|_| "State lock failed")?;
        *lock = Some(process);
    }

    let stdout_app = app.clone();
    thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines().map_while(Result::ok) {
            emit_log(&stdout_app, "info", &line);
            if let Some(progress) = parse_progress(&line) {
                let _ = stdout_app.emit("hardening-progress", progress);
            }
        }
    });

    let stderr_app = app.clone();
    let stderr_lines: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));
    let stderr_lines_writer = stderr_lines.clone();
    thread::spawn(move || {
        let reader = BufReader::new(stderr);
        for line in reader.lines().map_while(Result::ok) {
            if let Ok(mut lines) = stderr_lines_writer.lock() {
                lines.push(line.clone());
                let current_len = lines.len();
                if current_len > 40 {
                    let overflow = current_len - 40;
                    lines.drain(0..overflow);
                }
            }
            emit_log(&stderr_app, "error", &line);
        }
    });

    let monitor_app = app.clone();
    let monitor_state = state.process.clone();
    let monitor_stderr_lines = stderr_lines.clone();
    thread::spawn(move || loop {
        let mut should_break = false;

        if let Ok(mut lock) = monitor_state.lock() {
            if let Some(child) = lock.as_mut() {
                match child.try_wait() {
                    Ok(Some(status)) => {
                        if status.success() {
                            let _ = monitor_app.emit(
                                "hardening-progress",
                                HardeningProgress {
                                    stage: "done".to_string(),
                                    progress: 100,
                                    message: "Done! Protected file created.".to_string(),
                                },
                            );
                        } else {
                            let stderr_hint = monitor_stderr_lines
                                .lock()
                                .ok()
                                .and_then(|lines| lines.last().cloned())
                                .unwrap_or_else(|| "No stderr output captured".to_string());
                            let _ = monitor_app.emit(
                                "hardening-progress",
                                HardeningProgress {
                                    stage: "error".to_string(),
                                    progress: 0,
                                    message: format!(
                                        "Error: Process exited with code {:?}. {}",
                                        status.code(), stderr_hint
                                    ),
                                },
                            );
                        }

                        *lock = None;
                        should_break = true;
                    }
                    Ok(None) => {}
                    Err(error) => {
                        let _ = monitor_app.emit(
                            "hardening-progress",
                            HardeningProgress {
                                stage: "error".to_string(),
                                progress: 0,
                                message: format!("Error checking process status: {error}"),
                            },
                        );
                        *lock = None;
                        should_break = true;
                    }
                }
            } else {
                should_break = true;
            }
        } else {
            should_break = true;
        }

        if should_break {
            break;
        }

        thread::sleep(Duration::from_millis(200));
    });

    Ok(())
}

fn detect_repo_root() -> Option<PathBuf> {
    let mut current = std::env::current_dir().ok()?;

    loop {
        if has_pack_py(&current) {
            return Some(current);
        }

        if !current.pop() {
            break;
        }
    }

    None
}

fn has_pack_py(path: &Path) -> bool {
    path.join("pack.py").is_file()
}

fn resolve_pack_py_path(app: &AppHandle) -> Option<PathBuf> {
    if let Ok(root) = std::env::var("CRABSHELL_ROOT") {
        let candidate = PathBuf::from(root).join("pack.py");
        if candidate.is_file() {
            return Some(candidate);
        }
    }

    if let Some(root) = detect_repo_root() {
        let candidate = root.join("pack.py");
        if candidate.is_file() {
            return Some(candidate);
        }
    }

    if let Ok(resource_dir) = app.path().resource_dir() {
        let candidates = [
            resource_dir.join("pack.py"),
            resource_dir.join("resources").join("pack.py"),
            resource_dir.join("../Resources/pack.py"),
        ];

        for candidate in candidates {
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }

    if let Ok(exe_path) = std::env::current_exe() {
        let mut current = exe_path.parent().map(Path::to_path_buf);
        while let Some(path) = current {
            let candidate = path.join("pack.py");
            if candidate.is_file() {
                return Some(candidate);
            }
            current = path.parent().map(Path::to_path_buf);
        }
    }

    None
}

fn apply_java_env_fallbacks(cmd: &mut Command) {
    let current_path = std::env::var("PATH").unwrap_or_default();
    let java_candidate_bins = [
        "/opt/homebrew/opt/openjdk@21/bin",
        "/opt/homebrew/opt/openjdk@17/bin",
        "/opt/homebrew/opt/openjdk/bin",
        "/usr/local/opt/openjdk@21/bin",
        "/usr/local/opt/openjdk@17/bin",
        "/usr/local/opt/openjdk/bin",
    ];

    let mut preferred_java_bin: Option<String> = None;
    for bin_dir in java_candidate_bins {
        let java_bin = Path::new(bin_dir).join("java");
        if !java_bin.is_file() {
            continue;
        }

        if let Ok(output) = Command::new(&java_bin).arg("-version").output() {
            if output.status.success() {
                preferred_java_bin = Some(bin_dir.to_string());
                break;
            }
        }
    }

    let mut path_entries: Vec<String> = current_path
        .split(':')
        .filter(|entry| !entry.is_empty())
        .map(|entry| entry.to_string())
        .collect();

    if let Some(preferred) = preferred_java_bin.as_ref() {
        path_entries.retain(|entry| entry != preferred);
        path_entries.insert(0, preferred.clone());
    }

    for candidate in java_candidate_bins {
        if Path::new(candidate).is_dir() && !path_entries.iter().any(|entry| entry == candidate) {
            path_entries.push(candidate.to_string());
        }
    }

    cmd.env("PATH", path_entries.join(":"));

    let mut java_home_to_set: Option<String> = None;
    if let Ok(existing_java_home) = std::env::var("JAVA_HOME") {
        let java_bin = Path::new(&existing_java_home).join("bin/java");
        let existing_ok = java_bin.is_file()
            && Command::new(&java_bin)
                .arg("-version")
                .output()
                .map(|output| output.status.success())
                .unwrap_or(false);
        if existing_ok {
            java_home_to_set = Some(existing_java_home);
        }
    }

    if java_home_to_set.is_none() {
        if let Some(preferred) = preferred_java_bin.as_ref() {
            if let Some(parent) = Path::new(preferred).parent() {
                java_home_to_set = Some(parent.to_string_lossy().to_string());
            }
        }
    }

    if java_home_to_set.is_none() {
        let java_home_bin = Path::new("/usr/libexec/java_home");
        if java_home_bin.exists() {
            if let Ok(output) = Command::new(java_home_bin).output() {
                if output.status.success() {
                    if let Ok(java_home) = String::from_utf8(output.stdout) {
                        let trimmed = java_home.trim();
                        if !trimmed.is_empty() {
                            java_home_to_set = Some(trimmed.to_string());
                        }
                    }
                }
            }
        }
    }

    if let Some(java_home) = java_home_to_set {
        cmd.env("JAVA_HOME", java_home);
    }
}

#[tauri::command]
fn cancel_hardening(state: State<HardeningState>) -> Result<(), String> {
    let mut lock = state.process.lock().map_err(|_| "State lock failed")?;

    if let Some(child) = lock.as_mut() {
        child.kill().map_err(|error| format!("Failed to kill process: {error}"))?;
    }

    *lock = None;
    Ok(())
}

fn emit_log(app: &AppHandle, level: &str, message: &str) {
    if message.trim().is_empty() {
        return;
    }

    let timestamp = format!("{:?}", std::time::SystemTime::now());
    let _ = app.emit(
        "hardening-log",
        LogEntry {
            timestamp,
            level: level.to_string(),
            message: message.to_string(),
        },
    );
}

fn parse_progress(output: &str) -> Option<HardeningProgress> {
    if output.contains("[toolchain] download-start") {
        let file_name = output
            .split_whitespace()
            .nth(2)
            .unwrap_or("dependency");
        return Some(HardeningProgress {
            stage: "init".to_string(),
            progress: 3,
            message: format!("Downloading dependency: {file_name}"),
        });
    }

    if output.contains("[toolchain] download-progress") {
        let tokens: Vec<&str> = output.split_whitespace().collect();
        let file_name = tokens.get(2).copied().unwrap_or("dependency");
        let mut progress = 5;
        for token in &tokens {
            if let Some(value) = token.strip_suffix('%') {
                if let Ok(parsed) = value.parse::<u8>() {
                    progress = parsed.clamp(5, 30);
                    break;
                }
            }
        }
        return Some(HardeningProgress {
            stage: "init".to_string(),
            progress,
            message: format!("Downloading {file_name} ({progress}%)"),
        });
    }

    if output.contains("[toolchain] download-retry") {
        return Some(HardeningProgress {
            stage: "init".to_string(),
            progress: 6,
            message: "Network unstable, retrying dependency download...".to_string(),
        });
    }

    if output.contains("[toolchain] download-done") {
        let file_name = output
            .split_whitespace()
            .nth(2)
            .unwrap_or("dependency");
        return Some(HardeningProgress {
            stage: "init".to_string(),
            progress: 30,
            message: format!("Dependency ready: {file_name}"),
        });
    }

    let mapping = [
        ("Starting hardening process", "init", 1, "Starting hardening process..."),
        ("Decoding target APK with apktool", "building", 32, "Decoding target APK..."),
        ("Rebuilding decoded APK with apktool", "building", 45, "Rebuilding patched manifest..."),
        ("Building Shell", "building", 35, "Building shell..."),
        ("Building Shell (Native)", "building", 40, "Building shell (Native)..."),
        ("Building Shell (APK)", "building", 60, "Building shell (APK)..."),
        ("Building Shell (APK)...", "building", 55, "Building shell (APK)..."),
        ("Building Shell (Native)...", "building", 35, "Building shell (Native)..."),
        ("Detected AAB file", "init", 5, "Detected AAB file..."),
        ("Converting AAB", "building", 10, "Converting AAB to APK..."),
        ("Building Packer", "building", 20, "Building packer..."),
        ("Phase 1", "packing", 70, "Generating payload..."),
        ("Phase 2", "packing", 80, "Final packing..."),
        ("Signing", "signing", 90, "Signing..."),
        ("Done!", "done", 100, "Done!"),
    ];

    mapping.iter().find_map(|(needle, stage, progress, message)| {
        if output.contains(needle) {
            Some(HardeningProgress {
                stage: stage.to_string(),
                progress: *progress,
                message: message.to_string(),
            })
        } else {
            None
        }
    })
}

fn main() {
    tauri::Builder::default()
        .manage(HardeningState::default())
        .invoke_handler(tauri::generate_handler![
            select_file,
            select_keystore,
            select_output,
            start_hardening,
            cancel_hardening
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
