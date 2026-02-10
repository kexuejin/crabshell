package com.kapp.shell;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.net.Uri;
import android.util.Log;

public class BootstrapProvider extends ContentProvider {
    private static final String TAG = "BootstrapProvider";

    static {
        try {
            System.loadLibrary("shell");
        } catch (UnsatisfiedLinkError e) {
            Log.e(TAG, "Failed to load native library", e);
        }
    }

    private static native void nativeLoadDex(android.content.Context context, int sdkInt);

    @Override
    public boolean onCreate() {
        try {
            if (getContext() != null) {
                nativeLoadDex(getContext(), android.os.Build.VERSION.SDK_INT);
            }
        } catch (Throwable t) {
            Log.e(TAG, "nativeLoadDex failed", t);
        }
        return true;
    }

    @Override
    public Cursor query(Uri uri, String[] projection, String selection, String[] selectionArgs, String sortOrder) {
        return null;
    }

    @Override
    public String getType(Uri uri) {
        return null;
    }

    @Override
    public Uri insert(Uri uri, ContentValues values) {
        return null;
    }

    @Override
    public int delete(Uri uri, String selection, String[] selectionArgs) {
        return 0;
    }

    @Override
    public int update(Uri uri, ContentValues values, String selection, String[] selectionArgs) {
        return 0;
    }
}
