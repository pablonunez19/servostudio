"""Test the actual packaged HTTP server, bundled UI and simulator without USB."""
import json
import tempfile
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from server import make_handler
from studio import StudioControl

def run():
    with tempfile.TemporaryDirectory() as tmp:
        c=StudioControl(True,data_dir=tmp)
        srv=ThreadingHTTPServer(('127.0.0.1',0),make_handler(c,'smoke-test-key'))
        worker=threading.Thread(target=srv.serve_forever,daemon=True);worker.start()
        def req(path,body=None):
            r=urllib.request.Request(f'http://127.0.0.1:{srv.server_port}'+path,
                data=None if body is None else json.dumps(body).encode(),
                headers={'Authorization':'Bearer smoke-test-key'})
            with urllib.request.urlopen(r,timeout=3) as f:return f.read()
        try:
            assert b'Servo Studio' in req('/'), 'Bundled UI missing'
            req('/api/connect',{})
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                s=json.loads(req('/api/status'))
                if s['connected'] and not s['busy']:break
                time.sleep(.02)
            else:raise RuntimeError('Simulator did not connect')
            req('/api/move',{'angle':180,'hold':False})
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                s=json.loads(req('/api/status'))
                if not s['busy']:
                    assert not s['error'],s['error']
                    assert abs(s['position_deg']-180)<.34
                    break
                time.sleep(.02)
            else:raise RuntimeError('Simulator did not finish')
            assert json.loads(req('/api/capabilities'))['mode']=='simulation'
            req('/api/shutdown',{})
            worker.join(3)
            assert not worker.is_alive(),'Shutdown failed'
        finally:
            if worker.is_alive():srv.shutdown()
            srv.server_close();c.close()
    print('Servo Studio packaged smoke test passed')
