# Live Tempo Map Extractor

A small desktop tool for Ableton Live projects tempomap extraction. Add project files, check the tempo maps it extracts, and export them.

## Run
    pip install PySide6
    python app.py [files or folders ...]

## Supported input
Ableton Live (.als), REAPER (.rpp), MIDI (.mid/.midi/.smf), and a verified legacy Ardour (.ardour) subset.

**Experimental imports** (disabled by default): DAWproject (.dawproject), LMMS (.mmp/.mmpz), Studio One (.song), and modern Ardour step maps. Enable the checkbox, then reload. Partial readers reject unsupported automation/layouts; native-DAW validation remains incomplete. See [format scope and limitations](docs/FORMAT_SUPPORT.md).

Native FL Studio, Bitwig, Logic, Pro Tools, Cubase, Nuendo and Samplitude tempo-map readers are **not implemented / unconfirmed**, not advertised as supported.

## Tests
    QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v

Existing v0.1 release binaries have not been updated with this work.

## Keyboard
| Action | Shortcut |
|---|---|
| Add files | Ctrl+O |
| Add folder | Ctrl+Shift+O |
| Remove selected (file list focused) | Delete |
| Reload selected | F5 |
| Export (selected files, or all if none selected) | Ctrl+E / Enter |
| Export options | Ctrl+, |
| Clear list | Ctrl+Shift+Delete |
Tab moves between controls. Underlined letters work with Alt.

## Export options (Options… dialog)
- Resolution (PPQ), default 960
- Ramp step size, default 1/4 note: tempo ramps are written as steps
- Merge changes below, default 0.05 BPM
- Preserve absolute timing: each step uses the average BPM over its span, so the timing does not drift
- Include time signatures, Overwrite existing files (otherwise a numbered copy is saved)
