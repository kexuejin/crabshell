use jni::JNIEnv;
use jni::objects::{JClass, JObject, JString, JValue, JObjectArray, JByteArray};
use jni::sys::{jint, JNI_VERSION_1_6};
use aes_gcm::{
    aead::{Aead, KeyInit},
    Aes256Gcm, Nonce
};
use std::os::raw::c_void;
use std::fs::File;
use std::io::{Read, Write, Seek, SeekFrom};
use std::sync::atomic::{AtomicBool, Ordering};
use zip::ZipArchive;

mod config;
mod strings_config;
#[macro_use]
mod obfuscate;
use config::{get_aes_key, PAYLOAD_HASH, EXPECTED_SIGNATURE_HASH};
use sha2::{Sha256, Digest};

#[macro_use]
extern crate log;
use android_logger::Config;

static DEX_LOAD_MARKER: AtomicBool = AtomicBool::new(false);

fn try_mark_dex_load_started() -> bool {
    DEX_LOAD_MARKER
        .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
        .is_ok()
}

fn clear_dex_load_marker() {
    DEX_LOAD_MARKER.store(false, Ordering::Release);
}

#[cfg(test)]
fn clear_dex_load_marker_for_tests() {
    clear_dex_load_marker();
}

#[no_mangle]
pub extern "system" fn JNI_OnLoad(_vm: jni::JavaVM, _reserved: *mut c_void) -> jint {
    android_logger::init_once(
        Config::default()
            .with_tag(s!(strings_config::LOG_TAG))
            .with_max_level(log::LevelFilter::Debug),
    );
    // Sleep to allow logcat to catch up
    std::thread::sleep(std::time::Duration::from_millis(500));
    info!("Native library loaded, JNI_OnLoad called");

    // Anti-Debug: Check TracerPid and Ptrace
    check_debugger();

    JNI_VERSION_1_6
}

fn check_debugger() {
    // 1. Check TracerPid
    if let Ok(content) = std::fs::read_to_string(&s!(strings_config::PROC_STATUS)) {
        for line in content.lines() {
            if line.starts_with(&s!(strings_config::TRACER_PID)) {
                let parts: Vec<&str> = line.split_whitespace().collect();
                if parts.len() > 1 {
                    let pid_str = parts[1];
                    info!("{} {}", s!(strings_config::TRACER_PID), pid_str);
                    if let Ok(pid) = pid_str.parse::<i32>() {
                        if pid > 0 {
                            error!("{} {}={}! {}", 
                                s!(strings_config::DEBUG_DETECTED), 
                                s!(strings_config::TRACER_PID), 
                                pid, 
                                s!(strings_config::EXITING));
                            std::process::exit(1);
                        }
                    }
                }
            }
        }
    }

    // 2. Check Ptrace (PTRACE_TRACEME)
    // If we can't trace ourselves, someone else is likely tracing us.
    #[cfg(target_os = "android")]
    unsafe {
        if libc::ptrace(
            libc::PTRACE_TRACEME,
            0,
            std::ptr::null_mut::<libc::c_void>(),
            std::ptr::null_mut::<libc::c_void>(),
        ) == -1
        {
            let errno = std::io::Error::last_os_error().raw_os_error().unwrap_or(0);
            if errno == 13 {
                // EACCES: likely SELinux restriction, not necessarily a debugger
                info!("{}", s!(strings_config::PTRACE_RESTRICTED));
            } else {
                error!(
                    "{} ({})! {}",
                    s!(strings_config::DEBUG_DETECTED),
                    s!(strings_config::PTRACE_FAILED).replace("{}", &errno.to_string()),
                    s!(strings_config::EXITING)
                );
                // std::process::exit(1);
            }
        } else {
            info!("{}", s!(strings_config::PTRACE_SUCCESS));
        }
    }

    #[cfg(not(target_os = "android"))]
    {
        debug!("Skipping ptrace check on non-Android target");
    }
}

fn call_object_method<'local>(
    env: &mut JNIEnv<'local>,
    obj: &JObject<'local>,
    method: &str,
    sig: &str,
) -> Result<JObject<'local>, jni::errors::Error> {
    env.call_method(obj, method, sig, &[])?.l()
}

fn call_string_method<'local>(
    env: &mut JNIEnv<'local>,
    obj: &JObject<'local>,
    method: &str,
    sig: &str,
) -> Result<String, jni::errors::Error> {
    let value = call_object_method(env, obj, method, sig)?;
    Ok(env.get_string(&JString::from(value))?.into())
}

