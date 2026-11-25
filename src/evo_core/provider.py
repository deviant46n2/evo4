import json
import time
import urllib.error
import urllib.request

class _StreamingSecretRedactor:
    """Withhold partial secret prefixes so chunk boundaries cannot leak a key."""

    def __init__(self, secret):
        self.secret = secret if isinstance(secret, str) and secret and secret != "no-key" else None
        self.pending = ""

    def push(self, text):
        if not self.secret:
            return text
        combined = self.pending + text
        safe_end = max(0, len(combined) - len(self.secret) + 1)
        # Never emit a prefix that overlaps a complete secret spanning this boundary.
        for start in range(max(0, safe_end - len(self.secret) + 1), safe_end):
            if combined.startswith(self.secret, start) and start + len(self.secret) > safe_end:
                safe_end = start
                break
        safe = combined[:safe_end].replace(self.secret, "[REDACTED]")
        self.pending = combined[safe_end:]
        return safe

    def finish(self):
        pending = self.pending
        self.pending = ""
        if self.secret:
            pending = pending.replace(self.secret, "[REDACTED]")
        return pending


def _redact_value(value, secret):
    if isinstance(value, str) and secret:
        return value.replace(secret, "[REDACTED]")
    if isinstance(value, list):
        return [_redact_value(item, secret) for item in value]
    if isinstance(value, dict):
        return {
            _redact_value(key, secret): _redact_value(item, secret)
            for key, item in value.items()
        }
    return value


class ProviderError(RuntimeError):
    pass


class InvalidToolCallError(ProviderError):
    def __init__(self, message, finish_reason=None):
        super().__init__(message)
        self.finish_reason = finish_reason

class OpenAICompatibleProvider:
    """Streaming chat provider for llama.cpp and other OpenAI-compatible servers."""
    def __init__(self, base_url, api_key, model, timeout=600):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _redact_error(self, message):
        text = str(message)
        if self.api_key and self.api_key != "no-key":
            text = text.replace(str(self.api_key), "[REDACTED]")
        return text[:500]

    def list_models(self):
        request = urllib.request.Request(self.base_url + "/v1/models",
            headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=min(self.timeout,10)) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return [item.get("id") for item in payload.get("data",[]) if item.get("id")]
        except urllib.error.HTTPError as exc:
            # Provider bodies are untrusted and may echo credentials; discard by default.
            raise ProviderError(f"Model-list HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise ProviderError("Model-list request failed") from exc

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
        redactor = _StreamingSecretRedactor(self.api_key)
        tool_call_parts = {}
        content_type = ""
        saw_event = False
        valid_event = False
        malformed_event = False
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
                        malformed_event = True
                        continue
                    if not isinstance(event, dict):
                        malformed_event = True
                        continue
                    valid_event = True
                    if event.get("error") is not None:
                        error = event["error"]
                        if isinstance(error, dict):
                            message = error.get("message") or error.get("detail") or str(error)
                        else:
                            message = str(error)
                        raise ProviderError(f"Chat completion stream error: {self._redact_error(message)}")
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
                        safe_content = redactor.push(content)
                        if safe_content:
                            pieces.append(safe_content)
                            if on_token:
                                on_token(safe_content)
        except urllib.error.HTTPError as exc:
            # Do not persist or expose provider response bodies by default.
            raise ProviderError(f"Chat completion HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderError("Chat completion request failed") from exc
        final_safe_content = redactor.finish()
        if final_safe_content:
            pieces.append(final_safe_content)
            if on_token:
                on_token(final_safe_content)
        if not saw_event:
            raise ProviderError(f"Server returned no SSE data events (Content-Type: {content_type or 'unknown'})")
        if not valid_event:
            raise ProviderError(f"Server returned malformed SSE data (Content-Type: {content_type or 'unknown'})")
        if not pieces and not tool_call_parts and finish_reason != "length":
            raise ProviderError("Server returned an empty completion")
        finished = time.perf_counter()
        elapsed = finished-started
        completion_tokens = usage.get("completion_tokens")
        generation_time = finished-first_token if first_token else None
        parsed_calls = []

        # A length-finished response is incomplete by definition. Tool-call
        # argument fragments may contain partial JSON, so do not parse or
        # expose any of them. The coding agent will see finish_reason="length"
        # and perform its bounded safe continuation without executing calls.
        if finish_reason != "length":
            for index in sorted(tool_call_parts):
                secret = self.api_key if self.api_key != "no-key" else None
                call = _redact_value(tool_call_parts[index], secret)
                try:
                    arguments = json.loads(call["function"]["arguments"] or "{}")
                except json.JSONDecodeError as exc:
                    raise InvalidToolCallError(
                        f"Model returned invalid tool-call JSON: {exc}",
                        finish_reason=finish_reason,
                    ) from exc
                parsed_calls.append({
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["function"]["name"],
                        "arguments": arguments,
                    },
                })

        return {
            "content": "".join(pieces),
            "tool_calls": parsed_calls,
            "elapsed_seconds": elapsed,
            "ttft_seconds": first_token - started if first_token else None,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": completion_tokens,
            "tokens_per_second": (
                completion_tokens / generation_time
                if completion_tokens and generation_time and generation_time > 0
                else None
            ),
            "finish_reason": finish_reason,
            "truncated": finish_reason == "length",
        }
