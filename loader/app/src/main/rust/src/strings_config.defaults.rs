// Fallback strings used when generated strings_config.rs is absent in clean CI checkout.
// pack.py will overwrite src/strings_config.rs with obfuscated values during packaging.
#![allow(dead_code)]

pub const PROC_STATUS: &[u8] = b"/proc/self/status";
pub const TRACER_PID: &[u8] = b"TracerPid:";
pub const PAYLOAD_NAME: &[u8] = b"assets/kapp_payload.bin";
pub const LOG_TAG: &[u8] = b"KAppShell";
pub const ERR_NO_PAYLOAD: &[u8] = b"No shell payload found";
pub const ERR_INVALID_CHECKSUM: &[u8] = b"Invalid checksum";
pub const MSG_NATIVE_LOAD_DEX: &[u8] = b"nativeLoadDex (Application) called for SDK {}";
pub const MSG_OPEN_APK: &[u8] = b"Opening APK at {}";
pub const MAGIC_SHELL: &[u8] = b"SHELL";
pub const DEBUG_DETECTED: &[u8] = b"Debugger detected";
pub const EXITING: &[u8] = b"Exiting...";
pub const PTRACE_FAILED: &[u8] = b"ptrace failed with errno {}";
pub const PTRACE_RESTRICTED: &[u8] = b"Ptrace TRACEME restricted by system (errno 13).";
pub const PTRACE_SUCCESS: &[u8] = b"Ptrace TRACEME successful (no debugger attached).";
pub const TRACER_PID_LOG: &[u8] = b"TracerPid: {}";
