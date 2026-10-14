"""FLP rejection tests: base BPM must never masquerade as a tempo map."""
import importlib
import tempfile
import unittest
from pathlib import Path
from core import ReaderError

FIXTURES = Path(__file__).parent / "fixtures" / "flstudio"


class FLStudioTests(unittest.TestCase):
    def read(self, path):
        module = importlib.import_module("readers.flstudio")
        return module.read_flstudio(path, lambda _: None)

    def test_base_bpm_is_explicitly_unsupported(self):
        with self.assertRaisesRegex(ReaderError, "unsupported.*global tempo"):
            self.read(FIXTURES / "base-tempo.flp")


if __name__ == "__main__":
    unittest.main()
