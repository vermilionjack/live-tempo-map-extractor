# FL Studio / Studio One reader evidence

## Delivery and confidence

- `readers/flstudio.py`: **UNSUPPORTED, all native .flp projects rejected**.
  No scalar/base-BPM fallback. A seemingly static file does not prove the
  absence of initialized controls, pattern automation, tempo-linked clips,
  controller mappings, overlapping clips or curves.
- `readers/studioone.py`: **EXPERIMENTAL / HOST UNCONFIRMED**. Reads only the
  observed Studio One 5.5.2 ZIP/XML constant-segment layout. Every successful
  result carries that warning. Not a claim of general Studio One support.
- No parser dependency added; both readers import `core` inside the reader
  function only. Registration is intentionally left to the parent worker.

## Primary sources inspected (2026-10-14)

1. PyFLP source, commit `f937126b888ce94271bfea631b89166c74056530`:
   https://github.com/demberto/PyFLP/blob/f937126b888ce94271bfea631b89166c74056530/pyflp/project.py
   `Project.tempo` is explicitly documented as tempo **at the current playhead**;
   event 156 stores BPM times 1000, not a global arrangement tempo map.
   `channel.py` leaves controller linking as a TODO, while `controller.py`
   exposes partially understood parameter/destination fields. Decoding points
   alone is therefore insufficient evidence for extracting global tempo.
   https://github.com/demberto/PyFLP/blob/f937126b888ce94271bfea631b89166c74056530/pyflp/controller.py
   https://github.com/demberto/PyFLP/blob/f937126b888ce94271bfea631b89166c74056530/pyflp/channel.py
   https://github.com/demberto/PyFLP/blob/f937126b888ce94271bfea631b89166c74056530/pyproject.toml
   https://pypi.org/pypi/pyflp/json
2. flpkit source, commit `23b200e654616f6fe41d5418d3cca84bfc0b101b`:
   https://github.com/clarkipeng/flpkit/blob/23b200e654616f6fe41d5418d3cca84bfc0b101b/README.md
   MIT, dependency-free, differential/host-tested parser; it explicitly says
   automation **target-link bytes remain undecoded**. A good future parser
   substrate, but not evidence that native global tempo maps are resolved.
   https://github.com/clarkipeng/flpkit/blob/23b200e654616f6fe41d5418d3cca84bfc0b101b/pyproject.toml
   https://pypi.org/pypi/flpkit/json
3. studio-one-mcp author-maintained source, MIT, commit
   `063f7987f1095b836d07335bd823132b9f6e84b5`:
   https://github.com/NeanderthalMan/studio-one-mcp/blob/063f7987f1095b836d07335bd823132b9f6e84b5/src/song.js
   Its comments and README report verification on Studio One 5.5.2:
   tempo segment `tempo` is **seconds per quarter-note beat**; e.g. 0.5 is
   120 BPM. Positions in the observed map are quarter-note beats. We do NOT
   reproduce its default-BPM fallback or general curve handling.
   https://github.com/NeanderthalMan/studio-one-mcp/blob/063f7987f1095b836d07335bd823132b9f6e84b5/test/helpers/fixtures.js
   This source supplies a **synthetic** observed-shape fixture, including
   `Song/song.xml`, `Root/timeContext`, `tempoMap`, `timeSignatureMap`,
   `curveType="0"` and final `end="1e200"`. Our fixture is independently
   constructed in that shape, with extra tempo/meter changes for integration.
   https://github.com/NeanderthalMan/studio-one-mcp/blob/063f7987f1095b836d07335bd823132b9f6e84b5/LICENSE
   Upstream copyright: Copyright (c) 2026 Origami Research. MIT permission
   grants use/copy/modify/distribute subject to preserving its notice;
   software is supplied without warranty. No upstream implementation copied.
4. Independent ZIP entry corroboration, SongLens MIT source:
   https://github.com/askinner432/SongLens/blob/fb43906d1509ca3ad31bea1217cec73c0ed483cd/src/SongMetainfoBrowser.Core/SongMetadataReader.cs
   `LoadSongDocument` reads `Song/song.xml`. Project-Hub source independently
   uses `TempoMapSegment` and `60 / tempo`:
   https://github.com/anthogoz/Studio-One-Project-Hub/blob/main/src/components/StructureTempoMap.jsx

These are reverse-engineering authors' primary implementations, not official
DAW vendor format specifications. Search and direct GitHub/PyPI API retrieval
were used; no official published complete native schema was found.

## Fixture provenance / real-file limit

`studioone/steps.song` is an actual ZIP file inspected using Python ZipFile.
Entries: `Song/song.xml`, `metainfo.xml`. It is **synthetic, not saved by Studio
One**. Its generator metadata describes the modeled layout, not native-host
provenance. Global tempo points: 120 BPM at beat 0, 60 at beat 32, 90 at beat 40;
3/4 begins at beat 16. Exact integrated seconds: 0, 8, 16, 24.

