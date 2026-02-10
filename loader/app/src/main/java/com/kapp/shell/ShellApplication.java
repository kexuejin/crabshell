package com.kapp.shell;

import android.app.Application;
import android.content.Context;
import android.util.Log;

import java.io.File;

public class ShellApplication extends Application {
    private static final String TAG = "ShellApplication";
    private Application originalApp;

    static {
        try {
            System.loadLibrary("shell");
        } catch (UnsatisfiedLinkError e) {
            Log.e(TAG, "Failed to load native library", e);
        }
    }

    private static boolean sDexLoaded = false;

    // Native method to load DEX from memory or file
    private native void nativeLoadDex(Context context, int version);

    // Native method to load DEX using ApplicationInfo (earlier than
    // attachBaseContext)
    public static native void nativeLoadDexWithAppInfo(android.content.pm.ApplicationInfo appInfo, ClassLoader cl,
            int version);

    public static synchronized void ensureDexLoaded(Context context) {
        if (sDexLoaded)
            return;
        new ShellApplication().nativeLoadDex(context, android.os.Build.VERSION.SDK_INT);
        sDexLoaded = true;
    }

    public static synchronized void ensureDexLoaded(android.content.pm.ApplicationInfo appInfo, ClassLoader cl) {
        if (sDexLoaded)
            return;
        nativeLoadDexWithAppInfo(appInfo, cl, android.os.Build.VERSION.SDK_INT);
        sDexLoaded = true;
    }

    @Override
    protected void attachBaseContext(Context base) {
        super.attachBaseContext(base);
        Log.d(TAG, "attachBaseContext: Starting shell logic");
        ensureDexLoaded(base);
    }

    @Override
    public void onCreate() {
        super.onCreate();
        Log.d(TAG, "onCreate: ShellApplication started");
        ensureDexLoaded(getApplicationContext());

        try {
            String originalAppName = ShellComponentFactory.ORIGINAL_APP;
            if (originalAppName == null || originalAppName.isEmpty()
                    || originalAppName.equals("REPLACE_ORIGINAL_APP")) {
                android.content.pm.ApplicationInfo appInfo = getPackageManager().getApplicationInfo(getPackageName(),
                        android.content.pm.PackageManager.GET_META_DATA);
                originalAppName = appInfo.metaData.getString("kapp.original_application");
            }

            if (originalAppName == null) {
                Log.e(TAG, "onCreate: No original application class found");
                return;
            }

            Log.d(TAG, "onCreate: Loading original application: " + originalAppName);
            Class<?> clazz = getClassLoader().loadClass(originalAppName);
            originalApp = (Application) clazz.newInstance();

            // Attach context
            java.lang.reflect.Method attachMethod = Application.class.getDeclaredMethod("attach", Context.class);
            attachMethod.setAccessible(true);
            attachMethod.invoke(originalApp, getBaseContext());

            // Replace ShellApplication with originalApp in the system
            replaceApplication(getBaseContext(), originalApp);

            // Inject extracted assets
            injectAssets(getApplicationContext());

            // Initialize WorkManager via reflection if originalApp provides configuration
            initializeWorkManager(originalApp);

            Log.d(TAG, "onCreate: Calling original application onCreate");
            originalApp.onCreate();

        } catch (Exception e) {
            Log.e(TAG, "onCreate: Failed to delegate to original application", e);
            throw new RuntimeException(e);
        }
    }

    private void injectAssets(Context context) {
        try {
            File assetsZip = new File(context.getFilesDir(), "kapp_assets.zip");
            if (!assetsZip.exists()) {
                Log.w(TAG, "injectAssets: kapp_assets.zip does not exist, skipping");
                return;
            }

            android.content.res.AssetManager am = context.getAssets();
            java.lang.reflect.Method addAssetPath = android.content.res.AssetManager.class
                    .getDeclaredMethod("addAssetPath", String.class);
            addAssetPath.setAccessible(true);

            String path = assetsZip.getAbsolutePath();
            Log.d(TAG, "injectAssets: Adding asset path: " + path);

            Object cookie = addAssetPath.invoke(am, path);
            Log.d(TAG, "injectAssets: Result cookie: " + cookie);

        } catch (Exception e) {
            Log.e(TAG, "injectAssets: Failed to inject assets", e);
        }
    }

