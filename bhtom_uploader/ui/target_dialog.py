"""Create-target dialog, prefilled from FITS header coordinates."""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ..core.bhtom import BHTOMClient
from .worker import start_worker

# documented BHTOM classification codes (Documentation/DocumentationAPI.md)
CLASSIFICATIONS = [
    "Unknown", "Be-star outburst", "AGN", "BL Lac", "CV", "CEPH", "EB", "Galaxy",
    "LPV", "LBV", "M-dwarf flare", "Microlensing Event", "Nova", "Peculiar Supernova",
    "QSO", "RCrB", "RR Lyrae Variable", "SSO", "Star", "SN", "Supernova imposter",
    "Symbiotic star", "TDE", "Variable star-other", "XRB", "YSO",
]


class TargetDialog(QDialog):
    """Shown when the chosen target doesn't exist in BHTOM yet."""

    def __init__(
        self,
        client: BHTOMClient,
        name: str,
        ra: Optional[float] = None,
        dec: Optional[float] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.client = client
        self.created_name: Optional[str] = None

        self.setWindowTitle("Create target in BHTOM")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        intro = QLabel(
            f"Target <b>{name}</b> does not exist in BHTOM yet. "
            "Review the details (RA/Dec were read from the FITS header when available) "
            "and create it:"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.name_edit = QLineEdit(name)
        self.ra_spin = QDoubleSpinBox(decimals=6, minimum=0.0, maximum=360.0)
        self.ra_spin.setValue(ra if ra is not None else 0.0)
        self.dec_spin = QDoubleSpinBox(decimals=6, minimum=-90.0, maximum=90.0)
        self.dec_spin.setValue(dec if dec is not None else 0.0)
        self.epoch_spin = QDoubleSpinBox(decimals=1, minimum=1900.0, maximum=2100.0)
        self.epoch_spin.setValue(2000.0)
        self.class_combo = QComboBox()
        self.class_combo.addItems(CLASSIFICATIONS)
        self.importance_spin = QDoubleSpinBox(decimals=2, minimum=0.0, maximum=10.0)
        self.importance_spin.setValue(9.9)
        self.cadence_spin = QDoubleSpinBox(decimals=2, minimum=0.0, maximum=1000.0)
        self.cadence_spin.setValue(1.0)
        self.description_edit = QLineEdit(placeholderText="optional description")

        form.addRow("Name", self.name_edit)
        form.addRow("RA (deg)", self.ra_spin)
        form.addRow("Dec (deg)", self.dec_spin)
        form.addRow("Epoch", self.epoch_spin)
        form.addRow("Classification", self.class_combo)
        form.addRow("Importance", self.importance_spin)
        form.addRow("Cadence (d)", self.cadence_spin)
        form.addRow("Description", self.description_edit)
        layout.addLayout(form)

        self.error_label = QLabel()
        self.error_label.setObjectName("errorLabel")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        buttons = QDialogButtonBox()
        self.create_button = QPushButton("Create target")
        self.create_button.setObjectName("primary")
        buttons.addButton(self.create_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        self.create_button.clicked.connect(self._on_create)
        layout.addWidget(buttons)

    def _on_create(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            self.error_label.setText("Target name is required.")
            self.error_label.show()
            return
        if self.ra_spin.value() == 0.0 and self.dec_spin.value() == 0.0:
            self.error_label.setText(
                "RA/Dec look unset (0, 0). Enter the target coordinates in degrees."
            )
            self.error_label.show()
            return
        self.error_label.hide()
        self.create_button.setEnabled(False)
        self.create_button.setText("Creating…")

        def do_create():
            return self.client.create_target(
                name=name,
                ra=self.ra_spin.value(),
                dec=self.dec_spin.value(),
                epoch=self.epoch_spin.value(),
                classification=self.class_combo.currentText(),
                importance=self.importance_spin.value(),
                cadence=self.cadence_spin.value(),
                description=self.description_edit.text().strip() or None,
            )

        start_worker(do_create, on_result=self._on_created, on_error=self._on_error)

    def _on_created(self, _payload: dict) -> None:
        self.created_name = self.name_edit.text().strip()
        self.accept()

    def _on_error(self, message: str) -> None:
        self.create_button.setEnabled(True)
        self.create_button.setText("Create target")
        self.error_label.setText(message)
        self.error_label.show()
