import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from typing import Optional, Sequence, Tuple, Union

RUST_SHELL_DIR = "loader/app/src/main/rust"
PACKER_DIR = "packer"
SHELL_PROJECT_DIR = "loader"
TOOLCHAIN_SUBDIR = "crabshell-toolchain"
BUNDLETOOL_VERSION = os.environ.get("BUNDLETOOL_VERSION", "1.17.2")
APKTOOL_VERSION = os.environ.get("APKTOOL_VERSION", "2.11.1")
UBER_APK_SIGNER_VERSION = os.environ.get("UBER_APK_SIGNER_VERSION", "1.3.0")
BUNDLETOOL_JAR_URL = (
    f"https://github.com/google/bundletool/releases/download/{BUNDLETOOL_VERSION}/bundletool-all-{BUNDLETOOL_VERSION}.jar"
)
APKTOOL_JAR_URL = (
    f"https://github.com/iBotPeaches/Apktool/releases/download/v{APKTOOL_VERSION}/apktool_{APKTOOL_VERSION}.jar"
)
UBER_APK_SIGNER_JAR_URL = (
    f"https://github.com/patrickfav/uber-apk-signer/releases/download/v{UBER_APK_SIGNER_VERSION}/uber-apk-signer-{UBER_APK_SIGNER_VERSION}.jar"
)
TOOL_DOWNLOAD_RETRIES = int(os.environ.get("TOOL_DOWNLOAD_RETRIES", "3"))
TOOL_DOWNLOAD_TIMEOUT = int(os.environ.get("TOOL_DOWNLOAD_TIMEOUT", "60"))
ANDROID_NS = "http://schemas.android.com/apk/res/android"
ANDROID_NAME = f"{{{ANDROID_NS}}}name"
ANDROID_VALUE = f"{{{ANDROID_NS}}}value"
ANDROID_AUTHORITIES = f"{{{ANDROID_NS}}}authorities"
ANDROID_EXPORTED = f"{{{ANDROID_NS}}}exported"
ANDROID_INIT_ORDER = f"{{{ANDROID_NS}}}initOrder"



def run_checked_command(command: list[str], action: str, cwd: Optional[str] = None, env: Optional[dict[str, str]] = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode == 0:
        return result

    stdout_tail = "\n".join(result.stdout.splitlines()[-120:])
    stderr_tail = "\n".join(result.stderr.splitlines()[-120:])
    raise RuntimeError(
        f"{action} failed. command={command}\n"
        f"--- stdout (tail) ---\n{stdout_tail}\n"
        f"--- stderr (tail) ---\n{stderr_tail}"
    )


def get_toolchain_dir() -> str:
    env_dir = os.environ.get("CRABSHELL_TOOLCHAIN_DIR")
    if env_dir:
        path = os.path.expanduser(env_dir)
        os.makedirs(path, exist_ok=True)
        return path

    codex_home = os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex"))
    path = os.path.join(codex_home, "tools", TOOLCHAIN_SUBDIR)
    os.makedirs(path, exist_ok=True)
    return path


def format_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)}{unit}"
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{int(size)}B"


def resolve_download_urls(primary_url: str, env_var: str) -> list[str]:
    raw = os.environ.get(env_var, "").strip()
    urls: list[str] = []
    if raw:
        for item in raw.split(","):
            candidate = item.strip()
            if candidate:
                urls.append(candidate)

    if primary_url not in urls:
        urls.append(primary_url)

    return urls


def download_with_url_fallback(urls: Sequence[str], target_path: str, retries: int = TOOL_DOWNLOAD_RETRIES) -> None:
    errors: list[str] = []
    for url in urls:
        try:
            download_file_with_retries(url, target_path, retries=retries)
            return
        except Exception as error:
            errors.append(f"{url} -> {error}")
            print(f"[toolchain] source-failed {url} reason={error}")

    raise RuntimeError(
        "All download sources failed for "
        f"{os.path.basename(target_path)}: {' | '.join(errors)}"
    )


