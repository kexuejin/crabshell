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
use config::AES_KEY;

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
    
    // 2. Extract and decrypt the payload
    let decrypted_dex = match extract_payload(&apk_path) {
        Ok(data) => data,
        Err(e) => {
            error!("Failed to extract payload: {:?}", e);
            return;
        }
    };

    // 3. Load DEX
    let res = if sdk_int >= 26 {
        load_in_memory(&mut env, &context, &decrypted_dex)
    } else {
        load_file_landing(&mut env, &context, &decrypted_dex)
    };
    
    if let Err(e) = res {
        error!("native_load_dex failed: {:?}", e);
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

    let decrypted_dex = match extract_payload(&apk_path) {
        Ok(data) => data,
        Err(e) => {
             error!("Failed to extract payload (Provider): {:?}", e);
             return;
        }
    };

    let res = if sdk_int >= 26 {
        load_in_memory(&mut env, &context, &decrypted_dex)
    } else {
        load_file_landing(&mut env, &context, &decrypted_dex)
    };

    if let Err(e) = res {
        error!("nativeLoadDex (Provider) failed: {:?}", e);
        let _ = env.exception_clear();
    }
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
    
    let key = *AES_KEY;
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

fn load_in_memory(env: &mut JNIEnv, context: &JObject, file_list: &[(String, Vec<u8>)]) -> Result<(), jni::errors::Error> {
    info!("load_in_memory called with {} items", file_list.len());
    // 1. Separate DEXs and Libs
    let mut dex_buffers = Vec::new();
    let mut lib_buffers = Vec::new();
    let current_abi = get_current_abi();
    debug!("Current ABI: {}", current_abi);

    // Only extract libs for current ABI
    // Packer stores as "lib/<abi>/libname.so"
    let lib_prefix = format!("lib/{}/", current_abi);

    for (name, data) in file_list {
        if name.ends_with(".dex") {
             dex_buffers.push(data);
        } else if name.starts_with(&lib_prefix) && name.ends_with(".so") {
             // Extract filename
             let filename = name.strip_prefix(&lib_prefix).unwrap_or(name);
             lib_buffers.push((filename, data));
        }
    }

    debug!("Found {} DEXs and {} Libs for current ABI", dex_buffers.len(), lib_buffers.len());

    // 2. Extract Libs to Cache
    debug!("Extracting libs to cache...");
    let cache_dir = env.call_method(context, "getCacheDir", "()Ljava/io/File;", &[])?.l()?;
    let path_obj = env.call_method(&cache_dir, "getAbsolutePath", "()Ljava/lang/String;", &[])?.l()?;
    let path_jstr: JString = path_obj.into();
    let cache_path: String = env.get_string(&path_jstr)?.into();
    
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
        // We still replace classloader if we extracted libs? 
        // Actually, if no DEXs, we might just be loading libs.
        // But replacing classloader with a "null" one is dangerous.
        // Let's just return Ok if no DEXs?
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
    let parent_loader = env.call_method(
        context, 
        "getClassLoader", 
        "()Ljava/lang/ClassLoader;", 
        &[]
    )?.l()?;

    let dex_loader_cls = env.find_class("dalvik/system/InMemoryDexClassLoader")?;
    let buffer_array_obj: JObject = buffer_array.into();

    // Try finding constructor with library search path (API 27+)
    // public InMemoryDexClassLoader (ByteBuffer[] dexBuffers, String librarySearchPath, ClassLoader parent)
    let ctor_sig_with_lib = "([Ljava/nio/ByteBuffer;Ljava/lang/String;Ljava/lang/ClassLoader;)V";
    
    let libs_dir_j = env.new_string(&libs_dir)?;
    let libs_dir_obj: JObject = libs_dir_j.into();
    
    let loader_res = env.new_object(
        &dex_loader_cls,
        ctor_sig_with_lib,
        &[
            JValue::Object(&buffer_array_obj),
            JValue::Object(&libs_dir_obj),
            JValue::Object(&parent_loader)
        ]
    );

    let loader = match loader_res {
        Ok(l) => l,
        Err(_) => {
            // Fallback to 2-arg constructor (API 26) - Libs won't be loaded automatically
            let _ = env.exception_clear();
            env.new_object(
                &dex_loader_cls,
                "([Ljava/nio/ByteBuffer;Ljava/lang/ClassLoader;)V",
                &[JValue::Object(&buffer_array_obj), JValue::Object(&parent_loader)]
            )?
        }
    };

    // 5. Inject Dex Elements into Parent Loader (Hotfix style)
    // Instead of replacing the loader, we patch the existing one.
    inject_dex_elements(env, &loader, &parent_loader)?;
    
    // Diagnostic
    let test_class_name = "javax.inject.Provider";
    let test_jstr = env.new_string(test_class_name)?;
    // Try loading from parent now (since we injected)
    match env.call_method(&parent_loader, "loadClass", "(Ljava/lang/String;)Ljava/lang/Class;", &[JValue::Object(&test_jstr.into())]) {
        Ok(_) => info!("shell: Diagnostic: Successfully loaded {} from PARENT loader (Injection verified)", test_class_name),
        Err(_) => {
            let _ = env.exception_clear();
            warn!("shell: Diagnostic: Failed to load {} from PARENT loader", test_class_name);
        }
    }

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

fn load_file_landing(env: &mut JNIEnv, context: &JObject, file_list: &[(String, Vec<u8>)]) -> Result<(), jni::errors::Error> {
    // 1. Get cache dir
    let cache_dir = env.call_method(context, "getCacheDir", "()Ljava/io/File;", &[])?.l()?;
    
    let path_obj = env.call_method(&cache_dir, "getAbsolutePath", "()Ljava/lang/String;", &[])?.l()?;
    let path_jstr: JString = path_obj.into();
    let cache_path: String = env.get_string(&path_jstr)?.into();
    
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
    
    // Join paths with :
    let joined_paths = dex_paths.join(":");
    
    // 3. Create DexClassLoader
    // public DexClassLoader (String dexPath, String optimizedDirectory, String librarySearchPath, ClassLoader parent)
    let dex_path_j = env.new_string(&joined_paths)?;
    let libs_dir_j = env.new_string(&libs_dir)?;
    let null_j = JObject::null();
    let parent_loader = env.call_method(context, "getClassLoader", "()Ljava/lang/ClassLoader;", &[])?.l()?;
    
    let loader_cls = env.find_class("dalvik/system/DexClassLoader")?;
    let loader = env.new_object(
        loader_cls,
        "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/ClassLoader;)V",
        &[
            JValue::Object(&dex_path_j.into()), 
            JValue::Object(&null_j), // optimizedDirectory (deprecated/null)
            JValue::Object(&libs_dir_j.into()), // librarySearchPath
            JValue::Object(&parent_loader)
        ]
    )?;
    
    // 4. Inject Dex Elements (Hotfix)
    inject_dex_elements(env, &loader, &parent_loader)?;

    Ok(())
}

fn inject_dex_elements(env: &mut JNIEnv, source_loader: &JObject, target_loader: &JObject) -> Result<(), jni::errors::Error> {
    info!("shell: inject_dex_elements starting...");
    
    // 1. Get pathList from source
    let source_path_list = env.get_field(source_loader, "pathList", "Ldalvik/system/DexPathList;")?.l()?;

    // 2. Get pathList from target
    let target_path_list = env.get_field(target_loader, "pathList", "Ldalvik/system/DexPathList;")?.l()?;

    // 3. Get dexElements from source
    let source_elements_obj = env.get_field(source_path_list, "dexElements", "[Ldalvik/system/DexPathList$Element;")?.l()?;
    let source_array: JObjectArray = source_elements_obj.into();

    // 4. Get dexElements from target
    let target_elements_obj = env.get_field(&target_path_list, "dexElements", "[Ldalvik/system/DexPathList$Element;")?.l()?;
    let target_array: JObjectArray = target_elements_obj.into();
    
    // 5. Concatenate arrays (Target + Source) or (Source + Target)
    
    let source_len = env.get_array_length(&source_array)?;
    let target_len = env.get_array_length(&target_array)?;
    debug!("shell: Merging {} new elements into {} existing elements", source_len, target_len);

    let element_cls = env.find_class("dalvik/system/DexPathList$Element")?;
    
    let total_len = source_len + target_len;
    let new_array = env.new_object_array(total_len, element_cls, JObject::null())?;
    
    // Copy target (original) first
    for i in 0..target_len {
        let elem = env.get_object_array_element(&target_array, i)?;
        env.set_object_array_element(&new_array, i, elem)?;
    }
    
    // Append source (new)
    for i in 0..source_len {
        let elem = env.get_object_array_element(&source_array, i)?;
        env.set_object_array_element(&new_array, target_len + i, elem)?;
    }
    
    // 6. Set dexElements on target pathList
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
