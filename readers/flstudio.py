"""FL Studio .flp: explicit UNSUPPORTED global-tempo-map reader.

PyFLP's Project.tempo is the BPM at the saved playhead, not an arrangement
map. Automation target links, pattern-event automation, initialization,
clip placement and normalized-value curves cannot yet all be resolved here.
Returning that scalar would silently discard real tempo changes. Accordingly
ALL native FLP projects are rejected, including apparently static projects.
See tests/fixtures/daw_reader_evidence.md for source/dependency evidence.
"""
from __future__ import annotations
from pathlib import Path


def read_flstudio(path: Path, progress):
    from core import ReaderError

    raise ReaderError(
        "FL Studio .flp unsupported: reliable global tempo automation target "
        "resolution and arrangement evaluation are not implemented. A saved "
        "base/playhead BPM is not a tempo map. Use a verified tempo-bearing "
        "MIDI interchange file instead; verify that it preserves all changes."
    )


read_flp = read_flstudio