`flstudio/base-tempo.flp` is a **synthetic FLhd/FLdt minimal binary** with a
single 156 event at 120000. It demonstrates explicit refusal to interpret a
base/playhead scalar as a map. It is not an FL-authored project or validation
of FLP parsing (the adapter deliberately performs no FLP parsing).

No real Studio One song was available locally or in the inspected upstream
fixture trees. Studio One was not installed in the inspected /Applications
listing. Consequently **native real-project and host verification remain
unfulfilled**, prominently disclosed rather than implied by synthetic tests.

## Supported Studio One subset / fail-closed boundaries

- Exactly one `Song/song.xml`; bounded to 8 MiB, no extraction to disk.
- Observed UTF-8/non-namespaced `Song`, `Attributes x:id="Root"` with
  `defaultTimeFormat="2"`, unique `Attributes x:id="timeContext"`.
- Unique global `TempoMap x:id="tempoMap"` and `TimeSignatureMap
  x:id="timeSignatureMap"`; both must explicitly start at beat zero.
- Constant `TempoMapSegment` only: exact attributes `curveType`, `start`,
  `end`, `tempo`; finite positive tempo duration; strictly ordered contiguous
  segments; final observed effectively-infinite sentinel required.
- TimeSignatureMapSegment only: exact `start`, `numerator`, `denominator`;
  integer positive meters and power-of-two denominator; strictly ordered.
- Global tempo and meter event positions merged before integrating seconds,
  so a meter-only point inside a tempo segment has correct absolute time.
- Curves, end-tempo/tension or other extra attributes, unknown target content,
  gaps, overlaps, non-finite values, wrong units, ambiguous global maps,
  malformed archives/XML, DTD/entity declarations are rejected as ReaderError.
- Observed undeclared `x:id` prefix gets a supplied namespace only; no other
  general malformed XML repair. Already-declared x namespace also tested.

## Dependency recommendations (API-confirmed)

- **Do not add PyFLP now**: PyPI 2.2.1, Python >=3.8, GPL-3.0;
  79,232-byte wheel, 1,541,432-byte source distribution. Runtime dependencies:
  construct-typing >=0.5.6 (which brings construct), sortedcontainers >=2.4.0,
  typing-extensions >=4.6.1, f-enum >=0.2.0 for Python <=3.10.
  This is Python-3.9 compatible but introduces distribution/license review
  and still does not solve reliable tempo targeting. No GPL implementation
  was copied or installed.
- **Future preferred permissive substrate: flpkit**. PyPI 0.8.1,
  34,947-byte wheel, 54,970-byte sdist, no runtime dependencies, MIT license
  verified in repository (PyPI legacy license field is null). Requires
  Python >=3.11, so **cannot be adopted into this Python-3.9+ app as-is**.
  Requires a tested compatibility port or raising the app's minimum version,
  plus real global-target/initialization/arrangement decoding first.
- Studio One step subset uses stdlib zipfile/xml only. Adding a ZIP/XML package
  would not remove the outstanding native-format/curve validation work.

## Actual test evidence

Interpreter: Python 3.9.6 (system python3 on macOS).
Commands: `python3 -m unittest discover -s tests -p test_studioone.py -v` and
`python3 -m unittest discover -s tests -p test_flstudio.py -v`.

- Initial REDs: missing reader module (availability baseline only).
- Studio One semantic RED 1: four unsupported curve/target/attribute cases
  incorrectly accepted; then GREEN, 2 test methods.
- Studio One semantic RED 2: invalid duration leaked ZeroDivisionError;
  invalid meter leaked ValueError; nine invalid/discontinuous cases accepted;
  then GREEN, 3 test methods.
- Studio One semantic RED 3: DTD and competing global map accepted;
  then GREEN, 7 test methods.
- Studio One semantic RED 4: unknown terminal sentinel, meter past sentinel,
  and overflowing integrated times accepted; then GREEN, 11 test methods.
  UTF-16 entity fixture rejected (that case already failed closed on parsing).
- FL rejection GREEN: 1 test method.
- Final dedicated total: 12 tests, all passing. Fresh-process import probe
  confirmed importing either adapter does not import core.
- Full contemporaneous suite: `python3 -m unittest discover -s tests -v`,
  exit 0, **96 tests passed**. Qt emitted font-alias and offscreen-plugin
  informational warnings; no test failures. Other workers were editing their
  readers concurrently, so this is a snapshot of the combined working tree.

Fixture SHA-256 / bytes:
- `studioone/steps.song`: 572 bytes,
  `15da6838797e4437d26ff1658bc0439d7a58d4f4b4c64e368ddd67d363fcccdf`.
- `flstudio/base-tempo.flp`: 27 bytes,
  `935703c20e9920bda2fd90bc8636b36d8700c145fbaacd181f0a090f6c8ad127`.

Status: **UNIT / SYNTHETIC-FILE VERIFIED; NATIVE HOST NOT TESTED**.
