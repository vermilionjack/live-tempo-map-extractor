"""Bounded packaged-runtime probe, not a substitute for DAW host validation."""
import json
import tempfile
from pathlib import Path


def run(report_path):
    report: dict = {'ok': False}
    try:
        import app
        import core
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication
        from unittest.mock import patch
        qt = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(app, 'QSettings', lambda *a: QSettings(str(root / 'settings.ini'), QSettings.IniFormat)):
                window = app.MainWindow()
                window.show()
                qt.processEvents()
                assert window.windowTitle() == 'Tempo Map Extractor'
                assert not window.experimental_imports.isChecked()
                source = root / 'probe.rpp'
                source.write_text('TEMPO 103 4 4\n')
                tm = core.read_tempo_map(source)
                dest = root / 'probe.mid'
                core.write_midi(tm, dest, core.ExportOptions())
                assert abs(core.read_tempo_map(dest).points[0].bpm - 103) < .001
                core.write_csv(tm, root / 'probe.csv', core.ExportOptions())
                for extension in ('.als', '.dawproject', '.mmp', '.mmpz', '.song', '.ardour'):
                    assert extension in core.READERS
                window.close()
                qt.processEvents()
                report.update(ok=True, title=window.windowTitle(), version=app.APP_VERSION,
                              formats=list(core.SUPPORTED_EXTENSIONS),
                              checks=['Qt window', 'experimental default off', 'reader registration', 'RPP to MIDI roundtrip', 'CSV export'])
    except Exception as error:
        import traceback
        report['error'] = str(error)
        report['traceback'] = traceback.format_exc()
    Path(report_path).write_text(json.dumps(report, indent=2), encoding='utf-8')
    return 0 if report['ok'] else 1
