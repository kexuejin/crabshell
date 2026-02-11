import argparse
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from typing import Optional, Tuple

RUST_SHELL_DIR = "loader/app/src/main/rust"
PACKER_DIR = "packer"
SHELL_PROJECT_DIR = "loader"
APKTOOL_VERSION = os.environ.get("APKTOOL_VERSION", "2.11.1")
APKTOOL_JAR_URL = f"https://github.com/iBotPeaches/Apktool/releases/download/v{APKTOOL_VERSION}/apktool_{APKTOOL_VERSION}.jar"
from pathlib import Path
ANDROID_NS = "http://schemas.android.com/apk/res/android"
ANDROID_NAME = f"{{{ANDROID_NS}}}name"
ANDROID_VALUE = f"{{{ANDROID_NS}}}value"
ANDROID_AUTHORITIES = f"{{{ANDROID_NS}}}authorities"
ANDROID_EXPORTED = f"{{{ANDROID_NS}}}exported"
ANDROID_INIT_ORDER = f"{{{ANDROID_NS}}}initOrder"


def is_aab_file(path: str) -> bool:
    """Check if file is an AAB by looking for BundleConfig.pb"""
    try:
        with zipfile.ZipFile(path, 'r') as z:
            return 'BundleConfig.pb' in z.namelist()
    except:
        return False


def find_bundletool() -> str:
    """Find bundletool.jar or download it"""
    bundletool_jar = os.path.expanduser('~/bundletool.jar')
    if os.path.exists(bundletool_jar):
        return bundletool_jar
    
    # Download if not found
    print("Downloading bundletool...")
    url = 'https://github.com/google/bundletool/releases/download/1.17.2/bundletool-all-1.17.2.jar'
    urllib.request.urlretrieve(url, bundletool_jar)
    return bundletool_jar


def convert_aab_to_apk(aab_path: str, output_apk: str, temp_dir: str) -> str:
    """Convert AAB to universal APK using bundletool"""
    bundletool = find_bundletool()
    
    # Build universal APKs (unsigned for now)
    apks_path = os.path.join(temp_dir, 'temp.apks')
    cmd = [
        'java', '-jar', bundletool,
        'build-apks',
        '--bundle', aab_path,
        '--output', apks_path,
        '--mode', 'universal'
    ]
    subprocess.check_call(cmd)
    
    # Extract universal APK from .apks
    with zipfile.ZipFile(apks_path, 'r') as z:
        z.extract('universal.apk', temp_dir)
    
    universal_apk = os.path.join(temp_dir, 'universal.apk')
    shutil.move(universal_apk, output_apk)
    
    return output_apk


