"""EXPERIMENTAL Studio One ZIP/XML reader: constant (curveType=0) segments only.

Based on MIT-licensed studio-one-mcp's observed Studio One 5.5.2 layout,
NOT a published PreSonus format specification. Native-host round-trip remains
unconfirmed. See tests/fixtures/daw_reader_evidence.md for provenance and scope.
No third-party runtime dependency; core imports intentionally stay lazy.
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import NoReturn


def read_studioone(path: Path, progress):
    from core import ReaderError, TempoMap, TempoPoint, _fill_times_from_beats

    path = Path(path)

    def fail(message) -> NoReturn:
        raise ReaderError("Studio One (EXPERIMENTAL): " + message)

    def number(element, key):
        try:
            value = float(element.attrib[key])
        except (KeyError, ValueError):
            fail("missing or invalid " + key)
        if not math.isfinite(value):
            fail("non-finite " + key)
        return value

    def xid(element):
        return next((v for k, v in element.attrib.items()
                     if k.endswith("}id")), None)

    def one(parent, tag, identifier):
        matches = [e for e in parent if e.tag == tag and xid(e) == identifier]
        if len(matches) != 1 or (tag.endswith("Map") and
                                sum(e.tag == tag for e in parent) != 1):
            fail("missing or ambiguous global " + identifier)
        return matches[0]

    try:
        with zipfile.ZipFile(path) as archive:
            entries = [e for e in archive.infolist() if e.filename == "Song/song.xml"]
            if len(entries) != 1:
                fail("missing or duplicate Song/song.xml; unsupported .song layout")
            if entries[0].file_size > 8 * 1024 * 1024:
                fail("Song/song.xml exceeds 8 MiB safety limit")
            xml = archive.read(entries[0])
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        fail("cannot read ZIP song: " + str(exc))
    progress(0.25)
    if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
        fail("DTD/entity declarations are not supported")
    # Studio One's observed XML uses x:id without declaring xmlns:x.
    # Supply only that missing namespace, not a general malformed-XML repair.
    if not re.search(rb"xmlns:x\s*=", xml):
        xml = re.sub(rb"<Song(?=[\s>])", b'<Song xmlns:x="urn:studioone:x"', xml, count=1)
    try:
        song = ET.fromstring(xml)
    except ET.ParseError as exc:
        fail("malformed Song/song.xml: " + str(exc))
    if song.tag != "Song":
        fail("unsupported XML root")
    root = one(song, "Attributes", "Root")
    if root.get("defaultTimeFormat") != "2":
        fail("unsupported time format; only observed quarter-note layout 2 is supported")
    context = one(root, "Attributes", "timeContext")
    tempo_map = one(context, "TempoMap", "tempoMap")
    meter_map = one(context, "TimeSignatureMap", "timeSignatureMap")
    tempos = []
    for segment in tempo_map:
        if segment.tag != "TempoMapSegment" or list(segment):
            fail("unsupported tempo-map target/content")
        if set(segment.attrib) != {"curveType", "start", "end", "tempo"}:
            fail("unsupported tempo-segment attributes (curve/target encoding)")
        if segment.get("curveType") != "0":
            fail("unsupported tempo curve; only curveType=0 constant segments are supported")
        start, duration = number(segment, "start"), number(segment, "tempo")
        end = number(segment, "end")
        if start < 0 or end <= start or duration <= 0:
            fail("invalid tempo segment position/end/duration")
        bpm = 60.0 / duration
        if not math.isfinite(bpm) or bpm <= 0:
            fail("invalid BPM")
        if tempos and (start <= tempos[-1][0] or start != tempos[-1][2]):
            fail("tempo segments are unordered, overlapping or have gaps")
        tempos.append((start, bpm, end))
    if tempos and tempos[-1][2] != 1e200:
        fail("unsupported finite final tempo segment; expected observed infinite-end sentinel")
    meters = []
    for segment in meter_map:
        if segment.tag != "TimeSignatureMapSegment" or list(segment):
            fail("unsupported time-signature target/content")
        if set(segment.attrib) != {"start", "numerator", "denominator"}:
            fail("unsupported time-signature attributes")
        start = number(segment, "start")
        numerator = number(segment, "numerator")
        denominator = number(segment, "denominator")
        if (start < 0 or start >= 1e200
                or numerator != int(numerator) or numerator < 1
                or numerator > 1024 or denominator != int(denominator)
                or denominator < 1 or denominator > 1024
                or int(denominator) & (int(denominator) - 1)):
            fail("invalid time signature or position")
        if meters and start <= meters[-1][0]:
            fail("time signatures must have strictly increasing positions")
        meters.append((start, int(numerator), int(denominator)))
    if not tempos or not meters:
        fail("empty global tempo or time-signature map")
    if tempos[0][0] != 0 or meters[0][0] != 0:
        fail("global maps must explicitly start at beat zero")
    tempo_by_beat = {beat: bpm for beat, bpm, _ in tempos}
    meter_by_beat = {beat: (num, den) for beat, num, den in meters}
    bpm, num, den = tempos[0][1], meters[0][1], meters[0][2]
    points = []
    for beat in sorted(set(tempo_by_beat) | set(meter_by_beat)):
        bpm = tempo_by_beat.get(beat, bpm)
        num, den = meter_by_beat.get(beat, (num, den))
        points.append(TempoPoint(beat, 0.0, bpm, num, den))
    _fill_times_from_beats(points)
    if any(not math.isfinite(p.time) for p in points):
        fail("integrated time is non-finite")
    progress(1.0)
    return TempoMap(path, points, [
        "EXPERIMENTAL / HOST UNCONFIRMED: Studio One 5.5.2 observed ZIP/XML "
        "step-tempo subset; synthetic-fixture verified, not native-host verified."
    ])


read_song = read_studioone
