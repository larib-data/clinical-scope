# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# Collect non-code assets
datas = []
datas += collect_data_files("dash")
datas += collect_data_files("dash_daq")
datas += collect_data_files("dash_table")

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
    excludes=[],
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
    name='ClinicalVisuAppAlexis',
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
    name='ClinicalVisuAppAlexis',
)