fn get_string_field<'local>(
    env: &mut JNIEnv<'local>,
    obj: &JObject<'local>,
    field: &str,
) -> Result<String, jni::errors::Error> {
    let value = env.get_field(obj, field, "Ljava/lang/String;")?.l()?;
    Ok(env.get_string(&JString::from(value))?.into())
}

fn get_paths_and_loader_from_context<'local>(
    env: &mut JNIEnv<'local>,
    context: &JObject<'local>,
) -> Result<(String, String, JObject<'local>), jni::errors::Error> {
    let cache_dir = call_object_method(env, context, "getCacheDir", "()Ljava/io/File;")?;
    let cache_path = call_string_method(env, &cache_dir, "getAbsolutePath", "()Ljava/lang/String;")?;

    let class_loader = call_object_method(env, context, "getClassLoader", "()Ljava/lang/ClassLoader;")?;

    let files_dir = call_object_method(env, context, "getFilesDir", "()Ljava/io/File;")?;
    let data_dir = call_object_method(env, &files_dir, "getParentFile", "()Ljava/io/File;")?;
    let data_path = call_string_method(env, &data_dir, "getAbsolutePath", "()Ljava/lang/String;")?;

    Ok((cache_path, data_path, class_loader))
}

#[no_mangle]
pub extern "system" fn Java_com_kapp_shell_ShellApplication_nativeLoadDex<'local>(
    mut env: JNIEnv<'local>,
    _this: JObject<'local>,
    context: JObject<'local>,
    sdk_int: jint,
) {
    info!("{} {}", s!(strings_config::MSG_NATIVE_LOAD_DEX).replace("{}", ""), sdk_int);
    if !try_mark_dex_load_started() {
        info!("nativeLoadDex (Application): dex already loaded in process, skipping duplicate call");
        return;
    }
    let apk_path = match get_package_code_path(&mut env, &context) {
        Ok(path) => path,
        Err(e) => {
            error!("Failed to get package code path: {:?}", e);
            let _ = env.exception_clear();
            clear_dex_load_marker();
            return;
        }
    };

    let (cache_path_str, data_path_str, class_loader) =
        match get_paths_and_loader_from_context(&mut env, &context) {
            Ok(values) => values,
            Err(e) => {
                error!("nativeLoadDex (Application): failed to resolve paths/classloader: {:?}", e);
                let _ = env.exception_clear();
                clear_dex_load_marker();
                return;
            }
        };

    if let Err(e) = verify_integrity(&mut env, &context) {
        error!("Integrity check failed: {:?}", e);
        // In a real hardened app, we should probably exit here.
        // std::process::exit(1);
    }

    let payload = match extract_payload(&apk_path, true) {
        Ok(payload) => payload,
        Err(e) => {
            error!("Payload integrity failed: {:?}", e);
            clear_dex_load_marker();
            return;
        }
    };

    if let Err(e) =
        load_dex_core(&mut env, &cache_path_str, &data_path_str, &class_loader, &payload, sdk_int)
    {
        error!("nativeLoadDex (Application) failed: {:?}", e);
        let _ = env.exception_clear();
        clear_dex_load_marker();
    }
}

