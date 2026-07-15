"""Main window: drop zone -> scan table -> plan banner -> run, with log dock.

Layout follows the scientific-tool conventions from the design plan: central
master table + plan banner, dockable log pane, persistent status bar with the
user identity, job state and progress. All heavy work runs off-thread.
"""
from __future__ import annotations

import os
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStackedLayout,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.bhtom import BHTOMClient
from ..core.calibrator import Calibrator
from ..core.journal import UploadJournal
from ..core.lightcurve import parse_photometry, render_interactive_html, render_thumbnail
from ..core.models import FrameType, PlannedAction, ScanResult, UploadStatus
from ..core.pipeline import Pipeline, RunOptions, RunReport
from ..core.scanner import build_scan_result, is_fits_name, scan_directory, scan_paths
from ..core.settings import Settings
from ..core.watcher import FolderWatcher
from ..resources import resource_path
from .target_dialog import TargetDialog
from .theme import apply_theme
from .tray import TrayManager
from .widgets.plan_banner import PlanBanner
from .widgets.scan_table import ScanTableModel, make_scan_view
from .widgets.toast import Toast
from .worker import start_worker

POLL_INTERVAL_MS = 15_000
POLL_MAX_TICKS = 40  # ~10 minutes

FILTER_CHOICES = [
    "GaiaSP/any", "GaiaSP/U", "GaiaSP/B", "GaiaSP/V", "GaiaSP/R", "GaiaSP/I",
    "GaiaSP/u", "GaiaSP/g", "GaiaSP/r", "GaiaSP/i", "GaiaSP/z",
]


