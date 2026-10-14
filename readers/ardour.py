"""Conservative Ardour session reader (source links in fixture PROVENANCE.md).

Import core only at call time so core can register this adapter without cycles.
Unsupported serialization is a ReaderError, never a guessed constant map.
"""
from pathlib import Path
import math
import re
import xml.etree.ElementTree as ET


def read_ardour(path, progress=None, *, allow_experimental=False):
    """Read verified legacy initial BBT maps or opt-in Temporal step maps.

    Temporal support requires an explicit clock rate, consistent serialized
    quarters/time, and bar-aligned integer meters. Returned warnings MUST be
    displayed by callers. Ramps, BBT resets and legacy frame/pulse maps fail.
    No sample-rate or superclock-rate defaults are used.
    """
    from core import ReaderError, TempoMap, TempoPoint

    path = Path(path)
    if progress:
        progress(0.0)
    class NoDoctype(ET.TreeBuilder):
        def doctype(self, name, pubid, system):
            raise ReaderError("Ardour XML DTD/entity declarations are not supported")

    try:
        root = ET.parse(path, parser=ET.XMLParser(target=NoDoctype())).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ReaderError("Cannot read Ardour XML: {}".format(exc)) from exc
    if root.tag != "Session":
        raise ReaderError("Not an Ardour Session")
    maps = root.findall("TempoMap")
    if len(maps) != 1:
        raise ReaderError("Ardour requires exactly one TempoMap")
    def number(element, name, positive=True):
        try:
            value = float(element.attrib[name])
        except (KeyError, ValueError) as exc:
            raise ReaderError("Invalid or missing Ardour {}".format(name)) from exc
        if not math.isfinite(value) or (positive and value <= 0):
            raise ReaderError("Invalid Ardour {}".format(name))
        return value

    def integral(element, name, power_two=False):
        value = number(element, name)
        if not value.is_integer() or value > 2**31 - 1:
            raise ReaderError("Unsupported fractional or out-of-range Ardour {}".format(name))
        value = int(value)
        if power_two and value & (value - 1):
            raise ReaderError("Unsupported non-binary Ardour {}".format(name))
        return value

    node = maps[0]
    if node.find("Tempos") is not None or node.find("Meters") is not None:
        if not allow_experimental:
            raise ReaderError("Modern Ardour maps are experimental; explicit opt-in required")
        if any(child.tag not in ("Tempos", "Meters", "MusicTimes") for child in node):
            raise ReaderError("Unsupported mixed Ardour tempo-map serialization")
        if any(len(node.findall(tag)) > 1 for tag in ("Tempos", "Meters", "MusicTimes")):
            raise ReaderError("Duplicate Ardour tempo-map containers")
        if any(len(child) for child in node.findall("MusicTimes")):
            raise ReaderError("Unsupported Ardour MusicTimes/BBT-reset anchors")

        def uint(element, name):
            text = element.get(name, "")
            if not re.fullmatch(r"[0-9]{1,19}", text):
                raise ReaderError("Invalid or missing Ardour {}".format(name))
            value = int(text)
            if value > 2**63 - 1:
                raise ReaderError("Ardour {} is outside signed superclock range".format(name))
            return value

        rate = uint(node, "superclocks-per-second")
        if rate == 0:
            raise ReaderError("Ardour superclocks-per-second must be positive")

        def position(element):
            clock = uint(element, "sclock")
            text = element.get("quarters", "")
            match = re.fullmatch(r"([0-9]{1,10}):([0-9]{1,4})", text)
            if match:
                whole, ticks = map(int, match.groups())
                if whole > 2**31 - 1 or ticks >= 1920:
                    raise ReaderError("Invalid Ardour quarter-note ticks")
                beat = whole + ticks / 1920.0
            else:
                # Beats::operator>> also accepts pre-nutempo bare doubles.
                beat = number(element, "quarters", positive=False)
            if beat < 0 or not re.fullmatch(r"[1-9][0-9]*\|[1-9][0-9]*\|[0-9]+",
                                          element.get("bbt", "")):
                raise ReaderError("Invalid Ardour position/BBT")
            if beat == 0 and element.get("bbt") != "1|1|0":
                raise ReaderError("Unsupported nonstandard Ardour origin/BBT")
            return clock, beat

        def entries(container_name, child_name):
            containers = node.findall(container_name)
            if len(containers) != 1 or not len(containers[0]):
                raise ReaderError("Missing Ardour {}".format(container_name))
            values = []
            for element in containers[0]:
                if element.tag != child_name or len(element):
                    raise ReaderError("Unsupported Ardour {} entry".format(container_name))
                clock, beat = position(element)
                if values and (clock <= values[-1][0] or beat <= values[-1][1]):
                    raise ReaderError("Ardour positions must be strictly increasing")
                values.append((clock, beat, element))
            if values[0][:2] != (0, 0):
                raise ReaderError("Ardour tempo and meter must start at explicit zero")
            return values

        tempos = entries("Tempos", "Tempo")
        meters = entries("Meters", "Meter")
        events = {}
        for clock, beat, tempo in tempos:
            npm = number(tempo, "npm")
            if number(tempo, "enpm") != npm or tempo.get("type") != "Constant":
                raise ReaderError("Unsupported Ardour ramp; cannot export as a linear ramp")
            if "omega" in tempo.attrib and number(tempo, "omega", positive=False) != 0:
                raise ReaderError("Unsupported Ardour ramp coefficient")
            if tempo.get("continuing", tempo.get("clamped", "no")).lower() not in ("no", "false", "0"):
                raise ReaderError("Unsupported Ardour continuing tempo")
            if tempo.get("active", "yes").lower() not in ("yes", "true", "1"):
                raise ReaderError("Unsupported inactive Ardour tempo")
            note = integral(tempo, "note-type", power_two=True)
            bpm = npm * (4.0 / note)
            if not math.isfinite(bpm) or bpm <= 0:
                raise ReaderError("Invalid Ardour quarter-note tempo")
            events[clock] = [beat, bpm, None]
        for clock, beat, meter in meters:
            signature = (integral(meter, "divisions-per-bar"),
                         integral(meter, "note-value", power_two=True))
            event = events.setdefault(clock, [beat, None, None])
            if event[0] != beat:
                raise ReaderError("Conflicting Ardour tempo/meter positions")
            event[2] = signature
        points = []
        bpm, signature = None, None
        meter_start = 0.0
        for clock, (beat, new_bpm, new_signature) in sorted(events.items()):
            seconds = clock / rate
            if points:
                previous = points[-1]
                expected = previous.beat + (seconds - previous.time) * previous.bpm / 60.0
                # Beats are quantized to 1920 PPQN; clocks to one explicit tick.
                tolerance = 1.0 / 1920 + previous.bpm / (60.0 * rate)
                if beat <= previous.beat or abs(expected - beat) > tolerance:
                    raise ReaderError("Inconsistent Ardour serialized beat/time positions")
            if new_signature is not None and signature is not None:
                bar_span = signature[0] * 4.0 / signature[1]
                bars = (beat - meter_start) / bar_span
                if abs(bars - round(bars)) > 1e-8:
                    raise ReaderError("Unsupported mid-bar Ardour meter change")
                meter_start = beat
            if new_bpm is not None:
                bpm = new_bpm
            if new_signature is not None:
                signature = new_signature
            if bpm is None or signature is None:
                raise ReaderError("Missing initial Ardour tempo/meter")
            points.append(TempoPoint(beat, seconds, bpm, *signature))
        result = TempoMap(path, points, warnings=[
            "Experimental Ardour Temporal reader: source-verified constant segments only; "
            "no real modern session fixture or Ardour-host validation."])
        if progress:
            progress(1.0)
        return result

    if any(child.tag not in ("Tempo", "Meter") for child in node):
        raise ReaderError("Unsupported Ardour tempo-map serialization")
    tempos = node.findall("Tempo")
    meters = node.findall("Meter")
    if (len(tempos), len(meters)) != (1, 1):
        raise ReaderError("Unsupported Ardour map: only initial legacy BBT maps are verified")
    tempo, meter = tempos[0], meters[0]
    if len(tempo) or len(meter):
        raise ReaderError("Unsupported nested Ardour legacy tempo/meter state")
    if tempo.get("start") != "1|1|0" or meter.get("start") != "1|1|0":
        raise ReaderError("Unsupported Ardour legacy position (requires initial 1|1|0)")
    if any(key in element.attrib for element in (tempo, meter)
           for key in ("frame", "pulse", "sclock", "quarters")):
        raise ReaderError("Unsupported Ardour mixed or frame/pulse positions")
    if tempo.get("active", "yes").lower() not in ("yes", "true", "1"):
        raise ReaderError("Unsupported inactive Ardour tempo")
    if tempo.get("tempo-type", "Constant") != "Constant":
        raise ReaderError("Unsupported Ardour ramp")
    npm = number(tempo, "beats-per-minute")
    if ("end-beats-per-minute" in tempo.attrib
            and number(tempo, "end-beats-per-minute") != npm):
        raise ReaderError("Unsupported Ardour ramp (nonconstant endpoint)")
    note = integral(tempo, "note-type", power_two=True)
    den = integral(meter, "note-type", power_two=True)
    meter_name = "divisions-per-bar" if "divisions-per-bar" in meter.attrib else "beats-per-bar"
    num = integral(meter, meter_name)
    bpm = npm * (4.0 / note)
    if not math.isfinite(bpm) or bpm <= 0:
        raise ReaderError("Invalid Ardour quarter-note tempo")
    result = TempoMap(path, [TempoPoint(0, 0, bpm, num, den)])
    if progress:
        progress(1.0)
    return result
