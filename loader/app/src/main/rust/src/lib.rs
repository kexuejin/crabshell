use jni::JNIEnv;
use jni::objects::{JClass, JObject, JString, JValue, JObjectArray};
use jni::sys::{jint, JNI_VERSION_1_6};
use aes_gcm::{
    aead::{Aead, KeyInit},
    Aes256Gcm, Nonce
};
use std::os::raw::c_void;
use std::fs::File;
use std::io::{Read, Write, Seek, SeekFrom};
use zip::ZipArchive;

mod config;
use config::get_aes_key;

#[macro_use]
extern crate log;
use android_logger::Config;

#[no_mangle]
pub extern "system" fn JNI_OnLoad(_vm: jni::JavaVM, _reserved: *mut c_void) -> jint {
    android_logger::init_once(
        Config::default()
            .with_tag("KAppShell")
            .with_max_level(log::LevelFilter::Debug),
    );
    info!("Native library loaded, JNI_OnLoad called");

    // Basic Anti-Debug: Check TracerPid
    if is_debugger_attached() {
        warn!("Debugger detected! Exiting...");
        std::process::exit(1);
    }
    JNI_VERSION_1_6
}

fn is_debugger_attached() -> bool {
    // Check /proc/self/status for TracerPid
    if let Ok(content) = std::fs::read_to_string("/proc/self/status") {
        for line in content.lines() {
            if line.starts_with("TracerPid:") {
                if let Some(pid_str) = line.split_whitespace().nth(1) {
                    if let Ok(pid) = pid_str.parse::<i32>() {
                        if pid > 0 {
                            return true;
                        }
                    }
                }
            }
        }
    }
    false
}

#[no_mangle]
pub extern "system" fn Java_com_kapp_shell_ShellApplication_nativeLoadDex(
    mut env: JNIEnv,
    _class: JClass,
    context: JObject,
    sdk_int: jint,
) {
    info!("nativeLoadDex (Application) called for SDK {}", sdk_int);
    let apk_path = match get_package_code_path(&mut env, &context) {
        Ok(path) => path,
        Err(e) => {
            error!("Failed to get package code path: {:?}", e);
            let _ = env.exception_clear();
            return;
        }
    };
    
    let cache_dir = env.call_method(&context, "getCacheDir", "()Ljava/io/File;", &[]).unwrap().l().unwrap();
    let cache_path = env.call_method(&cache_dir, "getAbsolutePath", "()Ljava/lang/String;", &[]).unwrap().l().unwrap();
    let cache_path_str: String = env.get_string(&cache_path.into()).unwrap().into();

    let class_loader = env.call_method(&context, "getClassLoader", "()Ljava/lang/ClassLoader;", &[]).unwrap().l().unwrap();

    let files_dir = env.call_method(&context, "getFilesDir", "()Ljava/io/File;", &[]).unwrap().l().unwrap();
    let data_dir_obj = env.call_method(&files_dir, "getParentFile", "()Ljava/io/File;", &[]).unwrap().l().unwrap();
    let data_path_j = env.call_method(&data_dir_obj, "getAbsolutePath", "()Ljava/lang/String;", &[]).unwrap().l().unwrap();
    let data_path_str: String = env.get_string(&data_path_j.into()).unwrap().into();

    if let Err(e) = load_dex_core(&mut env, &apk_path, &cache_path_str, &data_path_str, &class_loader, sdk_int) {
        error!("nativeLoadDex (Application) failed: {:?}", e);
        let _ = env.exception_clear();
    }
}

#[no_mangle]
pub extern "system" fn Java_com_kapp_shell_ShellApplication_nativeLoadDexWithAppInfo(
    mut env: JNIEnv,
    _class: JClass,
    app_info: JObject,
    class_loader: JObject,
    sdk_int: jint,
) {
    info!("nativeLoadDexWithAppInfo called for SDK {}", sdk_int);
    
    // 1. Get APK path and data dir from ApplicationInfo
    let source_dir_j = env.get_field(&app_info, "sourceDir", "Ljava/lang/String;").unwrap().l().unwrap();
    let apk_path: String = env.get_string(&source_dir_j.into()).unwrap().into();
    
    let data_dir_j = env.get_field(&app_info, "dataDir", "Ljava/lang/String;").unwrap().l().unwrap();
    let data_dir: String = env.get_string(&data_dir_j.into()).unwrap().into();
    let cache_path_str = format!("{}/cache", data_dir);
    std::fs::create_dir_all(&cache_path_str).unwrap_or(());

    // 2. Load DEX using the modular core
    if let Err(e) = load_dex_core(&mut env, &apk_path, &cache_path_str, &data_dir, &class_loader, sdk_int) {
        error!("nativeLoadDexWithAppInfo failed: {:?}", e);
        let _ = env.exception_clear();
    }
}

