# Test project files

This folder contains 16 byte-for-byte copies from `tests/fixtures/`, flattened and prefixed by format to avoid filename collisions. Original fixtures remain in place for automated tests. Verify each copy against the SHA-256 below.

## Contents and status

| File | Format/status | Size (bytes) | SHA-256 |
|---|---|---:|---|
| `als--example-140.als` | Ableton Live project fixture; public upstream files, versions/evidence in PROVENANCE-ALS.md | 5958 | `729d6dc738183a17c2a8d2892ecdacbd08427daecfe37680b297ca75ed07703a` |
| `als--automation.als` | Ableton Live project fixture; public upstream files, versions/evidence in PROVENANCE-ALS.md | 3803 | `0460dffb04fa2137a2620fcaab7dd420b84a80c5bb2ccbabe657a213a0253c41` |
| `als--L12-automation.als` | Ableton Live project fixture; public upstream files, versions/evidence in PROVENANCE-ALS.md | 5444 | `5756a430081aad79c4fac6d4c1d3b0b22f4cf105a3d68971cf17e00a4f1ff11a` |
| `als--live8-patch-markers-noauto.als` | Ableton Live project fixture; public upstream files, versions/evidence in PROVENANCE-ALS.md | 253676 | `7d7b8ae5d82855e823e182b22cb35530991e0210e3cc334b92ec6e80d60d0e36` |
| `als--live9-patch-markers-noauto.als` | Ableton Live project fixture; public upstream files, versions/evidence in PROVENANCE-ALS.md | 628383 | `d41f5ddf6cee45a6a53843213c5adb249774faab3a4b1732b60b33dbe439b579` |
| `als--automation-pathological.als` | Ableton Live project fixture; public upstream files, versions/evidence in PROVENANCE-ALS.md | 11641 | `56180f912625a9ebdb16544c9e60e6758fa027a3d6262932e9f1efcca174611f` |
| `ardour--TestSession.ardour` | Ardour session fixture; real upstream sessions; see PROVENANCE-Ardour.md | 205918 | `6f44bda6e35ae06d695e40d0a466809fba1811fd8088840b012c387adecd6ea8` |
| `ardour--rec_enabled.ardour` | Ardour session fixture; real upstream sessions; see PROVENANCE-Ardour.md | 9961 | `05da51e400f22319d56ab8f3aa034756d426f6cc5e6d233f38ed3462b71f6767` |
| `dawproject--bitwig-example.project.xml` | DAWproject/Bitwig-related; archives are converter fixtures, not independent host exports; see PROVENANCE-DAWproject.md | 4462 | `df82d509b02284da2a87f2cd7fcbb47b8212fedd536fec573918f2e1e023e2c5` |
| `dawproject--bitwig_extended.dawproject` | DAWproject/Bitwig-related; archives are converter fixtures, not independent host exports; see PROVENANCE-DAWproject.md | 459702 | `61f46fde1cacb0646dd0c1ea373c1e8fc1e27eb3f8d7e0aceb0e1ec9445d08d0` |
| `dawproject--bitwig_simple.dawproject` | DAWproject/Bitwig-related; archives are converter fixtures, not independent host exports; see PROVENANCE-DAWproject.md | 459955 | `10d218aea875b30b84b9693b0c941292752e64bf2f34661c9dc69c49313ba1a0` |
| `flstudio--base-tempo.flp` | Synthetic minimal FLP; reader intentionally rejects; see PROVENANCE-other-formats.md | 27 | `935703c20e9920bda2fd90bc8636b36d8700c145fbaacd181f0a090f6c8ad127` |
| `lmms--emptyproject.mmp` | LMMS project fixtures; see PROVENANCE-LMMS.md | 15241 | `3aa0587475553dbc97bf61f89a9a7f4baa59ed2aff8122392718e1e32b143596` |
| `lmms--TobyDox-Psycho.mmpz` | LMMS project fixtures; see PROVENANCE-LMMS.md | 5787 | `004d4ae0d093d56616e6227d311ff053a912235e1c797b5c70b5d937446d0505` |
| `lmms--Oglsdl-PpTrip.mmpz` | LMMS project fixtures; see PROVENANCE-LMMS.md | 26015 | `4ec582dbfa753360d53a9502757f5256ce81e809a9eaae9798e701a23dd9b002` |
| `studioone--steps.song` | Synthetic ZIP/XML fixture, not Studio One-host-authored; see PROVENANCE-other-formats.md | 572 | `15da6838797e4437d26ff1658bc0439d7a58d4f4b4c64e368ddd67d363fcccdf` |

## Important limitations

- This is a test-fixture collection, not a set of uniformly host-validated demo projects. Synthetic files are explicitly identified above.
- Some readers are experimental or reject the format. See `docs/FORMAT_SUPPORT.md` and the provenance notes before interpreting results.
- The available upstream notices are retained here. Ardour fixtures carry GPL-2.0-or-later terms; preserve `LICENSE-Ardour-GPL-2-or-later.txt` when redistributing them. The LMMS fixtures retain upstream authorship/licensing; consult the LMMS project `COPYING` and embedded project metadata before redistributing those files.
- To rerun project tests, use the originals under `tests/fixtures/`; this flattened folder is for convenient inspection/sharing and is not wired into the test suite.
