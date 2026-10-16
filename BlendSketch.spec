# PyInstaller build for macOS, Windows and Linux. Build on each OS:  pyinstaller BlendSketch.spec
# (PyInstaller can't cross-compile; .github/workflows/build.yml builds all three.)
import os
import sys

sys.path.insert(0, SPECPATH)  # noqa: F821 (provided by PyInstaller)
from blendsketch import __version__

ICON = {"darwin": "packaging/icon.icns", "win32": "packaging/icon.ico"}.get(sys.platform, "packaging/icon.png")

a = Analysis(
    ["run.py"],
    pathex=["."],
    datas=[("packaging/icon.png", "packaging")],
    hiddenimports=["PySide6.QtSvg", "PySide6.QtMultimedia"],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
              "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtCharts", "PySide6.QtDataVisualization",
              "PySide6.QtPdf", "PySide6.QtDesigner", "PySide6.QtBluetooth", "PySide6.QtLocation"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="BlendSketch", console=False, icon=ICON)
coll = COLLECT(exe, a.binaries, a.datas, name="BlendSketch")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="BlendSketch.app",
        icon=ICON,
        bundle_identifier="studio.blendsketch.app",
        version=__version__,
        info_plist={
            "CFBundleShortVersionString": __version__,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
            # Double-clicking a .bsplaylist in Finder opens it in BlendSketch.
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "BlendSketch Playlist",
                "CFBundleTypeRole": "Editor",
                "LSHandlerRank": "Owner",
                "LSItemContentTypes": ["studio.blendsketch.playlist"],
                "CFBundleTypeIconFile": "icon.icns",
            }],
            "UTExportedTypeDeclarations": [{
                "UTTypeIdentifier": "studio.blendsketch.playlist",
                "UTTypeDescription": "BlendSketch Playlist",
                "UTTypeConformsTo": ["public.json", "public.data"],
                "UTTypeTagSpecification": {"public.filename-extension": ["bsplaylist"]},
            }],
        },
    )