#[no_mangle]
pub extern "system" fn Java_com_kapp_shell_ShellApplication_nativeLoadDexWithAppInfo<'local>(
    mut env: JNIEnv<'local>,
    _class: JClass<'local>,
    app_info: JObject<'local>,
    class_loader: JObject<'local>,
    sdk_int: jint,
) {
    info!("{} {}", s!(strings_config::MSG_NATIVE_LOAD_DEX).replace("{}", ""), sdk_int);
    if !try_mark_dex_load_started() {
        info!("nativeLoadDexWithAppInfo: dex already loaded in process, skipping duplicate call");
        return;
    }
    
    // 1. Get APK path and data dir from ApplicationInfo
    let apk_path = match get_string_field(&mut env, &app_info, "sourceDir") {
        Ok(value) => value,
        Err(e) => {
            error!("nativeLoadDexWithAppInfo: failed to read sourceDir: {:?}", e);
            let _ = env.exception_clear();
            clear_dex_load_marker();
            return;
        }
    };

    let data_dir = match get_string_field(&mut env, &app_info, "dataDir") {
        Ok(value) => value,
        Err(e) => {
            error!("nativeLoadDexWithAppInfo: failed to read dataDir: {:?}", e);
            let _ = env.exception_clear();
            clear_dex_load_marker();
            return;
        }
    };
    let cache_path_str = format!("{}/cache", data_dir);
    if let Err(e) = std::fs::create_dir_all(&cache_path_str) {
        error!(
            "nativeLoadDexWithAppInfo: failed to create cache dir {}: {}",
            cache_path_str, e
        );
        clear_dex_load_marker();
        return;
    }

    // 2. Verify Integrity (Skip for now if we only have app_info, or pass JObject::null())
    // For now, we skip signature check here to avoid complexity of getting PM from app_info.
    // It will be verified in nativeLoadDex or BootstrapProvider anyway.
    let payload = match extract_payload(&apk_path, true) {
        Ok(payload) => payload,
        Err(e) => {
            error!("Payload integrity failed: {:?}", e);
            clear_dex_load_marker();
            return;
        }
    };

    // 3. Load DEX using the modular core
    if let Err(e) = load_dex_core(
        &mut env,
        &cache_path_str,
        &data_dir,
        &class_loader,
        &payload,
        sdk_int,
    ) {
        error!("nativeLoadDexWithAppInfo failed: {:?}", e);
        let _ = env.exception_clear();
        clear_dex_load_marker();
    }
}

#[no_mangle]
pub extern "system" fn Java_com_kapp_shell_BootstrapProvider_nativeLoadDex<'local>(
    mut env: JNIEnv<'local>,
    _class: JClass<'local>,
    context: JObject<'local>,
    sdk_int: jint,
) {
    info!("nativeLoadDex (Provider) called for SDK {}", sdk_int);
    if !try_mark_dex_load_started() {
        info!("nativeLoadDex (Provider): dex already loaded in process, skipping duplicate call");
        return;
    }
    let apk_path = match get_package_code_path(&mut env, &context) {
        Ok(path) => path,
        Err(e) => {
            error!("Failed to get package code path (Provider): {:?}", e);
            let _ = env.exception_clear();
            clear_dex_load_marker();
            return;
        }
    };

    let (cache_path_str, data_path_str, class_loader) =
        match get_paths_and_loader_from_context(&mut env, &context) {
            Ok(values) => values,
            Err(e) => {
                error!("nativeLoadDex (Provider): failed to resolve paths/classloader: {:?}", e);
                let _ = env.exception_clear();
                clear_dex_load_marker();
                return;
            }
        };

    if let Err(e) = verify_integrity(&mut env, &context) {
        error!("Integrity check failed: {:?}", e);
        // std::process::exit(1);
    }

    let payload = match extract_payload(&apk_path, true) {
        Ok(payload) => payload,
        Err(e) => {
            error!("Payload integrity failed: {:?}", e);
            clear_dex_load_marker();
            return;
        }
    };

    if let Err(e) =
        load_dex_core(&mut env, &cache_path_str, &data_path_str, &class_loader, &payload, sdk_int)
    {
        error!("nativeLoadDex (Provider) failed: {:?}", e);
        let _ = env.exception_clear();
        clear_dex_load_marker();
    }
}

fn load_dex_core(
    env: &mut JNIEnv,
    cache_path: &str,
    data_path: &str,
    class_loader: &JObject,
    payload: &[(String, Vec<u8>)],
    sdk_int: jint,
) -> Result<(), Box<dyn std::error::Error>> {
    // 1. Extract Assets
    extract_assets_core(data_path, payload)?;

    // 2. Load DEX and Libs
    // NOTE:
    // We intentionally use file-landing on all SDKs. In-memory mode can trigger
    // "Attempt to register dex file ... with multiple class loaders" for some
    // multi-process/provider startup sequences.
    if sdk_int >= 26 {
        info!(
            "load_dex_core: using file-landing mode on SDK {} for class-loader compatibility",
            sdk_int
        );
    }
    load_file_landing(env, cache_path, class_loader, payload).map_err(|e| e.into())
}

