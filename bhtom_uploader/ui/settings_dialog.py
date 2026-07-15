"""Settings dialog: appearance, upload defaults, calibration options."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ..core.settings import Settings

_THEMES = [("System", "system"), ("Dark", "dark"), ("Light", "light"),
           ("Night", "night")]
_FILTERS = [
    "GaiaSP/any", "GaiaSP/U", "GaiaSP/B", "GaiaSP/V", "GaiaSP/R", "GaiaSP/I",
    "GaiaSP/u", "GaiaSP/g", "GaiaSP/r", "GaiaSP/i", "GaiaSP/z",
]


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Settings")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)

        # -- appearance
        appearance = QGroupBox("Appearance")
        form = QFormLayout(appearance)
        self.theme_combo = QComboBox()
        for label, value in _THEMES:
            self.theme_combo.addItem(label, value)
        index = self.theme_combo.findData(settings.theme)
        self.theme_combo.setCurrentIndex(max(index, 0))
        form.addRow("Theme", self.theme_combo)
        self.tray_check = QCheckBox(
            "Closing the window minimizes to tray while uploads/watching are active"
        )
        self.tray_check.setChecked(settings.minimize_to_tray)
        form.addRow(self.tray_check)
        layout.addWidget(appearance)

        # -- upload defaults
        upload = QGroupBox("Upload defaults")
        form = QFormLayout(upload)
        self.filter_combo = QComboBox()
        self.filter_combo.setEditable(True)
        self.filter_combo.addItems(_FILTERS)
        self.filter_combo.setCurrentText(settings.filter_name)
        form.addRow("Filter", self.filter_combo)
        self.observers_edit = QLineEdit(settings.observers,
                                        placeholderText="BHTOM usernames, e.g. Ihorrrzzz")
        self.observers_edit.setToolTip(
            "Optional: set observer usernames on uploaded data points\n"
            "(must be valid, case-sensitive BHTOM usernames)"
        )
        form.addRow("Observers", self.observers_edit)
        self.comment_edit = QLineEdit(settings.comment, placeholderText="optional upload comment")
        form.addRow("Comment", self.comment_edit)
        layout.addWidget(upload)

        # -- calibration
        calibration = QGroupBox("Calibration")
        form = QFormLayout(calibration)
        self.flat_min = QDoubleSpinBox(minimum=0, maximum=100000, decimals=0)
        self.flat_min.setSpecialValueText("off")
        self.flat_min.setValue(settings.flat_min_adu or 0)
        self.flat_min.setToolTip("Reject flats whose mean ADU is below this (0 = disabled)")
        form.addRow("Flat min mean ADU", self.flat_min)
        self.flat_max = QDoubleSpinBox(minimum=0, maximum=200000, decimals=0)
        self.flat_max.setSpecialValueText("off")
        self.flat_max.setValue(settings.flat_max_adu or 0)
        self.flat_max.setToolTip("Reject flats whose mean ADU is above this - near saturation (0 = disabled)")
        form.addRow("Flat max mean ADU", self.flat_max)
        self.cosmic_check = QCheckBox("Remove cosmic rays during calibration (L.A.Cosmic - slower)")
        self.cosmic_check.setChecked(settings.cosmic_ray)
        form.addRow(self.cosmic_check)
        layout.addWidget(calibration)

        note = QLabel("Applied to the next run. Service URLs live in config.ini.")
        note.setObjectName("subtle")
        layout.addWidget(note)

        buttons = QDialogButtonBox()
        save = QPushButton("Save")
        save.setObjectName("primary")
        buttons.addButton(save, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_save(self) -> None:
        s = self.settings
        s.theme = self.theme_combo.currentData()
        s.minimize_to_tray = self.tray_check.isChecked()
        s.filter_name = self.filter_combo.currentText().strip() or "GaiaSP/any"
        s.observers = self.observers_edit.text().strip()
        s.comment = self.comment_edit.text().strip()
        s.flat_min_adu = self.flat_min.value() or None
        s.flat_max_adu = self.flat_max.value() or None
        s.cosmic_ray = self.cosmic_check.isChecked()
        self.accept()
