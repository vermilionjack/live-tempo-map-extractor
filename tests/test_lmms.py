"""LMMS tests: real upstream files plus source-derived synthetic cases."""
from pathlib import Path
import importlib
import sys
import unittest
import tempfile
import struct
import zlib
import hashlib
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import ReaderError


def project(head, song=''):
    return ('<lmms-project type="song" version="1.0" creator="LMMS" creatorversion="1.2.2">'
            '<head>' + head + '</head><song>' + song + '</song></lmms-project>')


def automation(target='42', prog='0', points=((0, 120), (192, 90), (384, 150)),
               pos=0, length=576, mute=0):
    return ('<track type="5" muted="0"><automationpattern pos="%s" len="%s" prog="%s" mute="%s">'
            % (pos, length, prog, mute) + ''.join(
                '<time pos="%s" value="%s"/>' % pair for pair in points) +
            '<object id="%s"/></automationpattern></track>' % target)

class LmmsTests(unittest.TestCase):
    def test_upstream_fixture_hashes(self):
        folder = Path(__file__).parent / 'fixtures/lmms'
        manifest = json.loads((folder / 'manifest.json').read_text())
        self.assertEqual(len(manifest['fixtures']), 3)
        for entry in manifest['fixtures']:
            data = (folder / entry['file']).read_bytes()
            self.assertEqual(len(data), entry['bytes'])
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry['sha256'])

    def read_xml(self, xml, compressed=False):
        read = importlib.import_module('readers.lmms').read_lmms
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ('song.mmpz' if compressed else 'song.mmp')
            data = xml.encode()
            if compressed:
                data = struct.pack('>I', len(data)) + zlib.compress(data)
            path.write_bytes(data)
            return read(path, lambda value: None)

    def test_discrete_tempo_bound_by_id_not_name(self):
        xml = project('<bpm id="42" value="140" scale_type="linear"/>',
                      '<trackcontainer type="song">' + automation() + '</trackcontainer>')
        result = self.read_xml(xml)
        self.assertEqual([(p.beat, p.bpm) for p in result.points],
                         [(0, 120), (4, 90), (8, 150)])
        self.assertAlmostEqual(result.points[1].time, 2)
        self.assertAlmostEqual(result.points[2].time, 2 + 8 / 3)

    def test_project_end_comes_from_last_arrangement_pattern(self):
        song = '<trackcontainer><track><pattern pos="48" len="240"/></track></trackcontainer>'
        result = self.read_xml(project('<bpm value="120"/>', song))
        self.assertEqual(result.project_end_beat, 6)

    def test_reject_interpolated_tempo(self):
        for prog in ('1', '2'):
            with self.subTest(prog=prog), self.assertRaisesRegex(ReaderError, 'interpolat'):
                self.read_xml(project('<bpm id="42" value="140"/>',
                    '<trackcontainer>' + automation(prog=prog) + '</trackcontainer>'))

    def test_reject_tempo_controller(self):
        with self.assertRaisesRegex(ReaderError, 'controller'):
            self.read_xml(project('<bpm value="120"/><connection><bpm id="0"/></connection>'))

    def test_legacy_tempo_automation_is_not_silently_constant(self):
        with self.assertRaisesRegex(ReaderError, 'legacy'):
            self.read_xml(project('<automationpattern><bpm><time pos="0" value="120"/>'
                                  '<time pos="192" value="90"/></bpm></automationpattern>'))

    def test_unknown_time_shape_is_rejected(self):
        xml = project('<bpm id="42" value="140"/>', '<trackcontainer>' +
                      automation().replace('<time pos="0"', '<time outValue="130" pos="0"') +
                      '</trackcontainer>')
        with self.assertRaisesRegex(ReaderError, 'unknown.*automation'):
            self.read_xml(xml)

    def test_duplicate_target_id_is_rejected(self):
        xml = project('<bpm id="42" value="140"/>', '<trackcontainer><track><vol id="42"/>'
                      '</track>' + automation() + '</trackcontainer>')
        with self.assertRaisesRegex(ReaderError, 'duplicate'):
            self.read_xml(xml)

    def test_compressed_real_demo(self):
        read = importlib.import_module('readers.lmms').read_lmms
        path = Path(__file__).parent / 'fixtures/lmms/TobyDox-Psycho.mmpz'
        result = read(path, lambda value: None)
        self.assertEqual([(p.bpm, p.num, p.den) for p in result.points], [(180, 4, 4)])

    def test_real_eight_four_and_unbound_name_not_target(self):
        read = importlib.import_module('readers.lmms').read_lmms
        path = Path(__file__).parent / 'fixtures/lmms/Oglsdl-PpTrip.mmpz'
        result = read(path, lambda value: None)
        self.assertEqual([(p.bpm, p.num, p.den) for p in result.points], [(140, 8, 4)])
        self.assertTrue(any('Unbound' in warning for warning in result.warnings))

    def test_static_meters(self):
        for numerator, denominator in ((7, 8), (3, 4), (1, 1)):
            xml = project('').replace('<head>', '<head bpm="123" timesig_numerator="%s" '
                                      'timesig_denominator="%s">' % (numerator, denominator))
            for compressed in (False, True):
                with self.subTest(meter=(numerator, denominator), compressed=compressed):
                    result = self.read_xml(xml, compressed)
                    p = result.points[0]
                    self.assertEqual((p.bpm, p.num, p.den), (123, numerator, denominator))

    def test_delayed_tempo_and_persistence_after_clip_end(self):
        xml = project('<bpm id="42" value="120"/>', '<trackcontainer>' +
                      automation(points=((0, 90), (96, 180)), pos=192, length=96) +
                      '</trackcontainer>')
        result = self.read_xml(xml, compressed=True)
        self.assertEqual([(p.beat, p.bpm) for p in result.points], [(0, 120), (4, 90), (6, 180)])
        self.assertAlmostEqual(result.points[2].time, 2 + 4 / 3)
        self.assertFalse(any(p.ramp for p in result.points))

    def test_duplicate_ticks_final_value_wins_and_repeated_bpm_deduped(self):
        result = self.read_xml(project('<bpm id="42" value="140"/>', '<trackcontainer>' +
            automation(points=((0, 100), (0, 120), (48, 120), (96, 90))) + '</trackcontainer>'))
        self.assertEqual([(p.beat, p.bpm) for p in result.points], [(0, 120), (2, 90)])

    def test_muted_tempo_track_or_pattern_does_not_replace_header(self):
        for song in (automation(mute=1), automation().replace('muted="0"', 'muted="1"')):
            result = self.read_xml(project('<bpm id="42" value="140"/>',
                                          '<trackcontainer>' + song + '</trackcontainer>'))
            self.assertEqual([p.bpm for p in result.points], [140])

    def test_unrelated_interpolation_does_not_reject_tempo(self):
        song = '<trackcontainer><track><vol id="55" value="100"/></track>' + automation('55', '2') + '</trackcontainer>'
        result = self.read_xml(project('<bpm value="140"/>', song))
        self.assertEqual([p.bpm for p in result.points], [140])

    def test_unresolved_id_has_prominent_incomplete_warning(self):
        result = self.read_xml(project('<bpm value="140"/>', '<trackcontainer>' + automation('999') + '</trackcontainer>'))
        self.assertTrue(any(w.startswith('WARNING:') and 'Completeness' in w for w in result.warnings))

    def test_meter_automation_rejected(self):
        for key in ('timesig_numerator', 'timesig_denominator'):
            with self.subTest(key=key), self.assertRaisesRegex(ReaderError, 'meter automation'):
                self.read_xml(project('<%s id="42" value="4"/>' % key,
                             '<trackcontainer>' + automation(points=((0, 4), (192, 3))) + '</trackcontainer>'))

    def test_multiple_and_nested_patterns_rejected(self):
        head = '<bpm id="42" value="140"/>'
        with self.assertRaisesRegex(ReaderError, 'multiple'):
            self.read_xml(project(head, '<trackcontainer>' + automation() * 2 + '</trackcontainer>'))
        with self.assertRaisesRegex(ReaderError, 'nested'):
            self.read_xml(project(head, '<trackcontainer><track><bbtrack><trackcontainer>' +
                automation() + '</trackcontainer></bbtrack></track></trackcontainer>'))

    def test_invalid_automation_rejected(self):
        for points, length, position in [(((48, 120),), 192, 0), (((0, 0),), 192, 0),
                                        (((0, 120.5),), 192, 0), (((0, float('nan')),), 192, 0),
                                        (((0, 120), (193, 90)), 192, 0), (((0, 120),), 192, -1)]:
            with self.subTest(points=points, length=length, position=position), self.assertRaises(ReaderError):
                self.read_xml(project('<bpm id="42" value="140"/>', '<trackcontainer>' +
                    automation(points=points, length=length, pos=position) + '</trackcontainer>'))

    def test_invalid_header_rejected(self):
        for head in ('<bpm value="NaN"/>', '<bpm value="0"/>', '<bpm value="120.5"/>',
                     '<bpm/>', '<timesig_denominator value="3"/>', '<timesig_numerator value="0"/>',
                     '<bpm value="120" scale_type="log"/>'):
            with self.subTest(head=head), self.assertRaises(ReaderError):
                self.read_xml(project(head))

    def test_corrupt_compression_rejected(self):
        read = importlib.import_module('readers.lmms').read_lmms
        data = project('').encode()
        proper = struct.pack('>I', len(data)) + zlib.compress(data)
        for corrupted in (b'bad', proper[:-3], struct.pack('>I', 1) + proper[4:],
                          proper + b'extra', struct.pack('>I', 100_000_000) + proper[4:],
                          zlib.compress(data)):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'bad.mmpz'
                path.write_bytes(corrupted)
                with self.subTest(data=corrupted[:6]), self.assertRaises(ReaderError):
                    read(path, lambda value: None)

    def test_wrong_or_damaged_xml_rejected(self):
        for xml in ('<bad/>', '<lmms-project>', '<lmms-project type="song"><head/></lmms-project>',
                    '<!DOCTYPE lmms-project [<!ENTITY x "140">]>' + project('<bpm value="&x;"/>')):
            with self.subTest(xml=xml), self.assertRaises(ReaderError):
                self.read_xml(xml)

    def test_utf16_entity_declaration_is_rejected(self):
        read = importlib.import_module('readers.lmms').read_lmms
        xml = '<!DOCTYPE lmms-project [<!ENTITY x "120">]>' + project('<bpm value="&x;"/>')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'entity.mmp'
            path.write_bytes(xml.encode('utf-16'))
            with self.assertRaisesRegex(ReaderError, 'entity'):
                read(path, lambda value: None)

    def test_missing_tempo_warns_about_lmms_default(self):
        result = self.read_xml(project(''))
        self.assertEqual(result.points[0].bpm, 140)
        self.assertTrue(any('default 140' in w for w in result.warnings))

    def test_ambiguous_header_and_nested_model_content_rejected(self):
        for xml in (project('<bpm value="120"/><bpm value="90"/>'),
                    project('<bpm value="120"><automationpattern><time pos="0" value="90"/>'
                            '</automationpattern></bpm>'), project('').replace('version="1.0"', 'version="2.0"')):
            with self.subTest(xml=xml), self.assertRaises(ReaderError):
                self.read_xml(xml)

    def test_out_of_range_tick_and_malformed_target_id_rejected(self):
        with self.assertRaises(ReaderError):
            self.read_xml(project('<bpm id="42" value="140"/>', '<trackcontainer>' +
                automation(points=((0, 120),), pos=10 ** 400) + '</trackcontainer>'))
        with self.assertRaises(ReaderError):
            self.read_xml(project('<bpm id="not-an-id" value="140"/>', '<trackcontainer>' +
                automation(target='not-an-id') + '</trackcontainer>'))

    def test_real_plain_constant(self):
        read = importlib.import_module('readers.lmms').read_lmms
        path = Path(__file__).parent / 'fixtures/lmms/emptyproject.mmp'
        progress = []
        result = read(path, progress.append)
        self.assertEqual([(p.beat, p.time, p.bpm, p.num, p.den) for p in result.points],
                         [(0, 0, 140, 4, 4)])
        self.assertTrue(any('experimental' in w.lower() for w in result.warnings))
        self.assertEqual(progress[-1], 1.0)


if __name__ == '__main__':
    unittest.main()
