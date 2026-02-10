#!/bin/bash

# Configuration
export PATH="$HOME/.cargo/bin:$HOME/Library/Android/sdk/platform-tools:$HOME/Library/Android/sdk/emulator:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

TARGET_APK="Kid-beta-debug.apk"
OUTPUT_APK="protected.apk"
PACKAGE_NAME="com.flashget.kidscontrol"
AVD_NAME="Medium_Phone_API_35"
EMULATOR_PATH="/Users/kexuejin/Library/Android/sdk/emulator/emulator"
ADB_PATH="/Users/kexuejin/Library/Android/sdk/platform-tools/adb"

echo "--- Step 1: Packing APK ---"
python3 pack.py --target "$TARGET_APK" --output "$OUTPUT_APK"
if [ $? -ne 0 ]; then
    echo "Error: Packing failed."
    exit 1
fi

echo "--- Step 2: Checking Emulator ---"
DEVICE_SERIAL=$($ADB_PATH devices | grep -v "List" | grep "device$" | head -n 1 | awk '{print $1}')

if [ -z "$DEVICE_SERIAL" ]; then
    echo "Starting emulator $AVD_NAME..."
    $EMULATOR_PATH -avd "$AVD_NAME" -no-snapshot-load > /dev/null 2>&1 &
    
    echo "Waiting for emulator to boot (this may take a while)..."
    $ADB_PATH wait-for-device
    
    # Wait for the system to actually be ready
    while [ "$($ADB_PATH shell getprop sys.boot_completed | tr -d '\r')" != "1" ]; do
        sleep 5
    done
    echo "Emulator is ready."
    DEVICE_SERIAL=$($ADB_PATH devices | grep -v "List" | grep "device$" | head -n 1 | awk '{print $1}')
else
    echo "Using existing device: $DEVICE_SERIAL"
fi

echo "--- Step 3: Installing APK ---"
$ADB_PATH -s "$DEVICE_SERIAL" install -r "$OUTPUT_APK"
if [ $? -ne 0 ]; then
    echo "Error: Installation failed."
    exit 1
fi

echo "--- Step 4: Launching App ---"
# Using monkey to launch the main activity as we couldn't pinpoint the exact launcher activity name via tools easily
$ADB_PATH -s "$DEVICE_SERIAL" shell monkey -p "$PACKAGE_NAME" -c android.intent.category.LAUNCHER 1

echo "--- Step 5: Streaming Logs ---"
echo "Showing logs for $PACKAGE_NAME. Press Ctrl+C to stop."
$ADB_PATH -s "$DEVICE_SERIAL" logcat --pid=$($ADB_PATH -s "$DEVICE_SERIAL" shell pidof -s "$PACKAGE_NAME")
