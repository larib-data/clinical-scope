# Build Instructions

This folder contains the PyInstaller configuration and build scripts for creating a standalone executable of Clinical Scope.

## Prerequisites

1. **Python environment** with all dependencies installed:
   ```bash
   source .venv/bin/activate
   pip install -e .
   ```

2. **PyInstaller** installed:
   ```bash
   pip install pyinstaller
   ```

## Quick Build

Run the build script from anywhere:

```bash
./src/clinical_scope/build_info/build.sh
```

The script will:
- Auto-detect your platform (macOS ARM/Intel, Linux, Windows)
- Run PyInstaller with the correct settings
- Output to `builded_app/<platform>/`

## Manual Build

From the project root:

```bash
# macOS ARM (M1/M2/M3)
pyinstaller src/clinical_scope/build_info/core_api.spec --clean --distpath builded_app/macOS_arm

# macOS Intel
pyinstaller src/clinical_scope/build_info/core_api.spec --clean --distpath builded_app/macOS_intel

# Linux
pyinstaller src/clinical_scope/build_info/core_api.spec --clean --distpath builded_app/linux

# Windows
pyinstaller src/clinical_scope/build_info/core_api.spec --clean --distpath builded_app/windows
```

## Output Structure

```
builded_app/
└── macOS_arm/
    └── ClinicalScope/
        ├── ClinicalScope                    # Main executable
        ├── ClinicalScope_UserGuide.pdf      # User guide (committed artifact — see below)
        ├── LICENSE                          # Project license
        ├── DISCLAIMER.txt                   # Research-use-only notice
        ├── THIRD_PARTY_LICENSES.txt         # Bundled dependency notices (auto-generated)
        ├── demo_database/                   # Runnable demo config + demo patient
        ├── template_patient_data_structure/ # Empty folder skeleton to copy
        └── _internal/                       # Dependencies
```

## Static assets

Everything above the `_internal/` line except the executable is copied in by `assemble_bundle.py`, from the `ASSETS` manifest at the top of that file. Adding a file to the bundle means adding it there — both build entry points read the same list.

**The user guide PDF is a committed artifact, not a build product.** `assemble_bundle.py` copies `docs/user_guide/ClinicalScope_UserGuide.pdf` as it finds it in the repo; nothing regenerates it from `tutorial.md`, and a stale PDF copies just as cleanly as a fresh one — the build cannot tell the difference and says nothing. Regenerating is a manual step:

```bash
./docs/user_guide/build_pdf.sh    # needs pandoc + xelatex/pdflatex
```

It is deliberately not wired into `build.sh`: pandoc and a LaTeX engine would then be prerequisites on every build machine, CI runners included, to rebuild a file that changes a few times a year. The cost of that choice is that **`tutorial.md` and the PDF drift silently**, so run the script and commit the result whenever you edit the tutorial — and always before cutting a release ([RELEASING.md](../../../docs/RELEASING.md) step 1).

## License notices

After PyInstaller runs, the bundle is finished by `assemble_bundle.py` (shared by `build.sh` and the CI build workflow, so the step lives in one place): it copies the static assets in and runs `generate_third_party_licenses.py` to write `THIRD_PARTY_LICENSES.txt` — required because PyInstaller redistributes dependency code/libraries but strips their licenses. It harvests license texts from the **build interpreter's** installed packages (so run the build from the venv that produced it) and scans `_internal/` for native libraries. The native-library license map inside the script is **hand-maintained**: an unrecognised native lib is flagged as `*** TODO` in the output (and an `UNRECOGNISED NATIVE LIBRARIES` block), so re-check it per platform and after dependency changes.

If anything is unresolved (a package with no license file, or an unrecognised native lib) the script still writes the file but exits non-zero, which `build.sh` surfaces as a warning without failing the build — resolve the `*** TODO` entries before cutting a release. Rationale in [ADR-0002](../../../docs/adr/0002-warn-only-on-unresolved-license-attribution.md).

## Running the Built App

```bash
# macOS/Linux
./builded_app/macOS_arm/ClinicalScope/ClinicalScope

# Windows
builded_app\windows\ClinicalScope\ClinicalScope.exe
```

The app will open your browser to http://127.0.0.1:8050

## Spec File Configuration

The `core_api.spec` file configures the build:

| Setting | Value | Description |
|---------|-------|-------------|
| `name` | ClinicalScope | Output executable name |
| `console` | True | Shows terminal output (set False to hide) |
| `onefile` | False | Creates folder structure (faster startup) |
| `upx` | True | Compresses binaries |

### Hidden Imports

The spec file collects all submodules from:
- `dash` - Web framework
- `dash_daq` - DAQ components
- `clinical_scope` - This package

### Data Files

Non-code assets are collected from:
- `dash`
- `dash_daq`
- `dash_table`

## Troubleshooting

### Missing modules at runtime

If the app crashes with import errors, add the missing module to `hiddenimports` in the spec file:

```python
hiddenimports += ["missing_module"]
```

### App too large

To reduce size, add unused packages to `excludes`:

```python
excludes = ["matplotlib", "scipy", ...]
```

### Slow startup

The current config uses folder mode (`onefile=False`) which is faster. If you need a single file:

```python
exe = EXE(
    ...
    onefile=True,
)
# And remove the COLLECT section
```

## Version Info

The app displays its version from `pyproject.toml` in the top-right corner.
