"""Compatibility checks use an actual loopback HTTP server, not model inference."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
from test_app import make_client, create_avatar


@pytest.mark.parametrize('kind,adapter', [('local_openai','openai_compatible'),('ollama','ollama'),('custom_local_adapter','openai_compatible'),('custom_local_adapter','ollama')])
def test_legacy_connection_end_to_end_protocol(tmp_path, kind, adapter):
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            self.send_response(200);self.end_headers();self.wfile.write(b'{"data":[{"id":"fixture"}],"models":[{"name":"fixture"}]}')
        def do_POST(self):
            calls.append(self.path)
            self.rfile.read(int(self.headers.get('Content-Length',0)))
            payload={'message':{'content':'本机协议验收成功。'}} if self.path.endswith('/api/chat') else {'choices':[{'message':{'content':'本机协议验收成功。'}}]}
            self.send_response(200);self.end_headers();self.wfile.write(json.dumps(payload).encode())
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with make_client(tmp_path) as client:
            a=create_avatar(client,subject_kind='fictional');base=f"/api/avatars/{a['id']}"
            payload={'display_name':'local protocol fixture','connection_type':kind,'adapter_kind':adapter,'base_url':f'http://127.0.0.1:{server.server_port}','model':'fixture'}
            created=client.post('/api/model-connections',json=payload);assert created.status_code==201
            cid=created.json()['id']
            assert client.post('/api/model-connections/test',json={**payload,'connection_id':cid}).json()['ok']
            assert client.put(base+'/settings/model',json={'connection_id':cid}).status_code==200
            response=client.post(base+'/chat',json={'message':'协议验收','preview_mode':True})
            assert response.status_code==200,response.text
            assert '本机协议验收成功' in response.text
            assert calls
    finally:server.shutdown();server.server_close()