#[no_mangle]
pub extern "system" fn Java_com_kapp_shell_BootstrapProvider_nativeLoadDex(
    mut env: JNIEnv,
    _class: JClass,
    context: JObject,
    sdk_int: jint,
) {
    info!("nativeLoadDex (Provider) called for SDK {}", sdk_int);
    let apk_path = match get_package_code_path(&mut env, &context) {
        Ok(path) => path,
        Err(e) => {
            error!("Failed to get package code path (Provider): {:?}", e);
            let _ = env.exception_clear();
            return;
        }
    };

    let cache_dir = env.call_method(&context, "getCacheDir", "()Ljava/io/File;", &[]).unwrap().l().unwrap();
    let cache_path = env.call_method(&cache_dir, "getAbsolutePath", "()Ljava/lang/String;", &[]).unwrap().l().unwrap();
    let cache_path_str: String = env.get_string(&cache_path.into()).unwrap().into();

    let class_loader = env.call_method(&context, "getClassLoader", "()Ljava/lang/ClassLoader;", &[]).unwrap().l().unwrap();

    let files_dir = env.call_method(&context, "getFilesDir", "()Ljava/io/File;", &[]).unwrap().l().unwrap();
    let data_dir_obj = env.call_method(&files_dir, "getParentFile", "()Ljava/io/File;", &[]).unwrap().l().unwrap();
    let data_path_j = env.call_method(&data_dir_obj, "getAbsolutePath", "()Ljava/lang/String;", &[]).unwrap().l().unwrap();
    let data_path_str: String = env.get_string(&data_path_j.into()).unwrap().into();

    if let Err(e) = load_dex_core(&mut env, &apk_path, &cache_path_str, &data_path_str, &class_loader, sdk_int) {
        error!("nativeLoadDex (Provider) failed: {:?}", e);
        let _ = env.exception_clear();
    }
}

fn load_dex_core(
    env: &mut JNIEnv,
    apk_path: &str,
    cache_path: &str,
    data_path: &str,
    class_loader: &JObject,
    sdk_int: jint,
) -> Result<(), Box<dyn std::error::Error>> {
    let payload = extract_payload(apk_path)?;
    
    // 1. Extract Assets
    extract_assets_core(data_path, &payload)?;

    // 2. Load DEX and Libs
    if sdk_int >= 26 {
        load_in_memory(env, cache_path, class_loader, &payload)
    } else {
        load_file_landing(env, cache_path, class_loader, &payload)
    }.map_err(|e| e.into())
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

fn extract_payload(path: &str) -> Result<Vec<(String, Vec<u8>)>, Box<dyn std::error::Error>> {
    debug!("Opening APK at {}", path);
    let apk_file = File::open(path)?;
    let mut apk_zip = ZipArchive::new(apk_file)?;
    debug!("Opening assets/kapp_payload.bin...");
    let mut payload_entry = apk_zip.by_name("assets/kapp_payload.bin")?;
    let mut payload_bytes = Vec::new();
    payload_entry.read_to_end(&mut payload_bytes)?;
    debug!("Read {} bytes from payload", payload_bytes.len());

    let mut file = std::io::Cursor::new(payload_bytes);
    let file_len = file.get_ref().len() as u64;

    // Footer: [Metadata Size (4)] [Magic "SHELL" (5)]
    let footer_len = 9;
    if file_len < footer_len {
        return Err("File too small".into());
    }

    file.seek(SeekFrom::End(-(footer_len as i64)))?;
    let mut footer = vec![0u8; footer_len as usize];
    file.read_exact(&mut footer)?;

    let magic = &footer[4..9];
    debug!("Payload magic: {:?}", std::str::from_utf8(magic));
    if magic != b"SHELL" {
        return Err("No shell payload found".into());
    }

    let metadata_size = u32::from_le_bytes(footer[0..4].try_into()?) as u64;
    debug!("Metadata size: {}", metadata_size);
    
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
    debug!("Number of files in payload: {}", num_files);

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
        .ok_or("Invalid payload size")?;

    file.seek(SeekFrom::Start(payload_start))?;
    
    let key = get_aes_key();
    let cipher = Aes256Gcm::new(&key.into());
    let mut results = Vec::new();

    for (name, size, iv) in entries {
        let mut encrypted_data = vec![0u8; size as usize];
        file.read_exact(&mut encrypted_data)?;
        
        let nonce = Nonce::from_slice(&iv);
        let plaintext = cipher.decrypt(nonce, encrypted_data.as_ref())
            .map_err(|e| format!("Decryption failed: {:?}", e))?;
        
        debug!("Decrypted entry: {}", name);
        results.push((name, plaintext));
    }
    debug!("Successfully decrypted {} entries", results.len());
    
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
    
    // 3. Create DexClassLoader
    let dex_path_j = env.new_string(&joined_paths)?;
    let libs_dir_j = env.new_string(&libs_dir)?;
    let null_j = JObject::null();
    
    let loader_cls = env.find_class("dalvik/system/DexClassLoader")?;
    let loader = env.new_object(
        loader_cls,
        "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/ClassLoader;)V",
        &[
            JValue::Object(&dex_path_j.into()), 
            JValue::Object(&null_j),
            JValue::Object(&libs_dir_j.into()),
            JValue::Object(target_loader)
        ]
    )?;
    
    inject_dex_elements(env, &loader, target_loader)?;

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
