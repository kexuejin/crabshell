import unittest
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
        self.assertEqual(keep_libs, ["sqlite", "mmkv"])
        self.assertEqual(encrypt_assets, ["assets/*.js"])


if __name__ == "__main__":
    unittest.main()
