"""Uploads history: browse your past data products (/common/api/data)."""
from __future__ import annotations

import json
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..core.bhtom import BHTOMClient
from .theme import COLOR_ERROR, COLOR_MUTED, COLOR_SUCCESS, COLOR_WARNING
from .worker import start_worker

_COLUMNS = ("ID", "File", "Target", "Type", "Status", "MJD", "Mag", "Created")
_KEYS = (
    ("id",),
    ("fits_data", "photometry_data", "file_name", "filename", "name"),
    ("target_name", "target"),
    ("data_product_type", "type"),
    ("status", "status_message"),
    ("mjd",),
    ("mag", "magnitude"),
    ("created", "created_at"),
)


def _first(record: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _status_color(status: str) -> Optional[QColor]:
    upper = status.upper()
    if not upper:
        return None
    if "SUCCESS" in upper or upper.startswith("S"):
        return QColor(COLOR_SUCCESS)
    if "ERROR" in upper or "FAIL" in upper:
        return QColor(COLOR_ERROR)
    if "PROGRESS" in upper or "PROCESS" in upper or "TO DO" in upper:
        return QColor(COLOR_WARNING)
    return QColor(COLOR_MUTED)


class HistoryDialog(QDialog):
    """Paged, read-only browser over the user's uploaded data products."""

    def __init__(self, client: BHTOMClient, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.page = 1
        self.setWindowTitle("My uploads - BHTOM data products")
        self.resize(920, 520)

        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(1, 260)
        layout.addWidget(self.table)

        nav = QHBoxLayout()
        self.prev_button = QPushButton("← Previous")
        self.prev_button.clicked.connect(lambda: self._go(self.page - 1))
        self.next_button = QPushButton("Next →")
        self.next_button.clicked.connect(lambda: self._go(self.page + 1))
        self.page_label = QLabel()
        self.status_label = QLabel("loading…")
        self.status_label.setObjectName("subtle")
        nav.addWidget(self.status_label, 1)
        nav.addWidget(self.prev_button)
        nav.addWidget(self.page_label)
        nav.addWidget(self.next_button)
        layout.addLayout(nav)

        self._go(1)

    def _go(self, page: int) -> None:
        if page < 1:
            return
        self.page = page
        self.page_label.setText(f"page {page}")
        self.prev_button.setEnabled(page > 1)
        self.next_button.setEnabled(False)
        self.status_label.setText("loading…")
        start_worker(
            lambda: self.client.list_data_products(page=page),
            on_result=self._populate,
            on_error=lambda m: self.status_label.setText(f"failed: {m}"),
        )

    def _populate(self, records: list[dict]) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(records))
        for row, record in enumerate(records):
            if not isinstance(record, dict):
                record = {"status": str(record)}
            for col, keys in enumerate(_KEYS):
                item = QTableWidgetItem(_first(record, keys))
                if col == 4:
                    color = _status_color(item.text())
                    if color:
                        item.setForeground(color)
                if col == 0:
                    item.setToolTip(json.dumps(record, indent=1, default=str)[:1500])
                self.table.setItem(row, col, item)
        self.table.setSortingEnabled(True)
        self.status_label.setText(f"{len(records)} record(s) on this page")
        self.next_button.setEnabled(len(records) >= 100)  # server pages are large
        if not records and self.page > 1:
            self.status_label.setText("no more records")
