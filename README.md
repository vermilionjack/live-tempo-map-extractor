# Live Tempo Map Extractor

A small desktop tool for Ableton Live projects tempomap extraction. Add project files, check the tempo maps it extracts, and export them.

## Run
    pip install PySide6
    python app.py [files or folders ...]

## Supported input
REAPER projects (.rpp) and Standard MIDI Files (.mid/.midi/.smf).
To add another format, write a reader in core.py and add it to READERS.

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
