import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from evo_core.provider import OpenAICompatibleProvider

class ToolSSEHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        size=int(self.headers.get("Content-Length","0"))
        self.server.payload=json.loads(self.rfile.read(size))
        events=[
          {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_123","type":"function","function":{"name":"read_","arguments":"{\\"path\\":"}}]}}]},
          {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"file","arguments":"\\"a.py\\"}"}}]}}]},
          {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":3}}
        ]
        body="".join("data: "+json.dumps(e)+"\n\n" for e in events)+"data: [DONE]\n\n"
        raw=body.encode()
        self.send_response(200); self.send_header("Content-Type","text/event-stream")
        self.send_header("Content-Length",str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def log_message(self,*args): pass

class ProviderToolTests(unittest.TestCase):
    def test_streamed_tool_call_arguments_are_reassembled(self):
        server=ThreadingHTTPServer(("127.0.0.1",0),ToolSSEHandler)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            provider=OpenAICompatibleProvider(f"http://127.0.0.1:{server.server_port}","key","fake",3)
            result=provider.chat([{"role":"user","content":"read"}],tools=[{"type":"function"}])
            self.assertEqual(result["tool_calls"][0]["function"]["name"],"read_file")
            self.assertEqual(result["tool_calls"][0]["function"]["arguments"],{"path":"a.py"})
            self.assertIn("tools",server.payload)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

if __name__=="__main__":
    unittest.main()
