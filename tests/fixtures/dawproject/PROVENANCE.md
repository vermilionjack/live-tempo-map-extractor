# DAWproject fixture provenance and validation limits

## Primary specification

Bitwig's open DAWproject repository, pinned revision
`ee4dcdde75940f30e14e55401a26955a58b8322b`:
https://github.com/bitwig/dawproject/tree/ee4dcdde75940f30e14e55401a26955a58b8322b

Consulted Project.xsd and the Java source classes Arrangement, Transport,
Timeline, Points, RealPoint, Point, TimeUnit, TimeSignaturePoint,
AutomationTarget, and Interpolation. TimeUnit beats means quarter notes.
RealPoint interpolation applies to the outgoing segment; omitted means hold.
Linear tempo is integrated in the automation timeline's native coordinate
(beats or seconds), not approximated as a step or as the other ramp domain.

## Bitwig example

`bitwig-example.project.xml` is the complete XML example from the upstream
README.md at that revision, extracted from its XML code fence; a newline was
appended. Tests package these real example bytes into a ZIP at runtime. It is
not an independently exported binary project or a fabricated successful export.
Bitwig's README identifies the example as its example project. It contains
149 BPM, 4/4. Source license: MIT, copyright (c) 2020 Bitwig, full unchanged
notice in BITWIG-LICENSE.

SHA-256: `df82d509b02284da2a87f2cd7fcbb47b8212fedd536fec573918f2e1e023e2c5`

## Public archives (not created by this implementation)

Repository: https://github.com/audiohacking/daw2logic
Pinned revision: `490aaa7baddffc94c26a35fdfcf76840d377bb96`.
Paths: `tests/fixtures/bitwig_simple.dawproject` and
`tests/fixtures/bitwig_extended.dawproject`.
Both files are downloaded verbatim. Upstream README states the fixtures are
built from the Bitwig DAWproject example; these are public converter test
fixtures, NOT proof of an independent DAW export or a DAW round-trip.
The upstream README's License section states MIT, but no standalone LICENSE
file exists at this pinned revision. Preserve Bitwig's underlying MIT notice.
No separate licensing of included media was verified. These are test-only
fixtures, never application inputs bundled as sample commercial content.

- bitwig_simple.dawproject SHA-256:
  `10d218aea875b30b84b9693b0c941292752e64bf2f34661c9dc69c49313ba1a0`
- bitwig_extended.dawproject SHA-256:
  `61f46fde1cacb0646dd0c1ea373c1e8fc1e27eb3f8d7e0aceb0e1ec9445d08d0`

The extended fixture uses legacy `TempoAutomation target="id0"` rather than
current `<Target parameter="id0"/>`; reader accepts that only with an explicit
warning. Expected map is 120 BPM at beat 0 and 140 BPM at beat 4 (2 seconds),
with HOLD interpolation, not an invented ramp.

## Regression fixtures and limits

Minimal archives constructed inside tests/test_dawproject.py are authored
regressions, explicitly not captured DAW exports. They exercise beat-linear
and second-linear increasing/decreasing/equal ramps, mixed meter timing,
non-quarter-note meter denominators, malformed/unsupported automation,
and container/XML protections. No real public ramp fixture was located here;
ramp math is unit-verified against analytic integrals, DAW playback unverified.

The reader is explicitly experimental and tempo/meter-only. It does not
validate unrelated audio/plugins/tracks against the full XSD. Unsupported
curve modes and invalid tempo targets fail; there is no silent ramp flattening.
Only Project version 1.0 is accepted. Negative positions and duplicate events
are rejected as unsupported/ambiguous, not guessed.

Integration: register read_dawproject(path, progress) for `.dawproject`.
Requires core.TempoPoint(..., ramp, ramp_domain) with `ramp_domain="beat"`
or `"time"`, core.TempoMap(source, points, warnings), and core.ReaderError.
Core import occurs at function invocation to avoid a registry import cycle.
The parent owns readers/__init__.py and registration/UI/filter changes.
