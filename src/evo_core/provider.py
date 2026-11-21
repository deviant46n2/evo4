import json
import time
import urllib.error
import urllib.request

class ProviderError(RuntimeError):
    pass

class OpenAICompatibleProvider:
    """Streaming chat provider for llama.cpp and other OpenAI-compatible servers."""
    def __init__(self, base_url, api_key, model, timeout=600):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def list_models(self):
        request = urllib.request.Request(self.base_url + "/v1/models",
            headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=min(self.timeout,10)) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return [item.get("id") for item in payload.get("data",[]) if item.get("id")]
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"Model-list HTTP {exc.code}: {exc.read().decode(errors='replace')[:1000]}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise ProviderError(f"Model-list request failed: {exc}") from exc

    def chat(self, messages, max_tokens=2048, temperature=0.2, on_token=None, tools=None):
        payload = {"model":self.model,"messages":messages,"stream":True,
                   "stream_options":{"include_usage":True},"max_tokens":max_tokens,"temperature":temperature}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        request = urllib.request.Request(self.base_url + "/v1/chat/completions",
            data=json.dumps(payload,ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type":"application/json","Authorization":f"Bearer {self.api_key}"},
            method="POST")
        started = time.perf_counter()
        first_token = None
        usage = {}
        pieces = []
        tool_call_parts = {}
        content_type = ""
        saw_event = False
        finish_reason = None
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                content_type = response.headers.get("Content-Type","")
                for raw in response:
                    line = raw.decode("utf-8",errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    saw_event = True
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if event.get("usage"):
                        usage = event["usage"]
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    if choice.get("finish_reason") is not None:
                        finish_reason = str(choice["finish_reason"])
                    delta = choice.get("delta") or {}
                    for call in delta.get("tool_calls") or []:
                        index = call.get("index",0)
                        part = tool_call_parts.setdefault(index,{"id":"","type":"function","function":{"name":"","arguments":""}})
                        if call.get("id"): part["id"] = call["id"]
                        if call.get("type"): part["type"] = call["type"]
                        function = call.get("function") or {}
                        if function.get("name"): part["function"]["name"] += function["name"]
                        if function.get("arguments"): part["function"]["arguments"] += function["arguments"]
                    content = delta.get("content")
                    if isinstance(content,list):
                        content = "".join(part.get("text","") for part in content if isinstance(part,dict))
                    if isinstance(content,str) and content:
                        if first_token is None:
                            first_token = time.perf_counter()
                        pieces.append(content)
                        if on_token:
                            on_token(content)
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"Chat completion HTTP {exc.code}: {exc.read().decode(errors='replace')[:2000]}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"Chat completion request failed: {exc}") from exc
        if not saw_event:
            raise ProviderError(f"Server returned no SSE data events (Content-Type: {content_type or 'unknown'})")
        finished = time.perf_counter()
        elapsed = finished-started
        completion_tokens = usage.get("completion_tokens")
        generation_time = finished-first_token if first_token else None
        parsed_calls = []
        for index in sorted(tool_call_parts):
            call = tool_call_parts[index]
            try:
                arguments = json.loads(call["function"]["arguments"] or "{}")
            except json.JSONDecodeError as exc:
                raise ProviderError(f"Model returned invalid tool-call JSON: {exc}") from exc
            parsed_calls.append({"id":call["id"],"type":"function",
                                 "function":{"name":call["function"]["name"],"arguments":arguments}})
        return {"content":"".join(pieces),"tool_calls":parsed_calls,"elapsed_seconds":elapsed,
                "ttft_seconds":first_token-started if first_token else None,
                "prompt_tokens":usage.get("prompt_tokens"),"completion_tokens":completion_tokens,
                "tokens_per_second":(completion_tokens/generation_time if completion_tokens and generation_time and generation_time>0 else None),
                "finish_reason":finish_reason,"truncated":finish_reason=="length"}
