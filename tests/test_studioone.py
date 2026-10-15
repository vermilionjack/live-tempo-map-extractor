"""Synthetic Studio One 5.5.2-shape regression tests; NOT host verification."""
import importlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from core import ReaderError

FIXTURES = Path(__file__).parent / "fixtures" / "studioone"


class StudioOneTests(unittest.TestCase):
    def read(self, path):
        reader = importlib.import_module("readers.studioone")
        return reader.read_studioone(path, lambda _: None)

    def test_step_tempo_and_meter_merge(self):
        result = self.read(FIXTURES / "steps.song")
        self.assertEqual([(p.beat, p.time, p.bpm, p.num, p.den) for p in result.points],
                         [(0, 0, 120, 4, 4), (16, 8, 120, 3, 4),
                          (32, 16, 60, 3, 4), (40, 24, 90, 3, 4)])
        self.assertTrue(all(not p.ramp for p in result.points))
        self.assertTrue(any("EXPERIMENTAL" in w for w in result.warnings))

    def test_project_end_seconds_convert_through_tempo_map(self):
        result = self.changed('x:id="Root"', 'x:id="Root" length="30"')
        self.assertEqual(result.project_end_beat, 49)

    def changed(self, old, new):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "changed.song"
            with zipfile.ZipFile(FIXTURES / "steps.song") as original:
                xml = original.read("Song/song.xml").decode().replace(old, new)
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("Song/song.xml", xml)
            return self.read(path)

    def test_rejects_curves_and_unknown_target_content(self):
        cases = [("curveType=\"0\"", "curveType=\"1\""),
                 ("<TempoMapSegment", "<OtherTarget"),
                 ("tempo=\"0.5\"", "tempo=\"0.5\" tension=\"0.3\""),
                 ("tempo=\"0.5\"", "tempo=\"0.5\" endTempo=\"1\"")]
        for old, new in cases:
            with self.subTest(new=new), self.assertRaises(ReaderError):
                self.changed(old, new)

    def test_rejects_invalid_numbers_and_discontinuous_segments(self):
        cases = [("tempo=\"0.5\"", "tempo=\"0\""),
                 ("tempo=\"0.5\"", "tempo=\"-1\""),
                 ("tempo=\"0.5\"", "tempo=\"nan\""),
                 ("end=\"32\"", "end=\"31\""),
                 ("end=\"32\"", "end=\"33\""),
                 ("end=\"1e200\"", "end=\"64\""),
                 ("start=\"32\"", "start=\"-32\""),
                 ("start=\"40\"", "start=\"32\""),
                 ("numerator=\"3\"", "numerator=\"0\""),
                 ("denominator=\"4\"", "denominator=\"3\""),
                 ("numerator=\"3\"", "numerator=\"three\""),
                 ("<TimeSignatureMapSegment", "<WrongMeterTarget")]
        for old, new in cases:
            with self.subTest(new=new), self.assertRaises(ReaderError):
                self.changed(old, new)

    def test_rejects_document_types(self):
        with self.assertRaisesRegex(ReaderError, "DTD|entity"):
            self.changed('<Song>', '<!DOCTYPE Song [<!ENTITY t "0.5">]><Song>')

    def test_rejects_extra_global_maps(self):
        with self.assertRaisesRegex(ReaderError, "ambiguous|unsupported"):
            self.changed('<TempoMap x:id="tempoMap">',
                         '<TempoMap x:id="otherTarget"/><TempoMap x:id="tempoMap">')

    def test_declared_x_namespace(self):
        result = self.changed('<Song>', '<Song xmlns:x="http://www.presonus.com">')
        self.assertEqual(len(result.points), 4)

    def test_archive_and_layout_errors_are_reader_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.song"
            for payload in [b"not zip", b"PK"]:
                path.write_bytes(payload)
                with self.assertRaises(ReaderError):
                    self.read(path)
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("song.xml", "<Song/>")
            with self.assertRaisesRegex(ReaderError, "Song/song.xml"):
                self.read(path)
        for old, new in [('defaultTimeFormat="2"', 'defaultTimeFormat="1"'),
                         ('x:id="timeContext"', 'x:id="audioClipContext"'),
                         ('<TempoMap x:id="tempoMap">', '<TempoMap x:id="tempoMap"/>'),
                         ('<Song>', '<Unknown>')]:
            with self.subTest(new=new), self.assertRaises(ReaderError):
                self.changed(old, new)

    def test_rejects_unknown_terminal_sentinel(self):
        with self.assertRaisesRegex(ReaderError, "sentinel"):
            self.changed('end="1e200"', 'end="1e199"')

    def test_rejects_meter_beyond_terminal_sentinel(self):
        with self.assertRaisesRegex(ReaderError, "position"):
            self.changed('start="16"', 'start="1e299"')

    def test_rejects_nonfinite_integrated_time(self):
        with self.assertRaisesRegex(ReaderError, "time"):
            self.changed('tempo="0.5"', 'tempo="1e308"')

    def test_rejects_utf16_entity_document(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "entity.song"
            with zipfile.ZipFile(FIXTURES / "steps.song") as z:
                xml = z.read("Song/song.xml").decode().replace('encoding="UTF-8"', 'encoding="UTF-16"')
            xml = xml.replace('<Song>', '<!DOCTYPE Song [<!ENTITY t "0.5">]><Song>')
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("Song/song.xml", xml.encode("utf-16"))
            with self.assertRaises(ReaderError):
                self.read(path)


if __name__ == "__main__":
    unittest.main()
