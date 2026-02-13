import unittest
from types import SimpleNamespace
from unittest import mock

import pack


class PackBuildFlowTests(unittest.TestCase):
    def test_maybe_build_toolchain_does_not_build_shell(self):
        with mock.patch("pack.build_packer") as build_packer, mock.patch(
            "pack.patch_shell_loader_constants"
        ) as patch_constants, mock.patch("pack.build_shell") as build_shell:
            pack.maybe_build_toolchain(False, "com.example.App", "androidx.core.app.CoreComponentFactory")

        build_packer.assert_called_once_with()
        patch_constants.assert_called_once_with(
            "com.example.App", "androidx.core.app.CoreComponentFactory"
        )
        build_shell.assert_not_called()

    def test_build_shell_only_builds_shell_native_and_apk(self):
        with mock.patch("pack.find_java_cmd", return_value="/usr/bin/java"), mock.patch(
            "pack.java_home_from_cmd", return_value="/fake/java/home"
        ), mock.patch(
            "pack.run_checked_command"
        ) as run_checked_command, mock.patch(
            "pack.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
        ), mock.patch(
            "pack.os.path.exists", return_value=True
        ), mock.patch.dict(
            "pack.os.environ", {"PATH": "/usr/bin", "ANDROID_NDK_HOME": "/fake/ndk"}, clear=False
        ):
            pack.build_shell()

        actions = [call.args[1] for call in run_checked_command.call_args_list]
        self.assertEqual(actions, ["Build Shell (Native)"])


if __name__ == "__main__":
    unittest.main()