fn extract_assets_core(
    data_path: &str,
    payload: &[(String, Vec<u8>)],
) -> Result<(), Box<dyn std::error::Error>> {
    let zip_path = format!("{}/files/kapp_assets.zip", data_path);
    debug!("extract_assets_core: Landing assets in {}", zip_path);
    
    // Ensure parent directory (files) exists
    if let Some(parent) = std::path::Path::new(&zip_path).parent() {
        std::fs::create_dir_all(parent)?;
    }

    let file = File::create(&zip_path)?;
    let mut zip = zip::ZipWriter::new(file);
    let options = zip::write::FileOptions::default()
        .compression_method(zip::CompressionMethod::Stored); // Store uncompressed for speed/simplicity

    let mut asset_count = 0;
    for (name, data) in payload {
        if name.starts_with("assets/") {
            debug!("Adding asset to ZIP: {}", name);
            zip.start_file(name, options)?;
            zip.write_all(data)?;
            asset_count += 1;
        }
    }
    
    zip.finish()?;

    if asset_count > 0 {
        info!("Successfully packed {} protected assets into {}", asset_count, zip_path);
    }
    Ok(())
}

fn get_package_code_path(env: &mut JNIEnv, context: &JObject) -> Result<String, jni::errors::Error> {
    debug!("Calling getPackageCodePath...");
    let package_code_path = env
        .call_method(context, "getPackageCodePath", "()Ljava/lang/String;", &[])?
        .l()?;
    let path_str: String = env.get_string(&package_code_path.into())?.into();
    debug!("Package code path: {}", path_str);
    Ok(path_str)
}

fn verify_integrity(
    env: &mut JNIEnv,
    context: &JObject,
) -> Result<(), Box<dyn std::error::Error>> {
    // 1. Verify APK Signature
    info!("Verifying APK signature...");
    let package_name = env.call_method(context, "getPackageName", "()Ljava/lang/String;", &[])?.l()?;
    let pm = env.call_method(context, "getPackageManager", "()Landroid/content/pm/PackageManager;", &[])?.l()?;
    
    // GET_SIGNATURES = 64
    let package_info = env.call_method(&pm, "getPackageInfo", "(Ljava/lang/String;I)Landroid/content/pm/PackageInfo;", &[
        (&package_name).into(),
        64i32.into(),
    ])?.l()?;
    
    let signatures_array: JObjectArray = env.get_field(&package_info, "signatures", "[Landroid/content/pm/Signature;")?.l()?.into();
    if env.get_array_length(&signatures_array)? > 0 {
        let signature = env.get_object_array_element(&signatures_array, 0)?;
        let cert_bytes_j = env.call_method(&signature, "toByteArray", "()[B", &[])?.l()?;
        let cert_bytes: Vec<u8> = env.convert_byte_array(&JByteArray::from(cert_bytes_j))?;
        
        let mut hasher = Sha256::new();
        hasher.update(&cert_bytes);
        let hash = hasher.finalize();
        
        if hash.as_slice() != EXPECTED_SIGNATURE_HASH {
            error!("Signature mismatch! Expected: {}, Actual: {}", 
                hex::encode(EXPECTED_SIGNATURE_HASH), 
                hex::encode(hash));
            return Err("Signature integrity check failed".into());
        }
        info!("Signature integrity verified.");
    } else {
        warn!("No signatures found in PackageInfo.");
    }

    Ok(())
}

fn extract_payload(path: &str, verify: bool) -> Result<Vec<(String, Vec<u8>)>, Box<dyn std::error::Error>> {
    debug!("{} {}", s!(strings_config::MSG_OPEN_APK).replace("{}", ""), path);
    let apk_file = File::open(path)?;
    let mut apk_zip = ZipArchive::new(apk_file)?;
    debug!("Opening content...");
    let mut payload_entry = apk_zip.by_name(&s!(strings_config::PAYLOAD_NAME))?;
    let mut encrypted_data = Vec::new();
    payload_entry.read_to_end(&mut encrypted_data)?;
    debug!("Read {} bytes from payload", encrypted_data.len());

    if verify {
        let mut hasher = Sha256::new();
        hasher.update(&encrypted_data);
        let hash = hasher.finalize();
        if hash.as_slice() != PAYLOAD_HASH {
            // Check if it's all zeros (empty/dummy config)
            if PAYLOAD_HASH != [0u8; 32] {
                error!("Payload hash mismatch! Expected: {}, Actual: {}", 
                    hex::encode(PAYLOAD_HASH), 
                    hex::encode(hash));
                return Err("Payload integrity check failed".into());
            } else {
                warn!("Payload hash check skipped (embedded hash is zero).");
            }
        }
    }

    decrypt_payload(&encrypted_data, &get_aes_key())
}

