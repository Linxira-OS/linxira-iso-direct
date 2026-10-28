"""安装器启动契约: 134(SIGABRT) 的三层防回归测试。

134 的成因有两类, 都必须挡住:
1. pkexec 剥离会话环境 -> Qt 拿到 XDG_RUNTIME_DIR 却没有 wayland socket;
2. Calamares 的 appData 下缺 qml/ -> initQmlModulesDir FATAL。

这里用桩(pkexec/calamares)实际执行启动器, 断言它注入的环境与回退选择,
而不是只在源码里找字符串。仅在 POSIX 环境运行(CI 的 ubuntu-latest)。
"""

import os
import pathlib
import subprocess
import sys
import tempfile
import unittest


PROFILE_ROOT = pathlib.Path(__file__).parents[1]
INSTALLER_SHELL = PROFILE_ROOT / "airootfs/usr/local/bin/linxira-installer-shell"
LIVE_TMPFILES = PROFILE_ROOT / "airootfs/usr/lib/tmpfiles.d/linxira-live-tmpfiles.conf"


@unittest.skipUnless(sys.platform.startswith("linux"), "needs a POSIX shell")
class InstallerLaunchContractTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = pathlib.Path(self._tmp.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.runtime = self.root / "runtime"
        self.runtime.mkdir()
        self.env_dump = self.root / "calamares-env.txt"
        self.calamares = self.bin_dir / "calamares"
        self.calamares.write_text(
            "#!/bin/sh\n"
            f'{{ env | sort; }} > "{self.env_dump}"\n'
            "exit 0\n",
            encoding="utf-8",
        )
        self.calamares.chmod(0o755)
        pkexec = self.bin_dir / "pkexec"
        pkexec.write_text('#!/bin/sh\nexec "$@"\n', encoding="utf-8")
        pkexec.chmod(0o755)

    def run_launcher(self, extra_env=None):
        env = {
            "PATH": f"{self.bin_dir}:/usr/bin:/bin",
            "HOME": str(self.root),
            "LINXIRA_INSTALLER_USER": os.environ.get("USER") or "root",
            "LINXIRA_RUNTIME_DIR": str(self.runtime),
            "LINXIRA_CALAMARES": str(self.calamares),
            "LINXIRA_APP_DATA": str(self.root / "appdata"),
            "LINXIRA_QML_TARGET": str(self.root / "qml"),
            "LINXIRA_WAYLAND_WAIT": "1",
        }
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            ["bash", str(INSTALLER_SHELL)],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def exported_env(self):
        text = self.env_dump.read_text(encoding="utf-8")
        return dict(
            line.split("=", 1)
            for line in text.splitlines()
            if "=" in line
        )

    def test_wayland_socket_is_detected_and_exported(self):
        (self.runtime / "wayland-0").touch()
        result = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        exported = self.exported_env()
        self.assertEqual(exported.get("QT_QPA_PLATFORM"), "wayland")
        self.assertEqual(exported.get("WAYLAND_DISPLAY"), "wayland-0")
        self.assertEqual(exported.get("XDG_SESSION_TYPE"), "wayland")
        self.assertEqual(exported.get("XDG_RUNTIME_DIR"), str(self.runtime))
        self.assertEqual(exported.get("XDG_CURRENT_DESKTOP", "").split(":")[0], "KDE")

    def test_falls_back_to_x11_without_a_wayland_socket(self):
        result = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        exported = self.exported_env()
        self.assertEqual(exported.get("QT_QPA_PLATFORM"), "xcb")
        self.assertEqual(exported.get("XDG_SESSION_TYPE"), "x11")
        self.assertEqual(exported.get("DISPLAY"), ":0")
        self.assertNotIn("WAYLAND_DISPLAY", exported)

    def test_second_wayland_socket_name_is_preserved(self):
        (self.runtime / "wayland-2").touch()
        result = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.exported_env().get("WAYLAND_DISPLAY"), "wayland-2")

    def test_missing_appdata_qml_is_repaired_before_launch(self):
        qml_target = self.root / "qml"
        qml_target.mkdir()
        (qml_target / "calamares").mkdir()
        result = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        linked = self.root / "appdata" / "qml"
        self.assertTrue(linked.is_symlink(), "launcher must repair qml/ before calamares starts")
        self.assertEqual(os.readlink(linked), str(qml_target))

    def test_profile_ships_no_bytecode(self):
        # 只检查「会被打包」的文件,也就是 git 跟踪的那些。用 rglob 扫工作区会把
        # 测试自己 import 模块时生成的 __pycache__ 也算进来,导致跑第二遍必挂。
        try:
            tracked = subprocess.run(
                ["git", "ls-files", "-z", "--", "airootfs"],
                cwd=PROFILE_ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.split("\0")
        except (OSError, subprocess.CalledProcessError):
            tracked = [
                str(path.relative_to(PROFILE_ROOT))
                for path in (PROFILE_ROOT / "airootfs").rglob("*")
                if path.suffix == ".pyc" or path.name == "__pycache__"
            ]
        stale = [
            name
            for name in tracked
            if name.endswith(".pyc")
            or "/__pycache__/" in name
            or name.endswith("/__pycache__")
        ]
        self.assertEqual(stale, [], "profile must not ship generated bytecode")

    def test_live_tmpfiles_also_links_calamares_qml(self):
        # 开机兜底与启动器自愈是两条独立路径, 缺一不可丢。
        self.assertIn(
            "L+ /etc/calamares/qml - - - - /usr/share/calamares/qml",
            LIVE_TMPFILES.read_text(encoding="utf-8"),
        )

    def test_nothing_else_launches_calamares_directly(self):
        # 判定标准是「真的把它当命令执行」: 行首/exec 后面出现 calamares, 或
        # .desktop 的 Exec=。polkit 规则与配置文件里出现二进制路径属声明, 跳过。
        import re

        launches = re.compile(r"^\s*(?:exec\s+)?(?:/usr/bin/|/bin/)?calamares\b")
        exec_line = re.compile(r"^\s*Exec=.*\bcalamares\b")
        offenders = []
        for path in (PROFILE_ROOT / "airootfs").rglob("*"):
            if not path.is_file() or path == INSTALLER_SHELL:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for line in text.splitlines():
                if launches.search(line) or (path.suffix == ".desktop" and exec_line.search(line)):
                    offenders.append(f"{path.relative_to(PROFILE_ROOT)}: {line.strip()}")
                    break
        self.assertEqual(offenders, [], "calamares must only start through linxira-installer-shell")


if __name__ == "__main__":
    unittest.main()
