"""Tempo Map Extractor: compact desktop GUI.

Run:  python app.py [files or folders ...]
Requires: PySide6  (pip install PySide6)
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtCore import (QObject, QRunnable, QSettings, QSize, Qt, QThreadPool,
                            Signal, Slot)
from PySide6.QtGui import QAction, QKeySequence, QPalette, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QMainWindow, QMenu, QPushButton, QSpinBox, QSplitter, QStyle, QStyledItemDelegate,
    QStyleOptionProgressBar, QTableWidget, QTableWidgetItem, QToolButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import core

APP_NAME = "Tempo Map Extractor"
ROLE_PROGRESS = Qt.UserRole + 1   # float 0..1 while busy, None otherwise
ROLE_STATE = Qt.UserRole + 2      # "queued" | "reading" | "ok" | "error" | "exported"
COL_FILE, COL_STATUS, COL_POINTS, COL_BPM = range(4)


# --------------------------------------------------------------------------- workers
class WorkerSignals(QObject):
    progress = Signal(str, float)
    finished = Signal(str, object)    # key, result
    failed = Signal(str, str)         # key, user-facing message


class ReadJob(QRunnable):
    def __init__(self, path: Path):
        super().__init__()
        self.path, self.signals = path, WorkerSignals()

    def run(self):
        key = str(self.path)
        try:
            tm = core.read_tempo_map(self.path, lambda f: self.signals.progress.emit(key, f))
            self.signals.finished.emit(key, tm)
        except core.ReaderError as exc:
            self.signals.failed.emit(key, str(exc))
        except OSError as exc:
            self.signals.failed.emit(key, exc.strerror or "Cannot open file")
        except Exception:                       # unexpected: keep GUI alive
            traceback.print_exc()
            self.signals.failed.emit(key, "Unexpected error while reading")


class ExportJob(QRunnable):
    def __init__(self, tm, writer, dest: Path, opt):
        super().__init__()
        self.tm, self.writer, self.dest, self.opt = tm, writer, dest, opt
        self.signals = WorkerSignals()

    def run(self):
        key = str(self.tm.source)
        try:
            n = self.writer(self.tm, self.dest, self.opt)
            self.signals.finished.emit(key, (self.dest, n))
        except OSError as exc:
            self.signals.failed.emit(key, f"Export failed: {exc.strerror or 'write error'}")
        except Exception:
            traceback.print_exc()
            self.signals.failed.emit(key, "Export failed: unexpected error")


# --------------------------------------------------------------------------- widgets
class StatusDelegate(QStyledItemDelegate):
    """Draws a slim progress bar in the status cell while a file is busy."""

    def paint(self, painter, option, index):
        prog = index.data(ROLE_PROGRESS)
        if prog is None:
            return super().paint(painter, option, index)
        bar = QStyleOptionProgressBar()
        bar.rect = option.rect.adjusted(2, 3, -2, -3)
        bar.minimum, bar.maximum = 0, 100
        bar.progress = int(prog * 100)
        bar.text, bar.textVisible = f"{bar.progress}%", True
        bar.state = option.state
        QApplication.style().drawControl(QStyle.CE_ProgressBar, bar, painter)


class FileList(QTreeWidget):
    """File list with an empty-state hint; also a drop target."""
    HINT = "Drop project files or folders here\nor press Ctrl+O to add files"

    def __init__(self):
        super().__init__()
        self.setHeaderLabels(["File", "Status", "Points", "BPM"])
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setItemDelegateForColumn(COL_STATUS, StatusDelegate(self))
        self.setAccessibleName("Project files")
        h = self.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(COL_FILE, QHeaderView.Stretch)
        h.setSectionResizeMode(COL_STATUS, QHeaderView.Interactive)
        for c in (COL_POINTS, COL_BPM):
            h.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        h.resizeSection(COL_STATUS, 170)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.topLevelItemCount() == 0:
            from PySide6.QtGui import QPainter
            p = QPainter(self.viewport())
            p.setPen(self.palette().color(QPalette.PlaceholderText))
            p.drawText(self.viewport().rect(), Qt.AlignCenter, self.HINT)


class OptionsDialog(QDialog):
    def __init__(self, opt: core.ExportOptions, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Options")
        form = QFormLayout()

        self.ppq = QSpinBox(); self.ppq.setRange(24, 15360); self.ppq.setSingleStep(24)
        self.ppq.setValue(opt.ppq)
        self.ppq.setToolTip("MIDI resolution in ticks per quarter note")
        form.addRow("&Resolution (PPQ):", self.ppq)

        self.step = QDoubleSpinBox(); self.step.setRange(1 / 64, 4); self.step.setDecimals(4)
        self.step.setSingleStep(0.0625); self.step.setSuffix(" qn"); self.step.setValue(opt.ramp_step)
        self.step.setToolTip("Tempo ramps are written as steps of this length.\n"
                             "Smaller = smoother curve, more events.")
        form.addRow("Ramp &step size:", self.step)

        self.minchg = QDoubleSpinBox(); self.minchg.setRange(0, 5); self.minchg.setDecimals(3)
        self.minchg.setSingleStep(0.01); self.minchg.setSuffix(" BPM"); self.minchg.setValue(opt.min_bpm_change)
        self.minchg.setToolTip("Consecutive steps that differ less than this are merged.")
        form.addRow("&Merge changes below:", self.minchg)

        self.timing = QCheckBox("&Preserve absolute timing (average BPM per step)")
        self.timing.setChecked(opt.preserve_timing)
        self.timing.setToolTip("Recommended. Prevents drift between the original ramp and the stepped MIDI tempo.")
        self.meter = QCheckBox("Include &time signatures"); self.meter.setChecked(opt.include_meter)
        self.overwrite = QCheckBox("&Overwrite existing files"); self.overwrite.setChecked(opt.overwrite)
        self.overwrite.setToolTip("Otherwise a numbered copy is created.")
        for w in (self.timing, self.meter, self.overwrite):
            form.addRow(w)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        btns.button(QDialogButtonBox.RestoreDefaults).clicked.connect(lambda: self._load(core.ExportOptions()))
        lay = QVBoxLayout(self); lay.addLayout(form); lay.addWidget(btns)

    def _load(self, o):
        self.ppq.setValue(o.ppq); self.step.setValue(o.ramp_step); self.minchg.setValue(o.min_bpm_change)
        self.timing.setChecked(o.preserve_timing); self.meter.setChecked(o.include_meter)
        self.overwrite.setChecked(o.overwrite)

    def options(self) -> core.ExportOptions:
        return core.ExportOptions(self.ppq.value(), self.step.value(), self.minchg.value(),
                                  self.timing.isChecked(), self.meter.isChecked(), self.overwrite.isChecked())


# --------------------------------------------------------------------------- main window
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.settings = QSettings("AP Productions", APP_NAME)
        self.pool = QThreadPool.globalInstance()
        self.items: dict[str, QTreeWidgetItem] = {}
        self.maps: dict[str, core.TempoMap] = {}
        self.jobs: set = set()             # keep runnables' signal objects alive
        self.opt = self._load_options()
        self.out_dir: Path | None = None
        self._build_ui()
        self._restore_geometry()

    # ---------- layout
    def _build_ui(self):
        central = QWidget(); root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8); root.setSpacing(6)

        # actions (also drive keyboard shortcuts)
        self.act_add = self._action("&Add Files…", QKeySequence.Open, self.add_files_dialog)
        self.act_folder = self._action("Add &Folder…", "Ctrl+Shift+O", self.add_folder_dialog)
        self.act_remove = self._action("&Remove", QKeySequence.Delete, self.remove_selected)
        self.act_clear = self._action("C&lear All", "Ctrl+Shift+Delete", self.clear_all)
        self.act_retry = self._action("Re&load", QKeySequence.Refresh, self.reload_selected)
        self.act_export = self._action("&Export", "Ctrl+E", self.export)
        self.act_opts = self._action("Export &Options…", QKeySequence.Preferences, self.edit_options)
        self.addAction(self._action("Quit", QKeySequence.Quit, self.close))
        if QKeySequence(QKeySequence.Preferences).isEmpty():
            self.act_opts.setShortcut("Ctrl+,")

        top = QHBoxLayout()
        for act in (self.act_add, self.act_folder):
            b = QToolButton(); b.setDefaultAction(act); b.setToolButtonStyle(Qt.ToolButtonTextOnly)
            top.addWidget(b)
        top.addStretch()
        b = QToolButton(); b.setDefaultAction(self.act_remove); top.addWidget(b)
        root.addLayout(top)

        self.files = FileList()
        # Delete only acts on the file list, so it never steals the key from other widgets
        self.removeAction(self.act_remove); self.files.addAction(self.act_remove)
        self.act_remove.setShortcutContext(Qt.WidgetShortcut)
        self.files.itemSelectionChanged.connect(self._show_selected)
        self.files.setContextMenuPolicy(Qt.CustomContextMenu)
        self.files.customContextMenuRequested.connect(self._context_menu)

        review = QWidget(); rl = QVBoxLayout(review); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(3)
        self.review_label = QLabel("Tempo map")
        self.review_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Bar.Beat", "Time", "BPM", "Meter", "Ramp"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setAccessibleName("Extracted tempo map")
        self.review_label.setBuddy(self.table)
        rl.addWidget(self.review_label); rl.addWidget(self.table)

        split = QSplitter(Qt.Vertical); split.setChildrenCollapsible(False)
        split.addWidget(self.files); split.addWidget(review)
        split.setStretchFactor(0, 1); split.setStretchFactor(1, 1)
        root.addWidget(split, 1)

        # export row
        bottom = QHBoxLayout()
        fmt_lbl = QLabel("F&ormat:")
        self.fmt = QComboBox(); self.fmt.addItems(core.EXPORTERS)
        self.fmt.setCurrentText(self.settings.value("format", next(iter(core.EXPORTERS))))
        fmt_lbl.setBuddy(self.fmt)
        out_lbl = QLabel("Sa&ve to:")
        self.out = QComboBox(); self.out.addItem("Next to source file"); self.out.addItem("Choose folder…")
        self.out.activated.connect(self._out_changed); out_lbl.setBuddy(self.out)
        last = self.settings.value("out_dir", "")
        if last and Path(last).is_dir():
            self._set_out_dir(Path(last))
        opts = QPushButton("Op&tions…"); opts.clicked.connect(self.edit_options)
        opts.setToolTip("Curve approximation, resolution and overwrite settings (Ctrl+,)")
        self.export_btn = QPushButton("&Export"); self.export_btn.setDefault(True)
        self.export_btn.clicked.connect(self.export)
        self.export_btn.setToolTip("Export selected files, or all if none are selected (Ctrl+E)")
        for w in (fmt_lbl, self.fmt, out_lbl, self.out):
            bottom.addWidget(w)
        self.out.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        bottom.addStretch(); bottom.addWidget(opts); bottom.addWidget(self.export_btn)
        root.addLayout(bottom)

        self.setCentralWidget(central)
        self.statusBar().setSizeGripEnabled(True)
        self._update_state()

    def _action(self, text, shortcut, slot):
        a = QAction(text, self); a.setShortcut(QKeySequence(shortcut))
        a.setShortcutContext(Qt.WindowShortcut); a.triggered.connect(slot); self.addAction(a)
        return a

    def sizeHint(self):
        return QSize(720, 520)

    # ---------- adding files
    def add_files_dialog(self):
        patt = " ".join(f"*{e}" for e in core.SUPPORTED_EXTENSIONS)
        paths, _ = QFileDialog.getOpenFileNames(self, "Add project files", self.settings.value("last_dir", ""),
                                                f"Project files ({patt});;All files (*)")
        self.add_paths([Path(p) for p in paths])

    def add_folder_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "Add folder", self.settings.value("last_dir", ""))
        if d:
            self.add_paths([Path(d)])

    def add_paths(self, paths):
        found, skipped = [], 0
        for p in paths:
            if p.is_dir():
                found += sorted(f for f in p.rglob("*") if f.is_file()
                                and f.suffix.lower() in core.SUPPORTED_EXTENSIONS)
            elif p.suffix.lower() in core.SUPPORTED_EXTENSIONS:
                found.append(p)
            else:
                skipped += 1
        if paths:
            first = paths[0]
            self.settings.setValue("last_dir", str(first if first.is_dir() else first.parent))
        new = [f for f in found if str(f.resolve()) not in self.items]
        for f in new:
            self._queue_read(f.resolve())
        msg = f"Added {len(new)} file{'s' * (len(new) != 1)}"
        if dup := len(found) - len(new):
            msg += f", {dup} already listed"
        if skipped:
            msg += f", {skipped} unsupported skipped"
        if not found and paths:
            msg = "No supported project files found (" + ", ".join(core.SUPPORTED_EXTENSIONS) + ")"
        self.statusBar().showMessage(msg, 6000)
        if new and not self.files.selectedItems():
            self.files.setCurrentItem(self.items[str(new[0].resolve())])
        self._update_state()

    def _queue_read(self, path: Path):
        key = str(path)
        item = self.items.get(key)
        if item is None:
            item = QTreeWidgetItem([path.name, "", "", ""])
            item.setToolTip(COL_FILE, key); item.setData(COL_FILE, Qt.UserRole, key)
            for c in (COL_POINTS, COL_BPM):
                item.setTextAlignment(c, Qt.AlignRight | Qt.AlignVCenter)
            self.files.addTopLevelItem(item); self.items[key] = item
        self.maps.pop(key, None)
        self._set_status(item, "reading", "Queued", progress=0.0)
        item.setText(COL_POINTS, ""); item.setText(COL_BPM, "")
        job = ReadJob(path)
        job.signals.progress.connect(self._on_progress)
        job.signals.finished.connect(self._on_read)
        job.signals.failed.connect(self._on_failed)
        self._start(job)

    def _start(self, job):
        job.setAutoDelete(False); self.jobs.add(job)
        job.signals.finished.connect(lambda *_: self.jobs.discard(job))
        job.signals.failed.connect(lambda *_: self.jobs.discard(job))
        self.pool.start(job)

    # ---------- worker callbacks
    @Slot(str, float)
    def _on_progress(self, key, frac):
        if item := self.items.get(key):
            item.setData(COL_STATUS, ROLE_PROGRESS, frac)

    @Slot(str, object)
    def _on_read(self, key, tm):
        item = self.items.get(key)
        if item is None:              # removed while reading
            return
        self.maps[key] = tm
        lo, hi = tm.bpm_range
        ramps = sum(p.ramp for p in tm.points)
        text = "Ready" + (f" · {ramps} ramp{'s' * (ramps != 1)}" if ramps else "")
        if tm.warnings:
            text += " · ⚠"
            item.setToolTip(COL_STATUS, "\n".join(tm.warnings))
        self._set_status(item, "ok", text)
        item.setText(COL_POINTS, str(len(tm.points)))
        item.setText(COL_BPM, f"{lo:.1f}" if abs(hi - lo) < 0.05 else f"{lo:.1f}–{hi:.1f}")
        if item.isSelected() or self.files.currentItem() is item:
            self._show_selected()
        self._update_state()

    @Slot(str, str)
    def _on_failed(self, key, msg):
        if item := self.items.get(key):
            self._set_status(item, "error", msg)
            item.setToolTip(COL_STATUS, msg)
            self._update_state()
            if self.files.currentItem() is item:
                self._show_selected()

    def _set_status(self, item, state, text, progress=None):
        item.setData(COL_STATUS, ROLE_STATE, state)
        item.setData(COL_STATUS, ROLE_PROGRESS, progress)
        item.setText(COL_STATUS, text)
        err = state == "error"
        item.setForeground(COL_STATUS, QColor("#c62828") if err else self.palette().color(QPalette.Text))
        item.setIcon(COL_STATUS, self.style().standardIcon(QStyle.SP_MessageBoxCritical) if err else
                     self.style().standardIcon(QStyle.SP_DialogApplyButton) if state == "exported" else QIconNone)

    # ---------- review
    def _show_selected(self):
        item = self.files.currentItem()
        sel = self.files.selectedItems()
        if item is None or (sel and item not in sel):
            item = sel[0] if sel else None
        self.table.setRowCount(0)
        if item is None:
            self.review_label.setText("Tempo map"); return
        key = item.data(COL_FILE, Qt.UserRole)
        tm = self.maps.get(key)
        if tm is None:
            state = item.data(COL_STATUS, ROLE_STATE)
            self.review_label.setText(f"{item.text(COL_FILE)}: " +
                                      ("could not be read" if state == "error" else "reading…"))
            return
        dur = tm.points[-1].time
        extra = f" · {len(sel)} files selected" if len(sel) > 1 else ""
        self.review_label.setText(f"<b>{item.text(COL_FILE)}</b> · {len(tm.points)} tempo points · "
                                  f"last change at {self._fmt_time(dur)}{extra}"
                                  + (f" · <span style='color:#b26a00'>{'; '.join(tm.warnings)}</span>"
                                     if tm.warnings else ""))
        self.table.setRowCount(len(tm.points))
        for r, p in enumerate(tm.points):
            vals = [tm.bar_beat(p.beat), self._fmt_time(p.time), f"{p.bpm:.3f}".rstrip("0").rstrip("."),
                    f"{p.num}/{p.den}", "→" if p.ramp else ""]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                cell.setTextAlignment((Qt.AlignRight if c in (1, 2) else Qt.AlignCenter) | Qt.AlignVCenter)
                self.table.setItem(r, c, cell)
            self.table.item(r, 4).setToolTip("Linear ramp to next point" if p.ramp else "")

    @staticmethod
    def _fmt_time(sec):
        m, s = divmod(sec, 60)
        return f"{int(m)}:{s:06.3f}"

    # ---------- list management
    def _context_menu(self, pos):
        m = QMenu(self)
        for a in (self.act_retry, self.act_remove, None, self.act_export, None, self.act_clear):
            m.addSeparator() if a is None else m.addAction(a)
        m.exec(self.files.viewport().mapToGlobal(pos))

    def remove_selected(self):
        for item in self.files.selectedItems():
            key = item.data(COL_FILE, Qt.UserRole)
            self.items.pop(key, None); self.maps.pop(key, None)
            self.files.takeTopLevelItem(self.files.indexOfTopLevelItem(item))
        self._show_selected(); self._update_state()

    def clear_all(self):
        self.files.clear(); self.items.clear(); self.maps.clear()
        self._show_selected(); self._update_state()

    def reload_selected(self):
        for item in self.files.selectedItems() or []:
            self._queue_read(Path(item.data(COL_FILE, Qt.UserRole)))

    def _update_state(self):
        n = self.files.topLevelItemCount()
        ready = len(self.maps)
        errors = sum(self.items[k].data(COL_STATUS, ROLE_STATE) == "error" for k in self.items)
        busy = sum(self.items[k].data(COL_STATUS, ROLE_STATE) == "reading" for k in self.items)
        for a in (self.act_remove, self.act_clear, self.act_retry):
            a.setEnabled(n > 0)
        self.act_export.setEnabled(ready > 0); self.export_btn.setEnabled(ready > 0)
        if n:
            parts = [f"{n} file{'s' * (n != 1)}", f"{ready} ready"]
            if busy: parts.append(f"{busy} reading")
            if errors: parts.append(f"{errors} failed")
            self.statusBar().showMessage(" · ".join(parts))
        else:
            self.statusBar().clearMessage()

    # ---------- output & options
    def _out_changed(self, idx):
        if idx == 0:
            self.out_dir = None
            self.settings.setValue("out_dir", "")
        elif idx == self.out.count() - 1:          # "Choose folder…"
            d = QFileDialog.getExistingDirectory(self, "Export folder", str(self.out_dir or ""))
            if d:
                self._set_out_dir(Path(d))
            else:
                self.out.setCurrentIndex(0 if self.out_dir is None else 1)

    def _set_out_dir(self, d: Path):
        self.out_dir = d
        self.settings.setValue("out_dir", str(d))
        while self.out.count() > 2:
            self.out.removeItem(1)
        self.out.insertItem(1, d.name or str(d)); self.out.setItemData(1, str(d), Qt.ToolTipRole)
        self.out.setCurrentIndex(1)

    def edit_options(self):
        dlg = OptionsDialog(self.opt, self)
        if dlg.exec():
            self.opt = dlg.options(); self._save_options()

    def _load_options(self):
        d, s = core.ExportOptions(), QSettings("AP Productions", APP_NAME)
        conv = {bool: lambda v: v in (True, "true", "1", 1)}
        kw = {}
        for f, default in vars(d).items():
            v = s.value(f"options/{f}", default)
            kw[f] = conv.get(type(default), type(default))(v)
        return core.ExportOptions(**kw)

    def _save_options(self):
        for f, v in vars(self.opt).items():
            self.settings.setValue(f"options/{f}", v)

    # ---------- export
    def export(self):
        sel = [i.data(COL_FILE, Qt.UserRole) for i in self.files.selectedItems()]
        keys = [k for k in (sel or self.items) if k in self.maps]
        if not keys:
            self.statusBar().showMessage("Nothing to export: no successfully read files selected", 6000)
            return
        if self.out_dir and not self.out_dir.is_dir():
            self.statusBar().showMessage("Export folder no longer exists, choose another", 6000); return
        suffix, writer = core.EXPORTERS[self.fmt.currentText()]
        self.settings.setValue("format", self.fmt.currentText())
        self._pending, self._done, self._fail = len(keys), 0, 0
        self.export_btn.setEnabled(False); self.act_export.setEnabled(False)
        taken = set()
        for k in keys:
            tm = self.maps[k]
            dest = core.export_path(tm, self.out_dir, suffix, self.opt.overwrite)
            while dest in taken:                    # same file name from different folders
                dest = dest.with_name(dest.stem + "_" + suffix)
            taken.add(dest)
            self._set_status(self.items[k], "reading", "Exporting", progress=0.5)
            job = ExportJob(tm, writer, dest, self.opt)
            job.signals.finished.connect(self._on_exported)
            job.signals.failed.connect(self._on_export_failed)
            self._start(job)

    @Slot(str, object)
    def _on_exported(self, key, res):
        dest, n = res
        if item := self.items.get(key):
            self._set_status(item, "exported", f"Exported · {n} events")
            item.setToolTip(COL_STATUS, str(dest))
        self._done += 1; self._export_tick()

    @Slot(str, str)
    def _on_export_failed(self, key, msg):
        if item := self.items.get(key):
            self._set_status(item, "error", msg); item.setToolTip(COL_STATUS, msg)
        self._fail += 1; self._export_tick()

    def _export_tick(self):
        if self._done + self._fail < self._pending:
            return
        self._update_state()
        where = self.out_dir or "source folders"
        msg = f"Exported {self._done} file{'s' * (self._done != 1)} to {where}"
        if self._fail:
            msg += f" · {self._fail} failed (see list)"
        self.statusBar().showMessage(msg, 10000)

    # ---------- drag & drop
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, e):
        self.add_paths([Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()])
        e.acceptProposedAction()

    # ---------- window state
    def _restore_geometry(self):
        g = self.settings.value("geometry")
        if g is not None:
            self.restoreGeometry(g)
        else:
            self.resize(self.sizeHint())

    def closeEvent(self, e):
        self.settings.setValue("geometry", self.saveGeometry())
        super().closeEvent(e)


from PySide6.QtGui import QIcon  # noqa: E402
QIconNone = QIcon()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    w = MainWindow()
    w.setMinimumSize(520, 360)
    w.show()
    if len(sys.argv) > 1:
        w.add_paths([Path(a) for a in sys.argv[1:]])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
