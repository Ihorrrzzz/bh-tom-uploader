"""Scan table: dense sortable view of every FITS frame + live upload status.

Model/view over the ScanResult's frames; the Type column is user-editable
before a run (LOW-confidence classifications are the ones to double-check),
and the State/Note columns turn into live upload status during a run.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QStyledItemDelegate, QTableView

from ...core.models import (
    CalibrationState,
    Confidence,
    FrameInfo,
    FrameType,
    ScanResult,
    UploadItem,
    UploadStatus,
)
from ..theme import COLOR_ERROR, COLOR_MUTED, COLOR_SUCCESS, COLOR_WARNING, ACCENT

COLUMNS = ("File", "Type", "State", "Filter", "Exp (s)", "Bin", "Temp (°C)", "Note")
COL_FILE, COL_TYPE, COL_STATE, COL_FILTER, COL_EXP, COL_BIN, COL_TEMP, COL_NOTE = range(8)

_STATE_COLORS = {
    "raw": COLOR_WARNING,
    "calibrated": COLOR_SUCCESS,
    UploadStatus.PENDING: COLOR_MUTED,
    UploadStatus.CALIBRATING: ACCENT,
    UploadStatus.UPLOADING: ACCENT,
    UploadStatus.UPLOADED: COLOR_SUCCESS,
    UploadStatus.POLLING: ACCENT,
    UploadStatus.SUCCESS: COLOR_SUCCESS,
    UploadStatus.FAILED: COLOR_ERROR,
    UploadStatus.SKIPPED: COLOR_MUTED,
}


class ScanTableModel(QAbstractTableModel):
    type_overridden = Signal()  # user changed a frame type -> re-plan

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._frames: list[FrameInfo] = []
        self._items: dict[Path, UploadItem] = {}
        self._editable = True

    # -- population ------------------------------------------------------
    def set_scan(self, scan: Optional[ScanResult]) -> None:
        self.beginResetModel()
        self._frames = list(scan.frames) if scan else []
        self._items = {}
        self.endResetModel()

    def set_editable(self, editable: bool) -> None:
        self._editable = editable

    def update_item(self, item: UploadItem) -> None:
        self._items[item.source] = item
        for row, frame in enumerate(self._frames):
            if frame.path == item.source:
                top = self.index(row, COL_STATE)
                bottom = self.index(row, COL_NOTE)
                self.dataChanged.emit(top, bottom, [])
                break

    def frame_at(self, row: int) -> FrameInfo:
        return self._frames[row]

    # -- QAbstractTableModel ----------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._frames)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None

    def flags(self, index: QModelIndex):
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == COL_TYPE and self._editable:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def _state_of(self, frame: FrameInfo):
        """Current 'state' cell content: upload status wins over scan verdicts."""
        item = self._items.get(frame.path)
        if item is not None:
            return item.status
        if frame.error:
            return "error"
        if frame.frame_type is FrameType.LIGHT:
            return frame.calibration_state.value  # 'raw' | 'calibrated'
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        frame = self._frames[index.row()]
        col = index.column()
        item = self._items.get(frame.path)

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if col == COL_FILE:
                return frame.name
            if col == COL_TYPE:
                text = frame.frame_type.value
                if role == Qt.ItemDataRole.DisplayRole and frame.confidence is Confidence.LOW \
                        and frame.frame_type is not FrameType.UNKNOWN:
                    return f"{text} ?"
                return text
            if col == COL_STATE:
                state = self._state_of(frame)
                if isinstance(state, UploadStatus):
                    return state.value
                return state or "-"
            if col == COL_FILTER:
                return frame.filter_name or ""
            if col == COL_EXP:
                return "" if frame.exptime is None else f"{frame.exptime:g}"
            if col == COL_BIN:
                return "" if frame.binning is None else f"{frame.binning[0]}×{frame.binning[1]}"
            if col == COL_TEMP:
                return "" if frame.ccd_temp is None else f"{frame.ccd_temp:.1f}"
            if col == COL_NOTE:
                if item is not None and item.message:
                    return item.message
                if frame.error:
                    return frame.error
                if frame.frame_type is FrameType.LIGHT:
                    return frame.calibration_evidence
                return ""

        elif role == Qt.ItemDataRole.ForegroundRole:
            if col == COL_STATE:
                state = self._state_of(frame)
                color = _STATE_COLORS.get(state, COLOR_ERROR if state == "error" else None)
                if color:
                    return QColor(color)
            if col == COL_TYPE and frame.confidence is Confidence.LOW:
                return QColor(COLOR_WARNING)
            if frame.error:
                return QColor(COLOR_ERROR)

        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (COL_EXP, COL_TEMP):
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if col in (COL_BIN, COL_STATE, COL_TYPE):
                return int(Qt.AlignmentFlag.AlignCenter)

        elif role == Qt.ItemDataRole.ToolTipRole:
            if col == COL_FILE:
                return str(frame.path)
            if col == COL_TYPE and frame.confidence is Confidence.LOW:
                return "Classification inferred (no clear IMAGETYP) - double-click to correct"
            if col == COL_STATE and frame.frame_type is FrameType.LIGHT:
                return frame.calibration_evidence or None
            if col == COL_NOTE and item is not None:
                return item.message or None
        return None

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if index.column() != COL_TYPE or role != Qt.ItemDataRole.EditRole:
            return False
        try:
            new_type = FrameType(str(value))
        except ValueError:
            return False
        frame = self._frames[index.row()]
        if new_type is frame.frame_type:
            return True
        frame.frame_type = new_type
        frame.confidence = Confidence.HIGH  # explicit user decision
        if new_type is FrameType.LIGHT:
            if frame.calibration_state is CalibrationState.NOT_APPLICABLE:
                frame.calibration_state = CalibrationState.RAW
                frame.calibration_evidence = "type set manually - assumed raw"
        else:
            frame.calibration_state = CalibrationState.NOT_APPLICABLE
        self.dataChanged.emit(self.index(index.row(), 0), self.index(index.row(), COL_NOTE), [])
        self.type_overridden.emit()
        return True


class TypeDelegate(QStyledItemDelegate):
    """Combo editor for the Type column."""

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.addItems([t.value for t in FrameType])
        return combo

    def setEditorData(self, editor: QComboBox, index):
        current = str(index.data(Qt.ItemDataRole.EditRole) or "")
        pos = editor.findText(current)
        if pos >= 0:
            editor.setCurrentIndex(pos)

    def setModelData(self, editor: QComboBox, model, index):
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)


def make_scan_view(model: ScanTableModel, parent=None) -> tuple[QTableView, QSortFilterProxyModel]:
    """Configured QTableView + sort proxy for the scan model."""
    proxy = QSortFilterProxyModel(parent)
    proxy.setSourceModel(model)
    proxy.setSortRole(Qt.ItemDataRole.DisplayRole)

    view = QTableView(parent)
    view.setModel(proxy)
    view.setSortingEnabled(True)
    view.sortByColumn(COL_FILE, Qt.SortOrder.AscendingOrder)
    view.setAlternatingRowColors(True)
    view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
    view.setShowGrid(False)
    view.verticalHeader().setVisible(False)
    view.verticalHeader().setDefaultSectionSize(26)
    view.horizontalHeader().setStretchLastSection(True)
    view.setItemDelegateForColumn(COL_TYPE, TypeDelegate(view))
    view.setEditTriggers(
        QTableView.EditTrigger.DoubleClicked | QTableView.EditTrigger.SelectedClicked
    )
    # sensible starting widths
    for col, width in ((COL_FILE, 260), (COL_TYPE, 90), (COL_STATE, 100), (COL_FILTER, 70),
                       (COL_EXP, 70), (COL_BIN, 60), (COL_TEMP, 80)):
        view.setColumnWidth(col, width)
    return view, proxy
