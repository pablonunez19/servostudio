# Build natively on each supported OS; never bundle user data or access keys.
import sys
from pathlib import Path
root=Path(SPECPATH)
a=Analysis([str(root/'launcher.py')],pathex=[str(root)],binaries=[],
           datas=[(str(root/'index.html'),'.')],
           hiddenimports=['serial','serial.tools.list_ports'],hookspath=[],
           hooksconfig={},runtime_hooks=[],excludes=[],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='ServoStudio',
        debug=False,bootloader_ignore_signals=False,strip=False,upx=False,
        console=sys.platform!='darwin')
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='ServoStudio')
if sys.platform=='darwin':
    app=BUNDLE(coll,name='ServoStudio.app',icon=None,
               bundle_identifier='com.pablonunez19.servostudio',
               info_plist={'CFBundleShortVersionString':'0.3.0',
                           'NSHighResolutionCapable':True})
