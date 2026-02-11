package com.kapp.shell;

import android.app.AppComponentFactory;
import android.app.Application;
import android.app.Service;
import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.ContentProvider;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.util.Log;

public class ShellComponentFactory extends AppComponentFactory {
    private static final String TAG = "ShellComponentFactory";
    public static final String ORIGINAL_APP = "com.flashget.parentalcontrol.SandApp";
    public static final String ORIGINAL_FACTORY = "androidx.core.app.CoreComponentFactory";
    private static ApplicationInfo sAppInfo;
    private AppComponentFactory originalFactory;

    public ShellComponentFactory() {
        super();
        Log.e(TAG, "ShellComponentFactory constructor called!");
    }

    private void ensureDelegate(ClassLoader cl) {
        if (originalFactory != null)
            return;

        try {
            String originalFactoryName = null;

            if (sAppInfo != null && sAppInfo.metaData != null) {
                originalFactoryName = sAppInfo.metaData.getString("kapp.original_factory");
            }

            if (originalFactoryName == null || originalFactoryName.isEmpty()) {
                originalFactoryName = ORIGINAL_FACTORY;
            }

            Log.e(TAG, "ensureDelegate: Original factory name resolved: " + originalFactoryName);

            if (originalFactoryName != null && !originalFactoryName.isEmpty()
                    && !originalFactoryName.equals("REPLACE_ORIGINAL_FACTORY")
                    && !originalFactoryName.equals("androidx.core.app.CoreComponentFactory")) {
                Log.e(TAG, "ensureDelegate: Instantiating original factory: " + originalFactoryName);
                Class<?> clazz = cl.loadClass(originalFactoryName);
                originalFactory = (AppComponentFactory) clazz.newInstance();
                Log.e(TAG, "ensureDelegate: Delegating to " + originalFactoryName);
            }
        } catch (Exception e) {
            Log.e(TAG, "ensureDelegate: Failed to instantiate original factory", e);
        }
    }

    @Override
    public ClassLoader instantiateClassLoader(ClassLoader cl, ApplicationInfo aInfo) {
        Log.e(TAG, "instantiateClassLoader: Triggering early DEX load");
        sAppInfo = aInfo;
        ShellApplication.ensureDexLoaded(aInfo, cl);
        return super.instantiateClassLoader(cl, aInfo);
    }

    @Override
    public Application instantiateApplication(ClassLoader cl, String className)
            throws InstantiationException, IllegalAccessException, ClassNotFoundException {
        Log.e(TAG, "instantiateApplication: " + className);
        if (className.equals("com.kapp.shell.ShellApplication")) {
            return super.instantiateApplication(cl, className);
        }
        ensureDelegate(cl);
        if (originalFactory != null) {
            return originalFactory.instantiateApplication(cl, className);
        }
        return super.instantiateApplication(cl, className);
    }

    @Override
    public Activity instantiateActivity(ClassLoader cl, String className, Intent intent)
            throws InstantiationException, IllegalAccessException, ClassNotFoundException {
        Log.e(TAG, "instantiateActivity: " + className);
        ensureDelegate(cl);
        if (originalFactory != null) {
            return originalFactory.instantiateActivity(cl, className, intent);
        }
        return super.instantiateActivity(cl, className, intent);
    }

    @Override
    public BroadcastReceiver instantiateReceiver(ClassLoader cl, String className, Intent intent)
            throws InstantiationException, IllegalAccessException, ClassNotFoundException {
        Log.e(TAG, "instantiateReceiver: " + className);
        ensureDelegate(cl);
        if (originalFactory != null) {
            return originalFactory.instantiateReceiver(cl, className, intent);
        }
        return super.instantiateReceiver(cl, className, intent);
    }

    @Override
    public Service instantiateService(ClassLoader cl, String className, Intent intent)
            throws InstantiationException, IllegalAccessException, ClassNotFoundException {
        Log.e(TAG, "instantiateService: " + className);
        ensureDelegate(cl);
        if (originalFactory != null) {
            return originalFactory.instantiateService(cl, className, intent);
        }
        return super.instantiateService(cl, className, intent);
    }

    @Override
    public ContentProvider instantiateProvider(ClassLoader cl, String className)
            throws InstantiationException, IllegalAccessException, ClassNotFoundException {
        Log.e(TAG, "instantiateProvider: " + className);
        ensureDelegate(cl);
        if (originalFactory != null) {
            return originalFactory.instantiateProvider(cl, className);
        }
        return super.instantiateProvider(cl, className);
    }
}
