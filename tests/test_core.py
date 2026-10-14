import tempfile
import unittest
from pathlib import Path

import core


class TempoMapTests(unittest.TestCase):
    def test_read_rpp_and_export_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.rpp"
            source.write_text(
                "<REAPER_PROJECT 0.1\n"
                "TEMPO 120 4 4\n"
                "<TEMPOENVEX\n"
                "PT 0 120 1 0\n"
                "PT 2 90 0 0\n"
                ">\n>\n"
            )
            tempo_map = core.read_tempo_map(source)
            self.assertGreaterEqual(len(tempo_map.points), 2)
            self.assertEqual(tempo_map.points[0].bpm, 120)
            out = Path(tmp) / "tempo.csv"
            count = core.write_csv(tempo_map, out, core.ExportOptions())
            self.assertEqual(count, len(tempo_map.points))
            self.assertTrue(out.read_text().startswith("position,beat_qn"))

    def test_midi_export_can_be_read_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.rpp"
            source.write_text("TEMPO 100 4 4\n")
            tempo_map = core.read_tempo_map(source)
            out = Path(tmp) / "tempo.mid"
            count = core.write_midi(tempo_map, out, core.ExportOptions())
            self.assertGreater(count, 0)
            self.assertEqual(core.read_tempo_map(out).points[0].bpm, 100)

    def test_damaged_midi_has_readable_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "damaged.mid"
            source.write_bytes(b"MThd")
            with self.assertRaises(core.ReaderError):
                core.read_tempo_map(source)


if __name__ == "__main__":
    unittest.main()