class MainWindow(QMainWindow):
    def __init__(self, client: BHTOMClient, settings: Settings, user: dict, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.settings = settings
        self.user = user
        self.scan: Optional[ScanResult] = None
        self.journal = UploadJournal()
        self._thread: Optional[QThread] = None
        self._pipeline: Optional[Pipeline] = None
        self._target_check_seq = 0
        self._quitting = False
        self._watcher: Optional[FolderWatcher] = None
        self._watch_debounce = QTimer(self)
        self._watch_debounce.setSingleShot(True)
        self._watch_debounce.setInterval(3000)
        self._watch_debounce.timeout.connect(self._watch_rescan)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_tick)
        self._poll_state: Optional[dict] = None

        self.setWindowTitle("BHTOM Uploader")
        self.setWindowIcon(QIcon(str(resource_path("logo.png"))))
        self.setAcceptDrops(True)
        self.resize(1100, 720)

        self._build_ui()
        self._build_menu()
        self._build_tray()
        self._restore_geometry()
        self._log(f"signed in as {user.get('username', '?')}")
        start_worker(self._fetch_observatories,
                     on_result=self._on_observatories,
                     on_error=lambda m: self._log(f"observatory list failed: {m}"))

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        # -- header row: folder selection
        header = QHBoxLayout()
        self.select_button = QPushButton("Select folder…")
        self.select_button.clicked.connect(self._on_select_folder)
        self.rescan_button = QToolButton(text="⟳")
        self.rescan_button.setToolTip("Rescan the selected folder")
        self.rescan_button.clicked.connect(self._on_rescan)
        self.rescan_button.setEnabled(False)
        self.folder_label = QLabel("no folder selected - or drop one anywhere in this window")
        self.folder_label.setObjectName("subtle")
        header.addWidget(self.select_button)
        header.addWidget(self.rescan_button)
        header.addWidget(self.folder_label, 1)
        self.watch_check = QCheckBox("Watch folder")
        self.watch_check.setToolTip(
            "After the run, keep monitoring this folder: new FITS files are\n"
            "classified, calibrated when possible and uploaded automatically\n"
            "(raw frames are never auto-uploaded; duplicates are skipped)."
        )
        self.watch_check.toggled.connect(self._update_watch)
        header.addWidget(self.watch_check)
        self.dry_run_check = QCheckBox("Dry run")
        self.dry_run_check.setToolTip(
            "Test mode: files are processed by BHTOM but nothing is stored"
        )
        self.dry_run_check.setChecked(self.settings.dry_run)
        header.addWidget(self.dry_run_check)
        self.tray_button = QToolButton(text="Minimize to tray")
        self.tray_button.setToolTip(
            "Hide the window; the app keeps running in the system tray"
        )
        self.tray_button.clicked.connect(self._minimize_to_tray)
        header.addWidget(self.tray_button)
        root.addLayout(header)

        # -- plan banner
        self.banner = PlanBanner()
        root.addWidget(self.banner)

        # -- table with empty-state overlay
        self.model = ScanTableModel(self)
        self.model.type_overridden.connect(self._replan)
        self.table, self.proxy = make_scan_view(self.model, self)

        self.empty_label = QLabel(
            "Drop a folder with FITS files here\n- or click “Select folder…” -\n\n"
            "The app reads every FITS header, tells you what it found\n"
            "and what it plans to do before anything is uploaded.",
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        self.empty_label.setObjectName("emptyState")

        self.stack = QStackedLayout()
        self.stack.addWidget(self.empty_label)
        self.stack.addWidget(self.table)
        stack_host = QWidget()
        stack_host.setLayout(self.stack)
        root.addWidget(stack_host, 1)

        # -- form row: target / observatory / filter / start
        form = QHBoxLayout()
        form.setSpacing(8)

        form.addWidget(QLabel("Target"))
        self.target_edit = QLineEdit(placeholderText="from OBJECT header…")
        self.target_edit.setMaximumWidth(220)
        self.target_edit.editingFinished.connect(self._check_target_async)
        form.addWidget(self.target_edit)
        self.target_state = QLabel("")
        self.target_state.setMinimumWidth(18)
        form.addWidget(self.target_state)

        form.addWidget(QLabel("Observatory"))
        self.observatory_combo = QComboBox()
        self.observatory_combo.setMinimumWidth(280)
        self.observatory_combo.setEditable(True)
        self.observatory_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.observatory_combo.addItem("loading observatories…")
        self.observatory_combo.setEnabled(False)
        form.addWidget(self.observatory_combo, 1)

        form.addWidget(QLabel("Filter"))
        self.filter_combo = QComboBox()
        self.filter_combo.setEditable(True)
        self.filter_combo.addItems(FILTER_CHOICES)
        self.filter_combo.setCurrentText(self.settings.filter_name)
        form.addWidget(self.filter_combo)

        self.start_button = QPushButton("Start")
        self.start_button.setObjectName("primary")
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self._on_start)
        form.addWidget(self.start_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.hide()
        self.cancel_button.clicked.connect(self._on_cancel)
        form.addWidget(self.cancel_button)
        root.addLayout(form)

        self.setCentralWidget(central)

        # -- log dock (closable only: it can never float and cover the form row)
        self.log_view = QPlainTextEdit(readOnly=True)
        self.log_view.setObjectName("log")
        self.log_dock = QDockWidget("Log", self)
        self.log_dock.setObjectName("logDock")
        self.log_dock.setWidget(self.log_view)
        self.log_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.log_dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.log_dock.setMaximumHeight(180)

        # -- status bar
        self.state_label = QLabel("idle")
        self.progress = QProgressBar()
        self.progress.setFixedWidth(200)
        self.progress.hide()
        host = self.client.base_url.split("//", 1)[-1]
        self.user_label = QLabel(f"{self.user.get('username', '?')} @ {host}")
        self.statusBar().addWidget(self.state_label, 1)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().addPermanentWidget(self.user_label)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        settings_action = QAction("Settings…", self)
        settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(settings_action)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit_from_tray)
        file_menu.addAction(quit_action)

        view = self.menuBar().addMenu("&View")
        history_action = QAction("My uploads history…", self)
        history_action.triggered.connect(self._open_history)
        view.addAction(history_action)
        view.addAction(self.log_dock.toggleViewAction())
        theme_menu = view.addMenu("Theme")
        for mode, label in (
            ("system", "System"),
            ("dark", "Dark"),
            ("light", "Light"),
            ("night", "Night"),
        ):
            action = QAction(label, self)
            if mode == "night":
                action.setToolTip("Red-on-black: protects dark adaptation at the telescope")
            action.triggered.connect(lambda _=False, m=mode: self._set_theme(m))
            theme_menu.addAction(action)
        help_menu = self.menuBar().addMenu("&Help")
        open_site = QAction("Open BHTOM website", self)
        open_site.triggered.connect(
            lambda: __import__("webbrowser").open(self.client.base_url)
        )
        help_menu.addAction(open_site)

    def _build_tray(self) -> None:
        self.tray = TrayManager(self)
        self.tray.open_requested.connect(self._restore_from_tray)
        self.tray.pause_toggled.connect(
            lambda paused: self._pipeline is not None and self._pipeline.set_paused(paused)
        )
        self.tray.stop_requested.connect(self._on_cancel)
        self.tray.stop_watch_requested.connect(lambda: self.watch_check.setChecked(False))
        self.tray.quit_requested.connect(self._quit_from_tray)

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _minimize_to_tray(self) -> None:
        self.hide()
        self.tray.notify(
            "BHTOM Uploader is in the tray",
            "Click the tray icon to reopen, or right-click it to quit.",
        )

    def _quit_from_tray(self) -> None:
        self._quitting = True
        self.close()

    def _set_theme(self, mode: str) -> None:
        self.settings.theme = mode
        apply_theme(QApplication.instance(), mode)

    def _open_settings(self) -> None:
        from .settings_dialog import SettingsDialog

        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            apply_theme(QApplication.instance(), self.settings.theme)
            self.filter_combo.setCurrentText(self.settings.filter_name)
            self._log("settings saved")

    def _open_history(self) -> None:
        from .history_dialog import HistoryDialog

        HistoryDialog(self.client, self).exec()

    # ------------------------------------------------------------------
    # folder selection / drag-and-drop / scanning
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if not paths:
            return
        dirs = [p for p in paths if p.is_dir()]
        if dirs:
            self._scan_folder(dirs[0])
            return
        fits_files = [p for p in paths if is_fits_name(p.name)]
        if fits_files:
            root = Path(os.path.commonpath([str(p.parent) for p in fits_files]))
            self._scan_files(fits_files, root)

    def _on_select_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select folder containing FITS files")
        if folder:
            self._scan_folder(Path(folder))

    def _on_rescan(self) -> None:
        if self.scan is not None:
            self._scan_folder(self.scan.root)

    def _scan_folder(self, folder: Path) -> None:
        self.folder_label.setText(str(folder))
        self._begin_scan(lambda: scan_directory(folder))

    def _scan_files(self, files: list[Path], root: Path) -> None:
        self.folder_label.setText(f"{len(files)} file(s) from {root}")
        self._begin_scan(lambda: scan_paths(files, root))

    def _begin_scan(self, scan_fn) -> None:
        if self._running():
            return
        self.state_label.setText("scanning…")
        self.select_button.setEnabled(False)
        self.start_button.setEnabled(False)
        start_worker(scan_fn, on_result=self._on_scanned, on_error=self._on_scan_error)

    def _on_scanned(self, scan: ScanResult) -> None:
        self.scan = scan
        self.select_button.setEnabled(True)
        self.rescan_button.setEnabled(True)
        self.state_label.setText("idle")
        self.model.set_scan(scan)
        self.model.set_editable(True)
        self.banner.set_scan(scan)
        self.stack.setCurrentWidget(self.table if scan.frames else self.empty_label)
        self._autofill_target(scan)
        self._update_start_enabled()
        self._log(f"scanned {scan.root}: {scan.summary()}")
        for warning in scan.warnings:
            self._log(f"warning: {warning}")

    def _on_scan_error(self, message: str) -> None:
        self.select_button.setEnabled(True)
        self.state_label.setText("idle")
        QMessageBox.critical(self, "Scan failed", message)

    def _autofill_target(self, scan: ScanResult) -> None:
        objects = {g.object_name for g in scan.light_groups if g.object_name}
        if len(objects) == 1:
            self.target_edit.setText(next(iter(objects)))
            self._check_target_async()
        elif len(objects) > 1:
            self.target_edit.clear()
            self.target_edit.setPlaceholderText(
                f"{len(objects)} objects found - enter the BHTOM target name"
            )
        elif not self.target_edit.text() and self.settings.last_target:
            self.target_edit.setText(self.settings.last_target)

    def _replan(self) -> None:
        """User overrode a frame type in the table -> rebuild groups + plan."""
        if self.scan is None:
            return
        self.scan = build_scan_result(self.scan.frames, self.scan.root)
        self.model.set_scan(self.scan)
        self.banner.set_scan(self.scan)
        self._update_start_enabled()

    def _update_start_enabled(self) -> None:
        runnable = self.scan is not None and any(
            g.action is not PlannedAction.SKIP for g in self.scan.light_groups
        )
        self.start_button.setEnabled(runnable and not self._running())

    # ------------------------------------------------------------------
    # observatories + target checking
    # ------------------------------------------------------------------

    def _fetch_observatories(self) -> list[dict]:
        observatories = self.client.get_observatories()
        favourites = self.client.get_favourite_observatories()
        my_id = self.user.get("id")
        fav_camera_ids = {
            f.get("camera") for f in favourites if f.get("user") == my_id and f.get("camera")
        }
        entries: list[dict] = []
        for obs in observatories:
            for cam in obs.get("cameras") or []:
                if not cam.get("active_flg", True):
                    continue
                prefix = cam.get("prefix")
                if not prefix:
                    continue
                entries.append({
                    "label": f"{obs.get('name', '?')} - {cam.get('camera_name', '?')}",
                    "oname": prefix,
                    "fav": cam.get("id") in fav_camera_ids,
                })
        entries.sort(key=lambda e: (not e["fav"], e["label"].lower()))
        return entries

    def _on_observatories(self, entries: list[dict]) -> None:
        self._fav_onames = {e["oname"] for e in entries if e["fav"]}
        self.observatory_combo.clear()
        n_fav = sum(1 for e in entries if e["fav"])
        for i, entry in enumerate(entries):
            prefix = "★ " if entry["fav"] else ""
            self.observatory_combo.addItem(f"{prefix}{entry['label']}", entry["oname"])
            if n_fav and i == n_fav - 1:
                self.observatory_combo.insertSeparator(n_fav)
        completer = QCompleter([self.observatory_combo.itemText(i)
                                for i in range(self.observatory_combo.count())], self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.observatory_combo.setCompleter(completer)
        self.observatory_combo.setEnabled(True)
        saved = self.settings.observatory_oname
        if saved:
            index = self.observatory_combo.findData(saved)
            if index >= 0:
                self.observatory_combo.setCurrentIndex(index)
        self._log(f"loaded {len(entries)} observatory cameras ({n_fav} favourites)")

    def _selected_oname(self) -> Optional[str]:
        index = self.observatory_combo.findText(self.observatory_combo.currentText())
        if index < 0:
            return None
        return self.observatory_combo.itemData(index)

    def _check_target_async(self) -> None:
        name = self.target_edit.text().strip()
        if not name:
            self.target_state.setText("")
            return
        self._target_check_seq += 1
        seq = self._target_check_seq
        self.target_state.setText("…")

        def check():
            return self.client.target_exists(name)

        def on_result(exists: bool) -> None:
            if seq != self._target_check_seq:
                return  # stale
            self.target_state.setText("✓" if exists else "✗")
            self.target_state.setToolTip(
                "Target exists in BHTOM" if exists
                else "Target not found - you'll be offered to create it on Start"
            )
            self.target_state.setStyleSheet(
                "color: #57AB5A;" if exists else "color: #D29922;"
            )

        start_worker(check, on_result=on_result, on_error=lambda _m: None)

    # ------------------------------------------------------------------
    # run flow
    # ------------------------------------------------------------------

    def _running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def _on_start(self) -> None:
        if self.scan is None or self._running():
            return
        target = self.target_edit.text().strip()
        if not target:
            QMessageBox.warning(self, "Missing target", "Enter the BHTOM target name.")
            return
        oname = self._selected_oname()
        if not oname:
            QMessageBox.warning(
                self, "Missing observatory",
                "Pick your observatory/camera from the list (type to search).",
            )
            return

        allow_raw = False
        if self.scan.needs_confirmation:
            answer = QMessageBox.warning(
                self,
                "Raw frames without calibration",
                "Some frames are RAW and no calibration frames were found for them.\n"
                "Uploading raw or calibration frames to BHTOM is not recommended.\n\n"
                "Upload those raw frames anyway?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return
            allow_raw = answer == QMessageBox.StandardButton.Yes

        self.start_button.setEnabled(False)
        self.state_label.setText("checking target…")

        def check():
            return self.client.target_exists(target)

        start_worker(
            check,
            on_result=lambda exists: self._after_target_check(target, oname, allow_raw, exists),
            on_error=self._on_run_failed,
        )

    def _ensure_favourite_then_start(self, target: str, oname: str, allow_raw: bool) -> None:
        """BHTOM's upload service only accepts cameras from the user's own
        favourites list - add the picked one on demand, then start."""
        if oname in getattr(self, "_fav_onames", set()):
            self._start_pipeline(target, oname, allow_raw)
            return
        self._log(f"adding '{oname}' to your BHTOM favourite observatories (required for upload)")

        def add():
            self.client.add_favourite_observatory(oname, comment="added by BHTOM Uploader")
            return oname

        def on_added(added_oname: str) -> None:
            self._fav_onames.add(added_oname)
            self._start_pipeline(target, added_oname, allow_raw)

        def on_error(message: str) -> None:
            # maybe it already is a favourite (or the server phrasing changed):
            # proceed anyway - the upload itself gives the definitive answer
            self._log(f"could not add favourite ({message}) - trying the upload anyway")
            self._start_pipeline(target, oname, allow_raw)

        start_worker(add, on_result=on_added, on_error=on_error)

    def _after_target_check(self, target: str, oname: str, allow_raw: bool, exists: bool) -> None:
        if not exists:
            ra = dec = None
            for group in self.scan.light_groups:
                for frame in group.frames:
                    if frame.ra is not None and frame.dec is not None:
                        ra, dec = frame.ra, frame.dec
                        break
                if ra is not None:
                    break
            dialog = TargetDialog(self.client, target, ra=ra, dec=dec, parent=self)
            if dialog.exec() != TargetDialog.DialogCode.Accepted:
                self.state_label.setText("idle")
                self._update_start_enabled()
                return
            target = dialog.created_name or target
            self.target_edit.setText(target)
            self._log(f"created target '{target}' in BHTOM")
        self._ensure_favourite_then_start(target, oname, allow_raw)

    def _start_pipeline(self, target: str, oname: str, allow_raw: bool) -> None:
        # persist choices
        self.settings.last_target = target
        self.settings.observatory_oname = oname
        self.settings.filter_name = self.filter_combo.currentText().strip()
        self.settings.dry_run = self.dry_run_check.isChecked()

        options = RunOptions(
            target=target,
            observatory=oname,
            filter_name=self.filter_combo.currentText().strip() or "GaiaSP/any",
            dry_run=self.dry_run_check.isChecked(),
            comment=self.settings.comment,
            observers=self.settings.observers,
            allow_raw=allow_raw,
        )
        calibrator = Calibrator(
            flat_min_adu=self.settings.flat_min_adu,
            flat_max_adu=self.settings.flat_max_adu,
            cosmic_ray=self.settings.cosmic_ray,
            saturation_adu=self.settings.saturation_adu,
        )
        self._pipeline = Pipeline(
            self.scan, options, self.client, calibrator=calibrator, journal=self.journal
        )
        self._thread = QThread(self)
        self._pipeline.moveToThread(self._thread)
        self._thread.started.connect(self._pipeline.run)

        self._pipeline.log.connect(self._log)
        self._pipeline.state_changed.connect(self.state_label.setText)
        self._pipeline.progress.connect(self._on_progress)
        self._pipeline.item_updated.connect(self.model.update_item)
        self._pipeline.finished.connect(self._on_run_finished)
        self._pipeline.failed.connect(self._on_run_failed)

        self.model.set_editable(False)
        self.cancel_button.show()
        self.select_button.setEnabled(False)
        self.rescan_button.setEnabled(False)
        self.progress.setValue(0)
        self.progress.show()
        self.tray.set_state(running=True, watching=self._watching())
        self._thread.start()

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(done)

    def _teardown_thread(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(5000)
        self._thread = None
        self._pipeline = None
        self.cancel_button.hide()
        self.progress.hide()
        self.select_button.setEnabled(True)
        self.rescan_button.setEnabled(self.scan is not None)
        self.model.set_editable(True)
        self.tray.set_state(running=False, watching=self._watching())
        self._update_start_enabled()

    def _on_run_finished(self, report: RunReport) -> None:
        self._teardown_thread()
        self.state_label.setText("watching for new files…" if self._watching() else "idle")
        self.banner.set_result(report.summary(), report.target, self.client.target_url(report.target))
        self.tray.notify("BHTOM upload finished", f"{report.target}: {report.summary()}")

        if report.n_success and not report.dry_run:
            self._show_lightcurve_toast(report)
            self._begin_polling(report)
        self._update_watch()

    def _on_run_failed(self, message: str) -> None:
        self._teardown_thread()
        self.state_label.setText("idle")
        self.banner.set_error(message)
        if self.isVisible():
            QMessageBox.critical(self, "Run failed", message)
        else:
            self.tray.notify("BHTOM upload failed", message)

    # ------------------------------------------------------------------
    # light-curve toast
    # ------------------------------------------------------------------

    def _show_lightcurve_toast(self, report: RunReport) -> None:
        target = report.target
        dark = bool(QApplication.instance().property("darkTheme"))

        def build():
            text = self.client.download_photometry(target)
            points = parse_photometry(text)
            png = render_thumbnail(points, target, dark=dark)
            html_path = render_interactive_html(points, target)
            return png, html_path, len(points)

        def show(result) -> None:
            png, html_path, n_points = result
            pixmap = QPixmap()
            pixmap.loadFromData(png)
            Toast.show_toast(
                title=f"Upload complete - {report.summary()}\n"
                      f"{target}: {n_points} photometry points",
                pixmap=pixmap,
                on_open_plot=lambda: webbrowser.open(Path(html_path).as_uri()),
                on_open_page=lambda: webbrowser.open(self.client.target_url(target)),
            )
            self._log(f"light curve ready ({n_points} points) - toast shown")

        start_worker(
            build,
            on_result=show,
            on_error=lambda m: self._log(f"light curve fetch failed: {m}"),
        )

    # ------------------------------------------------------------------
    # server calibration-result polling
    # ------------------------------------------------------------------

    def _begin_polling(self, report: RunReport) -> None:
        id_map: dict[int, object] = {}
        for item in report.items:
            for dp_id in item.dataproduct_ids:
                id_map[dp_id] = item
        if not id_map:
            return
        for item in set(id_map.values()):
            item.status = UploadStatus.POLLING
            item.message = "waiting for BHTOM calibration…"
            self.model.update_item(item)
        self._poll_state = {"map": id_map, "pending": set(id_map), "ticks": 0}
        self.state_label.setText("waiting for BHTOM calibration results…")
        QTimer.singleShot(3000, self._poll_tick)  # quick first check, then every 15 s
        self._poll_timer.start()

    def _poll_tick(self) -> None:
        state = self._poll_state
        if not state or not state["pending"]:
            self._end_polling()
            return
        state["ticks"] += 1
        if state["ticks"] > POLL_MAX_TICKS:
            self._end_polling(timeout=True)
            return
        ids = sorted(state["pending"])
        start_worker(
            lambda: self.client.get_calibration_results(calib_ids=ids),
            on_result=self._on_poll_results,
            on_error=lambda m: self._log(f"calibration poll failed: {m}"),
        )

    def _on_poll_results(self, records: list) -> None:
        state = self._poll_state
        if not state:
            return
        for record in records:
            verdict = BHTOMClient.parse_verdict(record)
            if verdict.calib_id is None or verdict.calib_id not in state["map"]:
                continue
            item = state["map"][verdict.calib_id]
            status_text = verdict.status.upper()
            terminal = False
            if verdict.mag is not None or "SUCCESS" in status_text or status_text in ("S", "FINISHED", "DONE"):
                item.status = UploadStatus.SUCCESS
                item.verdict = verdict
                if verdict.mag is not None and verdict.is_limit:
                    item.message = f"limit {verdict.mag:.2f} mag (server)"
                elif verdict.mag is not None and verdict.mag_err is not None:
                    item.message = f"mag {verdict.mag:.3f} ± {verdict.mag_err:.3f} (server)"
                else:
                    item.message = "calibrated on server"
                terminal = True
            elif "ERROR" in status_text or "FAIL" in status_text:
                item.status = UploadStatus.FAILED
                item.verdict = verdict
                item.message = verdict.message or "server-side calibration failed"
                terminal = True
            elif "does not exist" in verdict.message.lower() and state["ticks"] > 4:
                item.message = "no calibration record on server"
                terminal = True
            if terminal:
                state["pending"].discard(verdict.calib_id)
                self.model.update_item(item)
                self._log(f"{item.name}: {item.message}")
        if not state["pending"]:
            self._end_polling()

    def _end_polling(self, timeout: bool = False) -> None:
        self._poll_timer.stop()
        if self._poll_state and timeout:
            for dp_id in self._poll_state["pending"]:
                item = self._poll_state["map"][dp_id]
                item.status = UploadStatus.UPLOADED
                item.message = "calibration still processing - check BHTOM later"
                self.model.update_item(item)
            self._log("stopped polling: server calibration still processing")
        self._poll_state = None
        if self.state_label.text().startswith("waiting"):
            self.state_label.setText("watching for new files…" if self._watching() else "idle")

    # ------------------------------------------------------------------
    # watch mode
    # ------------------------------------------------------------------

    def _watching(self) -> bool:
        return self._watcher is not None

    def _update_watch(self) -> None:
        want = self.watch_check.isChecked() and self.scan is not None
        if want and self._watcher is None:
            self._watcher = FolderWatcher(self.scan.root, parent=self)
            self._watcher.file_ready.connect(self._on_watch_file)
            self._watcher.watch_error.connect(lambda m: self._log(f"watch: {m}"))
            self._watcher.start()
            self._log(f"watching {self.scan.root} for new FITS files")
            if not self._running():
                self.state_label.setText("watching for new files…")
        elif not want and self._watcher is not None:
            self._watcher.stop()
            self._watcher.deleteLater()
            self._watcher = None
            self._log("stopped watching")
            if not self._running():
                self.state_label.setText("idle")
        self.tray.set_state(running=self._running(), watching=self._watching())

    def _on_watch_file(self, path: Path) -> None:
        self._log(f"watch: new file ready - {Path(path).name}")
        self._watch_debounce.start()  # batch a burst of files into one rescan

    def _watch_rescan(self) -> None:
        if self._watcher is None or self.scan is None:
            return
        if self._running():
            self._watch_debounce.start()  # try again after the current run
            return
        root = self.scan.root
        start_worker(
            lambda: scan_directory(root),
            on_result=self._on_watch_scanned,
            on_error=lambda m: self._log(f"watch rescan failed: {m}"),
        )

    def _on_watch_scanned(self, scan: ScanResult) -> None:
        if self._watcher is None:
            return
        self.scan = scan
        self.model.set_scan(scan)
        self.banner.set_scan(scan)
        self.stack.setCurrentWidget(self.table if scan.frames else self.empty_label)

        target = self.target_edit.text().strip()
        oname = self._selected_oname()
        if not target or not oname:
            self._log("watch: target/observatory not set - cannot auto-upload")
            return
        # never auto-upload a different object than the user's confirmed target
        for group in scan.light_groups:
            if (
                group.object_name
                and group.object_name.strip().lower() != target.lower()
                and group.action is not PlannedAction.SKIP
            ):
                group.action = PlannedAction.SKIP
                group.reason = (
                    f"OBJECT '{group.object_name}' differs from target '{target}' - "
                    "not auto-uploading (start manually if intended)"
                )
                self._log(f"watch: skipping {group.display_name} (different object)")
        runnable = any(
            g.action in (PlannedAction.UPLOAD_DIRECT, PlannedAction.CALIBRATE_THEN_UPLOAD)
            for g in scan.light_groups
        )
        if runnable:
            self._log("watch: auto-starting upload of new files")
            self._ensure_favourite_then_start(target, oname, allow_raw=False)
        else:
            self.state_label.setText("watching for new files…")

    def _on_cancel(self) -> None:
        if self._pipeline is not None:
            self._pipeline.cancel()
            self.state_label.setText("cancelling…")

    # ------------------------------------------------------------------
    # misc
    # ------------------------------------------------------------------

    def _log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_view.appendPlainText(f"[{stamp}] {message}")

    def _restore_geometry(self) -> None:
        data = self.settings.load_geometry("main")
        if data:
            self.restoreGeometry(data)
        state = self.settings.load_geometry("main_state")
        if state:
            self.restoreState(state)

    def closeEvent(self, event) -> None:
        # closing the window while work continues -> minimize to tray (the spec's
        # "select folder, minimize, it keeps calibrating and uploading on its own")
        if (
            not self._quitting
            and self.settings.minimize_to_tray
            and (self._running() or self._watching())
        ):
            event.ignore()
            self.hide()
            self.tray.notify(
                "BHTOM Uploader keeps working",
                "Uploads/watching continue in the background. "
                "Click the tray icon to reopen, or right-click → Quit to stop.",
            )
            return

        if self._running():
            answer = QMessageBox.question(
                self,
                "Upload in progress",
                "A run is still in progress. Cancel it and quit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self._quitting = False
                event.ignore()
                return
            if self._pipeline is not None:
                self._pipeline.cancel()
            self._teardown_thread()

        if self._watcher is not None:
            self._watcher.stop()
            self._watcher = None
        self._poll_timer.stop()
        self.tray.hide()
        self.settings.save_geometry("main", self.saveGeometry())
        self.settings.save_geometry("main_state", self.saveState())
        event.accept()
        QApplication.instance().quit()  # quitOnLastWindowClosed is off (tray mode)
