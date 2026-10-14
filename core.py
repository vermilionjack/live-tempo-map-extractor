"""Core logic: tempo-map model, project readers and exporters (no GUI code).

Add a reader for a new project format by writing a function
``read_xxx(path, progress) -> TempoMap`` and registering it in READERS.
"""
from __future__ import annotations

import csv
import math
import re
import struct
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
    ramp: bool = False   # True: tempo ramps linearly (in time) to the next point


@dataclass
class TempoMap:
    source: Path
    points: list[TempoPoint]
    warnings: list[str] = field(default_factory=list)

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


def _fill_times_from_beats(points: list[TempoPoint]) -> None:
    for prev, cur in zip(points, points[1:]):
        cur.time = prev.time + (cur.beat - prev.beat) * 60.0 / prev.bpm


# --------------------------------------------------------------------------- readers
def read_midi(path: Path, progress: Progress) -> TempoMap:
    data = path.read_bytes()
    if data[:4] != b"MThd":
        raise ReaderError("Not a Standard MIDI File")
    _, _, ntracks, division = struct.unpack(">IHHH", data[4:14])
    if division & 0x8000:
        raise ReaderError("SMPTE time division is not supported")
    ppq = division
    pos, events = 8 + struct.unpack(">I", data[4:8])[0], []
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
    return TempoMap(path, _dedupe(points), warnings)


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
    return TempoMap(path, _dedupe(points))


def _dedupe(points: list[TempoPoint]) -> list[TempoPoint]:
    out: list[TempoPoint] = []
    for p in points:
        if out and abs(p.bpm - out[-1].bpm) < 1e-6 and (p.num, p.den) == (out[-1].num, out[-1].den) \
                and not out[-1].ramp:
            continue
        out.append(p)
    return out


READERS: dict[str, Callable[[Path, Progress], TempoMap]] = {
    ".mid": read_midi, ".midi": read_midi, ".smf": read_midi,
    ".rpp": read_rpp,
}
SUPPORTED_EXTENSIONS = tuple(sorted(READERS))


def read_tempo_map(path: Path, progress: Progress = lambda f: None) -> TempoMap:
    reader = READERS.get(path.suffix.lower())
    if reader is None:
        raise ReaderError(f"Unsupported file type '{path.suffix}'")
    try:
        return reader(path, progress)
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
            t0 = _ramp_time_at(q0, p.bpm, nxt.bpm, span_t)
            t1 = _ramp_time_at(q1, p.bpm, nxt.bpm, span_t)
            if opt.preserve_timing:
                bpm = 60.0 * (q1 - q0) / (t1 - t0)
            else:
                bpm = p.bpm + (nxt.bpm - p.bpm) * t0 / span_t
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
    body, now = bytearray(), 0
    for tick, _, ev in events:
        body += _vlq(tick - now) + ev
        now = tick
    body += b"\x00\xFF\x2F\x00"
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
