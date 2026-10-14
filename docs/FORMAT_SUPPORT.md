# Format support

**Verified subset** means tested files and behavior, not all DAW versions. Synthetic tests check calculations, not native-host compatibility. No new reader has been compared against playback in its DAW.

| Format | Status / implemented scope |
| --- | --- |
| Ableton `.als` | Tested public Live 8/9/10/12 fixtures: constant, hold/beat-linear tempo, sentinel/jump handling, meter-only changes. Curves rejected. Playback quantization is warned about, not emulated. |
| REAPER `.rpp` | Existing reader with time-linear ramp regression; not a full compatibility audit. |
| MIDI `.mid/.midi/.smf` | Existing reader/exporter; SMPTE time division unsupported. |
| DAWproject `.dawproject` | **EXPERIMENTAL / HOST UNCONFIRMED**. Hold/linear tempo in beats or seconds, meter changes. Specification and converter-generated public fixtures; ramp tests synthetic. NOT direct `.bwproject/.cpr` support. |
| LMMS `.mmp/.mmpz` | **EXPERIMENTAL / PARTIAL**. Fixed tempo/static meter tested on real v1.2.2 fixtures. Single ID-bound discrete tempo pattern tested synthetically from source. Interpolation, meter automation, controllers and ambiguous patterns rejected. Unresolved IDs explicitly warn about unproven completeness. |
| Ardour `.ardour` | Verified legacy initial BBT-map subset with real fixtures. **EXPERIMENTAL** modern Temporal step maps and bar-aligned meter changes require opt-in; modern tests synthetic. Ramps and BBT resets rejected. |
| Studio One `.song` | **EXPERIMENTAL / HOST UNCONFIRMED**. Observed 5.5.2 ZIP/XML step tempo/meter subset; synthetic fixtures only. Curves/unknown layouts rejected. |
| FL Studio `.flp` | **NOT IMPLEMENTED / UNCONFIRMED**. Reliable global tempo automation targeting/evaluation not established. Not a supported input. |
| Bitwig `.bwproject` | **NOT IMPLEMENTED / UNCONFIRMED**. DAWproject export is a separate route. |
| Logic `.logicx`, Pro Tools `.ptx` | **NOT IMPLEMENTED / UNCONFIRMED**. |
| Cubase `.cpr`, Nuendo `.npr`, Samplitude `.vip` | **NOT IMPLEMENTED / UNCONFIRMED**. |

## Opt-in

Experimental imports are disabled by default. Enable **Experimental imports**, then reload. This also enables the modern Ardour subset. Warnings appear in status, tooltip and preview. API: `core.read_tempo_map(path, allow_experimental=True)`.

Unsupported native projects are never silently converted into a plausible fixed BPM map. Check warnings and validate exports before production use. CSV retains the original schema and does not serialize ramp domain.

## Evidence and releases

Source revisions, licenses, hashes and limitations are in fixture documentation under `tests/fixtures/als/`, `ardour/`, `dawproject/`, `lmms/`, and `tests/fixtures/daw_reader_evidence.md`. Converter-generated and synthetic files are not claimed host-authored evidence. DAWproject fixture media licensing remains unverified; no assertion of redistribution permission for media is made.

Repository remains private. Existing v0.1 binaries predate these changes and have NOT been refreshed. New releases require fresh platform builds and artifact checks.