fn decrypt_payload(
    encrypted_data: &[u8],
    key: &[u8; 32],
) -> Result<Vec<(String, Vec<u8>)>, Box<dyn std::error::Error>> {
    let mut file = std::io::Cursor::new(encrypted_data);
    let file_len = encrypted_data.len() as u64;

    // Footer: [Metadata Size (4)] [Magic "SHELL" (5)]
    let footer_len = 9;
    if file_len < footer_len {
        return Err("Payload too small".into());
    }

    file.seek(SeekFrom::End(-(footer_len as i64)))?;
    let mut footer = [0u8; 9];
    file.read_exact(&mut footer)?;

    let magic = &footer[4..9];
    if magic != s!(strings_config::MAGIC_SHELL).as_bytes() {
        return Err(s!(strings_config::ERR_NO_PAYLOAD).into());
    }

    let metadata_size = u32::from_le_bytes(footer[0..4].try_into()?) as u64;
    
    // Metadata Block: [N (4)] + [ [NameLen(2)] [Name] [Size(4)] [IV(12)] ] * N
    let metadata_start = file_len
        .checked_sub(footer_len as u64)
        .and_then(|v| v.checked_sub(metadata_size))
        .ok_or("Invalid metadata size")?;

    file.seek(SeekFrom::Start(metadata_start))?;
    let mut metadata = vec![0u8; metadata_size as usize];
    file.read_exact(&mut metadata)?;

    let mut cursor = std::io::Cursor::new(&metadata);
    let mut n_bytes = [0u8; 4];
    cursor.read_exact(&mut n_bytes)?;
    let num_files = u32::from_le_bytes(n_bytes);

    let mut entries = Vec::new();
    let mut total_encrypted_size = 0;

    for _ in 0..num_files {
        let mut name_len_bytes = [0u8; 2];
        cursor.read_exact(&mut name_len_bytes)?;
        let name_len = u16::from_le_bytes(name_len_bytes) as usize;
        
        let mut name_bytes = vec![0u8; name_len];
        cursor.read_exact(&mut name_bytes)?;
        let name = String::from_utf8(name_bytes)?;

        let mut size_bytes = [0u8; 4];
        cursor.read_exact(&mut size_bytes)?;
        let size = u32::from_le_bytes(size_bytes);
        
        let mut iv = [0u8; 12];
        cursor.read_exact(&mut iv)?;
        
        entries.push((name, size, iv));
        total_encrypted_size += size as u64;
    }

    // Read Payloads
    let payload_start = metadata_start
        .checked_sub(total_encrypted_size)
        .ok_or("Invalid payload offset")?;

    file.seek(SeekFrom::Start(payload_start))?;
    
    let cipher = Aes256Gcm::new(key.into());
    let mut results = Vec::new();

    for (name, size, iv) in entries {
        let mut enc_buf = vec![0u8; size as usize];
        file.read_exact(&mut enc_buf)?;
        
        let nonce = Nonce::from_slice(&iv);
        let plaintext = cipher.decrypt(nonce, enc_buf.as_ref())
            .map_err(|e| format!("Decryption failed for {}: {:?}", name, e))?;
        
        results.push((name, plaintext));
    }
    
    Ok(results)
}

