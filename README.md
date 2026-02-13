# CrabShell 🦀 (Android Packer)

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Build Status](https://github.com/kexuejin/crabshell/actions/workflows/build.yml/badge.svg)
![Rust](https://img.shields.io/badge/rust-1.70%2B-orange)
![Android](https://img.shields.io/badge/android-API%2024%2B-green)

CrabShell is an Android app hardening toolkit for APK/AAB pipelines. It encrypts DEX and native libraries, patches runtime bootstrap components, and supports end-to-end packing/signing with Rust + Python + Android shell runtime.

Use this project if you need:
- APK/AAB hardening automation in CI/CD.
- Runtime DEX/native payload decryption and loading.
- A research-oriented Android protection pipeline with source code.

**[中文文档](README_CN.md)**

## Features

-   **AES-256-GCM Encryption**: Securely encrypts original DEX files and native libraries using a randomly generated 32-byte key per build.
-   **Gen 2 Memory Loading**: On Android 8.0+ (API 26+), DEX files are loaded directly from memory (`InMemoryDexClassLoader`) without ever being written to disk.
-   **Legacy Support**: Fallback to file-based loading for Android 7.x (API 24/25).
-   **Multi-DEX Support**: Automatically handles APKs with multiple DEX files.
-   **Native Library Protection**: Encrypts and hides `.so` libraries, extracting them only on demand to a protected cache directory.
-   **Anti-Debugging**: Basic JNI-level debugger detection checks (e.g., `TracerPid`).
-   **One-Click Automation**: A Python script handles key generation, building, packing, and signing in a single command.

## Architecture

The project consists of two main components:

1.  **Packer (Host-side)**: Rust + Python pipeline.
    -   Uses the **target APK as final base** (resources/manifest preserved).
    -   Encrypts target `classes*.dex` and `lib/**/*.so` into `assets/kapp_payload.bin`.
    -   Injects bootstrap loader dex + `libshell.so`.
    -   Re-signs the output APK.

2.  **Shell (Android-side)**: A stub Android application.
    -   Usage standard Android entry points (`Application.attachBaseContext`).
    -   Loads a native Rust library (`libshell.so`).
    -   Locates encrypted payload from `assets/kapp_payload.bin`.
    -   Decrypts and loads the original app's code in runtime.

## Prerequisites

-   **Rust**: [Install Rust](https://www.rust-lang.org/tools/install)
-   **Android NDK**: Required for building the Shell's native library.
    -   Recommended: NDK 26.x
    -   Install `cargo-ndk`: `cargo install cargo-ndk`
    -   Add targets: `rustup target add aarch64-linux-android armv7-linux-androideabi x86_64-linux-android`
-   **Python 3**: For the automation script.
-   **JDK 17+**: For Android Gradle build.
-   **apktool**: Required for target manifest patch/rebuild.
-   **Android build-tools**: `apksigner` (required), `zipalign` (recommended).

## Quick Start

### Configuration File (Optional)

Instead of passing arguments every time, you can create a `kapp-config.json` file:

```json
{
    "target": "my-app.apk",
    "output": "protected.apk",
    "keystore": "release.jks",
    "ks_pass": "password",
    "key_alias": "alias",
    "no_sign": false
}
```

Then run:
```bash
python3 pack.py
```

1.  **Build the Docker Image**:
    ```bash
    docker build -t crabshell .
    ```

2.  **Run Packer**:
    Mount your target APK and output directory.
    ```bash
    docker run --rm -v $(pwd):/app -v /path/to/my-app.apk:/target.apk crabshell \
        python3 pack.py --target /target.apk --output /app/protected.apk
    ```

### Local Build

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/kexuejin/crabshell.git
    cd crabshell
    ```

2.  **Run the Packer**:
    Use the `pack.py` script to build everything and pack your target APK.
    
    ```bash
    python3 pack.py --target /path/to/your/app.apk --output protected.apk
    ```

    *Note: The first run will compile the Rust project and Gradle project, which might take a few minutes.*

3.  **Sign the APK** (Optional via script):
    ```bash
    python3 pack.py \
        --target app.apk \
        --keystore my-release-key.jks \
        --ks-pass pass:secret \
        --key-alias my-alias
    ```

    If no signing options are provided, the script now auto-signs with Android debug keystore
    (`~/.android/debug.keystore`). If missing, it will be generated automatically.

4.  **Skip Signing** (Optional):
    ```bash
    python3 pack.py --target app.apk --output protected.apk --no-sign
    ```
    *Note: Unsigned APKs usually cannot be installed directly on devices.*

## Manual Build

If you prefer to build components manually:

1.  **Build Packer**:
    ```bash
    cd packer && cargo build --release
    ```

2.  **Build Shell**:
    ```bash
    cd loader/app/src/main/rust
    cargo ndk -t arm64-v8a -t armeabi-v7a -o ../jniLibs build --release
    cd ../../../..
    ./gradlew assembleRelease
    ```

## CI / GitHub Actions

Workflow: `.github/workflows/build.yml`

- `core-build` (Ubuntu): runs `verify.sh` for non-GUI pipeline (packer + loader checks).
- `gui-package` (matrix): builds Tauri GUI bundles on all desktop platforms and uploads artifacts:
  - macOS: `CrabShell.app` + `CrabShell_*.dmg`
  - Linux: `.deb` + `.AppImage`
  - Windows: `.msi` + NSIS `.exe`

- `release.yml`: release workflow for GUI packages (all desktop platforms):
  - Trigger by tag push: `v*`
  - Or manual trigger: `workflow_dispatch` with inputs: `tag`, `prerelease`
  - Publishes `.dmg`, `.deb`, `.AppImage`, `.msi`, `.exe` to GitHub Releases
  - Release assets are normalized as `CrabShell-<tag>-<original-file-name>`

## Disclaimer

This tool is for **educational and research purposes only**. Do not use it for malicious purposes. The authors are not responsible for any misuse of this software.

## License

MIT License. See [LICENSE](LICENSE) file.
