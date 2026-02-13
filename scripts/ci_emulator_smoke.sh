#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

log_step() {
  echo
  echo "==== $1 ===="
}

fail() {
  echo "[FAIL] $1" >&2
  exit 1
}

ensure_ndk_env() {
  if [[ -n "${ANDROID_NDK_HOME:-}" ]]; then
    return
  fi

  if [[ -z "${ANDROID_SDK_ROOT:-}" ]]; then
    return
  fi

  local ndk_root="${ANDROID_SDK_ROOT}/ndk"
  if [[ -d "${ndk_root}" ]]; then
    local latest_ndk
    latest_ndk="$(ls -d "${ndk_root}/"* | sort -V | tail -n 1)"
    if [[ -n "${latest_ndk}" && -d "${latest_ndk}" ]]; then
      export ANDROID_NDK_HOME="${latest_ndk}"
    fi
  fi
}

wait_for_running_process() {
  local package_name="$1"
  local retries="${2:-20}"
  local sleep_seconds="${3:-2}"
  local pid=""

  for ((i = 0; i < retries; i++)); do
    pid="$(adb shell pidof "${package_name}" 2>/dev/null | tr -d '\r' || true)"
    if [[ -n "${pid}" ]]; then
      echo "${pid}"
      return 0
    fi
    sleep "${sleep_seconds}"
  done

  return 1
}

check_logs_for_crash() {
  local pid="$1"
  local label="$2"
  local logs
  logs="$(adb logcat -d --pid "${pid}" || true)"
  if echo "${logs}" | grep -E -q "FATAL EXCEPTION|UnsatisfiedLinkError|NoClassDefFoundError|Fatal signal"; then
    echo "[ERROR] ${label} logs contain crash signatures:"
    echo "${logs}"
    return 1
  fi
  return 0
}

assert_apk_contains_library() {
  local apk_path="$1"
  local lib_name="$2"
  python3 - "$apk_path" "$lib_name" <<'PY'
import sys
import zipfile

apk_path = sys.argv[1]
lib_name = sys.argv[2]
with zipfile.ZipFile(apk_path) as zf:
    names = zf.namelist()

if not any(name.endswith("/" + lib_name) or name == lib_name for name in names):
    raise SystemExit(f"{lib_name} not found in APK: {apk_path}")
PY
}

log_step "Prepare environment"
ensure_ndk_env
echo "Using ANDROID_NDK_HOME=${ANDROID_NDK_HOME:-unset}"
command -v adb >/dev/null || fail "adb not found in PATH"
command -v python3 >/dev/null || fail "python3 not found in PATH"

log_step "Build loader shell app"
pushd loader >/dev/null
./gradlew -q dependencies || true
./gradlew :app:assembleDebug --stacktrace
popd >/dev/null

loader_apk="loader/app/build/outputs/apk/debug/app-debug.apk"
[[ -f "${loader_apk}" ]] || fail "Loader APK missing: ${loader_apk}"

log_step "Build fixture apps (kappa + kappb)"
./loader/gradlew -p fixtures/test-apps :kappa:assembleDebug :kappb:assembleDebug --stacktrace

log_step "Pack fixture target APK (kappb includes mmkv)"
mkdir -p artifacts/ci
mmkv_input_apk="fixtures/test-apps/kappb/build/outputs/apk/debug/kappb-debug.apk"
mmkv_output_apk="artifacts/ci/kappb-protected.apk"
[[ -f "${mmkv_input_apk}" ]] || fail "MMKV target APK missing: ${mmkv_input_apk}"

assert_apk_contains_library "${mmkv_input_apk}" "libmmkv.so"
python3 pack.py --target "${mmkv_input_apk}" --output "${mmkv_output_apk}" --skip-build
[[ -f "${mmkv_output_apk}" ]] || fail "Protected MMKV APK missing: ${mmkv_output_apk}"

log_step "Install and launch protected mmkv target"
adb uninstall com.example.kappb >/dev/null 2>&1 || true
adb install -r "${mmkv_output_apk}" >/dev/null
adb logcat -c
adb shell monkey -p com.example.kappb -c android.intent.category.LAUNCHER 1 >/dev/null

target_pid="$(wait_for_running_process "com.example.kappb" 30 2)" || fail "Protected MMKV target failed to stay running after launch"
check_logs_for_crash "${target_pid}" "protected mmkv target" || fail "Protected MMKV target crashed after launch"

probe_result="$(adb shell run-as com.example.kappb cat files/mmkv_boot_probe.txt 2>/dev/null | tr -d '\r' || true)"
if [[ "${probe_result}" != "ok" ]]; then
  fail "MMKV probe result is invalid: ${probe_result:-<empty>}"
fi

echo "[OK] Emulator smoke checks passed (loader build + kappb mmkv target startup)."