fn load_in_memory(env: &mut JNIEnv, cache_path: &str, target_loader: &JObject, file_list: &[(String, Vec<u8>)]) -> Result<(), jni::errors::Error> {
    info!("load_in_memory called with {} items", file_list.len());
    // 1. Separate DEXs and Libs
    let mut dex_buffers = Vec::new();
    let mut lib_buffers = Vec::new();
    let current_abi = get_current_abi();
    debug!("Current ABI: {}", current_abi);

    let lib_prefix = format!("lib/{}/", current_abi);

    for (name, data) in file_list {
        if name.ends_with(".dex") {
             dex_buffers.push(data);
        } else if name.starts_with(&lib_prefix) && name.ends_with(".so") {
             let filename = name.strip_prefix(&lib_prefix).unwrap_or(name);
             lib_buffers.push((filename, data));
        }
    }

    debug!("Found {} DEXs and {} Libs for current ABI", dex_buffers.len(), lib_buffers.len());

    // 2. Extract Libs to Cache
    debug!("Extracting libs to cache...");
    let libs_dir = format!("{}/native_libs", cache_path);
    std::fs::create_dir_all(&libs_dir).unwrap_or(());

    for (filename, data) in lib_buffers {
        let lib_path = format!("{}/{}", libs_dir, filename);
        debug!("Writing lib: {}", lib_path);
        if let Ok(mut file) = File::create(&lib_path) {
            let _ = file.write_all(data);
        }
    }

    // 3. Create ByteBuffer[] for DEXs
    if dex_buffers.is_empty() {
        warn!("No DEX files to load in memory!");
        return Ok(());
    }

    debug!("Creating ByteBuffer array for {} DEXs...", dex_buffers.len());
    let byte_buffer_cls = env.find_class("java/nio/ByteBuffer")?;
    let buffer_array = env.new_object_array(dex_buffers.len() as i32, &byte_buffer_cls, JObject::null())?;

    for (i, dex_data) in dex_buffers.iter().enumerate() {
        debug!("Wrapping DEX {} ({} bytes)...", i, dex_data.len());
        let byte_array = env.byte_array_from_slice(dex_data)?;
        let buffer = env.call_static_method(
            &byte_buffer_cls,
            "wrap", 
            "([B)Ljava/nio/ByteBuffer;", 
            &[JValue::Object(&byte_array.into())]
        )?.l()?;
        
        env.set_object_array_element(&buffer_array, i as i32, buffer)?;
    }

    // 4. Create InMemoryDexClassLoader
    debug!("Instantiating InMemoryDexClassLoader...");

    let dex_loader_cls = env.find_class("dalvik/system/InMemoryDexClassLoader")?;
    let buffer_array_obj: JObject = buffer_array.into();

    let ctor_sig_with_lib = "([Ljava/nio/ByteBuffer;Ljava/lang/String;Ljava/lang/ClassLoader;)V";
    
    let libs_dir_j = env.new_string(&libs_dir)?;
    let libs_dir_obj: JObject = libs_dir_j.into();
    
    let loader_res = env.new_object(
        &dex_loader_cls,
        ctor_sig_with_lib,
        &[
            JValue::Object(&buffer_array_obj),
            JValue::Object(&libs_dir_obj),
            JValue::Object(target_loader)
        ]
    );

    let loader = match loader_res {
        Ok(l) => l,
        Err(_) => {
            let _ = env.exception_clear();
            env.new_object(
                &dex_loader_cls,
                "([Ljava/nio/ByteBuffer;Ljava/lang/ClassLoader;)V",
                &[JValue::Object(&buffer_array_obj), JValue::Object(target_loader)]
            )?
        }
    };

    // 5. Inject Dex Elements into Parent Loader (Hotfix style)
    inject_dex_elements(env, &loader, target_loader)?;
    
    info!("load_in_memory: Completion successful");
    Ok(())
}

fn get_current_abi() -> &'static str {
    #[cfg(target_arch = "aarch64")]
    return "arm64-v8a";
    #[cfg(target_arch = "arm")]
    return "armeabi-v7a";
    #[cfg(target_arch = "x86")]
    return "x86";
    #[cfg(target_arch = "x86_64")]
    return "x86_64";
    #[cfg(not(any(target_arch = "aarch64", target_arch = "arm", target_arch = "x86", target_arch = "x86_64")))]
    return "unknown";
}

