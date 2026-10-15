import tempfile
import unittest
from pathlib import Path

import core


class TempoMapTests(unittest.TestCase):
    # ALS coverage lives in test_als.py, with real project fixtures and separately
    # labelled synthetic XML. The old ALS helper invented meter bit-packing.
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
            self.assertEqual([(p.beat, p.time, p.bpm, p.ramp) for p in tempo_map.points],
                             [(0, 0, 120, False), (4, 2, 90, False)])
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
            self.assertEqual(count, 1)
            self.assertEqual(core.read_tempo_map(out).points[0].bpm, 100)

    def test_midi_export_reaches_project_end_for_static_tempo(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.rpp"
            tempo_map = core.TempoMap(source, [core.TempoPoint(0, 0, 100)],
                                      project_end_beat=64)
            out = Path(tmp) / "tempo.mid"
            core.write_midi(tempo_map, out, core.ExportOptions())
            exported = core.read_tempo_map(out)
            self.assertEqual(exported.project_end_beat, 64)

    def test_reaper_project_end_uses_last_item_end_not_last_tempo_point(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.rpp"
            source.write_text(
                "TEMPO 120 4 4\n"
                "<TRACK\n"
                "<ITEM\nPOSITION 0\nLENGTH 24\n>\n>\n"
            )
            tempo_map = core.read_tempo_map(source)
            self.assertEqual(tempo_map.project_end_beat, 48)

    def test_damaged_midi_has_readable_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "damaged.mid"
            source.write_bytes(b"MThd")
            with self.assertRaises(core.ReaderError):
                core.read_tempo_map(source)


if __name__ == "__main__":
    unittest.main()
