"""Experimental DAWproject 1.0 tempo-only reader (no audio/plugin import).

Primary specification: bitwig/dawproject, revision
 ee4dcdde75940f30e14e55401a26955a58b8322b, Arrangement, Timeline,
 RealPoint, TimeUnit, Points and Transport Java classes. RealPoint interpolation
 describes the outgoing segment; unspecified interpolation is hold.

Imports core only when called, so registering this adapter cannot introduce a
core/readers import cycle. Unsupported timelines fail instead of being flattened.
"""
from pathlib import Path
import bisect
import math
import xml.etree.ElementTree as ET
import zipfile


def read_dawproject(path, progress):
    from core import ReaderError, TempoMap, TempoPoint

    progress(0.0)
    try:
        with zipfile.ZipFile(path) as archive:
            matches = [item for item in archive.infolist() if item.filename == 'project.xml']
            if len(matches) != 1:
                raise ReaderError('DAWproject must contain exactly one root project.xml')
            if matches[0].file_size > 16 * 1024 * 1024:
                raise ReaderError('DAWproject project.xml exceeds the 16 MiB safety limit')
            data = archive.read(matches[0])
        declarations = data.upper().replace(b'\x00', b'')  # also UTF-16/UTF-32
        if b'<!DOCTYPE' in declarations or b'<!ENTITY' in declarations:
            raise ReaderError('DAWproject XML declarations/entities are not supported')
        root = ET.fromstring(data)
        if root.tag != 'Project' or root.get('version') != '1.0':
            raise ReaderError('Only DAWproject Project version 1.0 is supported')
        transport = root.find('Transport')
        tempo = transport.find('Tempo') if transport is not None else None
        meter = transport.find('TimeSignature') if transport is not None else None
        if tempo is None or meter is None:
            raise ReaderError('DAWproject requires Transport Tempo and TimeSignature')
        if tempo.get('unit') != 'bpm':
            raise ReaderError('DAWproject tempo must use bpm units')
        bpm = float(tempo.attrib['value'])
        num, den = int(meter.attrib['numerator']), int(meter.attrib['denominator'])
        if not math.isfinite(bpm) or bpm <= 0 or num <= 0 or den <= 0 or den & (den - 1):
            raise ReaderError('Invalid DAWproject transport tempo or meter')
        result = TempoMap(Path(path), [TempoPoint(0.0, 0.0, bpm, num, den)],
                          ['Experimental DAWproject reader: tempo/meter only; DAW playback round-trip unverified.'])
        arrangement = root.find('Arrangement')
        if len(root.findall('Arrangement')) > 1:
            raise ReaderError('Multiple DAWproject arrangements are unsupported')
        if arrangement is not None:
            def timeline(name, parameter, point_tag):
                elements = arrangement.findall(name)
                if len(elements) > 1:
                    raise ReaderError('Multiple %s timelines are unsupported' % name)
                if not elements:
                    return 'beats', []
                element = elements[0]
                unit = element.get('timeUnit', 'beats')
                if unit not in ('beats', 'seconds') or element.get('track'):
                    raise ReaderError('Unsupported time unit or track-scoped %s' % name)
                if name == 'TempoAutomation' and element.get('unit', 'bpm') != 'bpm':
                    raise ReaderError('TempoAutomation must use bpm units')
                targets = element.findall('Target')
                if len(targets) == 1:
                    if targets[0].get('parameter') != parameter.get('id') or not parameter.get('id'):
                        raise ReaderError('%s Target does not reference Transport' % name)
                elif not targets and element.get('target') == parameter.get('id') and parameter.get('id'):
                    result.warnings.append('Legacy %s target attribute accepted; not current Target schema.' % name)
                else:
                    raise ReaderError('%s requires a Transport Target' % name)
                values = []
                for point in element:
                    if point.tag == 'Target':
                        continue
                    if point.tag != point_tag:
                        raise ReaderError('Unsupported point type in %s' % name)
                    position = float(point.attrib['time'])
                    if not math.isfinite(position) or position < 0:
                        raise ReaderError('Automation position must be finite and nonnegative')
                    if point_tag == 'RealPoint':
                        value = float(point.attrib['value'])
                        interpolation = point.get('interpolation', 'hold')
                        if interpolation not in ('hold', 'linear') or set(point.attrib) - {'time', 'value', 'interpolation'}:
                            raise ReaderError('Unsupported DAWproject tempo interpolation/curve')
                        if not math.isfinite(value) or value <= 0:
                            raise ReaderError('Tempo must be positive and finite')
                        values.append((position, value, interpolation == 'linear'))
                    else:
                        n, d = int(point.attrib['numerator']), int(point.attrib['denominator'])
                        if n <= 0 or d <= 0 or d & (d - 1):
                            raise ReaderError('Invalid time signature')
                        values.append((position, n, d))
                values.sort(key=lambda event: event[0])
                if any(a[0] == b[0] for a, b in zip(values, values[1:])):
                    raise ReaderError('Duplicate automation positions are ambiguous')
                return unit, values

            tempo_unit, events = timeline('TempoAutomation', tempo, 'RealPoint')
            meter_unit, meters = timeline('TimeSignatureAutomation', meter, 'TimeSignaturePoint')
            if not events or events[0][0] > 0:
                events.insert(0, (0.0, bpm, False))
            # Native tempo coordinates define exact beat/time correspondence.
            nodes = [(0.0, 0.0, events[0][1], events[0][2])]
            for previous, event in zip(events, events[1:]):
                span = event[0] - previous[0]
                b0, b1, ramp = previous[1], event[1], previous[2]
                if tempo_unit == 'beats':
                    slope = (b1 - b0) / span if ramp else 0.0
                    dt = 60 * math.log1p(slope * span / b0) / slope if slope else 60 * span / b0
                    beat, time = event[0], nodes[-1][1] + dt
                else:
                    beat, time = nodes[-1][0] + span * ((b0 + b1) / 2 if ramp else b0) / 60, event[0]
                nodes.append((beat, time, b1, event[2]))
            beats = [node[0] for node in nodes]
            times = [node[1] for node in nodes]

            def coordinate(position, seconds=False):
                index = max(0, bisect.bisect_right(times if seconds else beats, position) - 1)
                q0, t0, b0, ramp = nodes[index]
                ramp = ramp and index + 1 < len(nodes)
                if ramp:
                    end = nodes[index + 1]
                    slope = (end[2] - b0) / ((end[0] - q0) if tempo_unit == 'beats' else (end[1] - t0))
                else:
                    slope = 0.0
                if seconds:
                    dt = position - t0
                    if tempo_unit == 'beats' and slope:
                        q = b0 * math.expm1(slope * dt / 60) / slope
                    else:
                        q = (b0 * dt + slope * dt * dt / 2) / 60
                else:
                    q = position - q0
                    if tempo_unit == 'beats' and slope:
                        dt = 60 * math.log1p(slope * q / b0) / slope
                    elif slope:
                        # Rationalized quadratic root avoids cancellation.
                        dt = 120 * q / (b0 + math.sqrt(b0 * b0 + 120 * slope * q))
                    else:
                        dt = 60 * q / b0
                value = b0 + slope * (q if tempo_unit == 'beats' else dt)
                return q0 + q, t0 + dt, value, ramp

            meter_changes = {}
            for position, n, d in meters:
                beat, _, _, _ = coordinate(position, meter_unit == 'seconds')
                meter_changes[beat] = (n, d)
            result.points = []
            for beat in sorted(set(beats) | set(meter_changes)):
                q, time, value, ramp = coordinate(beat)
                num, den = meter_changes.get(beat, (num, den))
                result.points.append(TempoPoint(q, time, value, num, den, ramp,
                                               'beat' if tempo_unit == 'beats' else 'time'))
        if any(not all(math.isfinite(value) for value in (point.beat, point.time, point.bpm))
               or point.bpm <= 0 for point in result.points):
            raise ReaderError('DAWproject tempo arithmetic exceeds supported numeric range')
        progress(1.0)
        return result
    except ReaderError:
        raise
    except (OSError, ValueError, LookupError, ArithmeticError, ET.ParseError,
            zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise ReaderError('Cannot read DAWproject: %s' % exc) from exc