    private void initializeWorkManager(Application app) {
        try {
            Log.d(TAG, "Checking for WorkManager configuration...");
            // Reflectively check for androidx.work.Configuration$Provider
            Class<?> providerClass = tryLoadClass("androidx.work.Configuration$Provider");
            if (providerClass == null) {
                Log.d(TAG, "androidx.work.Configuration$Provider not found, skipping WorkManager init");
                return;
            }

            if (providerClass.isInstance(app)) {
                Log.d(TAG, "Original app implements Configuration.Provider, retrieving config...");
                java.lang.reflect.Method getConfigMethod = providerClass.getMethod("getWorkManagerConfiguration");
                Object config = getConfigMethod.invoke(app);

                if (config != null) {
                    Log.d(TAG, "Initializing WorkManager with reflected config...");
                    Class<?> workManagerClass = tryLoadClass("androidx.work.WorkManager");
                    if (workManagerClass != null) {
                        java.lang.reflect.Method initMethod = workManagerClass.getMethod("initialize", Context.class,
                                tryLoadClass("androidx.work.Configuration"));
                        initMethod.invoke(null, this, config);
                        Log.d(TAG, "WorkManager initialized successfully");
                    }
                }
            } else {
                Log.d(TAG, "Original app does NOT implement Configuration.Provider");
            }
        } catch (Exception e) {
            // Log but don't crash if WorkManager init fails - app might might still work
            Log.w(TAG, "Failed to initialize WorkManager via reflection", e);
        }
    }

    private void replaceApplication(Context baseContext, Application newApp) {
        try {
            Log.d(TAG, "replaceApplication: Swapping Application instance...");

            // 1. Get ActivityThread
            Class<?> activityThreadClass = Class.forName("android.app.ActivityThread");
            java.lang.reflect.Method currentActivityThreadMethod = activityThreadClass
                    .getDeclaredMethod("currentActivityThread");
            Object activityThread = currentActivityThreadMethod.invoke(null);

            // 2. Get LoadedApk (mBoundApplication is not accessible easily, get it via
            // ContextImpl using reflection/methods)
            // Or easier: ContextImpl.mPackageInfo is LoadedApk
            Object loadedApk = null;
            try {
                java.lang.reflect.Field packageInfoField = baseContext.getClass().getDeclaredField("mPackageInfo");
                packageInfoField.setAccessible(true);
                loadedApk = packageInfoField.get(baseContext);
            } catch (Exception e) {
                // Fallback attempt
                Log.w(TAG, "Failed to get LoadedApk from Context, trying ActivityThread.mBoundApplication...");
            }

            if (loadedApk == null) {
                // Try from ActivityThread
                java.lang.reflect.Field mBoundApplicationField = activityThreadClass
                        .getDeclaredField("mBoundApplication");
                mBoundApplicationField.setAccessible(true);
                Object appBindData = mBoundApplicationField.get(activityThread);
                java.lang.reflect.Field infoField = appBindData.getClass().getDeclaredField("info");
                infoField.setAccessible(true);
                loadedApk = infoField.get(appBindData);
            }

            if (loadedApk != null) {
                // 3. Replace mApplication in LoadedApk
                Class<?> loadedApkClass = Class.forName("android.app.LoadedApk");
                java.lang.reflect.Field mApplicationField = loadedApkClass.getDeclaredField("mApplication");
                mApplicationField.setAccessible(true);
                mApplicationField.set(loadedApk, newApp);

                // 4. Update mAllApplications list in ActivityThread
                java.lang.reflect.Field mAllApplicationsField = activityThreadClass
                        .getDeclaredField("mAllApplications");
                mAllApplicationsField.setAccessible(true);
                java.util.ArrayList<Application> allApplications = (java.util.ArrayList<Application>) mAllApplicationsField
                        .get(activityThread);
                allApplications.remove(this);
                allApplications.add(newApp);

                // 5. Update mInitialApplication in ActivityThread
                java.lang.reflect.Field mInitialApplicationField = activityThreadClass
                        .getDeclaredField("mInitialApplication");
                mInitialApplicationField.setAccessible(true);
                mInitialApplicationField.set(activityThread, newApp);

                Log.d(TAG, "replaceApplication: Success!");
            } else {
                Log.e(TAG, "replaceApplication: Failed to find LoadedApk");
            }

        } catch (Exception e) {
            Log.e(TAG, "replaceApplication: Failed", e);
            // Non-fatal? Maybe, but likely will crash later on cast.
        }
    }

    private Class<?> tryLoadClass(String name) {
        try {
            return getClassLoader().loadClass(name);
        } catch (ClassNotFoundException e) {
            return null;
        }
    }
}
