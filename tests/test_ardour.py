"""Real upstream sessions plus explicitly synthetic boundary cases."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from readers.ardour import read_ardour
import core

FIXTURES = Path(__file__).parent / "fixtures" / "ardour"


class ArdourTests(unittest.TestCase):
    def read_xml(self, xml, **kwargs):
        # SYNTHETIC: XML written by the test, not an Ardour-generated session.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.ardour"
            path.write_text(xml, encoding="utf-8")
            return read_ardour(path, lambda value: None, **kwargs)

    def legacy_xml(self, tempo_extra="", meter_extra="", extra=""):
        # SYNTHETIC legacy serialization with explicit origin.
        return ('<Session><TempoMap>'
                '<Tempo start="1|1|0" beats-per-minute="120" note-type="4" {} />'
                '<Meter start="1|1|0" note-type="4" divisions-per-bar="4" {} />'
                '{}</TempoMap></Session>').format(tempo_extra, meter_extra, extra)

    def test_real_ardour_2_historical_meter_name(self):
        result = read_ardour(FIXTURES / "TestSession.ardour")
        p = result.points[0]
        self.assertEqual((p.beat, p.time, p.bpm, p.num, p.den), (0, 0, 145, 5, 4))

    def test_legacy_invalid_or_unsupported_never_falls_back(self):
        cases = [
            self.legacy_xml(tempo_extra='end-beats-per-minute="90"'),
            self.legacy_xml(tempo_extra='tempo-type="Ramped"'),
            self.legacy_xml(tempo_extra='active="no"'),
            self.legacy_xml(tempo_extra='frame="48000" pulse="1"'),
            self.legacy_xml(extra='<Tempo start="2|1|0" beats-per-minute="90"/>'),
            self.legacy_xml().replace('beats-per-minute="120"', 'beats-per-minute="nan"'),
            self.legacy_xml().replace('beats-per-minute="120"', 'beats-per-minute="0"'),
            self.legacy_xml().replace('divisions-per-bar="4"', 'divisions-per-bar="3.5"'),
            self.legacy_xml().replace('note-type="4"', 'note-type="0"'),
            self.legacy_xml().replace('note-type="4"', 'note-type="3"'),
            self.legacy_xml().replace('1|1|0', '2|1|0'),
            self.legacy_xml(extra='<Unexpected/>'),
            '<Session><TempoMap/></Session>',
            '<Session/>', '<Session><TempoMap/><TempoMap/></Session>',
            '<Other/>', '<Session>',
            '<!DOCTYPE Session [<!ENTITY bpm "120">]><Session/>',
        ]
        for xml in cases:
            with self.subTest(xml=xml):
                with self.assertRaises(core.ReaderError):
                    self.read_xml(xml)

    def test_legacy_note_type_converts_to_quarter_bpm(self):
        result = self.read_xml(self.legacy_xml().replace('note-type="4"', 'note-type="8"'))
        self.assertEqual((result.points[0].bpm, result.points[0].den), (60, 8))

    def modern_xml(self):
        # SYNTHETIC, source-shaped Temporal serialization; not a real session.
        return '''<Session version="7002" sample-rate="48000">
        <TempoMap superclocks-per-second="1000000"><Tempos>
        <Tempo npm="120" enpm="120" note-type="4" type="Constant"
               sclock="0" quarters="0:0" bbt="1|1|0" omega="0"/>
        <Tempo npm="90" enpm="90" note-type="4" type="Constant"
               sclock="2000000" quarters="4:0" bbt="2|1|0" omega="0"/>
        </Tempos><Meters>
        <Meter note-value="4" divisions-per-bar="4"
               sclock="0" quarters="0:0" bbt="1|1|0"/>
        <Meter note-value="8" divisions-per-bar="6"
               sclock="4666667" quarters="8:0" bbt="3|1|0"/>
        </Meters><MusicTimes/></TempoMap></Session>'''

    def test_modern_is_opt_in_experimental(self):
        with self.assertRaisesRegex(core.ReaderError, "experimental"):
            self.read_xml(self.modern_xml())
        result = self.read_xml(self.modern_xml(), allow_experimental=True)
        self.assertEqual([(p.beat, p.bpm, p.num, p.den, p.ramp) for p in result.points],
                         [(0, 120, 4, 4, False), (4, 90, 4, 4, False), (8, 90, 6, 8, False)])
        self.assertEqual([p.time for p in result.points], [0, 2, 4.666667])
        self.assertTrue(any("experimental" in warning.lower() for warning in result.warnings))

    def test_modern_real_rate_not_sample_rate_or_assumed_constant(self):
        xml = self.modern_xml().replace('1000000', '2000000').replace('sclock="2000000"',
               'sclock="4000000"').replace('sclock="4666667"', 'sclock="9333334"')
        result = self.read_xml(xml, allow_experimental=True)
        self.assertEqual([p.time for p in result.points], [0, 2, 4.666667])

    def test_modern_unsupported_or_inconsistent_rejected(self):
        xml = self.modern_xml()
        cases = [
            xml.replace(' superclocks-per-second="1000000"', ''),
            xml.replace('superclocks-per-second="1000000"', 'superclocks-per-second="0"'),
            xml.replace('enpm="120"', 'enpm="150"'),
            xml.replace('type="Constant"', 'type="Ramped"'),
            xml.replace('omega="0"', 'omega="0.1"'),
            xml.replace('omega="0"', 'continuing="yes" omega="0"'),
            xml.replace('<MusicTimes/>', '<MusicTimes><MusicTime/></MusicTimes>'),
            xml.replace('quarters="4:0"', 'quarters="5:0"'),
            xml.replace('sclock="2000000"', 'sclock="0"'),
            xml.replace('quarters="0:0"', 'quarters="0:1920"'),
            xml.replace('quarters="4:0"', 'quarters="bad"'),
            xml.replace('sclock="0"', 'sclock="-1"'),
            xml.replace('divisions-per-bar="6"', 'divisions-per-bar="6.5"'),
            xml.replace('note-value="8"', 'note-value="3"'),
            xml.replace('<Meters>', '<Meters><Unknown/>'),
            xml.replace('bbt="1|1|0"', 'bbt="2|1|0"'),
            xml.replace('enpm="90"', 'enpm="inf"'),
        ]
        for case in cases:
            with self.subTest(xml=case):
                with self.assertRaises(core.ReaderError):
                    self.read_xml(case, allow_experimental=True)

    def test_xml_entities_nested_legacy_and_extreme_meter_rejected(self):
        cases = [
            '<!DOCTYPE Session [<!ENTITY bpm "120">]>' + self.legacy_xml(),
            self.legacy_xml().replace('120', '&bpm;'),
            self.legacy_xml().replace('/>', '><Nested/></Tempo>', 1),
            self.legacy_xml().replace('divisions-per-bar="4"', 'divisions-per-bar="1e300"'),
        ]
        for case in cases:
            with self.subTest(xml=case):
                with self.assertRaises(core.ReaderError):
                    self.read_xml(case)

    def test_missing_file_is_reader_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(core.ReaderError):
                read_ardour(Path(directory) / "missing.ardour")

    def test_modern_fractional_beats_and_nonquarter_tempo(self):
        xml = self.modern_xml().replace('npm="120" enpm="120" note-type="4"',
                                       'npm="240" enpm="240" note-type="8"')
        xml = xml.replace('quarters="4:0"', 'quarters="4"')
        result = self.read_xml(xml, allow_experimental=True)
        self.assertEqual(result.points[0].bpm, 120)
        self.assertEqual(result.points[1].beat, 4)
        # Insert a quarter of a quarter-note at 125 ms before the later tempo.
        xml = xml.replace('<Tempo npm="90"', '''<Tempo npm="120" enpm="120"
             note-type="4" type="Constant" sclock="125000" quarters="0:480"
             bbt="1|1|480" omega="0"/><Tempo npm="90"''')
        result = self.read_xml(xml, allow_experimental=True)
        self.assertEqual((result.points[1].beat, result.points[1].time), (0.25, 0.125))

    def test_modern_colocated_tempo_meter_and_midbar_rejection(self):
        xml = self.modern_xml().replace('</Tempos>', '''<Tempo npm="100" enpm="100"
             note-type="4" type="Constant" sclock="4666667" quarters="8:0"
             bbt="3|1|0" omega="0"/></Tempos>''')
        result = self.read_xml(xml, allow_experimental=True)
        self.assertEqual(len(result.points), 3)
        self.assertEqual((result.points[-1].bpm, result.points[-1].num, result.points[-1].den),
                         (100, 6, 8))
        xml = self.modern_xml().replace('4666667', '2666667').replace('8:0', '5:0')
        with self.assertRaisesRegex(core.ReaderError, 'mid-bar'):
            self.read_xml(xml, allow_experimental=True)

    def test_public_fixture_bytes_match_pinned_revision(self):
        hashes = {
            "rec_enabled.ardour": "05da51e400f22319d56ab8f3aa034756d426f6cc5e6d233f38ed3462b71f6767",
            "TestSession.ardour": "6f44bda6e35ae06d695e40d0a466809fba1811fd8088840b012c387adecd6ea8",
        }
        for name, expected in hashes.items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest(), expected)

    def test_midi_export_accepts_reader_model(self):
        result = read_ardour(FIXTURES / "TestSession.ardour")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "tempo.mid"
            core.write_midi(result, target, core.ExportOptions())
            reread = core.read_midi(target, lambda value: None)
            self.assertAlmostEqual(reread.points[0].bpm, 145, places=3)
            self.assertEqual((reread.points[0].num, reread.points[0].den), (5, 4))

    def test_utf16_dtd_is_rejected(self):
        xml = '<!DOCTYPE Session [<!ENTITY bpm "120">]>' + self.legacy_xml()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.ardour"
            path.write_bytes(xml.encode("utf-16"))
            with self.assertRaises(core.ReaderError):
                read_ardour(path)

    def test_real_ardour_3_initial_map(self):
        progress = []
        result = read_ardour(FIXTURES / "rec_enabled.ardour", progress.append)
        self.assertIsInstance(result, core.TempoMap)
        self.assertEqual([(p.beat, p.time, p.bpm, p.num, p.den, p.ramp)
                          for p in result.points], [(0, 0, 120, 4, 4, False)])
        self.assertEqual(result.warnings, [])
        self.assertEqual(progress[-1], 1.0)


if __name__ == "__main__":
    unittest.main()
