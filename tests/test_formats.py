"""Public dispatch and explicit experimental opt-in regressions."""
import unittest
from pathlib import Path
from unittest.mock import patch
import core


class FormatDispatchTests(unittest.TestCase):
    def test_new_readers_are_registered(self):
        for extension in ('.dawproject', '.mmp', '.mmpz', '.ardour', '.song'):
            with self.subTest(extension=extension):
                self.assertIn(extension, core.SUPPORTED_EXTENSIONS)
        self.assertNotIn('.flp', core.SUPPORTED_EXTENSIONS)

    def test_experimental_dispatch_requires_opt_in_and_always_warns(self):
        for extension in ('.dawproject', '.mmp', '.mmpz', '.song'):
            with self.subTest(extension=extension):
                path = Path('example' + extension)
                with self.assertRaisesRegex(core.ReaderError, '[Ee]xperimental'):
                    core.read_tempo_map(path)
                with patch.dict(core.READERS, {extension: lambda p, progress: core.TempoMap(p, [core.TempoPoint(0, 0, 123)])}):
                    result = core.read_tempo_map(path, allow_experimental=True)
                    self.assertTrue(any('EXPERIMENTAL' in w for w in result.warnings))

    def test_unimplemented_formats_are_not_advertised_as_supported(self):
        for extension in ('.flp', '.ptx', '.bwproject', '.logicx', '.cpr', '.npr', '.vip'):
            with self.subTest(extension=extension):
                with self.assertRaisesRegex(core.ReaderError, 'not implemented|not supported'):
                    core.read_tempo_map(Path('example' + extension))


if __name__ == '__main__':
    unittest.main()
