use jni::JNIEnv;
use jni::objects::{JClass, JObject, JString, JValue, JByteArray};
use jni::sys::{jint, JNI_VERSION_1_6};
use aes_gcm::{
    aead::{Aead, KeyInit, Payload},
    Aes256Gcm, Nonce // Or `Aes128Gcm`
};
use std::ffi::{CStr, CString};
use std::os::raw::c_void;
use std::fs::File;
use std::io::{Read, Write};
use std::path::Path;

// Hardcoded key for demonstration (in production, use white-box cryptography or other obfuscation)
mod config;
use config::AES_KEY;

#[no_mangle]
pub extern "system" fn JNI_OnLoad(vm: jni::JavaVM, _reserved: *mut c_void) -> jint {
    // Basic Anti-Debug: Check TracerPid
    if is_debugger_attached() {
        // Log/Crash/Exit
        // For now, silent exit or crash
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
    let apk_path = match get_package_code_path(&mut env, &context) {
        Ok(path) => path,
        Err(_) => return,
    };
    
    // 2. Extract and decrypt the payload
    let decrypted_dex = match extract_payload(&apk_path) {
        Ok(data) => data,
        Err(_) => return,
    };

    // 3. Load DEX
    let res = if sdk_int >= 26 {
        // Gen 2: InMemoryDexClassLoader
        load_in_memory(&mut env, &context, &decrypted_dex)
    } else {
        // Gen 1: File Landing
        load_file_landing(&mut env, &context, &decrypted_dex)
    };
    
    if let Err(_) = res {
        // Handle error (log it)
    }
}

fn get_package_code_path(env: &mut JNIEnv, context: &JObject) -> Result<String, jni::errors::Error> {
    let package_code_path = env
        .call_method(context, "getPackageCodePath", "()Ljava/lang/String;", &[])?
        .l()?;
    let path_str: String = env.get_string(&package_code_path.into())?.into();
    Ok(path_str)
}

use std::io::{Seek, SeekFrom};

fn extract_payload(path: &str) -> Result<Vec<(String, Vec<u8>)>, Box<dyn std::error::Error>> {
    let mut file = File::open(path)?;
    let file_len = file.metadata()?.len();

    // Footer: [Metadata Size (4)] [Magic "SHELL" (5)]
    let footer_len = 9;
    if file_len < footer_len {
        return Err("File too small".into());
    }

    file.seek(SeekFrom::End(-(footer_len as i64)))?;
    let mut footer = vec![0u8; footer_len as usize];
    file.read_exact(&mut footer)?;

    let magic = &footer[4..9];
    if magic != b"SHELL" {
        return Err("No shell payload found".into());
    }

    let metadata_size = u32::from_le_bytes(footer[0..4].try_into()?) as u64;
    
    // Metadata Block: [N (4)] + [ [NameLen(2)] [Name] [Size(4)] [IV(12)] ] * N
    let metadata_start = file_len - footer_len - metadata_size;
    if metadata_start < 0 {
        return Err("Invalid metadata size".into());
    }

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
    let payload_start = metadata_start - total_encrypted_size;
    if payload_start < 0 {
         return Err("Invalid payload size".into());
    }

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
        
        results.push((name, plaintext));
    }
    
    Ok(results)
}

