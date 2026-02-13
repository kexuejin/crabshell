import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import pack


def write_zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            zf.writestr(name, content)


class ConvertApkToAabTests(unittest.TestCase):
    def test_convert_apk_to_aab_replaces_mmkv_lib_and_streams_without_extractall(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            original_aab = temp / "input.aab"
            hardened_apk = temp / "hardened.apk"
            output_aab = temp / "output.aab"

            write_zip(
                original_aab,
                {
                    "BundleConfig.pb": b"bundle-config",
                    "base/manifest/AndroidManifest.xml": b"manifest",
                    "base/dex/classes.dex": b"old-dex",
                    "base/lib/arm64-v8a/libmmkv.so": b"old-mmkv-lib",
                    "base/lib/arm64-v8a/libold.so": b"old-lib",
                    "base/assets/old.txt": b"old-asset",
                },
            )
            write_zip(
                hardened_apk,
                {
                    "classes.dex": b"new-dex-1",
                    "classes2.dex": b"new-dex-2",
                    "lib/arm64-v8a/libmmkv.so": b"new-mmkv-lib",
                    "assets/new.txt": b"new-asset",
                },
            )

            with mock.patch(
                "pack.zipfile.ZipFile.extractall",
                side_effect=AssertionError("extractall should not be used"),
            ):
                resolved = pack.convert_apk_to_aab(
                    str(hardened_apk), str(output_aab), str(original_aab), temp_dir
                )

            self.assertEqual(resolved, str(output_aab))

            with zipfile.ZipFile(output_aab, "r") as zf:
                names = set(zf.namelist())
                self.assertIn("BundleConfig.pb", names)
                self.assertIn("base/manifest/AndroidManifest.xml", names)
                self.assertIn("base/dex/classes.dex", names)
                self.assertIn("base/dex/classes2.dex", names)
                self.assertIn("base/lib/arm64-v8a/libmmkv.so", names)
                self.assertIn("base/assets/new.txt", names)
                self.assertNotIn("base/lib/arm64-v8a/libold.so", names)
                self.assertNotIn("base/assets/old.txt", names)

                self.assertEqual(zf.read("base/dex/classes.dex"), b"new-dex-1")
                self.assertEqual(zf.read("base/dex/classes2.dex"), b"new-dex-2")
                self.assertEqual(zf.read("base/lib/arm64-v8a/libmmkv.so"), b"new-mmkv-lib")
                self.assertEqual(zf.read("base/assets/new.txt"), b"new-asset")

    def test_convert_apk_to_aab_keeps_original_lib_assets_when_missing_in_apk(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            original_aab = temp / "input.aab"
            hardened_apk = temp / "hardened.apk"
            output_aab = temp / "output.aab"

            write_zip(
                original_aab,
                {
                    "BundleConfig.pb": b"bundle-config",
                    "base/dex/classes.dex": b"old-dex",
                    "base/lib/arm64-v8a/libkeep.so": b"keep-lib",
                    "base/assets/keep.txt": b"keep-asset",
                },
            )
            write_zip(
                hardened_apk,
                {
                    "classes.dex": b"new-dex",
                },
            )

            pack.convert_apk_to_aab(str(hardened_apk), str(output_aab), str(original_aab), temp_dir)

            with zipfile.ZipFile(output_aab, "r") as zf:
                names = set(zf.namelist())
                self.assertIn("base/dex/classes.dex", names)
                self.assertIn("base/lib/arm64-v8a/libkeep.so", names)
                self.assertIn("base/assets/keep.txt", names)
                self.assertEqual(zf.read("base/dex/classes.dex"), b"new-dex")
                self.assertEqual(zf.read("base/lib/arm64-v8a/libkeep.so"), b"keep-lib")
                self.assertEqual(zf.read("base/assets/keep.txt"), b"keep-asset")


if __name__ == "__main__":
    unittest.main()
