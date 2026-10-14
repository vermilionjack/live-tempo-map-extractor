# LMMS reader evidence and support boundary

**Experimental / partial.** Constant tempo, static meter, and one ID-bound
song-timeline discrete tempo pattern are supported. Not a general LMMS playback
engine. Meter automation, interpolated tempo, multiple competing tempo clips,
BB/nested tempo clips, legacy embedded tempo/meter envelopes, unknown time-node
fields, controller-driven models and logarithmic target scaling are rejected.
A rejected automated project never silently falls back to header BPM.

Unbound patterns (including ones named `Tempo`) are not tempo bindings. They are
ignored with a warning. Unresolved object IDs cause a prominent `WARNING` that
map completeness cannot be established and host verification is required. This
is deliberate partial-reader behavior, not a claim that header BPM is a complete
map. All reads carry an experimental warning. Fractional/out-of-range model
values and non-power-of-two meter denominators are conservatively rejected rather
than reproducing LMMS's integer-model rounding/clamping or exporter limitations.

## Primary source inspected

Pinned LMMS v1.2.2 commit: `94363be152f526edba4e884264d891f1361cf54b`.
Source base: https://github.com/LMMS/lmms/tree/94363be152f526edba4e884264d891f1361cf54b

- `src/core/DataFile.cpp`, `writeFile` and `loadData`: `.mmp` XML;
  `.mmpz` uses Qt `qCompress`/`qUncompress`. The reader checks the big-endian
  uncompressed-size prefix plus the zlib stream, bounds decompression to 32 MiB,
  rejects truncation, size mismatch, trailing bytes and XML entity declarations.
- `src/core/Song.cpp`, save/load: `head` stores `bpm`,
  `timesig_numerator`, `timesig_denominator` through the model serializer;
  `Song::automatedValuesAt` includes global and song tracks.
- `src/core/AutomatableModel.cpp`, save/load: static values may be attributes;
  automated values are child elements with `id`, `value`, `scale_type`.
  Controllers live under `connection`. Legacy envelopes are under
  `automationpattern/<model-name>`.
- `src/core/MeterModel.cpp`: two integer submodels; default 4/4 and range 1..32.
- `include/Song.h`: default BPM 140, minimum 10, maximum 999.
- `include/MidiTime.h`: `DefaultTicksPerTact = 192`.
  `src/core/Engine.cpp` (`LmmsCore::framesPerTick`) divides by
  `DefaultTicksPerTact / 4`, independently of meter: **48 ticks/quarter note**.
- `src/core/AutomationPattern.cpp`, save/load and `valueAt`: points use
  local integer `time@pos` and numeric `value`; `object@id` binds targets;
  `prog=0` discrete, 1 linear, 2 cubic. QMap overwrites duplicate ticks with
  the final serialized value. Before the first knot, `valueAt` returns zero;
  this reader therefore requires a local tick-zero knot instead of inventing
  an extrapolation. Missing/nonpositive length is auto-derived by LMMS; explicit
  points beyond a positive clip length are rejected here.
- `src/core/TrackContainer.cpp`, `automatedValuesFromTracks`: muted tracks and
  clips ignored; song clips keep their last value after the end, with relative
  time clamped to clip length. BB tracks loop and overlapping patterns have
  precedence rules, so those target cases are explicitly rejected.

## Real fixtures (unchanged bytes)

`manifest.json` records pinned URLs, lengths and SHA-256. Downloaded tag bytes
were separately compared byte-for-byte with commit-addressed downloads.

- `emptyproject.mmp`: upstream `tests/emptyproject.mmp`; 140 BPM, 4/4.
  It contains orphan object IDs, demonstrating why old named patterns must not
  be treated as bindings. Result includes a completeness warning.
- `TobyDox-Psycho.mmpz`: upstream demo; 180 BPM, 4/4; no tempo automation.
- `Oglsdl-PpTrip.mmpz`: upstream demo; 140 BPM, 8/4; unrelated automation and
  disconnected global `Tempo` pattern. Header values retained with warning.

Fixtures originate in the LMMS repository and retain their upstream authorship
and licensing; see upstream `COPYING` and project metadata. No LMMS source code
was copied into the implementation.

The other 40 song files in the v1.2.2 tree were inspected in scratch space,
not vendored. These public fixtures establish actual XML/compression/static
meter parsing. **Discrete tempo automation tests are source-derived synthetic
projects, not claimed to be host-authored fixtures.** LMMS playback has not been
run; audio/sample/block quantization is not emulated.

## Test evidence

Interpreter: `/Library/Developer/CommandLineTools/usr/bin/python3` (Python 3.9).
Availability RED: one test errored because `readers.lmms` did not exist; this is
not semantic correctness evidence. After module creation, the semantic RED run
showed wrong header-only tempo output and missing interpolation/controller
rejections (4 failures). Further semantic RED showed missing legacy-envelope,
unknown time-node and duplicate-ID rejection (3 failures); the next run passed
all 7 tests. A later semantic RED showed UTF-16 entities and missing default
warning not caught (2 failures), then those were repaired.

Final run evidence is in `test-results-final.txt`: **26 LMMS tests and 99 full-suite
tests passed, exit status 0, Python 3.9.6**. `test-results.txt` retains the previous
25/98-test green run. Both logs are actual subprocess output; unrelated GUI tests
emit Qt platform/font messages. Pure reader tests and pinned fixture bytes are
verified; **HOST PLAYBACK NOT TESTED**. No registration/core/app changes were made
by this reader agent; parent integration owns those changes.
