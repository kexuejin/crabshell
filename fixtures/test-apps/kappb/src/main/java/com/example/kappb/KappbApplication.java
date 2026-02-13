package com.example.kappb;

import android.app.Application;

import com.tencent.mmkv.MMKV;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;

public class KappbApplication extends Application {
    private static final String PROBE_KEY = "boot_probe_key";
    private static final String PROBE_FILE = "mmkv_boot_probe.txt";

    @Override
    public void onCreate() {
        super.onCreate();
        try {
            MMKV.initialize(this);
            MMKV mmkv = MMKV.defaultMMKV();
            if (mmkv == null) {
                throw new IllegalStateException("MMKV.defaultMMKV() returned null");
            }

            mmkv.encode(PROBE_KEY, "ok");
            String value = mmkv.decodeString(PROBE_KEY, "");
            if (!"ok".equals(value)) {
                throw new IllegalStateException("MMKV probe mismatch: " + value);
            }

            writeProbeResult("ok");
        } catch (Throwable throwable) {
            writeProbeResult("error:" + throwable.getClass().getSimpleName());
            throw new RuntimeException("MMKV initialization probe failed", throwable);
        }
    }

    private void writeProbeResult(String result) {
        File probeFile = new File(getFilesDir(), PROBE_FILE);
        try (FileOutputStream stream = new FileOutputStream(probeFile, false)) {
            stream.write(result.getBytes(StandardCharsets.UTF_8));
            stream.flush();
        } catch (Exception ignored) {
        }
    }
}