def download_file_with_retries(url: str, target_path: str, retries: int = TOOL_DOWNLOAD_RETRIES) -> None:
    target_name = os.path.basename(target_path)

    for attempt in range(1, retries + 1):
        temp_path = f"{target_path}.part"
        try:
            print(f"[toolchain] download-start {target_name} attempt={attempt}/{retries}")

            with urllib.request.urlopen(url, timeout=TOOL_DOWNLOAD_TIMEOUT) as response, open(temp_path, "wb") as output:
                content_length_header = response.headers.get("Content-Length")
                total_bytes = int(content_length_header) if content_length_header else 0
                downloaded_bytes = 0
                last_percent = -1

                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    output.write(chunk)
                    downloaded_bytes += len(chunk)

                    if total_bytes > 0:
                        percent = int(downloaded_bytes * 100 / total_bytes)
                        if percent >= 100:
                            percent = 100
                        if percent != last_percent and (percent % 10 == 0 or percent == 100):
                            print(
                                f"[toolchain] download-progress {target_name} {percent}% "
                                f"({format_bytes(downloaded_bytes)}/{format_bytes(total_bytes)})"
                            )
                            last_percent = percent
                    elif downloaded_bytes % (1024 * 1024 * 4) < 1024 * 256:
                        print(
                            f"[toolchain] download-progress {target_name} "
                            f"{format_bytes(downloaded_bytes)}"
                        )

                if total_bytes > 0 and downloaded_bytes < total_bytes:
                    raise urllib.error.ContentTooShortError(
                        f"retrieval incomplete: got only {downloaded_bytes} out of {total_bytes} bytes",
                        None,
                    )

            os.replace(temp_path, target_path)
            print(f"[toolchain] download-done {target_name}")
            return
        except Exception as error:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass

            if attempt < retries:
                print(
                    f"[toolchain] download-retry {target_name} "
                    f"attempt={attempt}/{retries} reason={error}"
                )
                continue

            raise RuntimeError(
                f"Failed to download {target_name} after {retries} attempts: {error}"
            )


def ensure_downloaded_file(url_or_urls: Union[str, Sequence[str]], target_path: str, sha256: Optional[str] = None) -> str:
    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    def validate_existing_file() -> bool:
        if not os.path.exists(target_path):
            return False

        if sha256:
            current = compute_sha256(target_path)
            if current.lower() != sha256.lower():
                print(f"Checksum mismatch for {target_path}, re-downloading...")
                try:
                    os.remove(target_path)
                except Exception:
                    pass
                return False

        if target_path.lower().endswith(".jar") and not is_valid_jar_file(target_path):
            print(f"[toolchain] detected corrupt jar, re-downloading: {target_path}")
            try:
                os.remove(target_path)
            except Exception:
                pass
            return False

        return True

    if validate_existing_file():
        return target_path

    urls = [url_or_urls] if isinstance(url_or_urls, str) else list(url_or_urls)
    print(f"[toolchain] downloading {os.path.basename(target_path)} from {urls[0]}")
    download_with_url_fallback(urls, target_path)

    if not validate_existing_file():
        raise RuntimeError(f"Downloaded file is invalid and could not be validated: {target_path}")

    return target_path


