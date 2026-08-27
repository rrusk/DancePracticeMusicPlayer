# -*- mode: python ; coding: utf-8 -*-
from kivy_deps import sdl2, glew, gstreamer


a = Analysis(
    ['music_player.py'],
    pathex=[],
    binaries=[],
    # Data the player reads from its own directory at runtime. Without
    # builtin_practice_types.json a packaged build offers only the two hardcoded
    # practice types, and without cues/ the gaps and round-warning tones of a
    # competition-round practice type are skipped.
    datas=[
        ('announce', 'announce'),
        ('cues', 'cues'),
        ('icons', 'icons'),
        ('builtin_practice_types.json', '.'),
    ],
    hiddenimports=['win32timezone'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['music.ini'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='music_player',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    *[Tree(p) for p in (sdl2.dep_bins + glew.dep_bins + gstreamer.dep_bins)],
    strip=False,
    upx=True,
    upx_exclude=[],
    name='music_player',
)
