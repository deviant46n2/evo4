import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from evo_core.provider import OpenAICompatibleProvider, ProviderError

class ToolSSEHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        size=int(self.headers.get("Content-Length","0"))
        self.server.payload=json.loads(self.rfile.read(size))
        second_arguments = (
            ""
            if getattr(self.server, "partial_tool_args", False)
            else '"a.py"}'
        )
        events=[
          {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_123","type":"function","function":{"name":"read_","arguments":'{"path":'}}]}}]},
          {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"file","arguments":second_arguments}}]}}]},
          {"choices":[{"delta":{},"finish_reason":getattr(self.server,"finish_reason","tool_calls")}]},
          {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":3}}
        ]
        body="".join("data: "+json.dumps(e)+"\n\n" for e in events)+"data: [DONE]\n\n"
        raw=body.encode()
        self.send_response(200); self.send_header("Content-Type","text/event-stream")
        self.send_header("Content-Length",str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def log_message(self,*args): pass

class PlainJSONHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        size=int(self.headers.get("Content-Length","0")); self.rfile.read(size)
        body=json.dumps({"choices":[{"message":{"role":"assistant","content":"plain"}}],
                         "usage":{"prompt_tokens":3,"completion_tokens":2}}).encode()
        self.send_response(200); self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self,*args): pass

class UnauthorizedHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body=b'{"error":"invalid api key"}'
        self.send_response(401); self.send_header("Content-Length",str(len(body)))
        self.end_headers(); self.wfile.write(body)
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
            self.assertEqual(result["finish_reason"],"tool_calls")
            self.assertFalse(result["truncated"])
            self.assertIn("tools",server.payload)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_length_finish_reason_is_exposed_as_truncated(self):
        server=ThreadingHTTPServer(("127.0.0.1",0),ToolSSEHandler)
        server.finish_reason="length"
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            provider=OpenAICompatibleProvider(f"http://127.0.0.1:{server.server_port}","key","fake",3)
            result=provider.chat([{"role":"user","content":"read"}])
            self.assertEqual(result["finish_reason"],"length")
            self.assertTrue(result["truncated"])
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_non_sse_json_response_is_rejected(self):
        server=ThreadingHTTPServer(("127.0.0.1",0),PlainJSONHandler)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            provider=OpenAICompatibleProvider(f"http://127.0.0.1:{server.server_port}","key","fake",3)
            with self.assertRaises(ProviderError):
                provider.chat([{"role":"user","content":"hello"}])
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_model_list_http_error_includes_response_body(self):
        server=ThreadingHTTPServer(("127.0.0.1",0),UnauthorizedHandler)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            provider=OpenAICompatibleProvider(f"http://127.0.0.1:{server.server_port}","bad","fake",3)
            with self.assertRaises(ProviderError) as raised:
                provider.list_models()
            self.assertIn("invalid api key",str(raised.exception))
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_truncated_partial_tool_arguments_are_discarded_without_json_parse(self):
        server=ThreadingHTTPServer(("127.0.0.1",0),ToolSSEHandler)
        server.finish_reason="length"
        server.partial_tool_args=True
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            provider=OpenAICompatibleProvider(
                f"http://127.0.0.1:{server.server_port}","key","fake",3
            )
            result=provider.chat(
                [{"role":"user","content":"read"}],
                tools=[{"type":"function"}],
            )
            self.assertEqual(result["finish_reason"],"length")
            self.assertTrue(result["truncated"])
            self.assertEqual(result["tool_calls"],[])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__=="__main__":
    unittest.main()


class ErrorSSEHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(size)
        body = 'data: {"error":{"message":"provider failed"}}\n\ndata: [DONE]\n\n'
        raw = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


class UsageThenContentSSEHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(size)
        events = [
            {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 0}},
            {"choices": [{"delta": {"content": "hello"}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
        ]
        body = "".join("data: " + json.dumps(e) + "\n\n" for e in events) + "data: [DONE]\n\n"
        raw = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


class EmptyCompletionSSEHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(size)
        events = [{"choices": [{"delta": {}, "finish_reason": "stop"}]}]
        body = "".join("data: " + json.dumps(e) + "\n\n" for e in events) + "data: [DONE]\n\n"
        raw = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


class MalformedSSESSEHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(size)
        body = "data: {not json}\n\ndata: [DONE]\n\n"
        raw = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


class ProviderReliabilityTests(unittest.TestCase):
    def _request(self, handler):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = OpenAICompatibleProvider(f"http://127.0.0.1:{server.server_port}", "key", "fake", 3)
            return provider
        finally:
            pass

    def test_sse_error_frame_raises(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), ErrorSSEHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = OpenAICompatibleProvider(f"http://127.0.0.1:{server.server_port}", "key", "fake", 3)
            with self.assertRaises(ProviderError) as raised:
                provider.chat([{"role": "user", "content": "hi"}])
            self.assertIn("provider failed", str(raised.exception))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_usage_only_then_content_succeeds(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), UsageThenContentSSEHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = OpenAICompatibleProvider(f"http://127.0.0.1:{server.server_port}", "key", "fake", 3)
            result = provider.chat([{"role": "user", "content": "hi"}])
            self.assertEqual(result["content"], "hello")
            self.assertEqual(result["prompt_tokens"], 1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_empty_completion_raises(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), EmptyCompletionSSEHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = OpenAICompatibleProvider(f"http://127.0.0.1:{server.server_port}", "key", "fake", 3)
            with self.assertRaises(ProviderError) as raised:
                provider.chat([{"role": "user", "content": "hi"}])
            self.assertIn("empty completion", str(raised.exception))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_malformed_sse_raises(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), MalformedSSESSEHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = OpenAICompatibleProvider(f"http://127.0.0.1:{server.server_port}", "key", "fake", 3)
            with self.assertRaises(ProviderError) as raised:
                provider.chat([{"role": "user", "content": "hi"}])
            self.assertIn("malformed SSE", str(raised.exception))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
