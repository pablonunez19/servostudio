#!/bin/zsh
cd "${0:A:h}"
exec /usr/bin/python3 server.py --simulate --port 8109 --open
