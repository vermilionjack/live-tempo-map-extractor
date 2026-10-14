"""Real Qt event-loop regressions; no user preferences or source files touched."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtWidgets import QApplication

import app
import core


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])
        cls.qt.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        settings = QSettings(str(self.root / "settings.ini"), QSettings.IniFormat)
        self.settings_patch = patch.object(app, "QSettings", lambda *args: settings)
        self.settings_patch.start()
        self.window = app.MainWindow()
        self.window.pool.setMaxThreadCount(2)
        self.window.show()
        self.qt.processEvents()

    def tearDown(self):
        self.assertTrue(self.window.pool.waitForDone(3000), "workers did not stop")
        self.qt.processEvents()
        self.window.close()
        self.qt.processEvents()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.settings_patch.stop()
        self.tmp.cleanup()

    def wait(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.qt.processEvents()
            time.sleep(0.005)
        self.qt.processEvents()
        self.assertTrue(predicate(), "Qt operation timed out")

    def source(self, name="sample.rpp", bpm=120):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"TEMPO {bpm} 4 4\n")
        return path

    def test_duplicate_paths_in_one_add_are_read_once(self):
        source = self.source()
        original = core.read_tempo_map
        with patch.object(core, "read_tempo_map", wraps=original) as reader:
            self.window.add_paths([source, self.root, source])
            self.wait(lambda: not self.window.jobs)
            self.assertEqual(reader.call_count, 1)
            self.assertEqual(self.window.files.topLevelItemCount(), 1)
            self.assertEqual(len(self.window.maps), 1)


    def test_stale_read_results_do_not_replace_new_generation(self):
        for action in ("reload", "remove", "clear"):
            for fail in (False, True):
                with self.subTest(action=action, fail=fail):
                    self.window.clear_all()
                    source = self.source()
                    key = str(source)
                    started, release = threading.Event(), threading.Event()
                    calls = []

                    def reader(path, progress):
                        calls.append(path)
                        if len(calls) == 1:
                            started.set()
                            if not release.wait(3):
                                raise RuntimeError("test worker release timed out")
                            progress(0.25)
                            if fail:
                                raise core.ReaderError("obsolete read error")
                            bpm = 90
                        else:
                            bpm = 140
                        return core.TempoMap(path, [core.TempoPoint(0, 0, bpm)])

                    with patch.object(core, "read_tempo_map", reader):
                        try:
                            self.window.add_paths([source])
                            self.wait(started.is_set)
                            if action == "reload":
                                self.window.act_retry.trigger()
                            else:
                                (self.window.remove_selected if action == "remove"
                                 else self.window.clear_all)()
                                self.window.add_paths([source])
                            self.wait(lambda: key in self.window.maps)
                            self.assertEqual(self.window.maps[key].points[0].bpm, 140)
                            release.set()
                            self.wait(lambda: not self.window.jobs)
                            self.assertEqual(self.window.maps[key].points[0].bpm, 140)
                            item = self.window.items[key]
                            self.assertEqual(item.data(app.COL_STATUS, app.ROLE_STATE), "ok")
                            self.assertIsNone(item.data(app.COL_STATUS, app.ROLE_PROGRESS))
                        finally:
                            release.set()
                            self.window.pool.waitForDone(3000)
                            self.qt.processEvents()


    def test_active_export_cannot_be_started_again_after_read_finishes(self):
        source = self.source()
        self.window.add_paths([source])
        self.wait(lambda: not self.window.jobs)
        started, release = threading.Event(), threading.Event()
        written = []

        def writer(tm, dest, opt):
            started.set()
            if not release.wait(3):
                raise RuntimeError("test export release timed out")
            written.append(dest)
            return core.write_csv(tm, dest, opt)

        self.window.fmt.setCurrentText("Spreadsheet (.csv)")
        with patch.dict(core.EXPORTERS, {"Spreadsheet (.csv)": (".csv", writer)}):
            try:
                self.window.export_btn.click()
                self.wait(started.is_set)
                self.window.add_paths([self.source("other.rpp")])
                self.wait(lambda: len(self.window.maps) == 2)
                self.assertFalse(self.window.export_btn.isEnabled())
                self.assertFalse(self.window.act_export.isEnabled())
                before = len(self.window.jobs)
                self.window.export()
                self.assertEqual(len(self.window.jobs), before)
                release.set()
                self.wait(lambda: not self.window.jobs)
                self.assertEqual(len(written), 1)
                self.assertTrue(written[0].read_text().startswith("position,beat_qn"))
                self.assertTrue(self.window.export_btn.isEnabled())
                self.assertIn("Exported 1 file", self.window.statusBar().currentMessage())
            finally:
                release.set()
                self.window.pool.waitForDone(3000)
                self.qt.processEvents()


    def test_stale_exports_do_not_change_reloaded_or_readded_rows(self):
        for action in ("reload", "remove", "clear"):
            for fail in (False, True):
                with self.subTest(action=action, fail=fail):
                    self.window.clear_all()
                    source = self.source()
                    key = str(source)
                    self.window.add_paths([source])
                    self.wait(lambda: not self.window.jobs)
                    started, release = threading.Event(), threading.Event()

                    def writer(tm, dest, opt):
                        started.set()
                        if not release.wait(3):
                            raise RuntimeError("test export release timed out")
                        if fail:
                            raise OSError("obsolete export error")
                        return core.write_csv(tm, dest, opt)

                    self.window.fmt.setCurrentText("Spreadsheet (.csv)")
                    with patch.dict(core.EXPORTERS, {"Spreadsheet (.csv)": (".csv", writer)}):
                        try:
                            self.window.export_btn.click()
                            self.wait(started.is_set)
                            source.write_text("TEMPO 140 4 4\n")
                            if action == "reload":
                                self.window.act_retry.trigger()
                            else:
                                (self.window.remove_selected if action == "remove"
                                 else self.window.clear_all)()
                                self.window.add_paths([source])
                            self.wait(lambda: key in self.window.maps
                                      and self.window.maps[key].points[0].bpm == 140)
                            release.set()
                            self.wait(lambda: not self.window.jobs)
                            self.assertEqual(self.window.items[key].data(
                                app.COL_STATUS, app.ROLE_STATE), "ok")
                            self.assertEqual(self.window._done + self.window._fail, 1)
                            self.assertFalse(self.window._exporting)
                        finally:
                            release.set()
                            self.window.pool.waitForDone(3000)
                            self.qt.processEvents()


    def test_close_waits_for_reader_without_blocking_gui(self):
        started, release = threading.Event(), threading.Event()

        def reader(path, progress):
            started.set()
            if not release.wait(3):
                raise RuntimeError("test worker release timed out")
            return core.TempoMap(path, [core.TempoPoint(0, 0, 120)])

        with patch.object(core, "read_tempo_map", reader):
            try:
                self.window.add_paths([self.source()])
                self.wait(started.is_set)
                before = time.monotonic()
                self.assertFalse(self.window.close(), "running jobs must defer window destruction")
                self.assertLess(time.monotonic() - before, 0.25)
                self.assertTrue(self.window.isVisible())
                jobs = len(self.window.jobs)
                self.window.add_paths([self.source("ignored.rpp")])
                self.assertEqual(len(self.window.jobs), jobs)
                release.set()
                self.wait(lambda: not self.window.isVisible())
                self.assertEqual(self.window.pool.activeThreadCount(), 0)
                self.assertFalse(self.window.jobs)
                self.assertFalse(self.window.maps, "closing workers must not update widgets")
            finally:
                release.set()
                self.window.pool.waitForDone(3000)
                self.qt.processEvents()


    def test_batch_collision_does_not_overwrite_existing_alternate(self):
        first = self.source("a/song.rpp", 100)
        second = self.source("b/song.rpp", 140)
        out = self.root / "exports"
        out.mkdir()
        existing = out / "song.tempo_.csv"
        existing.write_text("do not overwrite")
        numbered = out / "song.tempo (1).csv"
        numbered.write_text("also preserve numbered copies")
        self.window.add_paths([first, second])
        self.wait(lambda: not self.window.jobs)
        self.window.files.clearSelection()
        self.window._set_out_dir(out)
        self.window.fmt.setCurrentText("Spreadsheet (.csv)")
        self.window.export_btn.click()
        self.wait(lambda: not self.window.jobs)
        self.assertEqual(existing.read_text(), "do not overwrite")
        self.assertEqual(numbered.read_text(), "also preserve numbered copies")
        outputs = [path for path in out.glob("*.csv") if path not in (existing, numbered)]
        self.assertEqual(len(outputs), 2)
        bpms = {path.read_text().splitlines()[1].split(",")[3] for path in outputs}
        self.assertEqual(bpms, {"100.0000", "140.0000"})
        self.assertEqual(self.window._done, 2)


    def test_reload_clears_preview_and_disables_export_immediately(self):
        source = self.source()
        self.window.add_paths([source])
        self.wait(lambda: not self.window.jobs)
        self.assertEqual(self.window.table.rowCount(), 1)
        started, release = threading.Event(), threading.Event()
        original = core.read_tempo_map

        def reader(path, progress):
            started.set()
            if not release.wait(3):
                raise RuntimeError("test reload release timed out")
            return original(path, progress)

        with patch.object(core, "read_tempo_map", reader):
            try:
                self.window.act_retry.trigger()
                self.wait(started.is_set)
                self.assertEqual(self.window.table.rowCount(), 0)
                self.assertIn("reading", self.window.review_label.text())
                self.assertFalse(self.window.export_btn.isEnabled())
                self.assertFalse(self.window.act_export.isEnabled())
            finally:
                release.set()
                self.window.pool.waitForDone(3000)
                self.qt.processEvents()


    def test_close_waits_for_export_and_preserves_written_output(self):
        source = self.source()
        self.window.add_paths([source])
        self.wait(lambda: not self.window.jobs)
        started, release = threading.Event(), threading.Event()
        written = []

        def writer(tm, dest, opt):
            started.set()
            if not release.wait(3):
                raise RuntimeError("test export release timed out")
            result = core.write_csv(tm, dest, opt)
            written.append(dest)
            return result

        self.window.fmt.setCurrentText("Spreadsheet (.csv)")
        with patch.dict(core.EXPORTERS, {"Spreadsheet (.csv)": (".csv", writer)}):
            try:
                self.window.export_btn.click()
                self.wait(started.is_set)
                self.assertFalse(self.window.close())
                self.assertTrue(self.window.isVisible())
                release.set()
                self.wait(lambda: not self.window.isVisible())
                self.assertEqual(self.window.pool.activeThreadCount(), 0)
                self.assertFalse(self.window.jobs)
                self.assertEqual(len(written), 1)
                self.assertIn("120.0000", written[0].read_text())
            finally:
                release.set()
                self.window.pool.waitForDone(3000)
                self.qt.processEvents()


    def test_application_exit_drains_workers_before_window_deletion(self):
        source = self.source()
        script = r'''
import sys, threading
from pathlib import Path
from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtWidgets import QApplication
import app, core
source = Path(sys.argv[1])
settings = QSettings(str(source.parent / "child-settings.ini"), QSettings.IniFormat)
app.QSettings = lambda *args: settings
qt = QApplication([])
w = app.MainWindow()
w.setAttribute(Qt.WA_DeleteOnClose)
w.show()
started, release, done = threading.Event(), threading.Event(), threading.Event()
original = core.read_tempo_map

def reader(path, progress):
    started.set()
    if not release.wait(2):
        raise RuntimeError("child worker timed out")
    result = original(path, progress)
    done.set()
    return result

core.read_tempo_map = reader
w.add_paths([source])
poll = QTimer()
def request_close():
    if started.is_set():
        poll.stop()
        w.close()
        threading.Timer(0.1, release.set).start()
poll.timeout.connect(request_close)
poll.start(5)
QTimer.singleShot(3000, lambda: qt.exit(97))
result = qt.exec()
assert result == 0, result
assert done.is_set(), "application exited while reader was still running"
print("closed cleanly after worker completion")
'''
        result = subprocess.run([sys.executable, "-X", "faulthandler", "-c", script, str(source)],
                                cwd=Path(app.__file__).parent, capture_output=True,
                                text=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("closed cleanly after worker completion", result.stdout)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
