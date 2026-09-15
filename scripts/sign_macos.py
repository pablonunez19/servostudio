"""Ad-hoc integrity signing; does not provide publisher trust or notarization."""
import os
import subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]/'dist/ServoStudio.app'
# Remove only Finder metadata from our generated bundle, never quarantine flags.
for attr in ('com.apple.FinderInfo','com.apple.ResourceFork'):
    subprocess.run(['xattr','-dr',attr,str(root)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
subprocess.run(['codesign','--force','--deep','--sign','-','--timestamp=none',str(root)],check=True)
subprocess.run(['codesign','--verify','--deep','--strict',str(root)],check=True)