fn load_in_memory(env: &mut JNIEnv, context: &JObject, file_list: &[(String, Vec<u8>)]) -> Result<(), jni::errors::Error> {
    // 1. Separate DEXs and Libs
    let mut dex_buffers = Vec::new();
    let mut lib_buffers = Vec::new();
    let current_abi = get_current_abi();

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

    // 2. Extract Libs to Cache
    let cache_dir = env.call_method(context, "getCacheDir", "()Ljava/io/File;", &[])?.l()?;
    let path_obj = env.call_method(&cache_dir, "getAbsolutePath", "()Ljava/lang/String;", &[])?.l()?;
    let path_jstr: JString = path_obj.into();
    let cache_path: String = env.get_string(&path_jstr)?.into();
    
    let libs_dir = format!("{}/native_libs", cache_path);
    std::fs::create_dir_all(&libs_dir).unwrap_or(());

    for (filename, data) in lib_buffers {
        let lib_path = format!("{}/{}", libs_dir, filename);
        if let Ok(mut file) = File::create(&lib_path) {
            let _ = file.write_all(data);
        }
    }

    // 3. Create ByteBuffer[] for DEXs
    let byte_buffer_cls = env.find_class("java/nio/ByteBuffer")?;
    let buffer_array = env.new_object_array(dex_buffers.len() as i32, byte_buffer_cls, JObject::null())?;

    for (i, dex_data) in dex_buffers.iter().enumerate() {
        let byte_array = env.byte_array_from_slice(dex_data)?;
        let buffer = env.call_static_method(
            byte_buffer_cls, 
            "wrap", 
            "([B)Ljava/nio/ByteBuffer;", 
            &[JValue::Object(&byte_array.into())]
        )?.l()?;
        
        env.set_object_array_element(&buffer_array, i as i32, buffer)?;
    }

    // 4. Create InMemoryDexClassLoader
    let parent_loader = env.call_method(
        context, 
        "getClassLoader", 
        "()Ljava/lang/ClassLoader;", 
        &[]
    )?.l()?;

    let dex_loader_cls = env.find_class("dalvik/system/InMemoryDexClassLoader")?;

    // Try finding constructor with library search path (API 27+)
    // public InMemoryDexClassLoader (ByteBuffer[] dexBuffers, String librarySearchPath, ClassLoader parent)
    let ctor_sig_with_lib = "([Ljava/nio/ByteBuffer;Ljava/lang/String;Ljava/lang/ClassLoader;)V";
    
    // Check if this constructor exists (roughly check SDK Int or just try)
    // For simplicity, let's try calling it. If it fails, fallback to 2-arg (API 26).
    // Actually JNI calling doesn't throw easily catchable exceptions in Rust without checking.
    // JNI `new_object` will return Err if method not found (or exception thrown).
    
    let libs_dir_j = env.new_string(&libs_dir)?;
    
    let loader_res = env.new_object(
        dex_loader_cls,
        ctor_sig_with_lib,
        &[
            JValue::Object(&buffer_array.into()), 
            JValue::Object(&libs_dir_j.into()),
            JValue::Object(&parent_loader)
        ]
    );

    let loader = match loader_res {
        Ok(l) => l,
        Err(_) => {
            // Fallback to 2-arg constructor (API 26) - Libs won't be loaded automatically
            env.exception_clear();
            env.new_object(
                dex_loader_cls,
                "([Ljava/nio/ByteBuffer;Ljava/lang/ClassLoader;)V",
                &[JValue::Object(&buffer_array.into()), JValue::Object(&parent_loader)]
            )?
        }
    };

    // 5. Replace ClassLoader
    replace_classloader(env, context, &loader)?;
    
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
    
    // 4. Replace ClassLoader
    replace_classloader(env, context, &loader)?;

    Ok(())
}

fn replace_classloader(env: &mut JNIEnv, context: &JObject, new_loader: &JObject) -> Result<(), jni::errors::Error> {
    // context is likely the Application object
    // field mLoadedApk (ContextImpl) -> mPackageInfo (LoadedApk) -> mClassLoader
    
    // Accessing hidden fields requires stepping through reflection carefully or accessing known internal structures.
    // ContextWrapper -> mBase (ContextImpl) -> mPackageInfo (LoadedApk)
    
    // 1. Get mBase from ContextWrapper (Application extends ContextWrapper)
    let context_cls = env.find_class("android/content/ContextWrapper")?;
    let m_base_field = env.get_field_id(context_cls, "mBase", "Landroid/content/Context;")?;
    let m_base = env.get_field(context, &m_base_field)?.l()?;
    
    // 2. Get mPackageInfo from ContextImpl matches LoadedApk
    let context_impl_cls = env.get_object_class(&m_base)?;
    let m_package_info_field = env.get_field_id(context_impl_cls, "mPackageInfo", "Landroid/app/LoadedApk;")?;
    let m_package_info = env.get_field(&m_base, &m_package_info_field)?.l()?;
    
    // 3. Get mClassLoader from LoadedApk
    let loaded_apk_cls = env.get_object_class(&m_package_info)?;
    let m_class_loader_field = env.get_field_id(loaded_apk_cls, "mClassLoader", "Ljava/lang/ClassLoader;")?;
    
    // 4. Set it!
    env.set_field(&m_package_info, &m_class_loader_field, JValue::Object(new_loader))?;
    
    Ok(())
}
