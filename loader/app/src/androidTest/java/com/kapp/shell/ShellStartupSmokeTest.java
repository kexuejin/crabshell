package com.kapp.shell;

import static org.junit.Assert.assertEquals;

import android.content.Context;

import androidx.test.core.app.ApplicationProvider;
import androidx.test.ext.junit.runners.AndroidJUnit4;

import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class ShellStartupSmokeTest {
    @Test
    public void appContextIsAccessible() {
        Context appContext = ApplicationProvider.getApplicationContext();
        assertEquals("com.kapp.shell", appContext.getPackageName());
    }

    @Test
    public void ensureDexLoadedDoesNotThrow() {
        Context appContext = ApplicationProvider.getApplicationContext();
        ShellApplication.ensureDexLoaded(appContext);
    }
}
