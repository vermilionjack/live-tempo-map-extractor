# ALS fixture provenance and audit evidence

These **unaltered gzip-compressed Ableton projects** are copied from the public
`offlinemark/dawtool` repository, pinned to commit
`44f3e19ffc686477051e2d8a9049a838018d6256`:

https://github.com/offlinemark/dawtool/tree/44f3e19ffc686477051e2d8a9049a838018d6256/tests/als

| Local file | Upstream relative path | XML Creator | Evidence |
| --- | --- | --- | --- |
| `example-140.als` | `tests/als/example-140.als` | Ableton Live 10.1.7 | Constant 140 BPM, target-linked sentinel envelope |
| `automation.als` | `tests/als/automation.als` | Ableton Live 10.1.7 | MasterTrack, beats 4/8/12, BPM 60/120/200 |
| `L12-automation.als` | `tests/als/L12-automation.als` | Ableton Live 12.0b16 | MainTrack, same automation as Live 10 fixture |
| `live8-patch-markers-noauto.als` | `tests/als/live8/live8-patch-markers-noauto.als` | Ableton Live 8.1.4 | MasterChain/Mixer, legacy sentinel at 95.3 BPM |
| `live9-patch-markers-noauto.als` | `tests/als/live9/live9-patch-markers-noauto.als` | Ableton Live 9.7.1 | DeviceChain/Mixer, legacy sentinel at 135 BPM |
| `automation-pathological.als` | `tests/als/automation-pathological.als` | Ableton Live 10.1.7 | 663 events, duplicate-beat vertical jumps, fractional beat positions |

`test_fixture_bytes_match_pinned_public_sources` verifies their SHA-256 digests.
`DAWTOOL-LICENSE` is the complete unmodified upstream license/notice. No dawtool
Python implementation or GPL FL Studio parser is vendored into this project.
All XML built by `synthetic()` in `test_als.py` is explicitly synthetic; it is
not presented as an actual saved Live project.

## Primary-source implementation evidence

* Target linkage, Manual fallback, legacy XML, MainTrack rename, FloatEvent
  beat positions and curve fields:
  https://github.com/offlinemark/dawtool/blob/44f3e19ffc686477051e2d8a9049a838018d6256/dawtool/daw/ableton.py
* BPM interpolates in beat space; theoretical integration versus playback
  quantization are distinct modes:
  https://github.com/offlinemark/dawtool/blob/44f3e19ffc686477051e2d8a9049a838018d6256/dawtool/project.py
  https://github.com/offlinemark/dawtool/blob/44f3e19ffc686477051e2d8a9049a838018d6256/dawtool/util.py
* Independent meter enum decoding (numerator = value % 99 + 1,
  denominator = 2 ** (value // 99)), rather than fabricated bit packing:
  https://github.com/SatyrDiamond/DawVert/blob/c6c8be9e0660d9e75a3acecce43a13b0dbe0029c/plugins/input/r_ableton.py
* Independently observed meter enum range 0..494:
  https://github.com/evanmusial/ableton-live-tools/blob/560d96c60dd175bb431c52d02828879f1dbce76c/src/extract_timeline.py

These are implementations and real fixtures, **not an official Ableton ALS
schema**. The vendored fixtures' main meter is 4/4 (enum 201); other meter values
and meter changes have synthetic, implementation-grounded coverage, not an
actual varied-meter Live-save fixture.

## RED/GREEN evidence

Interpreter: system `python3`, Python 3.9.6. Commands run from the private repo;
only public reference repositories were cloned externally. No private source
was uploaded, and no push/release operation was performed.

Before repair:

```
python3 -m unittest discover -s tests -p test_als.py -v
Ran 16 tests; FAILED (failures=23, errors=1); exit 1
```

Counts include unittest subtest failures. Real Live 10 and Live 12 tempo maps
collapsed to fabricated 120 BPM; the actual 140 BPM file read as 120. Synthetic
regressions showed ignored target envelopes, Manual tempo/meter ignored,
missing meters, incorrect ramp integration, accepted invalid values and ignored
curves. Corrupt DEFLATE raised raw `zlib.error`. Existing Live 8/9 sentinel and
REAPER ramp cases already passed, so they are preservation tests, not new RED
claims. Progress checking was separated from semantic assertions before this
recorded RED run. An initial fixture expectation was corrected by inspecting the
actual Live 8 XML: its tempo is 95.3, not guessed from the Live 9 fixture.

A second cycle after the initial fix:

```
python3 -m unittest discover -s tests -p test_als.py -v
Ran 21 tests; FAILED (failures=1); exit 1
```

The remaining failure was missing AutomationTarget Id silently ignoring modern
automation. It now raises ReaderError. Additional passing tests cover ambiguous
and damaged matching envelopes, beat-zero overrides, fixture hashes and real
vertical jumps.

After repair, focused suites:

```
python3 -m unittest discover -s tests -p test_als.py -q  # 21 tests, OK
python3 -m unittest discover -s tests -p test_core.py -q # 3 tests, OK
python3 -m unittest discover -s tests -p test_gui.py -q  # 9 tests, OK
```

GUI suite is another worker's work and emits offscreen Qt plugin/font notices.
The concurrent full-suite run at this checkpoint had 42 tests and exited 1:
9 Ardour subtest failures, one historical Ardour meter error, and a missing
`readers.lmms` module from other workers' in-progress files. ALS/core/GUI passed;
this is **not** a claim that the shared repository's full suite was green then.

## Timing verification and limitations

The reference implementation was installed in an isolated scratch virtualenv
and genuinely executed in both modes (initial direct import was blocked by its
missing `hexdump` dependency, resolved in that isolated environment). Both real
ramp fixtures at beat 12 return:

* dawtool theoretical: `8.305065593537753` seconds
* dawtool quantized/playback model: `8.393819392378715` seconds

Our continuous integration matches the theoretical mode. A separate SciPy
quadrature probe (seed 0, 300 positive random rising/falling segments and partial
positions) passed at 1e-10 tolerance; worst absolute error was
`2.4158453015843406e-13` seconds. `compileall` and `git diff --check` also passed.
Every ALS ramp map
warns that Live playback quantization is **not emulated**; exact Live rendered
sample positions are not claimed. Curved envelopes (any CurveControl fields)
are explicitly rejected instead of silently linearized. REAPER remains
linear-in-time; ALS uses the explicit `TempoPoint.ramp_domain = "beat"` and
logarithmic integration, including meter splits and MIDI step export.

No Ableton-host execution was performed. This fixture set does not establish
all-version compatibility (notably Live 11 and current Live 12 releases are not
represented; the Live 12 file is a beta). Session tempo changes, external sync,
clip warping, and arbitrary curved automation are outside this arrangement
reader. CSV preserves point BPM/time/meter/ramp flags but its existing schema
does not serialize ramp_domain; it is a point listing, not a lossless curve
exchange format.
