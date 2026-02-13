import unittest
import tempfile
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pack


class PackMainHelpersTests(unittest.TestCase):
    def test_normalize_cli_list(self):
        self.assertEqual(pack.normalize_cli_list(None), [])
        self.assertEqual(pack.normalize_cli_list("one"), ["one"])
        self.assertEqual(pack.normalize_cli_list(["one", "", "two"]), ["one", "two"])

    def test_resolve_output_format_and_extension_auto_aab(self):
        with mock.patch("pack.is_aab_file", return_value=True):
            is_aab_input, output_format, output = pack.resolve_output_format_and_extension(
                "input.aab", "out.apk", "auto"
            )

        self.assertTrue(is_aab_input)
        self.assertEqual(output_format, "aab")
        self.assertEqual(output, "out.aab")

    def test_resolve_output_format_and_extension_force_apk(self):
        with mock.patch("pack.is_aab_file", return_value=True):
            is_aab_input, output_format, output = pack.resolve_output_format_and_extension(
                "input.aab", "out.aab", "apk"
            )

        self.assertTrue(is_aab_input)
        self.assertEqual(output_format, "apk")
        self.assertEqual(output, "out.apk")

    def test_collect_runtime_lists_merges_config_and_defaults(self):
        args = SimpleNamespace(
            keep_class=None,
            keep_prefix=["com.runtime.keep"],
            keep_lib=None,
            encrypt_asset=None,
        )
        config = {
            "keep_class": ["com.config.KeepClass"],
            "keep_lib": "sqlite",
            "encrypt_asset": ["assets/*.js"],
        }

        with mock.patch(
            "pack.extract_keep_classes_from_decoded_manifest",
            return_value=["com.manifest.Entry"],
        ):
            keep_classes, keep_prefixes, keep_libs, encrypt_assets = pack.collect_runtime_lists(
                args, config, "ignored"
            )

        self.assertEqual(
            keep_classes,
            ["com.manifest.Entry", "com.config.KeepClass"],
        )
        self.assertEqual(keep_prefixes, ["com.runtime.keep"])
        self.assertEqual(keep_libs, ["sqlite"])
        self.assertEqual(encrypt_assets, ["assets/*.js"])

    def test_collect_runtime_lists_keeps_mmkv_only_when_explicitly_requested(self):
        args = SimpleNamespace(
            keep_class=None,
            keep_prefix=None,
            keep_lib=None,
            encrypt_asset=None,
        )
        config = {"keep_lib": ["mmkv"]}

        with mock.patch(
            "pack.extract_keep_classes_from_decoded_manifest",
            return_value=[],
        ):
            _, _, keep_libs, _ = pack.collect_runtime_lists(args, config, "ignored")

        self.assertEqual(keep_libs, ["mmkv"])

    def test_resolve_ks_pass_prefers_cli_then_config_then_env(self):
        with mock.patch.dict("pack.os.environ", {"CRABSHELL_KS_PASS": "env-pass"}, clear=False):
            self.assertEqual(pack.resolve_ks_pass("cli-pass", "cfg-pass"), "cli-pass")
            self.assertEqual(pack.resolve_ks_pass(None, "cfg-pass"), "cfg-pass")
            self.assertEqual(pack.resolve_ks_pass(None, None), "env-pass")

    def test_decode_and_patch_target_manifest_uses_manifest_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            target_apk = workspace / "target.apk"
            target_apk.write_bytes(b"fake-apk-content")

            cache_root = workspace / "manifest-cache"
            cache_root.mkdir(parents=True, exist_ok=True)

            use_rebuilt_resources = False
            cache_key = pack.compute_manifest_cache_key(str(target_apk), use_rebuilt_resources)
            cache_dir = cache_root / cache_key
            cache_dir.mkdir(parents=True, exist_ok=True)

            (cache_dir / "AndroidManifest_patched.xml").write_bytes(b"<manifest/>")
            (cache_dir / "meta.json").write_text(
                '{"original_app":"com.example.App","original_factory":"androidx.core.app.CoreComponentFactory"}',
                encoding="utf-8",
            )

            with mock.patch.dict(
                "pack.os.environ",
                {
                    "CRABSHELL_MANIFEST_CACHE_DIR": str(cache_root),
                    "CRABSHELL_MANIFEST_CACHE": "1",
                    "CRABSHELL_USE_REBUILT_RESOURCES": "0",
                },
                clear=False,
            ), mock.patch("pack.ensure_apktool_cmd", side_effect=AssertionError("cache hit should avoid apktool")):
                patched_manifest, resources_arsc, original_app, original_factory = (
                    pack.decode_and_patch_target_manifest(str(target_apk), str(workspace))
                )

            self.assertEqual(Path(patched_manifest).read_bytes(), b"<manifest/>")
            self.assertIsNone(resources_arsc)
            self.assertEqual(original_app, "com.example.App")
            self.assertEqual(original_factory, "androidx.core.app.CoreComponentFactory")

    def test_compute_manifest_cache_key_changes_with_cache_salt_env(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            apk_path = Path(temp_dir) / "target.apk"
            apk_path.write_bytes(b"same-content")

            with mock.patch.dict("pack.os.environ", {"CRABSHELL_MANIFEST_CACHE_SALT": "salt-a"}, clear=False):
                key_a = pack.compute_manifest_cache_key(str(apk_path), False)
            with mock.patch.dict("pack.os.environ", {"CRABSHELL_MANIFEST_CACHE_SALT": "salt-b"}, clear=False):
                key_b = pack.compute_manifest_cache_key(str(apk_path), False)

            self.assertNotEqual(key_a, key_b)

    def test_compute_manifest_cache_key_changes_with_provider_env(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            apk_path = Path(temp_dir) / "target.apk"
            apk_path.write_bytes(b"same-content")

            with mock.patch.dict(
                "pack.os.environ",
                {"CRABSHELL_BOOTSTRAP_PROVIDER_CLASS": "com.kapp.shell.ProviderA"},
                clear=False,
            ):
                key_a = pack.compute_manifest_cache_key(str(apk_path), False)
            with mock.patch.dict(
                "pack.os.environ",
                {"CRABSHELL_BOOTSTRAP_PROVIDER_CLASS": "com.kapp.shell.ProviderB"},
                clear=False,
            ):
                key_b = pack.compute_manifest_cache_key(str(apk_path), False)

            self.assertNotEqual(key_a, key_b)

    def test_prune_manifest_cache_removes_entries_older_than_ttl(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir)
            old_dir = cache_root / "old"
            keep_dir = cache_root / "keep"
            old_dir.mkdir()
            keep_dir.mkdir()

            os.utime(old_dir, (100, 100))
            os.utime(keep_dir, (980, 980))

            removed = pack.prune_manifest_cache(
                str(cache_root),
                max_entries=0,
                ttl_seconds=60,
                now_ts=1000,
            )

            self.assertIn(str(old_dir), removed)
            self.assertFalse(old_dir.exists())
            self.assertTrue(keep_dir.exists())

    def test_prune_manifest_cache_keeps_newest_by_max_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir)
            entry1 = cache_root / "entry-1"
            entry2 = cache_root / "entry-2"
            entry3 = cache_root / "entry-3"
            entry1.mkdir()
            entry2.mkdir()
            entry3.mkdir()

            os.utime(entry1, (100, 100))
            os.utime(entry2, (200, 200))
            os.utime(entry3, (300, 300))

            removed = pack.prune_manifest_cache(
                str(cache_root),
                max_entries=2,
                ttl_seconds=0,
                now_ts=1000,
                preserve_paths={str(entry1)},
            )

            self.assertIn(str(entry2), removed)
            self.assertFalse(entry2.exists())
            self.assertTrue(entry1.exists())
            self.assertTrue(entry3.exists())


if __name__ == "__main__":
    unittest.main()
