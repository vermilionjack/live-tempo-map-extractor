"""Experimental, fail-closed LMMS song reader; see fixtures/lmms/README.md.

Source contract: LMMS v1.2.2 Song, AutomatableModel, AutomationPattern,
MeterModel and TrackContainer. Imports core only when called (registration
may import this module from core). No plugin/audio engine is instantiated.
"""
from pathlib import Path
import math
import struct
import xml.etree.ElementTree as ET
import zlib

_MAX_BYTES = 32 * 1024 * 1024
_KEYS = ('bpm', 'timesig_numerator', 'timesig_denominator')


def read_lmms(path, progress):
    """Read static meter and constant/single-pattern discrete song tempo.

    Known unsupported target automation raises ReaderError; unresolved targets
    return an explicitly warned partial map rather than a completeness claim.
    """
    from core import TempoMap, TempoPoint, ReaderError, _fill_times_from_beats

    path = Path(path)
    try:
        data = path.read_bytes()
        if len(data) > _MAX_BYTES:
            raise ValueError('project exceeds 32 MiB safety limit')
        if path.suffix.lower() == '.mmpz':
            if len(data) < 5:
                raise ValueError('truncated Qt-compressed project')
            expected = struct.unpack('>I', data[:4])[0]
            if expected > _MAX_BYTES:
                raise ValueError('uncompressed project exceeds 32 MiB safety limit')
            inflater = zlib.decompressobj()
            xml = inflater.decompress(data[4:], _MAX_BYTES + 1)
            if (len(xml) != expected or not inflater.eof or
                    inflater.unused_data or inflater.unconsumed_tail):
                raise ValueError('invalid Qt-compressed length or zlib stream')
            data = xml
        # Removing NULs exposes declarations in UTF-16/32 as well as UTF-8;
        # LMMS's harmless external-free DOCTYPE is allowed, entities are not.
        if b'<!ENTITY' in data.replace(b'\x00', b'').upper():
            raise ValueError('XML entity declarations are not supported')
        root = ET.fromstring(data)
        if root.tag not in ('lmms-project', 'multimedia-project') or root.get('type') != 'song':
            raise ValueError('not an LMMS song project')
        if root.get('version', '1.0') != '1.0':
            raise ValueError('unsupported LMMS project schema version')
        head = root.find('head')
        if len(root.findall('head')) != 1 or len(root.findall('song')) != 1:
            raise ValueError('missing or ambiguous LMMS head/song')
        if head is None or root.find('song') is None:
            raise ValueError('missing LMMS head or song')
        values = []
        for key, default in zip(_KEYS, (140, 4, 4)):
            if len(head.findall(key)) > 1:
                raise ValueError(f'duplicate {key} header model')
            node = head.find(key)
            if node is not None and len(node):
                raise ValueError(f'unknown nested {key} automation/model representation')
            raw = node.get('value') if node is not None else head.get(key, str(default))
            if raw is None:
                raise ValueError(f'missing {key} model value')
            value = float(raw)
            if not math.isfinite(value) or value != int(value):
                raise ValueError(f'{key} must be a finite integer')
            if not (10 <= value <= 999 if key == 'bpm' else 1 <= value <= 32):
                raise ValueError(f'{key} is outside LMMS model range')
            values.append(int(value))
        if values[2] & (values[2] - 1):
            raise ValueError('non-power-of-two meter denominator is unsupported')
        warnings = ['Experimental LMMS reader: constant or single-pattern discrete tempo; '
                    'static meter only. Playback not host-verified.']
        if head.find('bpm') is None and 'bpm' not in head.attrib:
            warnings.append('Missing tempo: using LMMS default 140 BPM.')
        model_ids = {}
        for key in _KEYS:
            if head.find('automationpattern/' + key) is not None:
                raise ValueError(f'legacy {key} automation is unsupported; no map exported')
            if head.find('connection/' + key) is not None:
                raise ValueError(f'{key} controller-driven automation is unsupported; no map exported')
            model = head.find(key)
            if model is not None:
                if model.get('scale_type', 'linear') != 'linear':
                    raise ValueError(f'{key} logarithmic/unknown scale is unsupported')
                model_id = model.get('id')
                if model_id:
                    if (not model_id.isascii() or not model_id.isdecimal() or
                            not 1 <= int(model_id) <= 2147483647 or str(int(model_id)) != model_id):
                        raise ValueError(f'malformed {key} automation model ID')
                    if model_id in model_ids:
                        raise ValueError('duplicate tempo/meter model ID')
                    model_ids[model_id] = key
        for model_id in model_ids:
            if sum(n.get('id') == model_id for n in root.iter()
                   if n.tag != 'object') != 1:
                raise ValueError('duplicate tempo/meter model ID in project')
        parents = {child: node for node in root.iter() for child in node}
        supported = []
        unbound = False
        all_ids = {n.get('id') for n in root.iter() if n.tag != 'object'}
        for pattern in root.iter('automationpattern'):
            if not pattern.findall('time'):
                continue
            ancestor = pattern
            muted = False
            while ancestor is not None:
                if ancestor.get('mute', '0') == '1' or ancestor.get('muted', '0') == '1':
                    muted = True
                ancestor = parents.get(ancestor)
            if muted:
                continue
            objects = pattern.findall('object')
            if not objects:
                unbound = True
                continue
            targets = {o.get('id') for o in objects}
            if any(t not in all_ids for t in targets):
                if not any('Unresolved automation' in warning for warning in warnings):
                    warnings.append('WARNING: Unresolved automation object IDs were ignored. '
                                    'Completeness cannot be established; verify this map in LMMS before export.')
            relevant = targets.intersection(model_ids)
            if not relevant:
                continue
            if any(model_ids[t] != 'bpm' for t in relevant):
                raise ValueError('meter automation is unsupported; no map exported')
            owner = parents.get(pattern)
            if owner is None or owner.tag != 'track' or owner.get('type') not in ('5', '6'):
                raise ValueError('unsupported tempo automation track')
            container = parents.get(owner)
            song = root.find('song')
            if not (container is song or (container is not None and
                    container.tag == 'trackcontainer' and parents.get(container) is song)):
                raise ValueError('nested/Beat+Bassline tempo automation is unsupported')
            if pattern.get('prog', '0') != '0':
                raise ValueError('interpolated tempo automation is unsupported; no map exported')
            if any(n.tag not in ('time', 'object') for n in pattern) or any(
                    set(n.attrib) - {'pos', 'value'} for n in pattern.findall('time')):
                raise ValueError('unknown tempo automation representation is unsupported')
            supported.append(pattern)
        if len(supported) > 1:
            raise ValueError('multiple tempo automation patterns/precedence are unsupported')
        if unbound:
            warnings.append('Unbound LMMS automation patterns were ignored: names are not '
                            'target bindings; header tempo is not replaced by a pattern named Tempo.')
        points = [TempoPoint(0, 0, *values)]
        if supported:
            pattern = supported[0]
            start = int(pattern.get('pos', '0'))
            if not 0 <= start <= 2147483647:
                raise ValueError('negative/out-of-range automation position')
            length = int(pattern.get('len', '0'))
            events = {}
            for node in pattern.findall('time'):
                tick = int(node.get('pos', ''))
                bpm = float(node.get('value', ''))
                if not 0 <= tick <= 2147483647 - start or not math.isfinite(bpm) or bpm != int(bpm) or not 10 <= bpm <= 999:
                    raise ValueError('invalid tempo automation tick or BPM; integer BPM required')
                if length > 0 and tick > length:
                    raise ValueError('tempo automation points beyond clip length are unsupported')
                events[tick] = bpm  # LMMS QMap: final serialized duplicate wins.
            if 0 not in events:
                raise ValueError('tempo automation needs a knot at local tick zero')
            for tick, bpm in sorted(events.items()):
                beat = (start + tick) / 48.0
                if beat == 0:
                    points[0].bpm = bpm
                elif bpm != points[-1].bpm:
                    points.append(TempoPoint(beat, 0, bpm, values[1], values[2]))
            _fill_times_from_beats(points)
            warnings.append('Discrete tempo automation decoded at 48 ticks per quarter note; '
                            'LMMS audio-block/sample rounding is not emulated.')
        progress(1.0)
        return TempoMap(path, points, warnings)
    except (OSError, ValueError, TypeError, ET.ParseError, zlib.error) as exc:
        raise ReaderError(f'LMMS: {exc}') from exc
