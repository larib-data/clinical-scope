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
        ├── ClinicalScope    # Main executable
        └── _internal/               # Dependencies
```

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
hiddenimports += ['missing_module']
```

### App too large

To reduce size, add unused packages to `excludes`:

```python
excludes=['matplotlib', 'scipy', ...]
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
