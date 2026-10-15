"""Core logic: tempo-map model, project readers and exporters (no GUI code).

Add a reader for a new project format by writing a function
``read_xxx(path, progress) -> TempoMap`` and registering it in READERS.
"""
from __future__ import annotations

import csv
import gzip
import math
import re
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

Progress = Callable[[float], None]  # receives 0.0 .. 1.0


# --------------------------------------------------------------------------- model
@dataclass
class TempoPoint:
    beat: float          # position in quarter notes from project start
    time: float          # position in seconds
    bpm: float
    num: int = 4
    den: int = 4
    ramp: bool = False   # True: tempo ramps linearly to the next point
    ramp_domain: str = "time"  # REAPER: time; Ableton: beat


@dataclass
class TempoMap:
    source: Path
    points: list[TempoPoint]
    warnings: list[str] = field(default_factory=list)
    project_end_beat: Optional[float] = None

    @property
    def bpm_range(self) -> tuple[float, float]:
        bpms = [p.bpm for p in self.points]
        return min(bpms), max(bpms)

    def bar_beat(self, beat: float) -> str:
        """Return 'bar.beat' (1-based, beats in meter units) for a quarter-note position."""
        bar, seg_start, num, den = 1, 0.0, 4, 4
        for p in self.points:
            if p.beat > beat + 1e-9:
                break
            if (p.num, p.den) != (num, den):
                bar += math.ceil((p.beat - seg_start) / (num * 4 / den) - 1e-9)
                seg_start, num, den = p.beat, p.num, p.den
        qn_per_bar = num * 4 / den
        rel = beat - seg_start
        whole = int((rel + 1e-9) // qn_per_bar)
        beat_in_bar = (rel - whole * qn_per_bar) / (4 / den) + 1
        bar += whole
        if abs(beat_in_bar - round(beat_in_bar)) < 1e-6:
            return f"{bar}.{int(round(beat_in_bar))}"
        return f"{bar}.{beat_in_bar:.2f}"


class ReaderError(Exception):
    """A readable, user-facing problem with a project file."""


# --------------------------------------------------------------------------- helpers
def _ramp_time_at(q: float, b0: float, b1: float, seg_t: float) -> float:
    """Seconds after a ramp start at which q quarter notes have elapsed
    (tempo changes linearly in time from b0 to b1 over seg_t seconds)."""
    if seg_t <= 0:
        return 0.0
    k = (b1 - b0) / seg_t
    if abs(k) < 1e-12:
        return 60.0 * q / b0
    disc = b0 * b0 + 2 * k * 60.0 * q
    return (-b0 + math.sqrt(max(disc, 0.0))) / k


def _fill_beats_from_times(points: list[TempoPoint]) -> None:
    for prev, cur in zip(points, points[1:]):
        dt = cur.time - prev.time
        avg = (prev.bpm + cur.bpm) / 2 if prev.ramp else prev.bpm
        cur.beat = prev.beat + avg * dt / 60.0


def _beat_ramp_time_at(q: float, b0: float, b1: float, span_q: float) -> float:
    """Integral of 60/BPM over q beats of a beat-linear segment."""
    if span_q <= 0:
        return 0.0
    slope = (b1 - b0) / span_q
    if abs(b1 - b0) < 1e-12:
        return 60.0 * q / b0
    return 60.0 * math.log1p(slope * q / b0) / slope


def _fill_times_from_beats(points: list[TempoPoint]) -> None:
    for prev, cur in zip(points, points[1:]):
        span = cur.beat - prev.beat
        if prev.ramp and prev.ramp_domain == "beat":
            dt = _beat_ramp_time_at(span, prev.bpm, cur.bpm, span)
        elif prev.ramp:
            dt = 120.0 * span / (prev.bpm + cur.bpm)
        else:
            dt = span * 60.0 / prev.bpm
        cur.time = prev.time + dt


# --------------------------------------------------------------------------- readers
def read_midi(path: Path, progress: Progress) -> TempoMap:
    data = path.read_bytes()
    if data[:4] != b"MThd":
        raise ReaderError("Not a Standard MIDI File")
    _, _, ntracks, division = struct.unpack(">IHHH", data[4:14])
    if division & 0x8000:
        raise ReaderError("SMPTE time division is not supported")
    ppq = division
    pos, events, end_tick = 8 + struct.unpack(">I", data[4:8])[0], [], 0
    for t in range(ntracks):
        if data[pos:pos + 4] != b"MTrk":
            raise ReaderError(f"Track {t + 1} is damaged")
        length = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        i, end, tick, status = pos + 8, pos + 8 + length, 0, 0
        while i < end:
            delta = 0
            while True:
                b = data[i]; i += 1
                delta = (delta << 7) | (b & 0x7F)
                if not b & 0x80:
                    break
            tick += delta
            b = data[i]
            if b & 0x80:
                status = b; i += 1
            if status == 0xFF:
                mtype = data[i]; i += 1
                ln = 0
                while True:
                    c = data[i]; i += 1
                    ln = (ln << 7) | (c & 0x7F)
                    if not c & 0x80:
                        break
                payload = data[i:i + ln]; i += ln
                if mtype == 0x51 and ln == 3:
                    events.append((tick, "tempo", 60e6 / int.from_bytes(payload, "big")))
                elif mtype == 0x58 and ln >= 2:
                    events.append((tick, "ts", (payload[0], 2 ** payload[1])))
                elif mtype == 0x2F:
                    end_tick = max(end_tick, tick)
                    break
            elif status in (0xF0, 0xF7):
                ln = 0
                while True:
                    c = data[i]; i += 1
                    ln = (ln << 7) | (c & 0x7F)
                    if not c & 0x80:
                        break
                i += ln
            else:
                i += 1 if (status & 0xF0) in (0xC0, 0xD0) else 2
        pos = end
        progress((t + 1) / max(ntracks, 1))

    events.sort(key=lambda e: e[0])
    points: list[TempoPoint] = [TempoPoint(0, 0, 120.0)]
    warnings = [] if any(e[1] == "tempo" for e in events) else ["No tempo events; assumed 120 BPM"]
    for tick, kind, val in events:
        beat = tick / ppq
        last = points[-1]
        if abs(beat - last.beat) > 1e-9:
            last = TempoPoint(beat, 0, last.bpm, last.num, last.den)
            points.append(last)
        if kind == "tempo":
            last.bpm = val
        else:
            last.num, last.den = val
    _fill_times_from_beats(points)
    return TempoMap(path, _dedupe(points), warnings, end_tick / ppq)


_PT = re.compile(r"^\s*PT\s+(\S+)\s+(\S+)(?:\s+(\S+))?(?:\s+(\S+))?")


def read_rpp(path: Path, progress: Progress) -> TempoMap:
    text = path.read_text(errors="replace")
    m = re.search(r"^\s*TEMPO\s+(\S+)\s+(\d+)\s+(\d+)", text, re.M)
    if not m:
        raise ReaderError("No TEMPO line found (is this a REAPER project?)")
    base = TempoPoint(0, 0, float(m.group(1)), int(m.group(2)), int(m.group(3)))
    points: list[TempoPoint] = []
    env = re.search(r"<TEMPOENVEX(.*?)^\s*>", text, re.S | re.M)
    if env:
        lines = env.group(1).splitlines()
        num, den = base.num, base.den
        for n, line in enumerate(lines):
            pm = _PT.match(line)
            if pm:
                shape = int(pm.group(3) or 0)
                ts = int(float(pm.group(4) or 0))
                if ts:
                    num, den = ts & 0xFFFF, ts >> 16
                points.append(TempoPoint(0, float(pm.group(1)), float(pm.group(2)),
                                         num, den, ramp=(shape == 0)))
            progress((n + 1) / max(len(lines), 1))
    if not points:
        points = [base]
    elif points[0].time > 0:
        points.insert(0, TempoPoint(0, 0, points[0].bpm, base.num, base.den))
    points[-1].ramp = False
    _fill_beats_from_times(points)
    end_seconds = _rpp_project_end(text)
    end_beat = _beat_at_time(points, end_seconds) if end_seconds is not None else None
    return TempoMap(path, _dedupe(points), project_end_beat=end_beat)


def _rpp_project_end(text: str) -> Optional[float]:
    """Find the latest media-item or region end in a REAPER project."""
    ends = []
    item_depth = None
    item_position = item_length = None
    for line in text.splitlines():
        stripped = line.strip()
        if item_depth is None and stripped.startswith("<ITEM"):
            item_depth, item_position, item_length = 1, None, None
            continue
        if item_depth is not None:
            if item_depth == 1:
                match = re.match(r"(?:POSITION|LENGTH)\s+(\S+)", stripped)
                if match:
                    value = float(match.group(1))
                    if not math.isfinite(value) or value < 0:
                        raise ReaderError("Invalid REAPER item timeline extent")
                    if stripped.startswith("POSITION"):
                        item_position = value
                    else:
                        item_length = value
            if stripped.startswith("<"):
                item_depth += 1
            elif stripped == ">":
                item_depth -= 1
                if item_depth == 0:
                    if item_position is not None and item_length is not None:
                        ends.append(item_position + item_length)
                    item_depth = None
        region = re.match(r"REGION\s+\S+\s+\S+\s+(\S+)", stripped)
        if region:
            end = float(region.group(1))
            if math.isfinite(end) and end >= 0:
                ends.append(end)
    return max(ends) if ends else None


def _beat_at_time(points: list[TempoPoint], time: float) -> float:
    """Convert absolute seconds to quarter notes through a tempo map."""
    if time <= points[0].time:
        return points[0].beat
    for point, nxt in zip(points, points[1:]):
        if time <= nxt.time:
            lo, hi = point.beat, nxt.beat
            for _ in range(60):
                mid = (lo + hi) / 2
                if point.ramp and point.ramp_domain == "beat":
                    elapsed = _beat_ramp_time_at(mid - point.beat, point.bpm, nxt.bpm,
                                                 nxt.beat - point.beat)
                elif point.ramp:
                    elapsed = _ramp_time_at(mid - point.beat, point.bpm, nxt.bpm,
                                            nxt.time - point.time)
                else:
                    elapsed = (mid - point.beat) * 60 / point.bpm
                if point.time + elapsed < time:
                    lo = mid
                else:
                    hi = mid
            return (lo + hi) / 2
    last = points[-1]
    return last.beat + (time - last.time) * last.bpm / 60


def read_als(path: Path, progress: Progress) -> TempoMap:
    """Read arrangement tempo from observed Live 8/9 and 10/12 XML layouts.

    Envelope-target lookup and sentinel handling are based on dawtool's real
    Live fixtures (see tests/fixtures/als/README.md). Times use the continuous
    integral of beat-linear BPM, not REAPER's time-linear ramps. Live playback
    quantization is not emulated; curved envelopes are rejected explicitly.
    """
    import xml.etree.ElementTree as ET

    try:
        text = gzip.decompress(path.read_bytes())
    except (OSError, EOFError, zlib.error) as exc:
        raise ReaderError("Invalid or corrupt gzip data (is this a .als?)") from exc
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ReaderError("Could not parse the XML inside the .als file") from exc

    live_set = root.find("LiveSet") if root.tag == "Ableton" else None
    if live_set is None:
        raise ReaderError("No Ableton LiveSet found")
    track = live_set.find("MainTrack")
    if track is None:
        track = live_set.find("MasterTrack")
    if track is None:
        raise ReaderError("No MainTrack or MasterTrack found")
    mixer = track.find("DeviceChain/Mixer")
    if mixer is None:
        mixer = track.find("MasterChain/Mixer")  # observed Live 8 layout
    if mixer is None:
        raise ReaderError("No main/master mixer found")
    tempo = mixer.find("Tempo")
    if tempo is None:
        raise ReaderError("No main/master Tempo parameter found")
    warnings: list[str] = []

    def number(el, attribute, label):
        raw = el.get(attribute) if el is not None else None
        if raw is None:
            raise ReaderError(f"Missing {label}")
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ReaderError(f"Missing or invalid {label}") from exc
        if not math.isfinite(value):
            raise ReaderError(f"Non-finite {label}")
        return value

    def events_for(parameter):
        if parameter is None:
            return []
        target = parameter.find("AutomationTarget")
        if target is not None and not target.get("Id"):
            raise ReaderError("Missing automation target Id")
        if target is not None:
            matches = []
            for env in track.findall("AutomationEnvelopes/Envelopes/AutomationEnvelope"):
                pointee = env.find("EnvelopeTarget/PointeeId")
                if pointee is not None and pointee.get("Value") == target.get("Id"):
                    matches.append(env)
            if len(matches) > 1:
                raise ReaderError("Ambiguous duplicate automation envelopes")
            if matches:
                events = matches[0].find("Automation/Events")
                if events is None:
                    raise ReaderError("Automation envelope has no Events")
                return list(events)
        events = parameter.find("ArrangerAutomation/Events")
        return list(events) if events is not None else []

    def parsed_events(parameter, tag, decode):
        out = []
        for ev in events_for(parameter):
            if ev.tag != tag:
                raise ReaderError(f"Unsupported {ev.tag} in {parameter.tag} automation")
            if any(key.startswith("CurveControl") for key in ev.attrib):
                raise ReaderError("Curved tempo automation is not supported")
            beat = number(ev, "Time", "automation beat")
            out.append((beat, decode(number(ev, "Value", f"{parameter.tag} value"))))
        # Stable sorting retains the two sides of a vertical tempo jump.
        return sorted(out, key=lambda ev: ev[0])

    def bpm(value):
        if value <= 0:
            raise ReaderError("Tempo must be positive")
        return value

    def meter(value):
        # EnumEvent value, NOT numerator/denominator bit packing. Independent
        # primary implementations: DawVert r_ableton.py and ableton-live-tools.
        if not value.is_integer() or not 0 <= value <= 494:
            raise ReaderError("Unsupported Ableton time-signature enum value")
        den_index, num_index = divmod(int(value), 99)
        return num_index + 1, 2 ** den_index

    def initial_and_events(parameter, events, decode, default=None):
        before = [value for beat, value in events if beat < 0]
        nonnegative = [(beat, value) for beat, value in events if beat >= 0]
        if before:
            initial = before[-1]
        elif nonnegative and nonnegative[0][0] == 0:
            initial = nonnegative[0][1]
        elif parameter is not None and parameter.find("Manual") is not None:
            initial = decode(number(parameter.find("Manual"), "Value", f"{parameter.tag} Manual"))
        elif default is not None:
            initial = default
            warnings.append("No time-signature data; assumed 4/4")
        else:
            raise ReaderError("No initial tempo automation or Manual tempo found")
        return initial, nonnegative

    raw_tempo = parsed_events(tempo, "FloatEvent", bpm)
    initial_bpm, tempo_events = initial_and_events(tempo, raw_tempo, bpm)
    tempo_points = [TempoPoint(0, 0, initial_bpm, ramp_domain="beat")]
    if tempo_events and tempo_events[0][0] == 0:
        tempo_points = []  # beat-zero automation overrides the pre-roll value
    for beat, value in tempo_events:
        tempo_points.append(TempoPoint(beat, 0, value, ramp_domain="beat"))
    # Pre-roll/Manual is held to the first actual breakpoint, not ramped from
    # the negative sentinel. Real breakpoint pairs interpolate in beat space.
    first_real = 1 if tempo_events and tempo_events[0][0] > 0 else 0
    for i in range(first_real, len(tempo_points) - 1):
        p, nxt = tempo_points[i:i + 2]
        p.ramp = nxt.beat > p.beat and nxt.bpm != p.bpm
    if any(p.ramp for p in tempo_points):
        warnings.append("ALS ramp times use continuous beat-linear integration; Live playback tempo quantization is not emulated")

    signature = mixer.find("TimeSignature")
    raw_meters = parsed_events(signature, "EnumEvent", meter)
    initial_meter, meter_events = initial_and_events(signature, raw_meters, meter, (4, 4))
    meters = [(0, *initial_meter)] + [(beat, *value) for beat, value in meter_events]
    points = _apply_meters(tempo_points, meters)
    _fill_times_from_beats(points)
    progress(1.0)
    parents = {child: parent for parent in live_set.iter() for child in parent}
    arrangement_ends = []
    for clip in live_set.iter():
        if clip.tag not in ("AudioClip", "MidiClip"):
            continue
        ancestor = parents.get(clip)
        in_arrangement = False
        while ancestor is not None:
            if ancestor.tag == "ArrangerAutomation":
                in_arrangement = True
                break
            ancestor = parents.get(ancestor)
        current_end = clip.find("CurrentEnd")
        if in_arrangement and current_end is not None:
            end = float(current_end.get("Value", "nan"))
            if math.isfinite(end) and end >= 0:
                arrangement_ends.append(end)
    project_end = max(arrangement_ends) if arrangement_ends else None
    return TempoMap(path, _dedupe(points), warnings, project_end)


def _apply_meters(tempo: list[TempoPoint], meters: list[tuple[float, int, int]]) -> list[TempoPoint]:
    """Insert every meter breakpoint, interpolating beat-linear tempo if needed."""
    if not meters:
        return tempo
    meters.sort(key=lambda m: m[0])
    out = list(tempo)
    existing = {p.beat for p in tempo}
    ti = 0
    for beat, _, _ in meters:
        if beat in existing:
            continue
        while ti + 1 < len(tempo) and tempo[ti + 1].beat <= beat:
            ti += 1
        p = tempo[ti]
        value = p.bpm
        if p.ramp and ti + 1 < len(tempo):
            nxt = tempo[ti + 1]
            value += (nxt.bpm - p.bpm) * (beat - p.beat) / (nxt.beat - p.beat)
        out.append(TempoPoint(beat, 0, value, ramp=p.ramp, ramp_domain=p.ramp_domain))
        existing.add(beat)
    out.sort(key=lambda p: p.beat)
    mi, num, den = 0, 4, 4
    for p in out:
        while mi < len(meters) and meters[mi][0] <= p.beat:
            _, num, den = meters[mi]
            mi += 1
        p.num, p.den = num, den
    return out


def _dedupe(points: list[TempoPoint]) -> list[TempoPoint]:
    out: list[TempoPoint] = []
    for p in points:
        if out and abs(p.bpm - out[-1].bpm) < 1e-6 and (p.num, p.den) == (out[-1].num, out[-1].den) \
                and not out[-1].ramp and not p.ramp:
            continue
        out.append(p)
    return out


from readers.ardour import read_ardour
from readers.dawproject import read_dawproject
from readers.lmms import read_lmms
from readers.studioone import read_studioone

# Experimental imports require explicit opt-in; registration is not a promise
# of complete support for every DAW version or automation type.
EXPERIMENTAL_EXTENSIONS = frozenset({".dawproject", ".mmp", ".mmpz", ".song"})
UNIMPLEMENTED_EXTENSIONS = frozenset({".flp", ".ptx", ".bwproject", ".logicx", ".cpr", ".npr", ".vip"})
READERS: dict[str, Callable[[Path, Progress], TempoMap]] = {
    ".mid": read_midi, ".midi": read_midi, ".smf": read_midi,
    ".rpp": read_rpp, ".als": read_als,
    ".ardour": read_ardour, ".dawproject": read_dawproject,
    ".mmp": read_lmms, ".mmpz": read_lmms, ".song": read_studioone,
}
SUPPORTED_EXTENSIONS = tuple(sorted(READERS))


def read_tempo_map(path: Path, progress: Progress = lambda f: None, *,
                   allow_experimental: bool = False) -> TempoMap:
    extension = path.suffix.lower()
    reader = READERS.get(extension)
    if reader is None:
        if extension in UNIMPLEMENTED_EXTENSIONS:
            raise ReaderError(f"Native {extension} tempo-map import is not implemented / not supported yet")
        raise ReaderError(f"Unsupported file type '{path.suffix}'")
    experimental = extension in EXPERIMENTAL_EXTENSIONS
    if experimental and not allow_experimental:
        raise ReaderError("Experimental format: enable 'Experimental imports' and reload. "
                          "DAW-host compatibility and complete automation support are not confirmed.")
    try:
        if extension == '.ardour' and allow_experimental:
            result = read_ardour(path, progress, allow_experimental=True)
        else:
            result = reader(path, progress)
        if experimental:
            result.warnings.insert(0, "EXPERIMENTAL / HOST UNCONFIRMED: verify this tempo map before use.")
        return result
    except ReaderError:
        raise
    except (IndexError, struct.error, ValueError) as exc:
        raise ReaderError(f"File appears damaged ({exc.__class__.__name__})") from exc


# --------------------------------------------------------------------------- export
@dataclass
class ExportOptions:
    ppq: int = 960
    ramp_step: float = 0.25        # quarter notes per tempo step when approximating ramps
    min_bpm_change: float = 0.05   # merge consecutive steps closer than this
    preserve_timing: bool = True   # step BPM = average over step (no timing drift)
    include_meter: bool = True
    overwrite: bool = False


def approximate(tm: TempoMap, opt: ExportOptions) -> list[tuple[float, float]]:
    """Return (beat, bpm) steps; linear ramps become stair steps."""
    steps: list[tuple[float, float, float]] = []   # (beat, time, bpm)
    pts = tm.points
    for i, p in enumerate(pts):
        nxt = pts[i + 1] if i + 1 < len(pts) else None
        if not (p.ramp and nxt):
            steps.append((p.beat, p.time, p.bpm))
            continue
        span_q, span_t = nxt.beat - p.beat, nxt.time - p.time
        n = max(1, math.ceil(span_q / opt.ramp_step - 1e-9))
        for k in range(n):
            q0, q1 = k * span_q / n, (k + 1) * span_q / n
            if p.ramp_domain == "beat":
                t0 = _beat_ramp_time_at(q0, p.bpm, nxt.bpm, span_q)
                t1 = _beat_ramp_time_at(q1, p.bpm, nxt.bpm, span_q)
            else:
                t0 = _ramp_time_at(q0, p.bpm, nxt.bpm, span_t)
                t1 = _ramp_time_at(q1, p.bpm, nxt.bpm, span_t)
            if opt.preserve_timing:
                bpm = 60.0 * (q1 - q0) / (t1 - t0)
            else:
                fraction = q0 / span_q if p.ramp_domain == "beat" else t0 / span_t
                bpm = p.bpm + (nxt.bpm - p.bpm) * fraction
            steps.append((p.beat + q0, p.time + t0, bpm))
    # merge steps whose change is below the threshold
    merged: list[list[float]] = []
    end_beat, end_time = pts[-1].beat, pts[-1].time
    for j, (q, t, bpm) in enumerate(steps):
        if merged and abs(bpm - merged[-1][2]) < opt.min_bpm_change:
            continue
        merged.append([q, t, bpm])
    if opt.preserve_timing:
        # recompute merged steps as averages so absolute timing is kept
        bounds = [(m[0], m[1]) for m in merged]
        for j in range(len(merged) - 1):
            (q0, t0), (q1, t1) = bounds[j], bounds[j + 1]
            if t1 > t0:
                merged[j][2] = 60.0 * (q1 - q0) / (t1 - t0)
    return [(q, bpm) for q, _, bpm in merged]


def _vlq(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.insert(0, (n & 0x7F) | 0x80)
        n >>= 7
    return bytes(out)


def write_midi(tm: TempoMap, dest: Path, opt: ExportOptions) -> int:
    events: list[tuple[int, int, bytes]] = []   # (tick, order, data)
    events.append((0, 0, b"\xFF\x03" + _vlq(9) + b"Tempo Map"))
    if opt.include_meter:
        last = None
        for p in tm.points:
            if (p.num, p.den) != last:
                if p.den <= 0 or p.den & (p.den - 1):
                    continue   # MIDI can only store power-of-two denominators
                dd = int(round(math.log2(p.den)))
                events.append((round(p.beat * opt.ppq), 1, bytes([0xFF, 0x58, 4, p.num, dd, 24, 8])))
                last = (p.num, p.den)
    steps = approximate(tm, opt)
    for q, bpm in steps:
        us = max(1, min(0xFFFFFF, round(60e6 / bpm)))
        events.append((round(q * opt.ppq), 2, b"\xFF\x51\x03" + us.to_bytes(3, "big")))
    events.sort(key=lambda e: (e[0], e[1]))
    last_event_tick = max(tick for tick, _, _ in events)
    last_point = tm.points[-1]
    fallback_end = last_point.beat + last_point.num * 4 / last_point.den
    project_end = tm.project_end_beat if tm.project_end_beat is not None else fallback_end
    if project_end <= 0 and last_point.beat <= 0:
        project_end = fallback_end
    end_tick = max(math.ceil(max(project_end, last_point.beat) * opt.ppq), last_event_tick + 1)
    body, now = bytearray(), 0
    for tick, _, ev in events:
        body += _vlq(tick - now) + ev
        now = tick
    body += _vlq(end_tick - now) + b"\xFF\x2F\x00"
    header = b"MThd" + struct.pack(">IHHH", 6, 1, 1, opt.ppq)
    dest.write_bytes(header + b"MTrk" + struct.pack(">I", len(body)) + bytes(body))
    return len(steps)


def write_csv(tm: TempoMap, dest: Path, opt: ExportOptions) -> int:
    with dest.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["position", "beat_qn", "time_s", "bpm", "meter", "ramp_to_next"])
        for p in tm.points:
            w.writerow([tm.bar_beat(p.beat), f"{p.beat:.6f}", f"{p.time:.6f}",
                        f"{p.bpm:.4f}", f"{p.num}/{p.den}", int(p.ramp)])
    return len(tm.points)


EXPORTERS = {"MIDI tempo track (.mid)": (".mid", write_midi),
             "Spreadsheet (.csv)": (".csv", write_csv)}


def export_path(tm: TempoMap, out_dir: Optional[Path], suffix: str, overwrite: bool) -> Path:
    folder = out_dir or tm.source.parent
    dest = folder / f"{tm.source.stem}.tempo{suffix}"
    n = 1
    while not overwrite and dest.exists():
        dest = folder / f"{tm.source.stem}.tempo ({n}){suffix}"
        n += 1
    return dest