def convert_apk_to_aab(apk_path: str, output_aab: str, original_aab: str, temp_dir: str) -> str:
    """Convert hardened APK back to AAB format"""
    # Extract original AAB structure
    aab_extract_dir = os.path.join(temp_dir, 'aab_structure')
    os.makedirs(aab_extract_dir, exist_ok=True)
    
    with zipfile.ZipFile(original_aab, 'r') as z:
        z.extractall(aab_extract_dir)
    
    # Extract hardened APK
    apk_extract_dir = os.path.join(temp_dir, 'hardened_apk')
    os.makedirs(apk_extract_dir, exist_ok=True)
    
    with zipfile.ZipFile(apk_path, 'r') as z:
        z.extractall(apk_extract_dir)
    
    # Replace base module contents with hardened APK contents
    base_dir = os.path.join(aab_extract_dir, 'base')
    
    # Copy hardened DEX files
    base_dex_dir = os.path.join(base_dir, 'dex')
    if os.path.exists(base_dex_dir):
        shutil.rmtree(base_dex_dir)
    os.makedirs(base_dex_dir, exist_ok=True)
    
    for item in os.listdir(apk_extract_dir):
        if item.endswith('.dex'):
            src = os.path.join(apk_extract_dir, item)
            dst = os.path.join(base_dex_dir, item)
            shutil.copy2(src, dst)
    
    # Copy hardened native libraries
    apk_lib_dir = os.path.join(apk_extract_dir, 'lib')
    if os.path.exists(apk_lib_dir):
        base_lib_dir = os.path.join(base_dir, 'lib')
        if os.path.exists(base_lib_dir):
            shutil.rmtree(base_lib_dir)
        shutil.copytree(apk_lib_dir, base_lib_dir)
    
    # Copy hardened assets
    apk_assets_dir = os.path.join(apk_extract_dir, 'assets')
    if os.path.exists(apk_assets_dir):
        base_assets_dir = os.path.join(base_dir, 'assets')
        if os.path.exists(base_assets_dir):
            shutil.rmtree(base_assets_dir)
        shutil.copytree(apk_assets_dir, base_assets_dir)
    
    # NOTE: We do NOT copy the manifest from the hardened APK
    # The original AAB manifest is already patched (from the AAB-to-APK conversion)
    # and is in the correct protobuf format that bundletool expects.
    # The hardened APK has a binary XML manifest which is incompatible with AAB format.
    
    # Rebuild AAB
    with zipfile.ZipFile(output_aab, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(aab_extract_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, aab_extract_dir)
                z.write(file_path, arcname)
    
    return output_aab


def generate_config(config_path: str, key_bytes: bytes, payload_hash: bytes = None, signature_hash: bytes = None):
    # key_bytes is the real key (32 bytes)
    # Generate a random mask (KEY_PART_1)
    mask_bytes = os.urandom(32)
    
    # internal key (KEY_PART_2) = real_key XOR mask
    encrypted_key_bytes = bytearray(32)
    for i in range(32):
        encrypted_key_bytes[i] = key_bytes[i] ^ mask_bytes[i]
        
    mask_str = ", ".join([f"0x{b:02x}" for b in mask_bytes])
    encrypted_key_str = ", ".join([f"0x{b:02x}" for b in encrypted_key_bytes])
    
    # Generate a random XOR key for string obfuscation
    string_xor_key = os.urandom(32)
    string_xor_key_str = ", ".join([f"0x{b:02x}" for b in string_xor_key])

    # List of sensitive strings to obfuscate
    sensitive_strings = {
        "PROC_STATUS": "/proc/self/status",
        "TRACER_PID": "TracerPid:",
        "PAYLOAD_NAME": "assets/kapp_payload.bin",
        "LOG_TAG": "KAppShell",
        # Logic strings
        "ERR_NO_PAYLOAD": "No shell payload found",
        "ERR_INVALID_CHECKSUM": "Invalid checksum",
        "MSG_NATIVE_LOAD_DEX": "nativeLoadDex (Application) called for SDK {}",
        "MSG_OPEN_APK": "Opening APK at {}",
        "MAGIC_SHELL": "SHELL",
        # New strings for better protection
        "DEBUG_DETECTED": "Debugger detected",
        "EXITING": "Exiting...",
        "PTRACE_FAILED": "ptrace failed with errno {}",
        "PTRACE_RESTRICTED": "Ptrace TRACEME restricted by system (errno 13).",
        "PTRACE_SUCCESS": "Ptrace TRACEME successful (no debugger attached).",
        "TRACER_PID_LOG": "TracerPid: {}"
    }

    strings_content = "// Auto-generated by pack.py. DO NOT EDIT.\n\n"
    for name, s in sensitive_strings.items():
        s_bytes = s.encode("utf-8")
        obfuscated = bytearray()
        for i in range(len(s_bytes)):
            obfuscated.append(s_bytes[i] ^ string_xor_key[i % 32])
        obs_str = ", ".join([f"0x{b:02x}" for b in obfuscated])
        strings_content += f"pub const {name}: &[u8] = &[{obs_str}];\n"

    config_content = f"""
// Auto-generated by pack.py. DO NOT EDIT.

// KEY_PART_1 (Mask)
const KEY_PART_1: [u8; 32] = [{mask_str}];

// KEY_PART_2 (Masked Key)
const KEY_PART_2: [u8; 32] = [{encrypted_key_str}];

// STRING_XOR_KEY
pub const STRING_XOR_KEY: [u8; 32] = [{string_xor_key_str}];

#[inline(always)]
pub fn get_aes_key() -> [u8; 32] {{
    let mut key = [0u8; 32];
    for i in 0..32 {{
        key[i] = KEY_PART_1[i] ^ KEY_PART_2[i];
    }}
    key
}}

pub const PAYLOAD_HASH: [u8; 32] = [{", ".join([f"0x{b:02x}" for b in (payload_hash or b'\x00'*32)])}];
pub const EXPECTED_SIGNATURE_HASH: [u8; 32] = [{", ".join([f"0x{b:02x}" for b in (signature_hash or b'\x00'*32)])}];
"""
    output_dir = os.path.dirname(config_path)
    os.makedirs(output_dir, exist_ok=True)
    with open(config_path, "w") as f:
        f.write(config_content)
        
    strings_config_path = os.path.join(output_dir, "strings_config.rs")
    with open(strings_config_path, "w") as f:
        f.write(strings_content)
        
    print(f"Generated config -> {config_path}")
    print(f"Generated strings -> {strings_config_path}")

def get_apk_signature_hash(apk_path: str) -> Optional[bytes]:
    apksigner = find_android_build_tool("apksigner")
    if not apksigner:
        print("Warning: apksigner not found, cannot get signature hash.")
        return None
    
    try:
        output = subprocess.check_output([apksigner, "verify", "--print-certs", apk_path], stderr=subprocess.STDOUT).decode()
        for line in output.splitlines():
            if "SHA-256 digest:" in line:
                hash_str = line.split(":", 1)[1].strip()
                return bytes.fromhex(hash_str)
    except Exception as e:
        print(f"Warning: Failed to get signature hash: {e}")
    return None

def calculate_sha256(file_path: str) -> bytes:
    import hashlib
    with open(file_path, "rb") as f:
        return hashlib.sha256(f.read()).digest()


def ensure_tool_exists(tool: str):
    if shutil.which(tool) is None:
        raise RuntimeError(f"Required tool not found: {tool}")


def sdk_roots() -> list[str]:
    roots = [
        os.environ.get("ANDROID_SDK_ROOT"),
        os.environ.get("ANDROID_HOME"),
        os.path.expanduser("~/Library/Android/sdk"),
        "/usr/local/lib/android/sdk",
    ]
    result = []
    for root in roots:
        if root and os.path.isdir(root):
            result.append(root)
    return result


def find_android_build_tool(tool_name: str) -> Optional[str]:
    in_path = shutil.which(tool_name)
    if in_path:
        return in_path

    candidates: list[Tuple[Tuple[int, ...], str]] = []
    for root in sdk_roots():
        build_tools_dir = os.path.join(root, "build-tools")
        if not os.path.isdir(build_tools_dir):
            continue

        for version in os.listdir(build_tools_dir):
            tool_path = os.path.join(build_tools_dir, version, tool_name)
            if os.path.isfile(tool_path) and os.access(tool_path, os.X_OK):
                parsed = tuple(int(p) if p.isdigit() else 0 for p in version.replace("-", ".").split("."))
                candidates.append((parsed, tool_path))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def ensure_apktool_cmd() -> list[str]:
    apktool = shutil.which("apktool")
    if apktool:
        return [apktool]

    java = shutil.which("java")
    if not java:
        raise RuntimeError("apktool not found and java not available for apktool jar fallback")

    codex_home = os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex"))
    tools_dir = os.path.join(codex_home, "tools")
    os.makedirs(tools_dir, exist_ok=True)
    apktool_jar = os.path.join(tools_dir, f"apktool-{APKTOOL_VERSION}.jar")

    if not os.path.exists(apktool_jar):
        print(f"apktool not found, downloading apktool jar {APKTOOL_VERSION}...")
        try:
            urllib.request.urlretrieve(APKTOOL_JAR_URL, apktool_jar)
        except Exception as error:
            raise RuntimeError(f"Failed to download apktool from {APKTOOL_JAR_URL}: {error}")

    return [java, "-jar", apktool_jar]


def build_packer():
    print("Building Packer...")
    env = os.environ.copy()
    cargo_bin = os.path.expanduser("~/.cargo/bin")
    if cargo_bin not in env.get("PATH", ""):
        env["PATH"] = f"{cargo_bin}:{env.get('PATH', '')}"
    subprocess.check_call(["cargo", "build", "--release"], cwd=PACKER_DIR, env=env)


def patch_shell_loader_constants(original_app: str, original_factory: str):
    print(f"Patching Shell loader constants: App={original_app}, Factory={original_factory}")
    factory_java = os.path.join(SHELL_PROJECT_DIR, "app/src/main/java/com/kapp/shell/ShellComponentFactory.java")
    if not os.path.exists(factory_java):
        print(f"Warning: {factory_java} not found, skipping constant patching")
        return

    with open(factory_java, "r") as f:
        content = f.read()

    if original_app:
        content = content.replace("REPLACE_ORIGINAL_APP", original_app)
    if original_factory:
        content = content.replace("REPLACE_ORIGINAL_FACTORY", original_factory)

    with open(factory_java, "w") as f:
        f.write(content)


def build_shell():
    print("Building Shell (Native)...")
    env = os.environ.copy()
    
    cargo_bin = os.path.expanduser("~/.cargo/bin")
    if cargo_bin not in env.get("PATH", ""):
        env["PATH"] = f"{cargo_bin}:{env.get('PATH', '')}"

    if "ANDROID_NDK_HOME" in env:
        ndk_home = env["ANDROID_NDK_HOME"]
        if not os.path.exists(ndk_home):
            print(f"Warning: ANDROID_NDK_HOME is set to '{ndk_home}' but that directory does not exist. Ignoring.")
            del env["ANDROID_NDK_HOME"]

    if "ANDROID_NDK_HOME" not in env:
        print("ANDROID_NDK_HOME not set or invalid. Attempting to detect...")
        possible_paths = [
            os.path.expanduser("~/Library/Android/sdk/ndk"),
            os.path.join(env.get("ANDROID_HOME", ""), "ndk"),
            os.path.join(env.get("ANDROID_SDK_ROOT", ""), "ndk"),
            "/usr/local/lib/android/sdk/ndk",
            os.path.expanduser("~/Library/Android/sdk/ndk-bundle"),
        ]

        found_ndk = None
        for path in possible_paths:
            if path and os.path.isdir(path):
                versions = sorted(
                    [
                        d
                        for d in os.listdir(path)
                        if os.path.isdir(os.path.join(path, d)) and d and d[0].isdigit()
                    ],
                    key=lambda version: version.split("."),
                )
                if versions:
                    found_ndk = os.path.join(path, versions[-1])
                    break
                if os.path.exists(os.path.join(path, "sysroot")):
                    found_ndk = path
                    break

        if found_ndk:
            print(f"Detected NDK at: {found_ndk}")
            env["ANDROID_NDK_HOME"] = found_ndk
        else:
            raise RuntimeError(
                "Could not detect Android NDK. Please set ANDROID_NDK_HOME to your NDK installation."
            )

    subprocess.check_call(
        ["cargo", "ndk", "-t", "arm64-v8a", "-t", "armeabi-v7a", "-o", "../jniLibs", "build", "--release"],
        cwd=RUST_SHELL_DIR,
        env=env,
    )

    print("Building Shell (APK)...")
    gradlew = "./gradlew" if os.path.exists(os.path.join(SHELL_PROJECT_DIR, "gradlew")) else "gradle"
    subprocess.check_call([gradlew, "assembleRelease"], cwd=SHELL_PROJECT_DIR, env=env)

    print("Building Packer...")
    subprocess.check_call(["cargo", "build", "--release"], cwd=PACKER_DIR, env=env)


def get_shell_apk_path() -> str:
    shell_apk = os.path.join(
        SHELL_PROJECT_DIR,
        "app",
        "build",
        "outputs",
        "apk",
        "release",
        "app-release-unsigned.apk",
    )
    if not os.path.exists(shell_apk):
        raise FileNotFoundError(f"Shell APK not found at {shell_apk}")
    return shell_apk


def load_string_resources(res_dir: str) -> dict[str, str]:
    values_dir = Path(res_dir)
    result: dict[str, str] = {}
    if not values_dir.exists():
        return result

    for values_path in values_dir.glob("values*/strings.xml"):
        try:
            tree = ET.parse(values_path)
            root = tree.getroot()
        except Exception:
            continue

        for node in root.findall("string"):
            name = node.attrib.get("name")
            if not name:
                continue
            text = "".join(node.itertext()) if node.text is not None else ""
            if text:
                result[name] = text

    return result


def inline_manifest_meta_data_string_values(application: ET.Element, string_table: dict[str, str]):
    if not string_table:
        return

    for element in application.iter():
        value = element.attrib.get(ANDROID_VALUE)
        if not value:
            continue

        if value.startswith("@string/"):
            name = value.split("/", 1)[1]
            resolved = string_table.get(name)
            if resolved:
                element.set(ANDROID_VALUE, resolved)


def ensure_bootstrap_provider(application: ET.Element, provider_class: str):
    for provider in application.findall("provider"):
        if provider.attrib.get(ANDROID_NAME) == provider_class:
            return

    provider = ET.SubElement(application, "provider")
    provider.set(ANDROID_NAME, provider_class)
    provider.set(ANDROID_AUTHORITIES, "${applicationId}.kapp-bootstrap")
    provider.set(ANDROID_EXPORTED, "false")
    provider.set(ANDROID_INIT_ORDER, "1000")


def decode_and_patch_target_manifest(target_apk: str, temp_dir: str) -> Tuple[str, Optional[str], str, str]:
    apktool_cmd = ensure_apktool_cmd()

    decoded_dir = os.path.join(temp_dir, "target_decoded")
    patched_manifest = os.path.join(temp_dir, "AndroidManifest_patched.xml")

    print("Decoding target APK with apktool...")
    subprocess.check_call(apktool_cmd + ["d", "-f", target_apk, "-o", decoded_dir])

    print("Patching decoded AndroidManifest.xml...")
    manifest_path = os.path.join(decoded_dir, "AndroidManifest.xml")
    res_dir = os.path.join(decoded_dir, "res")
    
    provider_class = "com.kapp.shell.BootstrapProvider"
    shell_factory_class = "com.kapp.shell.ShellComponentFactory"
    meta_key = "kapp.original_application"
    factory_meta_key = "kapp.original_factory"

    ET.register_namespace("android", ANDROID_NS)
    tree = ET.parse(manifest_path)
    root = tree.getroot()

    application = root.find("application")
    if application is None:
        raise RuntimeError("No <application> element found in AndroidManifest.xml")

    android_app_factory = f"{{{ANDROID_NS}}}appComponentFactory"
    original_factory = application.attrib.get(android_app_factory, "")
    if original_factory:
        print(f"Original appComponentFactory: '{original_factory}'")
        application.set(android_app_factory, shell_factory_class)

    original_app = application.attrib.get(ANDROID_NAME, "")
    print(f"Original application: '{original_app}'")
    
    # Replace the application class with our shell
    application.set(ANDROID_NAME, "com.kapp.shell.ShellApplication")
    
    # Strip debuggable flag to ensure ptrace works and app is hardened
    if f"{{{ANDROID_NS}}}debuggable" in application.attrib:
        print("Stripping android:debuggable attribute...")
        del application.attrib[f"{{{ANDROID_NS}}}debuggable"]

    # Inject original app metadata
    original_app_meta = None
    original_factory_meta = None
    for child in application.findall("meta-data"):
        name = child.attrib.get(ANDROID_NAME)
        if name == meta_key:
            original_app_meta = child
        elif name == factory_meta_key:
            original_factory_meta = child

    if original_app_meta is None:
        original_app_meta = ET.SubElement(application, "meta-data")
    original_app_meta.set(ANDROID_NAME, meta_key)
    original_app_meta.set(ANDROID_VALUE, original_app)

    if original_factory:
        if original_factory_meta is None:
            original_factory_meta = ET.SubElement(application, "meta-data")
        original_factory_meta.set(ANDROID_NAME, factory_meta_key)
        original_factory_meta.set(ANDROID_VALUE, original_factory)

    ensure_bootstrap_provider(application, provider_class)

    if res_dir and os.path.exists(res_dir):
        strings = load_string_resources(res_dir)
        inline_manifest_meta_data_string_values(application, strings)

    tree.write(manifest_path, encoding="utf-8", xml_declaration=True)

    print("Rebuilding decoded APK with apktool to get patched binary AndroidManifest.xml...")
    manifest_built_apk = os.path.join(temp_dir, "manifest-only.apk")
    subprocess.check_call(apktool_cmd + ["b", decoded_dir, "-o", manifest_built_apk])

    # Extract compiled binary AndroidManifest.xml from rebuilt minimal APK
    import zipfile

    resources_arsc = os.path.join(temp_dir, "resources.arsc")

    with zipfile.ZipFile(manifest_built_apk, "r") as zf:
        with zf.open("AndroidManifest.xml") as mf, open(patched_manifest, "wb") as out:
            out.write(mf.read())
        
        try:
            with zf.open("resources.arsc") as rsc, open(resources_arsc, "wb") as out:
                out.write(rsc.read())
        except KeyError:
            print("Warning: resources.arsc not found in rebuilt APK.")
            resources_arsc = None

    # We do NOT want to use the rebuilt resources.arsc because it might have a different
    # string pool than the valid binary XML files we are copying from the original APK.
    # Mixing rebuilt ARSC with original binary XMLs causes Resources$NotFoundException.
    # So we return None for resources_arsc to force packer to use the original one.
    return patched_manifest, None, original_app, original_factory


def extract_keep_classes_from_decoded_manifest(decoded_dir: str) -> list[str]:
    manifest_path = os.path.join(decoded_dir, "AndroidManifest.xml")
    if not os.path.exists(manifest_path):
        return []

    try:
        tree = ET.parse(manifest_path)
        root = tree.getroot()
    except Exception:
        return []

    package_name = root.attrib.get("package", "")
    android_name = f"{{{ANDROID_NS}}}name"
    android_app_factory = f"{{{ANDROID_NS}}}appComponentFactory"

    application = root.find("application")
    if application is None:
        return []

    values = []

    # We generally only need to keep the appComponentFactory in plaintext because 
    # the system loads it before our ShellApplication. 
    # BUT with ShellComponentFactory in the loader, we don't need to keep the target's factory.
    # factory = application.attrib.get(android_app_factory, "")
    # if factory:
    #     values.append(factory.strip())

    deduped = []
    seen = set()
    for item in values:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped


def extract_keep_prefixes(keep_classes: list[str]) -> list[str]:
    prefixes = []
    seen = set()
    for class_name in keep_classes:
        parts = class_name.split('.')
        if len(parts) >= 2:
            prefix = '.'.join(parts[:-1])
            if prefix not in seen:
                prefixes.append(prefix)
                seen.add(prefix)
    return prefixes


def pack_apk(
    target_apk: str,
    output_apk: str,
    bootstrap_apk: str,
    patched_manifest: str,
    keep_classes: list[str],
    keep_prefixes: list[str],
    keep_libs: list[str],
    encrypt_assets: list[str],
    signing_config: Tuple[str, str, str],
    key_bytes: bytes,
    resources_arsc: Optional[str] = None,
):
    packer_bin = os.path.join(PACKER_DIR, "target", "release", "packer")
    bootstrap_lib_dir = os.path.join(SHELL_PROJECT_DIR, "app", "src", "main", "jniLibs")

    if not os.path.exists(bootstrap_lib_dir):
        raise FileNotFoundError(f"Bootstrap libs directory not found at {bootstrap_lib_dir}")

    print(f"Packing {target_apk} using target-preserving mode...")
    cmd = [
        packer_bin,
        "--target",
        target_apk,
        "--output",
        output_apk,
        "--bootstrap-apk",
        bootstrap_apk,
        "--bootstrap-lib-dir",
        bootstrap_lib_dir,
        "--patched-manifest",
        patched_manifest,
    ]

    if resources_arsc:
        cmd.extend(["--resources", resources_arsc])

    for keep_class in keep_classes:
        cmd.extend(["--keep-class", keep_class])

    for keep_prefix in keep_prefixes:
        cmd.extend(["--keep-prefix", keep_prefix])

    for keep_lib in keep_libs:
        cmd.extend(["--keep-lib", keep_lib])

    if encrypt_assets:
        for asset_pattern in encrypt_assets:
            cmd.extend(["--encrypt-asset", asset_pattern])

    payload_path = os.path.join(os.path.dirname(output_apk), "kapp_payload.bin")
    
    # Phase 1: Generate payload only
    print("Phase 1: Generating payload for hashing...")
    payload_cmd = cmd + ["--payload-out", payload_path]
    subprocess.check_call(payload_cmd)
    
    payload_hash = calculate_sha256(payload_path)
    print(f"Payload hash: {payload_hash.hex()}")
    
    # Get signing config hash
    signature_hash = None
    keystore, ks_pass, key_alias = signing_config
    if keystore and os.path.exists(keystore):
        try:
            # We can't use apksigner verify on a keystore directly easily, 
            # but we can use keytool to get the cert hash.
            keytool = shutil.which("keytool")
            if keytool:
                out = subprocess.check_output([
                    keytool, "-list", "-v", 
                    "-keystore", keystore, 
                    "-storepass", ks_pass, 
                    "-alias", key_alias
                ]).decode()
                for line in out.splitlines():
                    if "SHA256:" in line:
                        hash_str = line.split(":", 1)[1].strip().replace(":", "")
                        signature_hash = bytes.fromhex(hash_str)
                        break
        except Exception as e:
            print(f"Warning: Failed to get signature hash from keystore: {e}")

    if not signature_hash:
        print("Warning: Could not determine signature hash. Using dummy value.")
        signature_hash = b'\x00' * 32

    # Re-generate configs with hashes
    generate_config(os.path.join(RUST_SHELL_DIR, "src", "config.rs"), key_bytes, payload_hash, signature_hash)
    generate_config(os.path.join(PACKER_DIR, "src", "config.rs"), key_bytes, payload_hash, signature_hash)
    
    # Re-build shell with new config
    build_shell()
    
    # Phase 2: Final pack using pre-generated payload
    print("Phase 2: Final packing...")
    final_cmd = cmd + ["--payload-in", payload_path]
    subprocess.check_call(final_cmd)


def sign_apk(apk_path, keystore, ks_pass, key_alias):
    print(f"Signing {apk_path}...")
    if ks_pass.startswith("pass:"):
        ks_pass = ks_pass[len("pass:"):]

    apksigner = find_android_build_tool("apksigner")
    if not apksigner:
        raise RuntimeError("apksigner not found in PATH or Android SDK build-tools")

    cmd = [
        apksigner,
        "sign",
        "--ks",
        keystore,
        "--ks-pass",
        f"pass:{ks_pass}",
    ]
    if key_alias:
        cmd.extend(["--ks-key-alias", key_alias])
    cmd.append(apk_path)

    subprocess.check_call(cmd)


def get_default_debug_signing() -> Tuple[str, str, str]:
    debug_keystore = os.path.expanduser("~/.android/debug.keystore")
    debug_alias = "androiddebugkey"
    debug_password = "android"

    if not os.path.exists(debug_keystore):
        ensure_tool_exists("keytool")
        os.makedirs(os.path.dirname(debug_keystore), exist_ok=True)
        print(f"Debug keystore not found, generating: {debug_keystore}")
        subprocess.check_call(
            [
                "keytool",
                "-genkeypair",
                "-v",
                "-keystore",
                debug_keystore,
                "-storepass",
                debug_password,
                "-alias",
                debug_alias,
                "-keypass",
                debug_password,
                "-dname",
                "CN=Android Debug,O=Android,C=US",
                "-keyalg",
                "RSA",
                "-keysize",
                "2048",
                "-validity",
                "10000",
            ]
        )

    return debug_keystore, debug_password, debug_alias


def resolve_signing(
    keystore: Optional[str], ks_pass: Optional[str], key_alias: Optional[str]
) -> Tuple[str, str, Optional[str]]:
    if keystore and ks_pass:
        return keystore, ks_pass, key_alias

    print("No signing config provided. Falling back to Android debug keystore.")
    return get_default_debug_signing()


def load_config(config_path):
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            return json.load(f)
    return {}


def main():
    parser = argparse.ArgumentParser(description="CrabShell Packer Automation Script")
    parser.add_argument("--config", default="kapp-config.json", help="Path to config file")
    parser.add_argument("--target", help="Path to the target APK to pack")
    parser.add_argument("--output", default="protected.apk", help="Output APK path")
    parser.add_argument("--keystore", help="Path to keystore for signing")
    parser.add_argument("--ks-pass", help="Keystore password")
    parser.add_argument("--key-alias", help="Key alias")
    parser.add_argument("--no-sign", action="store_true", help="Skip APK signing")
    parser.add_argument("--skip-build", action="store_true", help="Skip building packer and shell")
    parser.add_argument("--keep-class", action="append", help="Class names to keep in plaintext (can be specified multiple times)")
    parser.add_argument("--keep-prefix", action="append", help="Package prefixes to keep in plaintext (can be specified multiple times)")
    parser.add_argument("--keep-lib", action="append", help="Library names (without lib prefix or .so) to keep in plaintext (can be specified multiple times)")
    parser.add_argument("--encrypt-asset", action="append", help="Pattern of assets to encrypt (e.g. assets/*.js)")
    parser.add_argument("--output-format", choices=['auto', 'apk', 'aab'], default='auto',
                       help="Output format (auto=same as input, apk=force APK, aab=force AAB)")

    args = parser.parse_args()

    config = load_config(args.config)

    target = args.target or config.get("target")
    output = args.output if args.output != "protected.apk" else config.get("output", "protected.apk")
    keystore = args.keystore or config.get("keystore")
    ks_pass = args.ks_pass or config.get("ks_pass")
    key_alias = args.key_alias or config.get("key_alias")
    no_sign = args.no_sign or config.get("no_sign", False)
    skip_build = args.skip_build or config.get("skip_build", False)

    if not target:
        print("Error: Target APK not specified (use --target or config file).")
        return

    # Normalize output path. If user passes a directory, place a default file inside it.
    if os.path.isdir(output) or output.endswith(os.sep):
        target_base = os.path.splitext(os.path.basename(target))[0]
        output = os.path.join(output, f"{target_base}-protected.apk")

    output_parent = os.path.dirname(output)
    if output_parent:
        os.makedirs(output_parent, exist_ok=True)

    key_bytes = secrets.token_bytes(32)
    # Initial config generation for packer build
    generate_config(os.path.join(RUST_SHELL_DIR, "src", "config.rs"), key_bytes)
    generate_config(os.path.join(PACKER_DIR, "src", "config.rs"), key_bytes)

    # Detect AAB input and determine output format
    is_aab_input = is_aab_file(target)
    output_format = args.output_format
    
    # Auto-detect output format
    if output_format == 'auto':
        output_format = 'aab' if is_aab_input else 'apk'
    
    # Ensure output extension matches format
    if output_format == 'aab' and not output.endswith('.aab'):
        output = output.replace('.apk', '.aab')
    elif output_format == 'apk' and not output.endswith('.apk'):
        output = output.replace('.aab', '.apk')

    with tempfile.TemporaryDirectory(prefix="kapp-") as temp_dir:
        original_aab_path = None
        
        # Convert AAB to APK if needed
        if is_aab_input:
            print(f"Detected AAB file: {target}")
            original_aab_path = target
            temp_apk = os.path.join(temp_dir, "universal_from_aab.apk")
            print("Converting AAB to universal APK...")
            target = convert_aab_to_apk(target, temp_apk, temp_dir)
            print(f"Converted to: {target}")
        
        decoded_dir = os.path.join(temp_dir, "target_decoded")
        # We need to decode and patch the manifest to find original app/factory
        patched_manifest, resources_arsc, original_app, original_factory = decode_and_patch_target_manifest(target, temp_dir)
        
        if not skip_build:
            build_packer()
            # Patch shell source with actual target app/factory names
            patch_shell_loader_constants(original_app, original_factory)
            build_shell()

        bootstrap_apk = get_shell_apk_path()
        
        keep_classes = extract_keep_classes_from_decoded_manifest(decoded_dir)
        manual_keep_classes = args.keep_class or config.get("keep_class", [])
        if isinstance(manual_keep_classes, str):
             manual_keep_classes = [manual_keep_classes]
        keep_classes.extend(manual_keep_classes)
        
        keep_prefixes = []
        manual_keep_prefixes = args.keep_prefix or config.get("keep_prefix", [])
        if isinstance(manual_keep_prefixes, str):
            manual_keep_prefixes = [manual_keep_prefixes]
        keep_prefixes.extend(manual_keep_prefixes)
        
        keep_libs = args.keep_lib or config.get("keep_lib", [])
        if isinstance(keep_libs, str):
            keep_libs = [keep_libs]
        if "mmkv" not in keep_libs:
            keep_libs.append("mmkv")
            
        encrypt_assets = args.encrypt_asset or config.get("encrypt_asset", [])
        if isinstance(encrypt_assets, str):
            encrypt_assets = [encrypt_assets]

        signing_keystore, signing_ks_pass, signing_alias = resolve_signing(keystore, ks_pass, key_alias)
        
        pack_apk(target, output, bootstrap_apk, patched_manifest, keep_classes, keep_prefixes, keep_libs, encrypt_assets, 
                 (signing_keystore, signing_ks_pass, signing_alias), key_bytes, resources_arsc)

        if no_sign:
            print("Skipping signing (--no-sign). Output APK may fail to install.")
        else:
            sign_apk(output, signing_keystore, signing_ks_pass, signing_alias)
        
        # Convert back to AAB if needed
        if output_format == 'aab' and original_aab_path:
            print("Converting hardened APK back to AAB...")
            temp_apk = output
            # Output already has correct extension from earlier logic
            if not output.endswith('.aab'):
                output = output.replace('.apk', '.aab') if output.endswith('.apk') else output + '.aab'
            convert_apk_to_aab(temp_apk, output, original_aab_path, temp_dir)
            print(f"Created hardened AAB: {output}")

    print(f"Done! Protected {output_format.upper()}: {output}")


if __name__ == "__main__":
    main()
