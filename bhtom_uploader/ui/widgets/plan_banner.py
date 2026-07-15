"""Plan banner: always tells the user what was detected and what will happen."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from ...core.models import PlannedAction, ScanResult

_MAX_GROUP_LINES = 5
_MAX_WARNINGS = 4


class PlanBanner(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("planBanner")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        self.headline = QLabel()
        self.headline.setObjectName("bannerHeadline")
        self.headline.setWordWrap(True)

        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.RichText)  # allows the target-page link

        self.warnings = QLabel()
        self.warnings.setObjectName("warningsLabel")
        self.warnings.setWordWrap(True)

        layout.addWidget(self.headline)
        layout.addWidget(self.details)
        layout.addWidget(self.warnings)
        self.details.setOpenExternalLinks(True)
        self.warnings.hide()
        self.hide()

    # ------------------------------------------------------------------
    def set_scan(self, scan: Optional[ScanResult]) -> None:
        if scan is None or not scan.frames:
            self.hide()
            return
        self.headline.setText(f"Detected: {scan.summary()}")

        lines: list[str] = []
        for group in scan.light_groups:
            calib = scan.calibration_for(group)
            n = len(group.frames)
            if group.action is PlannedAction.UPLOAD_DIRECT:
                lines.append(f"▸ {group.display_name}: upload {n} calibrated frame(s) directly")
            elif group.action is PlannedAction.CALIBRATE_THEN_UPLOAD:
                lines.append(
                    f"▸ {group.display_name}: calibrate {group.n_raw} raw frame(s) "
                    f"using {calib.describe()}, then upload {n}"
                )
            elif group.action is PlannedAction.UPLOAD_RAW_CONFIRM:
                lines.append(
                    f"▸ {group.display_name}: {n} RAW frame(s), no calibration set - "
                    "uploading raw is not recommended; you will be asked to confirm"
                )
        if not lines:
            lines.append("▸ no light frames to upload - select a folder containing your object frames")
        if len(lines) > _MAX_GROUP_LINES:
            hidden = len(lines) - _MAX_GROUP_LINES
            lines = lines[:_MAX_GROUP_LINES] + [f"… and {hidden} more group(s)"]
        self.details.setText("<br>".join(lines))

        if scan.warnings:
            shown = scan.warnings[:_MAX_WARNINGS]
            more = len(scan.warnings) - len(shown)
            text = "⚠ " + "  •  ".join(shown)
            if more > 0:
                text += f"  (+{more} more)"
            self.warnings.setText(text)
            self.warnings.show()
        else:
            self.warnings.hide()
        self.show()

    def set_result(self, summary: str, target: str, target_url: str) -> None:
        """Post-run state: outcome + a link to the target page."""
        self.headline.setText(f"Run finished - {summary}")
        self.details.setText(
            f'▸ target <a href="{target_url}">{target}</a> - click to review on BHTOM'
        )
        self.warnings.hide()
        self.show()

    def set_error(self, message: str) -> None:
        self.headline.setText("Run failed")
        self.details.setText(f"▸ {message}")
        self.warnings.hide()
        self.show()
