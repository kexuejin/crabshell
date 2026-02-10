#!/bin/bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

echo "=========================================="
echo " Android Packer Verification Script"
echo "=========================================="

# 1. Check Rust
if [ -f "$HOME/.cargo/env" ]; then
    source "$HOME/.cargo/env"
fi

if ! command -v cargo &> /dev/null; then
    echo -e "${RED}[FAIL] Rust (cargo) is not installed.${NC}"
    echo "Please install Rust: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
    exit 1
else
    echo -e "${GREEN}[OK] Rust is installed.$(cargo --version)${NC}"
fi

# 2. Check Android NDK targets
echo "Checking Android targets..."
TARGETS=$(rustup target list --installed)
if [[ $TARGETS == *"aarch64-linux-android"* ]]; then
    echo -e "${GREEN}[OK] Android targets installed.${NC}"
else
    echo -e "${RED}[FAIL] Android targets missing.${NC}"
    echo "Please run: rustup target add aarch64-linux-android armv7-linux-androideabi"
    exit 1
fi

# 3. Check cargo-ndk
if ! command -v cargo-ndk &> /dev/null; then
    echo -e "${RED}[FAIL] cargo-ndk is not installed.${NC}"
    echo "Please run: cargo install cargo-ndk"
    exit 1
fi

# 3.1 Check apktool
if ! command -v apktool &> /dev/null; then
    echo -e "${RED}[WARN] apktool is not installed.${NC}"
    echo "pack.py can auto-download apktool jar fallback if java is available."
else
    echo -e "${GREEN}[OK] apktool is installed.${NC}"
fi

# 3.2 Check apksigner
if ! command -v apksigner &> /dev/null; then
    echo -e "${RED}[WARN] apksigner is not in PATH.${NC}"
    echo "pack.py will try Android SDK build-tools auto-discovery."
else
    echo -e "${GREEN}[OK] apksigner is installed.${NC}"
fi

# 3.3 Check zipalign (recommended)
if ! command -v zipalign &> /dev/null; then
    echo -e "${RED}[WARN] zipalign is not installed.${NC}"
    echo "Install Android build-tools for better APK alignment compatibility."
else
    echo -e "${GREEN}[OK] zipalign is installed.${NC}"
fi

# 4. Check Gradle (or Wrapper)
if [ ! -f "loader/gradlew" ]; then
    echo -e "${RED}[WARN] Gradle Wrapper not found.${NC}"
    echo "Generating Gradle Wrapper..."
    # Try to use local gradle if available
    if command -v gradle &> /dev/null; then
        cd loader
        gradle wrapper
        cd ..
    else
        echo -e "${RED}[FAIL] Gradle not found. Cannot generate wrapper.${NC}"
        echo "Please install Gradle or Android Studio."
        exit 1
    fi
fi

# 5. Build Packer
echo "Building Packer..."
cd packer
cargo build --release
if [ $? -eq 0 ]; then
    echo -e "${GREEN}[OK] Packer built successfully.${NC}"
else
    echo -e "${RED}[FAIL] Packer build failed.${NC}"
    exit 1
fi
cd ..

# 6. Build Shell
echo "Ensuring NDK is installed..."
cd loader
if [ -f "./gradlew" ]; then
    CMD="./gradlew"
else
    CMD="gradle"
fi
# Trigger NDK install (tasks that need NDK but don't fail if we don't have sources yet? actually any task might verify NDK)
# 'dependencies' task usually triggers SDK/NDK checks if configured.
$CMD -q dependencies > /dev/null 2>&1 || true
cd ..

echo "Building Android Shell (Native)..."
cd loader/app/src/main/rust
# Ensure env vars are set
if [ -z "$ANDROID_NDK_HOME" ]; then
    echo -e "${RED}[WARN] ANDROID_NDK_HOME is not set.${NC}"
    
    # Try standard MacOS path
    POSSIBLE_PATHS=(
        "$HOME/Library/Android/sdk/ndk"
        "${ANDROID_HOME}/ndk"
        "${ANDROID_SDK_ROOT}/ndk"
        "/usr/local/lib/android/sdk/ndk"
    )

    for SDK_NDK_DIR in "${POSSIBLE_PATHS[@]}"; do
        if [ -d "$SDK_NDK_DIR" ]; then
            # Pick the latest version
            LATEST_NDK=$(ls -d "$SDK_NDK_DIR"/* | sort -V | tail -n 1)
            if [ -d "$LATEST_NDK" ]; then
                export ANDROID_NDK_HOME="$LATEST_NDK"
                echo "Using detected NDK: $ANDROID_NDK_HOME"
                break
            fi
        fi
    done
fi

if [ -z "$ANDROID_NDK_HOME" ]; then
    echo -e "${RED}[FAIL] Could not detect ANDROID_NDK_HOME. Please set it manually.${NC}"
    exit 1
fi

cargo ndk -t arm64-v8a -t armeabi-v7a -o ../jniLibs build --release
if [ $? -ne 0 ]; then
    echo -e "${RED}[FAIL] Cargo NDK build failed.${NC}"
    exit 1
fi
cd ../../../..

echo "Building Android Shell (APK)..."
cd loader
if [ -f "./gradlew" ]; then
    CMD="./gradlew"
else
    echo -e "${RED}[WARN] ./gradlew not found. Using system gradle.${NC}"
    CMD="gradle"
fi

$CMD assembleRelease
if [ $? -eq 0 ]; then
    echo -e "${GREEN}[OK] Android Shell built successfully.${NC}"
else
    echo -e "${RED}[FAIL] Android Shell build failed.${NC}"
    exit 1
fi
cd ..

echo -e "${GREEN}All verification steps passed!${NC}"
