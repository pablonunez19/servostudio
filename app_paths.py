"""Writable user data is kept outside the source or frozen application bundle."""
import os
import sys
from pathlib import Path

def user_data_dir():
    if os.environ.get('SERVOSTUDIO_DATA_DIR'):
        return Path(os.environ['SERVOSTUDIO_DATA_DIR']).expanduser()
    if sys.platform=='win32':
        return Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData'/'Local')))/'ServoStudio'
    if sys.platform=='darwin':return Path.home()/'Library'/'Application Support'/'ServoStudio'
    return Path(os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local'/'share')))/'servostudio'
