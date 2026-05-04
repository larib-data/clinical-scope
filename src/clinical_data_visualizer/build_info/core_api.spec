# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# Collect non-code assets
datas = []
datas += collect_data_files("dash")
datas += collect_data_files("dash_daq")
datas += collect_data_files("dash_table")

# Include Dash assets (CSS) so they're found at runtime by Dash(__name__)
datas += [('../dash_api/assets', 'clinical_data_visualizer/dash_api/assets')]

# Collect hidden imports
hiddenimports = []
hiddenimports += collect_submodules("dash")
hiddenimports += collect_submodules("dash_daq")
hiddenimports += collect_submodules("clinical_data_visualizer")

a = Analysis(
    ['../dash_api/core_api.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # --- Testing tools ---
        "pytest", "pluggy", "iniconfig",

        # --- Dev / linting tools ---
        "ruff", "editorconfig",

        # --- Build tools (only needed to produce the bundle, not to run it) ---
        "altgraph", "macholib",

        # --- Jupyter notebook ecosystem ---
        # dash_daq pulls in traitlets/comm/ipywidgets/IPython at import time, so those
        # cannot be excluded.  The packages below are the Jupyter *UI* layer on top
        # (notebook widgets, lab widgets) which are never exercised in a Dash app.
        "jupyterlab_widgets", "widgetsnbextension", "matplotlib_inline",

        # --- Installed but not imported anywhere in this project ---
        "dash_extensions",       # installed, but our app does not use it
        "dataclass_wizard",      # installed, but our app does not use it
        "functional",            # installed, but our app does not use it
        "more_itertools",        # installed, but our app does not use it

        # --- Pydantic stack (not used by our app or its runtime deps) ---
        "pydantic", "pydantic_core", "annotated_types", "typing_inspection",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ClinicalDataVisualizer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,   # Set False if you do NOT want terminal output
    onefile=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ClinicalDataVisualizer',
)
