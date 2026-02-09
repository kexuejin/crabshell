# CrabShell 🦀 (Android Packer)

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Build Status](https://github.com/your-username/kapp-shield/actions/workflows/build.yml/badge.svg)
![Rust](https://img.shields.io/badge/rust-1.70%2B-orange)
![Android](https://img.shields.io/badge/android-API%2024%2B-green)

CrabShell involves a custom Android Packer solution designed to protect Android applications (APK) by encrypting their DEX files and native libraries. It features a Rust-based host packer and an Android client shell that decrypts and loads the payload in memory at runtime.

**[中文文档](README_CN.md)** (Coming Soon)

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

1.  **Packer (Host-side)**: A Rust CLI tool.
    -   Reads the target APK.
    -   Extracts `classes*.dex` and `lib/**/*.so`.
    -   Encrypts them individually.
    -   Appends the encrypted payload + metadata to the `Shell` APK.

2.  **Shell (Android-side)**: A stub Android application.
    -   Usage standard Android entry points (`Application.attachBaseContext`).
    -   Loads a native Rust library (`libshell.so`).
    -   Locates the appended payload in its own APK.
    -   Decrypts and loads the original app's code and resources.

## Prerequisites

-   **Rust**: [Install Rust](https://www.rust-lang.org/tools/install)
-   **Android NDK**: Required for building the Shell's native library.
    -   Recommended: NDK 26.x
    -   Install `cargo-ndk`: `cargo install cargo-ndk`
    -   Add targets: `rustup target add aarch64-linux-android armv7-linux-androideabi x86_64-linux-android`
-   **Python 3**: For the automation script.
-   **JDK 17+**: For Android Gradle build.

## Quick Start

### Configuration File (Optional)

Instead of passing arguments every time, you can create a `kapp-config.json` file:

```json
{
    "target": "my-app.apk",
    "output": "protected.apk",
    "keystore": "release.jks",
    "ks_pass": "password",
    "key_alias": "alias"
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
    git clone https://github.com/your-username/crabshell.git
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

## Disclaimer

This tool is for **educational and research purposes only**. Do not use it for malicious purposes. The authors are not responsible for any misuse of this software.

## License

MIT License. See [LICENSE](LICENSE) file.
