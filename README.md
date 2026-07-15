# BHTOM Uploader

A Windows desktop client for **[BHTOM](https://bh-tom2.astrouw.edu.pl)** (Black Hole Target Observation Manager):
**bulk upload of calibrated FITS frames** from your telescope straight to your BHTOM account -
with automatic CCD calibration, full transparency about every step, and hands-off operation from the system tray.

Built with PySide6 (Qt 6) · astropy · ccdproc.

---

## What it does

1. **Drop a folder** (or pick one) containing your night's FITS files.
2. The app reads every FITS header and **classifies each frame** (light / bias / dark / flat),
   detects whether lights are **already calibrated** (CALSTAT, HISTORY provenance, filename conventions),
   and shows a **plan banner**: what was found and exactly what will happen. Low-confidence
   classifications are marked `?` and can be corrected per-row before running.
3. On **Start**:
   - raw lights **+** calibration frames → **calibrate first** (masters built per binning/filter), then upload;
   - already-calibrated lights → **upload directly**;
   - raw lights with **no** calibration frames → a warning: uploading raw files is *not recommended* -
     you must explicitly confirm.
4. **Minimize to tray** - calibration and uploads continue in the background.
5. On success a **bottom-right toast** shows the target's light curve for a minute -
   click through to the full interactive plot (with a Lomb-Scargle **phase-folded view** when a period is found)
   or the BHTOM target page.
6. The app then **polls BHTOM's calibration results** so each file's row ends with the server's verdict:
   standardized magnitude ± error, or limit, or the server's error message.

### Watch mode

Tick **Watch folder** and the app keeps monitoring the directory: new FITS files
(e.g. arriving during an observing night) are detected, waited on until fully written,
classified, calibrated when possible and uploaded automatically.
Safety rules: raw frames are **never** auto-uploaded, frames whose `OBJECT` differs from
your confirmed target are skipped (logged), and an **upload journal** guarantees nothing
is ever uploaded twice - even across restarts.

### More

- **Observatory picker** fed live from your BHTOM account (favourites first, searchable) - ONAME resolved automatically.
- **Target check & create**: target name autofilled from the `OBJECT` header, existence verified against BHTOM,
  and a create-target dialog (prefilled with RA/DEC from the FITS header) when it doesn't exist yet.
- **Uploads history** browser (View → My uploads history).
- **Dry run** toggle - full end-to-end test, server stores nothing.
- **Credentials in Windows Credential Manager** (via `keyring`) - never in plaintext files.
- Themes: dark (default), light, follow-system, and a **red night mode** that protects dark adaptation.
- Append-only log pane (dockable) - everything the app does is visible.

---

## Calibration algorithm

Implemented on **ccdproc** (astropy-affiliated) with the standard reduction recipe:

| Step | Method |
|---|---|
| Master bias | sigma-clipped average combine (5σ, MAD std) |
| Master dark | darks are **bias-subtracted first**, normalized to a 1-second rate frame, sigma-clipped combine |
| Master flat | flats **bias- and dark-corrected before combining**, screened by mean ADU (optional min/max), inverse-median scaled, per filter |
| Lights | `subtract_bias` → `subtract_dark(scale=True)` (exposure-scaled) → `flat_correct` (guarded against non-positive flats) |
| Cosmic rays | optional L.A.Cosmic (astroscrappy), off by default (Settings) |

Guards: stacks must share shape/binning; CCD-TEMP spread > 5 °C warns; NaN/Inf sanitized.
Every output carries provenance (`CALSTAT` + `HISTORY BHTOM-UPLOADER …`), which the scanner reads back -
so re-scanning your own outputs classifies them as calibrated. Masters are saved to
`Calibrated files/masters/` for inspection and reuse.

---

## Running from source

```bash
# Python 3.12+ (developed on 3.14)
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

Or in PyCharm: the bundled run configuration **"Run BHTOM Uploader"** runs `main.py`.

Service URLs live in [`config.ini`](config.ini) - if BHTOM moves domains again, change them there:

```ini
[API]
bhtom_url = https://bh-tom2.astrouw.edu.pl
upload_url = https://uploadsvc2.bh-tom2.astrouw.edu.pl
```

## Tests

```bash
.venv\Scripts\python -m pytest tests -q
```

78 tests: synthetic-FITS calibration math (signal recovery, sigma-clip outlier rejection,
exposure scaling), scanner classification decision table, provenance round-trip,
API client against recorded live response shapes, pipeline flows, journal, watcher stability logic.

## Installing as a normal Windows app (no Python required)

End users run **`BHTOM-Uploader-Setup-<version>.exe`** - a standard installer that
installs per-user (no admin rights), adds a Start-menu entry and optional desktop
icon, and uninstalls cleanly from Windows Settings. It contains only the
application and `config.ini`; credentials are never bundled (each user's login is
stored in their own Windows Credential Manager).

### Building the installer

```bash
# 1) freeze the app
.venv\Scripts\python -m PyInstaller --noconfirm --clean --windowed --name "BHTOM Uploader" ^
  --icon "bhtom_uploader\resources\app.ico" ^
  --add-data "bhtom_uploader\resources;bhtom_uploader\resources" ^
  --exclude-module tkinter --exclude-module _tkinter main.py
copy config.ini "dist\BHTOM Uploader\config.ini"

# 2) compile the installer (Inno Setup 6)
ISCC.exe installer.iss   ->  dist\BHTOM-Uploader-Setup-<version>.exe
```

The intermediate `dist/BHTOM Uploader/` folder is itself portable: copy it anywhere
and run `BHTOM Uploader.exe`. Self-check of a built bundle:
`"BHTOM Uploader.exe" --smoke` writes `smoke_result.txt` (verifies Qt boots and the
Windows Credential Manager keyring backend is active).

## Supported input formats

Plain FITS (`.fits/.fit/.fts`), fpack/gzip-compressed (`.fits.fz`, `.fits.gz`) and
multi-extension FITS such as raw LCO Sinistro frames (metadata in the primary HDU,
image in compressed extensions; the first image extension is processed). Validated
end-to-end against a real public LCO night of the Gaia alert Gaia24amo
(1-m cpt1m013 + Sinistro fa01: raw lights + same-camera bias/dark/sky-flat sets).

## Project layout

```
bhtom_uploader/
├── app.py              QApplication bootstrap (theme, login → main window)
├── core/               UI-independent engine
│   ├── scanner.py      FITS discovery, classification, calibrated-detection, planning
│   ├── calibrator.py   ccdproc masters + light calibration + provenance
│   ├── bhtom.py        typed BHTOM REST client (auth, upload, targets, results, …)
│   ├── pipeline.py     QThread state machine: calibrate → upload → report
│   ├── watcher.py      watchdog folder monitor with stable-file detection
│   ├── journal.py      duplicate-upload prevention (per target, across restarts)
│   ├── lightcurve.py   photometry parsing, toast thumbnail, interactive plot + folding
│   ├── credentials.py  Windows Credential Manager storage
│   └── settings.py     config.ini URLs + QSettings preferences
└── ui/                 PySide6 windows and widgets (login, main, tray, toast, dialogs)
tests/                  pytest suite with synthetic FITS fixtures
```

## Acknowledgment

Data uploaded/downloaded via BHTOM is subject to the BHTOM data policy:

> The data was obtained via [BHTOM](https://bhtom.space), which has received funding from the
> European Union's Horizon 2020 research and innovation program under grant agreement
> No. 101004719 (OPTICON-RadioNet Pilot).
