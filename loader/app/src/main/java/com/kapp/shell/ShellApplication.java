package com.kapp.shell;

import android.app.Application;
import android.content.Context;
import android.util.Log;

import java.io.File;

public class ShellApplication extends Application {
    private static final String TAG = "ShellApplication";

    static {
        try {
            System.loadLibrary("shell");
        } catch (UnsatisfiedLinkError e) {
            Log.e(TAG, "Failed to load native library", e);
        }
    }

    // Native method to load DEX from memory or file
    private native void nativeLoadDex(Context context, int version);

    @Override
    protected void attachBaseContext(Context base) {
        super.attachBaseContext(base);
        Log.d(TAG, "attachBaseContext: Starting shell logic");

        // Determine Android version to choose loading strategy
        // 0 for Gen 1 (File) or Gen 2 (Memory) based on API level in native code
        nativeLoadDex(base, android.os.Build.VERSION.SDK_INT);
    }

    @Override
    public void onCreate() {
        super.onCreate();
        Log.d(TAG, "onCreate: ShellApplication started");
        // Ensure the original application's onCreate is called if we replaced the
        // Application
        // However, since we replace the ClassLoader, the system might have already
        // instantiated the original Application
        // if we did it right.
        // In a real shell, we would find the original Application class name from
        // metadata and invoke it.
    }
}
