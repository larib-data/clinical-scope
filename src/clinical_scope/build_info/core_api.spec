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
datas += [('../dash_api/assets', 'clinical_scope/dash_api/assets')]

# Collect hidden imports
hiddenimports = []
hiddenimports += collect_submodules("dash")
hiddenimports += collect_submodules("dash_daq")
hiddenimports += collect_submodules("clinical_scope")
# dash >= 4.3 imports pydantic at startup (dash/types.py); pydantic v2 loads its
# compiled pydantic_core and some submodules via dynamic imports the crawler misses.
hiddenimports += collect_submodules("pydantic")
hiddenimports += collect_submodules("pydantic_core")
datas += collect_data_files("pydantic")

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
        "setuptools", "pkg_resources", "pip",

        # --- Jupyter notebook ecosystem ---
        # dash_daq pulls in traitlets/comm/ipywidgets/IPython at import time, so those
        # cannot be excluded.  The packages below are the Jupyter *UI* layer on top
        # (notebook widgets, lab widgets) which are never exercised in a Dash app.
        "jupyterlab_widgets", "widgetsnbextension", "matplotlib_inline",

        # --- Installed but not imported anywhere in this project ---
        "dash_extensions",
        "dataclass_wizard",
        "functional",

        # --- GNU Readline (GPL-3) ---
        # The stdlib `readline` extension links GNU Readline (libreadline.so.8 on
        # Linux) -- a GPL-3 lib in an otherwise attribution-only bundle. Unused by
        # this web app, so excluding it keeps the GPL out. No-op where absent.
        "readline", "rlcompleter",
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
    name='ClinicalScope',
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
    name='ClinicalScope',
)