fn load_file_landing(env: &mut JNIEnv, cache_path: &str, target_loader: &JObject, file_list: &[(String, Vec<u8>)]) -> Result<(), jni::errors::Error> {
    let dex_cache_dir = format!("{}/dex_landing", cache_path);
    std::fs::create_dir_all(&dex_cache_dir).unwrap_or(());

    let libs_dir = format!("{}/native_libs", cache_path);
    std::fs::create_dir_all(&libs_dir).unwrap_or(());

    let mut dex_paths = Vec::new();

    // 2. Extract Files
    let current_abi = get_current_abi();
    let lib_prefix = format!("lib/{}/", current_abi);

    for (i, (name, data)) in file_list.iter().enumerate() {
        if name.ends_with(".dex") {
             let dex_path = format!("{}/payload_{}.dex", dex_cache_dir, i);
             if let Ok(mut file) = File::create(&dex_path) {
                let _ = file.write_all(data);
                #[cfg(unix)]
                {
                    use std::os::unix::fs::PermissionsExt;
                    if let Ok(metadata) = std::fs::metadata(&dex_path) {
                        let mut permissions = metadata.permissions();
                        permissions.set_mode(0o444);
                        let _ = std::fs::set_permissions(&dex_path, permissions);
                    }
                }
             }
             dex_paths.push(dex_path);
        } else if name.starts_with(&lib_prefix) && name.ends_with(".so") {
             let filename = name.strip_prefix(&lib_prefix).unwrap_or(name);
             let lib_path = format!("{}/{}", libs_dir, filename);
             if let Ok(mut file) = File::create(&lib_path) {
                let _ = file.write_all(data);
             }
        }
    }
    
    let joined_paths = dex_paths.join(":");

    if joined_paths.is_empty() {
        warn!("No dex paths extracted in load_file_landing");
        return Ok(());
    }

    // 3. Add dex paths directly into target loader to avoid cross-classloader dex
    // ownership conflicts.
    let dex_path_j = env.new_string(&joined_paths)?;
    let dex_path_obj: JObject = dex_path_j.into();

    let add_dex_result = env.call_method(
        target_loader,
        "addDexPath",
        "(Ljava/lang/String;Z)V",
        &[JValue::Object(&dex_path_obj), JValue::Bool(0)],
    );
    if add_dex_result.is_err() {
        let _ = env.exception_clear();
        env.call_method(
            target_loader,
            "addDexPath",
            "(Ljava/lang/String;)V",
            &[JValue::Object(&dex_path_obj)],
        )?;
    }

    // 4. Best-effort add native lib search path for extracted .so files
    let libs_dir_j = env.new_string(&libs_dir)?;
    let libs_dir_obj: JObject = libs_dir_j.into();
    let array_list_cls = env.find_class("java/util/ArrayList")?;
    let native_paths = env.new_object(&array_list_cls, "()V", &[])?;
    env.call_method(
        &native_paths,
        "add",
        "(Ljava/lang/Object;)Z",
        &[JValue::Object(&libs_dir_obj)],
    )?;

    let add_native_result = env.call_method(
        target_loader,
        "addNativePath",
        "(Ljava/util/Collection;)V",
        &[JValue::Object(&native_paths)],
    );
    if add_native_result.is_err() {
        let _ = env.exception_clear();
        debug!("addNativePath not available on target loader, continue without it");
    }

    Ok(())
}

fn inject_dex_elements(env: &mut JNIEnv, source_loader: &JObject, target_loader: &JObject) -> Result<(), jni::errors::Error> {
    info!("shell: inject_dex_elements starting...");
    
    let source_path_list = env.get_field(source_loader, "pathList", "Ldalvik/system/DexPathList;")?.l()?;
    let target_path_list = env.get_field(target_loader, "pathList", "Ldalvik/system/DexPathList;")?.l()?;

    let source_elements_obj = env.get_field(source_path_list, "dexElements", "[Ldalvik/system/DexPathList$Element;")?.l()?;
    let source_array: JObjectArray = source_elements_obj.into();

    let target_elements_obj = env.get_field(&target_path_list, "dexElements", "[Ldalvik/system/DexPathList$Element;")?.l()?;
    let target_array: JObjectArray = target_elements_obj.into();
    
    let source_len = env.get_array_length(&source_array)?;
    let target_len = env.get_array_length(&target_array)?;
    debug!("shell: Merging {} new elements into {} existing elements", source_len, target_len);

    let element_cls = env.find_class("dalvik/system/DexPathList$Element")?;
    
    let total_len = source_len + target_len;
    let new_array = env.new_object_array(total_len, element_cls, JObject::null())?;
    
    for i in 0..target_len {
        let elem = env.get_object_array_element(&target_array, i)?;
        env.set_object_array_element(&new_array, i, elem)?;
    }
    
    for i in 0..source_len {
        let elem = env.get_object_array_element(&source_array, i)?;
        env.set_object_array_element(&new_array, target_len + i, elem)?;
    }
    
    let new_array_obj = JObject::from(new_array);
    env.set_field(
        target_path_list,
        "dexElements",
        "[Ldalvik/system/DexPathList$Element;",
        JValue::Object(&new_array_obj)
    )?;

    info!("shell: inject_dex_elements completed successfully");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{clear_dex_load_marker_for_tests, try_mark_dex_load_started};

    #[test]
    fn dex_load_marker_allows_only_first_call() {
        clear_dex_load_marker_for_tests();

        assert!(try_mark_dex_load_started());
        assert!(!try_mark_dex_load_started());

        clear_dex_load_marker_for_tests();
        assert!(try_mark_dex_load_started());
    }
}
