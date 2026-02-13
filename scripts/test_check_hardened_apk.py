import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_hardened_apk as checker


class CheckHardenedApkTests(unittest.TestCase):
    def _write_apk(self, entries: dict[str, bytes]) -> Path:
        temp_dir = tempfile.mkdtemp()
        apk_path = Path(temp_dir) / "sample.apk"
        with zipfile.ZipFile(apk_path, "w") as zf:
            for name, content in entries.items():
                zf.writestr(name, content)
        return apk_path

    def test_validate_hardened_apk_passes_with_expected_layout(self):
        apk = self._write_apk(
            {
                "classes.dex": b"bootstrap",
                "assets/kapp_payload.bin": b"payload",
                "lib/arm64-v8a/libshell.so": b"shell",
            }
        )
        errors = checker.validate_hardened_apk(
            apk_path=apk,
            required_entries=["assets/kapp_payload.bin"],
            forbidden_libs=["mmkv"],
            min_plaintext_dex=1,
            max_plaintext_dex=1,
        )
        self.assertEqual(errors, [])

    def test_validate_hardened_apk_reports_missing_required_entry(self):
        apk = self._write_apk({"classes.dex": b"bootstrap"})
        errors = checker.validate_hardened_apk(
            apk_path=apk,
            required_entries=["assets/kapp_payload.bin"],
            forbidden_libs=[],
            min_plaintext_dex=None,
            max_plaintext_dex=None,
        )
        self.assertIn("Missing required entry: assets/kapp_payload.bin", errors)

    def test_validate_hardened_apk_reports_forbidden_lib(self):
        apk = self._write_apk(
            {
                "classes.dex": b"bootstrap",
                "assets/kapp_payload.bin": b"payload",
                "lib/arm64-v8a/libmmkv.so": b"mmkv",
            }
        )
        errors = checker.validate_hardened_apk(
            apk_path=apk,
            required_entries=["assets/kapp_payload.bin"],
            forbidden_libs=["mmkv"],
            min_plaintext_dex=None,
            max_plaintext_dex=None,
        )
        self.assertIn("Forbidden native library remains in APK: libmmkv.so", errors)

    def test_validate_hardened_apk_reports_plaintext_dex_overflow(self):
        apk = self._write_apk(
            {
                "classes.dex": b"bootstrap",
                "classes2.dex": b"leftover",
                "assets/kapp_payload.bin": b"payload",
            }
        )
        errors = checker.validate_hardened_apk(
            apk_path=apk,
            required_entries=["assets/kapp_payload.bin"],
            forbidden_libs=[],
            min_plaintext_dex=None,
            max_plaintext_dex=1,
        )
        self.assertTrue(any("Plaintext classes*.dex count too large" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
