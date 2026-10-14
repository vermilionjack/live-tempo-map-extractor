# Tempo Map Extractor

A desktop tool to inspect tempo maps and time signatures from DAW project files and export MIDI tempo tracks or CSV. Tested input subsets include Ableton Live, REAPER, MIDI and legacy Ardour, with opt-in experimental DAWproject, LMMS, Studio One and modern Ardour readers. This is not a universal DAW-project converter.

## Run
    pip install PySide6
    python app.py [files or folders ...]

## Supported input
Ableton Live (.als), REAPER (.rpp), MIDI (.mid/.midi/.smf), and a verified legacy Ardour (.ardour) subset.

**Experimental imports** (disabled by default): DAWproject (.dawproject), LMMS (.mmp/.mmpz), Studio One (.song), and modern Ardour step maps. Enable the checkbox, then reload. Partial readers reject unsupported automation/layouts; native-DAW validation remains incomplete. See [format scope and limitations](docs/FORMAT_SUPPORT.md).

Native FL Studio, Bitwig, Logic, Pro Tools, Cubase, Nuendo and Samplitude tempo-map readers are **not implemented / unconfirmed**, not advertised as supported.

## Tests
    QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v

Version **v.01.1** includes the corrected readers, GUI lifecycle fixes and opt-in experimental imports. Download the Windows x64 executable or macOS Apple Silicon ZIP from Releases. The macOS build is not notarized, and the Windows executable is unsigned. The archived v0.1 binaries predate these changes.

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
