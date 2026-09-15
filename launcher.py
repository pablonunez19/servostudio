"""Standalone entry point. Double-clicking opens the authenticated browser panel."""
import sys
from server import main

if __name__=='__main__':
    if '--self-test' in sys.argv:
        from smoke_test import run
        run()
    else:
        main()
