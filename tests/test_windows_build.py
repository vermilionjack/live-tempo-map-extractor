from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from build_support.build_windows import collect_icu_binaries


class WindowsBuildTests(unittest.TestCase):
    def test_collects_all_qt_icu_runtime_dlls(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "PySide6"
            qt_bin = root / "Qt6" / "bin"
            qt_bin.mkdir(parents=True)
            names = ["icudt77.dll", "icuin77.dll", "icuuc77.dll", "Qt6Core.dll"]
            for name in names:
                (qt_bin / name).write_bytes(b"fixture")
            result = collect_icu_binaries(root)
            self.assertEqual({p.name for p in result}, set(names[:3]))

    def test_fails_when_a_required_icu_component_is_missing(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "PySide6"
            root.mkdir()
            for name in ("icudt77.dll", "icuin77.dll"):
                (root / name).write_bytes(b"fixture")
            with self.assertRaisesRegex(RuntimeError, "icuuc"):
                collect_icu_binaries(root)


if __name__ == "__main__":
    unittest.main()
