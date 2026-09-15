"""Archive native builds with executable permissions, plus checksums."""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import tarfile
import zipfile

p=argparse.ArgumentParser()
p.add_argument('--platform',required=True)
args=p.parse_args()
root=Path(__file__).resolve().parents[1]
out=root/'release';out.mkdir(exist_ok=True)
name='ServoStudio-'+args.platform
if args.platform.startswith('macos'):
    target=out/(name+'.zip')
    subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(root/'dist/ServoStudio.app'),str(target)],check=True)
elif args.platform.startswith('windows'):
    target=Path(shutil.make_archive(str(out/name),'zip',root/'dist','ServoStudio'))
else:
    target=out/(name+'.tar.gz')
    with tarfile.open(target,'w:gz') as t:t.add(root/'dist/ServoStudio',arcname='ServoStudio')
(out/(target.name+'.sha256')).write_text(hashlib.sha256(target.read_bytes()).hexdigest()+'  '+target.name+'\n')
print(target)
