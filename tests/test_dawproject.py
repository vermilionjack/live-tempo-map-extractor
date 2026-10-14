"""Public fixture tests plus authored, deliberately minimal regression archives."""
import hashlib
import importlib
import math
import tempfile
import unittest
import zipfile
from pathlib import Path

import core

FIXTURES = Path(__file__).parent / 'fixtures' / 'dawproject'


class DawprojectTests(unittest.TestCase):
    def read_xml(self, xml):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.dawproject'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('project.xml', xml)
            return importlib.import_module('readers.dawproject').read_dawproject(path, lambda _: None)

    def project(self, automation='', bpm=120, meter='4', den='4'):
        return ('<Project version="1.0"><Transport>'
                '<Tempo id="tempo" unit="bpm" value="%s"/>'
                '<TimeSignature id="meter" numerator="%s" denominator="%s"/>'
                '</Transport><Arrangement>%s</Arrangement></Project>' % (bpm, meter, den, automation))

    def test_public_bitwig_example(self):
        result = self.read_xml((FIXTURES / 'bitwig-example.project.xml').read_text())
        self.assertEqual([(p.beat, p.time, p.bpm, p.num, p.den) for p in result.points],
                         [(0.0, 0.0, 149.0, 4, 4)])
        self.assertTrue(any('experimental' in warning.lower() for warning in result.warnings))

    def test_beat_linear_ramp_split_by_meter(self):
        automation = ('<TempoAutomation unit="bpm"><Target parameter="tempo"/>'
                      '<RealPoint time="0" value="60" interpolation="linear"/>'
                      '<RealPoint time="8" value="120"/></TempoAutomation>'
                      '<TimeSignatureAutomation><Target parameter="meter"/>'
                      '<TimeSignaturePoint time="4" numerator="7" denominator="8"/>'
                      '</TimeSignatureAutomation>')
        points = self.read_xml(self.project(automation)).points
        self.assertEqual([p.beat for p in points], [0, 4, 8])
        self.assertEqual([p.bpm for p in points], [60, 90, 120])
        self.assertEqual([p.ramp for p in points], [True, True, False])
        self.assertEqual([p.ramp_domain for p in points[:2]], ['beat', 'beat'])
        self.assertAlmostEqual(points[1].time, 8 * math.log(1.5))
        self.assertAlmostEqual(points[2].time, 8 * math.log(2))
        self.assertEqual((points[1].num, points[1].den), (7, 8))

    def test_seconds_linear_ramp_and_beat_meter(self):
        automation = ('<TempoAutomation timeUnit="seconds" unit="bpm">'
                      '<Target parameter="tempo"/>'
                      '<RealPoint time="0" value="60" interpolation="linear"/>'
                      '<RealPoint time="4" value="120"/></TempoAutomation>'
                      '<TimeSignatureAutomation><Target parameter="meter"/>'
                      '<TimeSignaturePoint time="2.5" numerator="3" denominator="4"/>'
                      '</TimeSignatureAutomation>')
        points = self.read_xml(self.project(automation)).points
        self.assertEqual([p.beat for p in points], [0, 2.5, 6])
        self.assertAlmostEqual(points[1].time, 2)
        self.assertEqual([p.bpm for p in points], [60, 90, 120])
        self.assertEqual(points[1].ramp_domain, 'time')

    def test_public_archives(self):
        reader = importlib.import_module('readers.dawproject').read_dawproject
        simple = reader(FIXTURES / 'bitwig_simple.dawproject', lambda _: None)
        extended = reader(FIXTURES / 'bitwig_extended.dawproject', lambda _: None)
        self.assertEqual(simple.points[0].bpm, 149)
        self.assertEqual([(p.beat, p.time, p.bpm, p.ramp) for p in extended.points],
                         [(0, 0, 120, False), (4, 2, 140, False)])
        self.assertTrue(any('legacy' in warning.lower() for warning in extended.warnings))

    def test_invalid_transport_values_are_rejected(self):
        for bpm, numerator, denominator in [('nan', '4', '4'), ('inf', '4', '4'),
                                             ('120', '4', '3'), ('0', '4', '4'),
                                             ('120', '0', '4')]:
            with self.subTest(bpm=bpm, numerator=numerator, denominator=denominator):
                with self.assertRaises(core.ReaderError):
                    self.read_xml(self.project(bpm=bpm, meter=numerator, den=denominator))

    def test_unsupported_or_invalid_automation_is_rejected(self):
        bad = [
            '<RealPoint time="0" value="120" interpolation="bezier"/>',
            '<RealPoint time="0" value="120" curve="0.5"/>',
            '<RealPoint time="nan" value="120"/>',
            '<RealPoint time="-1" value="120"/>',
            '<RealPoint time="0" value="inf"/>',
            '<RealPoint time="0" value="0"/>',
            '<RealPoint time="0" value="120"/><RealPoint time="0" value="90"/>',
            '<IntegerPoint time="0" value="120"/>',
        ]
        for points in bad:
            with self.subTest(points=points):
                with self.assertRaises(core.ReaderError):
                    self.read_xml(self.project('<TempoAutomation><Target parameter="tempo"/>' +
                                               points + '</TempoAutomation>'))
        for attributes, target in [('timeUnit="samples"', 'tempo'),
                                   ('track="track"', 'tempo'), ('unit="normalized"', 'tempo'),
                                   ('', 'anotherParameter')]:
            with self.subTest(attributes=attributes, target=target):
                with self.assertRaises(core.ReaderError):
                    self.read_xml(self.project('<TempoAutomation %s><Target parameter="%s"/>'
                                               '<RealPoint time="0" value="120"/></TempoAutomation>' %
                                               (attributes, target)))

    def test_late_unsorted_steps_and_meter_seconds(self):
        automation = ('<TempoAutomation><Target parameter="tempo"/>'
                      '<RealPoint time="8" value="60"/>'
                      '<RealPoint time="4" value="90"/></TempoAutomation>'
                      '<TimeSignatureAutomation timeUnit="seconds"><Target parameter="meter"/>'
                      '<TimeSignaturePoint time="1" numerator="5" denominator="8"/>'
                      '</TimeSignatureAutomation>')
        points = self.read_xml(self.project(automation)).points
        self.assertEqual([p.beat for p in points], [0, 2, 4, 8])
        self.assertEqual([p.bpm for p in points], [120, 120, 90, 60])
        self.assertEqual([(p.num, p.den) for p in points], [(4, 4), (5, 8), (5, 8), (5, 8)])
        self.assertAlmostEqual(points[-1].time, 2 + 8 / 3)

    def test_decreasing_ramps_and_seconds_meter(self):
        for unit in ('beats', 'seconds'):
            with self.subTest(unit=unit):
                automation = ('<TempoAutomation timeUnit="%s"><Target parameter="tempo"/>'
                              '<RealPoint time="0" value="120" interpolation="linear"/>'
                              '<RealPoint time="4" value="60"/></TempoAutomation>'
                              '<TimeSignatureAutomation timeUnit="seconds"><Target parameter="meter"/>'
                              '<TimeSignaturePoint time="1" numerator="3" denominator="8"/>'
                              '</TimeSignatureAutomation>') % unit
                points = self.read_xml(self.project(automation)).points
                self.assertAlmostEqual(points[1].time, 1)
                if unit == 'seconds':
                    self.assertAlmostEqual(points[1].beat, 1.875)
                    self.assertAlmostEqual(points[1].bpm, 105)
                    self.assertAlmostEqual(points[-1].beat, 6)
                else:
                    self.assertAlmostEqual(points[1].beat, 8 * (1 - math.exp(-0.25)))
                    self.assertAlmostEqual(points[1].bpm, 120 * math.exp(-0.25))
                    self.assertAlmostEqual(points[-1].time, 4 * math.log(2))

    def test_equal_ramp_and_meter_at_tempo_boundary(self):
        automation = ('<TempoAutomation><Target parameter="tempo"/>'
                      '<RealPoint time="0" value="120" interpolation="linear"/>'
                      '<RealPoint time="4" value="120" interpolation="linear"/></TempoAutomation>'
                      '<TimeSignatureAutomation timeUnit="seconds"><Target parameter="meter"/>'
                      '<TimeSignaturePoint time="2" numerator="6" denominator="8"/>'
                      '<TimeSignaturePoint time="3" numerator="7" denominator="8"/>'
                      '</TimeSignatureAutomation>')
        points = self.read_xml(self.project(automation)).points
        self.assertEqual([(p.beat, p.time, p.ramp) for p in points],
                         [(0, 0, True), (4, 2, False), (6, 3, False)])
        self.assertEqual((points[1].num, points[1].den), (6, 8))

    def test_malformed_container_and_xml_are_rejected(self):
        reader = importlib.import_module('readers.dawproject').read_dawproject
        for xml in ('<Project', '<Project version="2.0"/>', '<NotProject/>',
                    '<?xml version="1.0" encoding="unknown-encoding"?>' + self.project(),
                    '<!DOCTYPE Project [<!ENTITY bpm "120">]>' + self.project()):
            with self.subTest(xml=xml):
                with self.assertRaises(core.ReaderError):
                    self.read_xml(xml)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.dawproject'
            path.write_bytes(b'not a ZIP')
            with self.assertRaises(core.ReaderError):
                reader(path, lambda _: None)
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('nested/project.xml', self.project())
            with self.assertRaises(core.ReaderError):
                reader(path, lambda _: None)

    def test_utf16_entities_and_numeric_overflow_rejected(self):
        xml = ('<?xml version="1.0" encoding="UTF-16"?>'
               '<!DOCTYPE Project [<!ENTITY evil "120">]>' + self.project()).encode('utf-16')
        with self.assertRaises(core.ReaderError):
            self.read_xml(xml)
        automation = ('<TempoAutomation timeUnit="seconds"><Target parameter="tempo"/>'
                      '<RealPoint time="0" value="1e308" interpolation="linear"/>'
                      '<RealPoint time="1e308" value="1e308"/></TempoAutomation>')
        with self.assertRaises(core.ReaderError):
            self.read_xml(self.project(automation))

    def test_progress_and_empty_automation(self):
        reader = importlib.import_module('readers.dawproject').read_dawproject
        progress = []
        reader(FIXTURES / 'bitwig_simple.dawproject', progress.append)
        self.assertEqual(progress, [0.0, 1.0])
        points = self.read_xml(self.project('<TempoAutomation><Target parameter="tempo"/>'
                                            '</TempoAutomation>')).points
        self.assertEqual([(p.beat, p.time, p.bpm) for p in points], [(0, 0, 120)])

    def test_public_fixture_hashes(self):
        expected = {
            'bitwig-example.project.xml': 'df82d509b02284da2a87f2cd7fcbb47b8212fedd536fec573918f2e1e023e2c5',
            'bitwig_simple.dawproject': '10d218aea875b30b84b9693b0c941292752e64bf2f34661c9dc69c49313ba1a0',
            'bitwig_extended.dawproject': '61f46fde1cacb0646dd0c1ea373c1e8fc1e27eb3f8d7e0aceb0e1ec9445d08d0',
        }
        for name, digest in expected.items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest(), digest)

    def test_meter_only_and_initial_override(self):
        automation = ('<TimeSignatureAutomation><Target parameter="meter"/>'
                      '<TimeSignaturePoint time="0" numerator="7" denominator="8"/>'
                      '<TimeSignaturePoint time="8" numerator="3" denominator="4"/>'
                      '</TimeSignatureAutomation>')
        points = self.read_xml(self.project(automation)).points
        self.assertEqual([(p.beat, p.time, p.bpm, p.num, p.den) for p in points],
                         [(0, 0, 120, 7, 8), (8, 4, 120, 3, 4)])


if __name__ == '__main__':
    unittest.main()
