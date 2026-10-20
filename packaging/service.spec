# Headless AMD64 one-file build. Run on Windows with x64 Python 3.11.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parent
analysis = Analysis(
    [str(root / 'windows_service.py')],
    pathex=[str(root)],
    binaries=[],
    datas=collect_data_files('certifi') + [(str(root / 'LICENSE'), '.')],
    hiddenimports=['win32timezone', 'servicemanager', 'win32service',
                   'win32serviceutil', 'win32event', 'pywintypes'],
    excludes=['tkinter', 'customtkinter', 'pystray', 'PIL'],
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, analysis.binaries, analysis.datas, [],
    name='tg-ws-proxy', console=True, upx=False,
    version=str(root / 'packaging' / 'service_version.txt'),
)
