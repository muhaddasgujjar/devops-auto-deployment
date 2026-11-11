"""Authenticated loopback-only SQLite inbox with idempotent immutable receipts."""
import hashlib
import hmac
import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from backend.monitoring import canonical


def create_receiver(database,token,port=8092):
    if len(token)<32: raise ValueError('A separate receiver credential is required')
    database=Path(database)
    database.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(database) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY,sha256 TEXT NOT NULL,payload TEXT NOT NULL,received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
    database.chmod(0o600)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def respond(self,status,document):
            raw=json.dumps(document).encode(); self.send_response(status)
            self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(raw)
        def do_GET(self):
            self.respond(200 if self.path=='/health/live' else 404,{'alive':True})
        def do_POST(self):
            if self.path!='/notifications': return self.respond(404,{})
            if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+token):
                return self.respond(401,{})
            self.connection.settimeout(5)
            try:
                length=int(self.headers.get('Content-Length','0'))
                if self.headers.get('Transfer-Encoding') or not 0<length<=65536: return self.respond(413,{})
                raw=self.rfile.read(length)
                if len(raw)!=length: return self.respond(400,{})
                payload=json.loads(raw,parse_constant=lambda x: (_ for _ in ()).throw(ValueError()))
                identity=payload['id']
                if not isinstance(identity,str) or len(identity)!=36 or identity!=self.headers.get('Idempotency-Key'):
                    return self.respond(422,{})
                encoded=canonical(payload); digest=hashlib.sha256(encoded).hexdigest()
                with sqlite3.connect(database,timeout=5) as conn:
                    conn.execute('INSERT OR IGNORE INTO receipts(id,sha256,payload) VALUES(?,?,?)',
                                 (identity,digest,encoded.decode()))
                    previous=conn.execute('SELECT sha256 FROM receipts WHERE id=?',(identity,)).fetchone()[0]
                    if previous!=digest: return self.respond(409,{})
                return self.respond(200,{'id':identity,'sha256':digest})
            except (ValueError,KeyError,TypeError,UnicodeError): return self.respond(422,{})
            except (sqlite3.Error,TimeoutError,OSError): return self.respond(503,{})
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.daemon_threads=True
    return server


def main():
    config=json.loads(Path(os.environ['RELEASE_RECEIVER_CONFIG_FILE']).read_text())
    create_receiver('/var/lib/release-notification-receiver/inbox.sqlite3',config['token']).serve_forever()


if __name__=='__main__': main()
