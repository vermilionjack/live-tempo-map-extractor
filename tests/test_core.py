import gzip
import tempfile
import unittest
from pathlib import Path

import core


def _make_als_xml(bpm_values, meters=None, time_sig_int=0x0424):
    """Build a minimal .als (XML) string with a MasterTrack tempo automation.
    time_sig_int encodes (numerator,denominator): default 4/4 -> 0x0424."""
    from xml.sax.saxutils import escape
    events = ""
    for bpm in bpm_values:
        events += f'<FloatEvent Time="0" Value="{bpm}"/>'
    meter_events = ""
    for num, den in (meters or []):
        val = (num << 8) | den
        meter_events += f'<FloatEvent Time="0" Value="{val}"/>'
    return (
        '<Ableton>'
        '<LiveSet>'
        '<MasterTrack Id="0">'
        '<DeviceChain>'
        '<Mixer>'
        f'<Tempo Id="0"><ArrangerAutomation><Events>{events}</Events></ArrangerAutomation></Tempo>'
        f'<TimeSignature Id="1"><ArrangerAutomation><Events>{meter_events}</Events></ArrangerAutomation></TimeSignature>'
        '</Mixer>'
        '</DeviceChain>'
        '</MasterTrack>'
        '</LiveSet>'
        '</Ableton>'
    )


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

    def test_read_als_single_tempo(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "single.als"
            source.write_bytes(gzip.compress(_make_als_xml([120.0]).encode()))
            tempo_map = core.read_tempo_map(source)
            self.assertEqual(tempo_map.points[0].bpm, 120)

    def test_read_als_negative_time_sentinel(self):
        # Ableton emits the initial tempo with a large-negative sentinel Time.
        # That sentinel must be normalised to beat 0, not dropped.
        xml = (
            '<Ableton><LiveSet><MasterTrack><DeviceChain><Mixer>'
            '<Tempo Id="0"><ArrangerAutomation><Events>'
            '<FloatEvent Time="-63072000" Value="103"/>'
            '</Events></ArrangerAutomation></Tempo></Mixer></DeviceChain></MasterTrack></LiveSet></Ableton>'
        )
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sentinel.als"
            source.write_bytes(gzip.compress(xml.encode()))
            tempo_map = core.read_tempo_map(source)
            self.assertEqual(tempo_map.points[0].bpm, 103)
            self.assertAlmostEqual(tempo_map.points[0].beat, 0.0)

    def test_read_als_tempo_ramp(self):
        # Two events at the same beat -> the second overrides; with distinct
        # beats they form a ramp. Verify the map carries both values.
        xml = (
            '<Ableton><LiveSet><MasterTrack Id="0"><DeviceChain><Mixer>'
            '<Tempo Id="0">'
            '<ArrangerAutomation><Events>'
            '<FloatEvent Time="0" Value="120"/>'
            '<FloatEvent Time="8" Value="60"/>'
            '</Events></ArrangerAutomation>'
            '</Tempo></Mixer></DeviceChain></MasterTrack></LiveSet></Ableton>'
        )
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "ramp.als"
            source.write_bytes(gzip.compress(xml.encode()))
            tempo_map = core.read_tempo_map(source)
            bpms = [p.bpm for p in tempo_map.points]
            self.assertIn(120, bpms)
            self.assertIn(60, bpms)

    def test_read_als_not_gzip_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "bad.als"
            source.write_bytes(b"this is not gzip or xml")
            with self.assertRaises(core.ReaderError):
                core.read_tempo_map(source)

    def test_read_als_time_signature(self):
        xml = (
            '<Ableton><LiveSet><MasterTrack Id="0"><DeviceChain><Mixer>'
            '<Tempo Id="0">'
            '<ArrangerAutomation><Events><FloatEvent Time="0" Value="120"/></Events></ArrangerAutomation>'
            '</Tempo>'
            '<TimeSignature Id="1">'
            '<ArrangerAutomation><Events><FloatEvent Time="0" Value="68"/></Events></ArrangerAutomation>'
            '</TimeSignature>'
            '</Mixer></DeviceChain></MasterTrack></LiveSet></Ableton>'
        )
        val = 68  # 0x44 -> num=4 (>>8... actually 68=0x44 -> num=0,den=68? compute below)
        num, den = val >> 8, val & 0xFF  # (0, 68) — not a valid meter
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "ts.als"
            source.write_bytes(gzip.compress(xml.encode()))
            # 68 packs as 0x44; with num=0 this should be skipped -> default 4/4
            tempo_map = core.read_tempo_map(source)
            self.assertEqual(tempo_map.points[0].num, 4)
            self.assertEqual(tempo_map.points[0].den, 4)


if __name__ == "__main__":
    unittest.main()