def compute_sha256(file_path: str) -> str:
    digest = hashlib.sha256()
    with open(file_path, "rb") as file:
        while True:
            chunk = file.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def is_executable_file(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def is_valid_jar_file(path: str) -> bool:
    if not os.path.isfile(path):
        return False
    if not zipfile.is_zipfile(path):
        return False

    try:
        with zipfile.ZipFile(path, "r") as jar_file:
            bad_entry = jar_file.testzip()
            return bad_entry is None
    except Exception:
        return False


def is_aab_file(path: str) -> bool:
    """Check if file is an AAB by looking for BundleConfig.pb"""
    try:
        with zipfile.ZipFile(path, 'r') as z:
            return 'BundleConfig.pb' in z.namelist()
    except (zipfile.BadZipFile, OSError):
        return False


def find_java_cmd() -> str:
    """Find a usable Java executable."""
    def _is_usable(java_path: str) -> bool:
        try:
            result = subprocess.run(
                [java_path, "-version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            return result.returncode == 0
        except Exception:
            return False

    # 1) JAVA_HOME explicitly set
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        java_bin = os.path.join(java_home, "bin", "java")
        if os.path.isfile(java_bin) and os.access(java_bin, os.X_OK) and _is_usable(java_bin):
            return java_bin

    # 2) java in PATH
    java_in_path = shutil.which("java")
    if java_in_path and _is_usable(java_in_path):
        return java_in_path

    # 3) common Homebrew/OpenJDK locations (works for GUI apps without shell env)
    brew_candidates = [
        "/opt/homebrew/opt/openjdk@21/bin/java",
        "/opt/homebrew/opt/openjdk@17/bin/java",
        "/opt/homebrew/opt/openjdk/bin/java",
        "/usr/local/opt/openjdk@21/bin/java",
        "/usr/local/opt/openjdk@17/bin/java",
        "/usr/local/opt/openjdk/bin/java",
    ]
    for candidate in brew_candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK) and _is_usable(candidate):
            return candidate

    # 4) macOS java_home lookup
    if os.name == "posix":
        java_home_cmd = "/usr/libexec/java_home"
        if os.path.exists(java_home_cmd):
            try:
                resolved_home = subprocess.check_output([java_home_cmd], stderr=subprocess.STDOUT).decode().strip()
                java_bin = os.path.join(resolved_home, "bin", "java")
                if os.path.isfile(java_bin) and os.access(java_bin, os.X_OK) and _is_usable(java_bin):
                    return java_bin
            except Exception:
                pass

    raise RuntimeError(
        "Java runtime not found or unusable. The system `java` command is likely a macOS placeholder. "
        "Please install JDK 17+ and set JAVA_HOME if needed. "
        "macOS example: `brew install --cask temurin`"
    )


def normalize_java_env() -> str:
    """Ensure JAVA_HOME/PATH point to a usable Java runtime."""
    java_cmd = find_java_cmd()
    java_home = java_home_from_cmd(java_cmd)
    if java_home:
        os.environ["JAVA_HOME"] = java_home

    java_bin_dir = str(Path(java_cmd).resolve().parent)
    path_entries = [entry for entry in os.environ.get("PATH", "").split(os.pathsep) if entry]
    path_entries = [entry for entry in path_entries if entry != java_bin_dir]
    path_entries.insert(0, java_bin_dir)
    os.environ["PATH"] = os.pathsep.join(path_entries)
    return java_cmd


def find_keytool_cmd() -> str:
    """Find a usable keytool executable."""

    def _is_usable(keytool_path: str) -> bool:
        try:
            result = subprocess.run(
                [keytool_path, "-help"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            return result.returncode == 0
        except Exception:
            return False

    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        keytool_bin = os.path.join(java_home, "bin", "keytool")
        if os.path.isfile(keytool_bin) and os.access(keytool_bin, os.X_OK) and _is_usable(keytool_bin):
            return keytool_bin

    keytool_in_path = shutil.which("keytool")
    if keytool_in_path and _is_usable(keytool_in_path):
        return keytool_in_path

    java_cmd = find_java_cmd()
    sibling_keytool = str((Path(java_cmd).resolve().parent / "keytool"))
    if os.path.isfile(sibling_keytool) and os.access(sibling_keytool, os.X_OK) and _is_usable(sibling_keytool):
        return sibling_keytool

    brew_candidates = [
        "/opt/homebrew/opt/openjdk@21/bin/keytool",
        "/opt/homebrew/opt/openjdk@17/bin/keytool",
        "/opt/homebrew/opt/openjdk/bin/keytool",
        "/usr/local/opt/openjdk@21/bin/keytool",
        "/usr/local/opt/openjdk@17/bin/keytool",
        "/usr/local/opt/openjdk/bin/keytool",
    ]
    for candidate in brew_candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK) and _is_usable(candidate):
            return candidate

    raise RuntimeError(
        "keytool not found or unusable. Please install JDK 17+ and ensure keytool is available."
    )


def find_bundletool() -> str:
    """Find bundletool jar from managed toolchain, downloading if needed."""
    toolchain_dir = get_toolchain_dir()
    bundletool_jar = os.path.join(toolchain_dir, f"bundletool-{BUNDLETOOL_VERSION}.jar")
    return ensure_downloaded_file(resolve_download_urls(BUNDLETOOL_JAR_URL, "CRABSHELL_BUNDLETOOL_URLS"), bundletool_jar)


def find_uber_apk_signer() -> str:
    """Find uber-apk-signer jar from managed toolchain, downloading if needed."""
    toolchain_dir = get_toolchain_dir()
    signer_jar = os.path.join(toolchain_dir, f"uber-apk-signer-{UBER_APK_SIGNER_VERSION}.jar")
    return ensure_downloaded_file(resolve_download_urls(UBER_APK_SIGNER_JAR_URL, "CRABSHELL_UBER_APK_SIGNER_URLS"), signer_jar)


def convert_aab_to_apk(aab_path: str, output_apk: str, temp_dir: str) -> str:
    """Convert AAB to universal APK using bundletool"""
    bundletool = find_bundletool()
    java_cmd = find_java_cmd()

    # bundletool build-apks requires signing config in most environments.
    # We use debug signing to generate a universal APK for internal processing.
    debug_keystore, debug_password, debug_alias = get_default_debug_signing()
    
    # Build universal APKs (unsigned for now)
    apks_path = os.path.join(temp_dir, 'temp.apks')
    cmd = [
        java_cmd, '-jar', bundletool,
        'build-apks',
        '--bundle', aab_path,
        '--output', apks_path,
        '--mode', 'universal',
        '--ks', debug_keystore,
        '--ks-pass', f'pass:{debug_password}',
        '--ks-key-alias', debug_alias,
        '--key-pass', f'pass:{debug_password}'
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        combined_output = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()
        raise RuntimeError(
            "bundletool build-apks failed. "
            f"command={cmd}. output={combined_output or 'No output'}"
        )
    
    # Extract universal APK from .apks
    with zipfile.ZipFile(apks_path, 'r') as z:
        if 'universal.apk' not in z.namelist():
            raise RuntimeError(
                "bundletool output does not contain universal.apk. "
                f"entries={z.namelist()[:20]}"
            )
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

    payload_hash_bytes = payload_hash if payload_hash is not None else bytes(32)
    signature_hash_bytes = signature_hash if signature_hash is not None else bytes(32)
    payload_hash_str = ", ".join([f"0x{b:02x}" for b in payload_hash_bytes])
    signature_hash_str = ", ".join([f"0x{b:02x}" for b in signature_hash_bytes])

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

pub const PAYLOAD_HASH: [u8; 32] = [{payload_hash_str}];
pub const EXPECTED_SIGNATURE_HASH: [u8; 32] = [{signature_hash_str}];
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


def parse_rust_u8_array(source: str, const_name: str) -> bytes:
    pattern = re.compile(
        rf"const\s+{re.escape(const_name)}\s*:\s*\[u8;\s*32\]\s*=\s*\[(.*?)\];",
        re.DOTALL,
    )
    match = pattern.search(source)
    if not match:
        raise ValueError(f"Missing {const_name} in generated config")

    values: list[int] = []
    for item in match.group(1).split(","):
        token = item.strip()
        if not token:
            continue
        values.append(int(token, 0))

    if len(values) != 32:
        raise ValueError(f"{const_name} must have 32 bytes, got {len(values)}")
    if any(value < 0 or value > 0xFF for value in values):
        raise ValueError(f"{const_name} contains out-of-range byte value")

    return bytes(values)


def load_key_bytes_from_generated_config(config_path: str) -> bytes:
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    source = Path(config_path).read_text(encoding="utf-8")
    key_part_1 = parse_rust_u8_array(source, "KEY_PART_1")
    key_part_2 = parse_rust_u8_array(source, "KEY_PART_2")
    return bytes(part_1 ^ part_2 for part_1, part_2 in zip(key_part_1, key_part_2))


def select_key_bytes(skip_build: bool, packer_config_path: str) -> bytes:
    if not skip_build:
        return secrets.token_bytes(32)

    key_bytes = load_key_bytes_from_generated_config(packer_config_path)
    print(f"--skip-build enabled, reusing existing key from {packer_config_path}")
    return key_bytes

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
    return bytes.fromhex(compute_sha256(file_path))


def ensure_tool_exists(tool: str):
    if shutil.which(tool) is None:
        raise RuntimeError(f"Required tool not found: {tool}")


def java_home_from_cmd(java_cmd: str) -> Optional[str]:
    """Derive JAVA_HOME from java executable path."""
    java_path = Path(java_cmd).resolve()
    # .../Contents/Home/bin/java -> .../Contents/Home
    if java_path.parent.name == "bin":
        candidate = java_path.parent.parent
        if (candidate / "bin" / "java").exists():
            return str(candidate)
    return None


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
    toolchain_dir = get_toolchain_dir()
    managed_candidates = [
        os.path.join(toolchain_dir, "bin", tool_name),
        os.path.join(toolchain_dir, tool_name),
    ]
    for candidate in managed_candidates:
        if is_executable_file(candidate):
            return candidate

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
    toolchain_dir = get_toolchain_dir()

    bundled_candidates = [
        os.path.join(toolchain_dir, "bin", "apktool"),
        os.path.join(toolchain_dir, "apktool"),
    ]
    for candidate in bundled_candidates:
        if is_executable_file(candidate):
            return [candidate]

    apktool = shutil.which("apktool")
    if apktool:
        return [apktool]

    java = find_java_cmd()
    apktool_jar = os.path.join(toolchain_dir, f"apktool-{APKTOOL_VERSION}.jar")
    ensure_downloaded_file(resolve_download_urls(APKTOOL_JAR_URL, "CRABSHELL_APKTOOL_URLS"), apktool_jar)
    return [java, "-jar", apktool_jar]


def build_packer():
    print("Building Packer...")
    env = os.environ.copy()
    cargo_bin = os.path.expanduser("~/.cargo/bin")
    if cargo_bin not in env.get("PATH", ""):
        env["PATH"] = f"{cargo_bin}:{env.get('PATH', '')}"
    run_checked_command(["cargo", "build", "--release"], "Build Packer", cwd=PACKER_DIR, env=env)


def patch_shell_loader_constants(original_app: str, original_factory: str):
    print(f"Patching Shell loader constants: App={original_app}, Factory={original_factory}")
    factory_java = os.path.join(SHELL_PROJECT_DIR, "app/src/main/java/com/kapp/shell/ShellComponentFactory.java")
    if not os.path.exists(factory_java):
        print(f"Warning: {factory_java} not found, skipping constant patching")
        return

    with open(factory_java, "r") as f:
        content = f.read()

    original_app_value = original_app or ""
    original_factory_value = original_factory or ""

    app_pattern = r'(public\s+static\s+final\s+String\s+ORIGINAL_APP\s*=\s*)".*?";'
    factory_pattern = r'(public\s+static\s+final\s+String\s+ORIGINAL_FACTORY\s*=\s*)".*?";'

    app_replacement = r'\1"' + original_app_value.replace("\\", "\\\\").replace('"', '\\"') + '";'
    factory_replacement = r'\1"' + original_factory_value.replace("\\", "\\\\").replace('"', '\\"') + '";'

    content, app_count = re.subn(app_pattern, app_replacement, content, count=1)
    content, factory_count = re.subn(factory_pattern, factory_replacement, content, count=1)

    if app_count == 0:
        content = content.replace("REPLACE_ORIGINAL_APP", original_app_value)
    if factory_count == 0:
        content = content.replace("REPLACE_ORIGINAL_FACTORY", original_factory_value)

    with open(factory_java, "w") as f:
        f.write(content)


def build_shell():
    print("Building Shell (Native)...")
    env = os.environ.copy()

    java_cmd = find_java_cmd()
    detected_java_home = java_home_from_cmd(java_cmd)
    if detected_java_home:
        env["JAVA_HOME"] = detected_java_home

    java_bin_dir = str(Path(java_cmd).resolve().parent)
    path_entries = [entry for entry in env.get("PATH", "").split(os.pathsep) if entry]
    path_entries = [entry for entry in path_entries if entry != java_bin_dir]
    path_entries.insert(0, java_bin_dir)
    env["PATH"] = os.pathsep.join(path_entries)
    
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

    run_checked_command(
        ["cargo", "ndk", "-t", "arm64-v8a", "-t", "armeabi-v7a", "-o", "../jniLibs", "build", "--release"],
        "Build Shell (Native)",
        cwd=RUST_SHELL_DIR,
        env=env,
    )

    print("Building Shell (APK)...")
    gradlew = "./gradlew" if os.path.exists(os.path.join(SHELL_PROJECT_DIR, "gradlew")) else "gradle"
    gradle_result = subprocess.run(
        [gradlew, "assembleRelease"],
        cwd=SHELL_PROJECT_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    if gradle_result.returncode != 0:
        stdout_tail = "\n".join(gradle_result.stdout.splitlines()[-120:])
        stderr_tail = "\n".join(gradle_result.stderr.splitlines()[-120:])
        raise RuntimeError(
            "Gradle assembleRelease failed. "
            f"JAVA_HOME={env.get('JAVA_HOME', '<unset>')} "
            f"gradlew={gradlew}\n"
            f"--- stdout (tail) ---\n{stdout_tail}\n"
            f"--- stderr (tail) ---\n{stderr_tail}"
        )

    print("Building Packer...")
    run_checked_command(["cargo", "build", "--release"], "Build Packer", cwd=PACKER_DIR, env=env)


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


def ensure_bootstrap_provider(
    application: ET.Element, provider_class: str, provider_authorities: str
):
    for provider in application.findall("provider"):
        if provider.attrib.get(ANDROID_NAME) != provider_class:
            continue
        provider.set(ANDROID_AUTHORITIES, provider_authorities)
        provider.set(ANDROID_EXPORTED, "false")
        provider.set(ANDROID_INIT_ORDER, "1000")
        return

    provider = ET.SubElement(application, "provider")
    provider.set(ANDROID_NAME, provider_class)
    provider.set(ANDROID_AUTHORITIES, provider_authorities)
    provider.set(ANDROID_EXPORTED, "false")
    provider.set(ANDROID_INIT_ORDER, "1000")


def decode_and_patch_target_manifest(target_apk: str, temp_dir: str) -> Tuple[str, Optional[str], str, str]:
    apktool_cmd = ensure_apktool_cmd()

    decoded_dir = os.path.join(temp_dir, "target_decoded")
    patched_manifest = os.path.join(temp_dir, "AndroidManifest_patched.xml")

    def run_apktool(command: list[str], action: str) -> None:
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            return
        stdout_tail = "\n".join(result.stdout.splitlines()[-120:])
        stderr_tail = "\n".join(result.stderr.splitlines()[-120:])
        raise RuntimeError(
            f"apktool {action} failed. command={command}\n"
            f"--- stdout (tail) ---\n{stdout_tail}\n"
            f"--- stderr (tail) ---\n{stderr_tail}"
        )

    print("Decoding target APK with apktool...")
    decode_cmd = apktool_cmd + ["d", "-f", target_apk, "-o", decoded_dir]
    decoded_with_no_res = False
    try:
        run_apktool(decode_cmd, "decode")
    except RuntimeError as decode_error:
        print(f"Warning: apktool full decode failed, retrying with -r (no resources). reason={decode_error}")
        decode_cmd_no_res = apktool_cmd + ["d", "-f", "-r", target_apk, "-o", decoded_dir]
        run_apktool(decode_cmd_no_res, "decode (-r)")
        decoded_with_no_res = True

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

    application.set(ANDROID_NAME, "com.kapp.shell.ShellApplication")

    if f"{{{ANDROID_NS}}}debuggable" in application.attrib:
        print("Stripping android:debuggable attribute...")
        del application.attrib[f"{{{ANDROID_NS}}}debuggable"]

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

    package_name = (root.attrib.get("package") or "").strip()
    if not package_name:
        raise RuntimeError("Target manifest missing package attribute")
    ensure_bootstrap_provider(application, provider_class, f"{package_name}.kapp-bootstrap")

    if not decoded_with_no_res and res_dir and os.path.exists(res_dir):
        strings = load_string_resources(res_dir)
        inline_manifest_meta_data_string_values(application, strings)

    tree.write(manifest_path, encoding="utf-8", xml_declaration=True)

    print("Rebuilding decoded APK with apktool to get patched binary AndroidManifest.xml...")
    manifest_built_apk = os.path.join(temp_dir, "manifest-only.apk")
    build_cmd = apktool_cmd + ["b", decoded_dir, "-o", manifest_built_apk]
    run_apktool(build_cmd, "build")

    import zipfile

    resources_arsc = None
    use_rebuilt_resources = os.environ.get("CRABSHELL_USE_REBUILT_RESOURCES", "0") == "1"

    with zipfile.ZipFile(manifest_built_apk, "r") as zf:
        with zf.open("AndroidManifest.xml") as mf, open(patched_manifest, "wb") as out:
            out.write(mf.read())

        if use_rebuilt_resources:
            rebuilt_resources = os.path.join(temp_dir, "resources.arsc")
            try:
                with zf.open("resources.arsc") as rsc, open(rebuilt_resources, "wb") as out:
                    out.write(rsc.read())
                resources_arsc = rebuilt_resources
            except KeyError:
                print("Warning: resources.arsc not found in rebuilt APK.")
        else:
            print("Preserving original target resources.arsc (skip rebuilt resources replacement).")

    return patched_manifest, resources_arsc, original_app, original_factory


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
    run_checked_command(payload_cmd, "Generate payload")
    
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
    run_checked_command(final_cmd, "Final packing")


def sign_apk(apk_path, keystore, ks_pass, key_alias):
    print(f"Signing {apk_path}...")
    if ks_pass.startswith("pass:"):
        ks_pass = ks_pass[len("pass:"):]

    apksigner = find_android_build_tool("apksigner")
    if apksigner:
        cmd = [
            apksigner,
            "sign",
            "--ks",
            keystore,
            "--ks-pass",
            f"pass:{ks_pass}",
            "--key-pass",
            f"pass:{ks_pass}",
        ]
        if key_alias:
            cmd.extend(["--ks-key-alias", key_alias])
        cmd.append(apk_path)

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return

        combined_output = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()
        print(
            "Warning: apksigner failed, falling back to managed uber-apk-signer. "
            f"reason={combined_output or 'No output'}"
        )

    java_cmd = find_java_cmd()
    signer_jar = find_uber_apk_signer()

    fallback_cmd = [
        java_cmd,
        "-jar",
        signer_jar,
        "--apks",
        apk_path,
        "--ks",
        keystore,
        "--ksPass",
        ks_pass,
        "--ksAlias",
        key_alias or "androiddebugkey",
        "--ksKeyPass",
        ks_pass,
        "--overwrite",
    ]
    result = subprocess.run(fallback_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        combined_output = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()
        raise RuntimeError(
            "APK signing failed (apksigner unavailable/failed and uber-apk-signer fallback failed). "
            f"command={fallback_cmd}. output={combined_output or 'No output'}"
        )


def get_default_debug_signing() -> Tuple[str, str, str]:
    debug_alias = "androiddebugkey"
    debug_password = "android"
    keytool_cmd = find_keytool_cmd()

    home_debug_keystore = os.path.expanduser("~/.android/debug.keystore")
    temp_debug_keystore = os.path.join(tempfile.gettempdir(), "kapp-debug.keystore")

    def can_write_dir(directory: str) -> bool:
        try:
            os.makedirs(directory, exist_ok=True)
            probe = os.path.join(directory, f".kapp-write-test-{os.getpid()}")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe)
            return True
        except Exception:
            return False

    debug_keystore = home_debug_keystore
    if not can_write_dir(os.path.dirname(home_debug_keystore)):
        debug_keystore = temp_debug_keystore
        print(
            "Default ~/.android directory is not writable in current runtime. "
            f"Using temporary debug keystore: {debug_keystore}"
        )

    os.makedirs(os.path.dirname(debug_keystore), exist_ok=True)

    def generate_debug_keystore(target_path: str) -> None:
        if os.path.exists(target_path):
            try:
                os.remove(target_path)
            except Exception:
                pass

        print(f"Generating debug keystore: {target_path}")
        cmd = [
            keytool_cmd,
            "-genkeypair",
            "-v",
            "-noprompt",
            "-keystore",
            target_path,
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
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            combined_output = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()
            raise RuntimeError(
                "keytool generate debug keystore failed. "
                f"command={cmd}. output={combined_output or 'No output'}"
            )

    def verify_debug_keystore(target_path: str) -> bool:
        verify_cmd = [
            keytool_cmd,
            "-list",
            "-keystore",
            target_path,
            "-storepass",
            debug_password,
            "-alias",
            debug_alias,
        ]
        verify = subprocess.run(verify_cmd, capture_output=True, text=True)
        return verify.returncode == 0

    def ensure_keystore(target_path: str) -> str:
        if not os.path.exists(target_path):
            generate_debug_keystore(target_path)
            return target_path

        if not verify_debug_keystore(target_path):
            broken_path = f"{target_path}.broken"
            print(
                "Existing debug keystore is invalid for default credentials. "
                f"Backing up to: {broken_path}"
            )
            try:
                if os.path.exists(broken_path):
                    os.remove(broken_path)
                os.rename(target_path, broken_path)
            except Exception as rename_error:
                print(f"Warning: failed to back up invalid debug keystore: {rename_error}")
                try:
                    os.remove(target_path)
                except Exception:
                    pass

            generate_debug_keystore(target_path)

        return target_path

    try:
        debug_keystore = ensure_keystore(debug_keystore)
    except RuntimeError as e:
        if debug_keystore != temp_debug_keystore:
            print(
                "Failed to prepare ~/.android debug keystore, retrying with temporary location. "
                f"Reason: {e}"
            )
            debug_keystore = temp_debug_keystore
            os.makedirs(os.path.dirname(debug_keystore), exist_ok=True)
            debug_keystore = ensure_keystore(debug_keystore)
        else:
            raise

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


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CrabShell Packer Automation Script")
    parser.add_argument("--config", default="kapp-config.json", help="Path to config file")
    parser.add_argument("--target", help="Path to the target APK to pack")
    parser.add_argument("--output", default="protected.apk", help="Output APK path")
    parser.add_argument("--keystore", help="Path to keystore for signing")
    parser.add_argument("--ks-pass", help="Keystore password")
    parser.add_argument("--key-alias", help="Key alias")
    parser.add_argument("--no-sign", action="store_true", help="Skip APK signing")
    parser.add_argument("--skip-build", action="store_true", help="Skip building packer and shell")
    parser.add_argument(
        "--keep-class",
        action="append",
        help="Class names to keep in plaintext (can be specified multiple times)",
    )
    parser.add_argument(
        "--keep-prefix",
        action="append",
        help="Package prefixes to keep in plaintext (can be specified multiple times)",
    )
    parser.add_argument(
        "--keep-lib",
        action="append",
        help="Library names (without lib prefix or .so) to keep in plaintext (can be specified multiple times)",
    )
    parser.add_argument(
        "--encrypt-asset", action="append", help="Pattern of assets to encrypt (e.g. assets/*.js)"
    )
    parser.add_argument(
        "--output-format",
        choices=["auto", "apk", "aab"],
        default="auto",
        help="Output format (auto=same as input, apk=force APK, aab=force AAB)",
    )
    return parser


def normalize_cli_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [item for item in value if item]


def normalize_output_path(target: str, output: str) -> str:
    if os.path.isdir(output) or output.endswith(os.sep):
        target_base = os.path.splitext(os.path.basename(target))[0]
        return os.path.join(output, f"{target_base}-protected.apk")
    return output


def resolve_output_format_and_extension(
    target: str, output: str, requested_output_format: str
) -> tuple[bool, str, str]:
    is_aab_input = is_aab_file(target)
    output_format = requested_output_format
    if output_format == "auto":
        output_format = "aab" if is_aab_input else "apk"

    if output_format == "aab" and not output.endswith(".aab"):
        output = f"{os.path.splitext(output)[0]}.aab"
    elif output_format == "apk" and not output.endswith(".apk"):
        output = f"{os.path.splitext(output)[0]}.apk"

    return is_aab_input, output_format, output


def collect_runtime_lists(args, config: dict, decoded_dir: str) -> tuple[list[str], list[str], list[str], list[str]]:
    keep_classes = extract_keep_classes_from_decoded_manifest(decoded_dir)
    keep_classes.extend(normalize_cli_list(args.keep_class or config.get("keep_class")))

    keep_prefixes = normalize_cli_list(args.keep_prefix or config.get("keep_prefix"))

    keep_libs = normalize_cli_list(args.keep_lib or config.get("keep_lib"))
    if "mmkv" not in keep_libs:
        keep_libs.append("mmkv")

    encrypt_assets = normalize_cli_list(args.encrypt_asset or config.get("encrypt_asset"))
    return keep_classes, keep_prefixes, keep_libs, encrypt_assets


def maybe_build_toolchain(skip_build: bool, original_app: str, original_factory: str):
    if skip_build:
        return
    build_packer()
    patch_shell_loader_constants(original_app, original_factory)
    build_shell()


def prepare_target_manifest(
    target: str, is_aab_input: bool, temp_dir: str
) -> tuple[str, Optional[str], str, Optional[str], str, str]:
    original_aab_path = None
    target_apk = target

    if is_aab_input:
        print(f"Detected AAB file: {target}")
        original_aab_path = target
        temp_apk = os.path.join(temp_dir, "universal_from_aab.apk")
        print("Converting AAB to universal APK...")
        target_apk = convert_aab_to_apk(target, temp_apk, temp_dir)
        print(f"Converted to: {target_apk}")

    patched_manifest, resources_arsc, original_app, original_factory = decode_and_patch_target_manifest(
        target_apk, temp_dir
    )
    return target_apk, original_aab_path, patched_manifest, resources_arsc, original_app, original_factory


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    normalize_java_env()

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

    output = normalize_output_path(target, output)

    output_parent = os.path.dirname(output)
    if output_parent:
        os.makedirs(output_parent, exist_ok=True)

    packer_config_path = os.path.join(PACKER_DIR, "src", "config.rs")
    key_bytes = select_key_bytes(skip_build, packer_config_path)
    # Initial config generation for packer build
    generate_config(os.path.join(RUST_SHELL_DIR, "src", "config.rs"), key_bytes)
    generate_config(packer_config_path, key_bytes)

    is_aab_input, output_format, output = resolve_output_format_and_extension(
        target, output, args.output_format
    )

    with tempfile.TemporaryDirectory(prefix="kapp-") as temp_dir:
        decoded_dir = os.path.join(temp_dir, "target_decoded")
        (
            target,
            original_aab_path,
            patched_manifest,
            resources_arsc,
            original_app,
            original_factory,
        ) = prepare_target_manifest(target, is_aab_input, temp_dir)

        maybe_build_toolchain(skip_build, original_app, original_factory)

        bootstrap_apk = get_shell_apk_path()
        keep_classes, keep_prefixes, keep_libs, encrypt_assets = collect_runtime_lists(
            args, config, decoded_dir
        )

        signing_keystore, signing_ks_pass, signing_alias = resolve_signing(keystore, ks_pass, key_alias)

        # apksigner only supports APK. For AAB output, keep an intermediate APK and
        # convert it to AAB afterwards.
        apk_output_path = output
        if output_format == 'aab':
            apk_output_path = os.path.join(temp_dir, "hardened_for_aab.apk")

        pack_apk(
            target,
            apk_output_path,
            bootstrap_apk,
            patched_manifest,
            keep_classes,
            keep_prefixes,
            keep_libs,
            encrypt_assets,
            (signing_keystore, signing_ks_pass, signing_alias),
            key_bytes,
            resources_arsc,
        )

        if no_sign:
            if output_format == 'aab':
                print("Skipping signing (--no-sign). Intermediate APK may be unsigned before AAB conversion.")
            else:
                print("Skipping signing (--no-sign). Output APK may fail to install.")
        else:
            sign_apk(apk_output_path, signing_keystore, signing_ks_pass, signing_alias)
        
        # Convert back to AAB if needed
        if output_format == 'aab' and original_aab_path:
            print("Converting hardened APK back to AAB...")
            temp_apk = apk_output_path
            # Output already has correct extension from earlier logic
            if not output.endswith('.aab'):
                output = output.replace('.apk', '.aab') if output.endswith('.apk') else output + '.aab'
            convert_apk_to_aab(temp_apk, output, original_aab_path, temp_dir)
            print(f"Created hardened AAB: {output}")

    print(f"Done! Protected {output_format.upper()}: {output}")


if __name__ == "__main__":
    main()
