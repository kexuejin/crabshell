import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pack


class SelectKeyBytesTests(unittest.TestCase):
    def test_select_key_bytes_skip_build_reads_existing_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.rs"
            config_path.write_text(
                """
const KEY_PART_1: [u8; 32] = [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e, 0x0f, 0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1a, 0x1b, 0x1c, 0x1d, 0x1e, 0x1f, 0x20];
const KEY_PART_2: [u8; 32] = [0x20, 0x1f, 0x1e, 0x1d, 0x1c, 0x1b, 0x1a, 0x19, 0x18, 0x17, 0x16, 0x15, 0x14, 0x13, 0x12, 0x11, 0x10, 0x0f, 0x0e, 0x0d, 0x0c, 0x0b, 0x0a, 0x09, 0x08, 0x07, 0x06, 0x05, 0x04, 0x03, 0x02, 0x01];
                """.strip(),
                encoding="utf-8",
            )

            expected = bytes(
                [
                    0x21,
                    0x1D,
                    0x1D,
                    0x19,
                    0x19,
                    0x1D,
                    0x1D,
                    0x11,
                    0x11,
                    0x1D,
                    0x1D,
                    0x19,
                    0x19,
                    0x1D,
                    0x1D,
                    0x01,
                    0x01,
                    0x1D,
                    0x1D,
                    0x19,
                    0x19,
                    0x1D,
                    0x1D,
                    0x11,
                    0x11,
                    0x1D,
                    0x1D,
                    0x19,
                    0x19,
                    0x1D,
                    0x1D,
                    0x21,
                ]
            )

            resolved = pack.select_key_bytes(skip_build=True, packer_config_path=str(config_path))
            self.assertEqual(resolved, expected)

    def test_select_key_bytes_non_skip_build_generates_random_key(self):
        fixed_key = bytes([0x42] * 32)
        with mock.patch("pack.secrets.token_bytes", return_value=fixed_key) as token_bytes:
            resolved = pack.select_key_bytes(skip_build=False, packer_config_path="unused")

        self.assertEqual(resolved, fixed_key)
        token_bytes.assert_called_once_with(32)


if __name__ == "__main__":
    unittest.main()
