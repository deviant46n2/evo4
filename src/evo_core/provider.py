import http.client
import json
import time
import urllib.error
import urllib.request

from .provider_endpoint import ProviderEndpointError

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

class ProviderHTTPError(ProviderError):
    def __init__(self, status_code, operation):
        self.status_code = int(status_code)
        super().__init__(f"{operation} HTTP {self.status_code}")


class ProviderTimeoutError(ProviderError):
    pass


class ProviderMalformedResponseError(ProviderError):
    pass


class OpenAICompatibleProvider:
    """Streaming chat provider for llama.cpp and other OpenAI-compatible servers.

    The optional pinned transport is used by Registry-bound adapters. Legacy
    TOML callers retain urllib's existing behavior and are not silently moved
    onto Registry endpoint policy.
    """
    def __init__(self, base_url, api_key, model, timeout=600, *, transport=None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.transport = transport

    def _open_response(self, request, method, route, timeout):
        if self.transport is None:
            return urllib.request.urlopen(request, timeout=timeout)
        headers = {name: value for name, value in request.header_items()}
        return self.transport.open_response(
            self.base_url, method, route, headers=headers,
            body=request.data, timeout=timeout,
        )

    def _redact_error(self, message):
        text = str(message)
        if self.api_key and self.api_key != "no-key":
            text = text.replace(str(self.api_key), "[REDACTED]")
        return text[:500]

    def list_models(self, *, timeout_seconds=None):
        request = urllib.request.Request(self.base_url + "/v1/models",
            headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"})
        try:
            with self._open_response(request, "GET", "/models", min(self.timeout, 10) if timeout_seconds is None else min(self.timeout, timeout_seconds, 10)) as response:
                status = getattr(response, "status", 200)
                if status >= 400:
                    raise ProviderHTTPError(status, "Model-list")
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise ProviderMalformedResponseError("Model-list response is malformed")
            return [item.get("id") for item in payload["data"] if isinstance(item, dict) and item.get("id")]
        except urllib.error.HTTPError as exc:
            # Provider bodies are untrusted and may echo credentials; discard by default.
            raise ProviderHTTPError(exc.code, "Model-list") from exc
        except TimeoutError as exc:
            if self.transport is None:
                raise ProviderError("Model-list request failed") from exc
            raise ProviderTimeoutError("Model-list request timed out") from exc
        except (urllib.error.URLError, OSError, http.client.HTTPException, json.JSONDecodeError) as exc:
            raise ProviderError("Model-list request failed") from exc
        except ProviderEndpointError as exc:
            if "timed out" in str(exc):
                raise ProviderTimeoutError("Model-list request timed out") from exc
            raise ProviderError("Model-list request failed endpoint policy") from exc

    def chat(self, messages, max_tokens=2048, temperature=0.2, on_token=None, tools=None, *, timeout_seconds=None):
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
            with self._open_response(request, "POST", "/chat/completions", self.timeout if timeout_seconds is None else min(self.timeout, timeout_seconds)) as response:
                status = getattr(response, "status", 200)
                if status >= 400:
                    raise ProviderHTTPError(status, "Chat completion")
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
                        if not isinstance(event["usage"], dict):
                            malformed_event = True
                            continue
                        usage = event["usage"]
                    choices = event.get("choices", [])
                    if choices is None:
                        choices = []
                    if not isinstance(choices, list):
                        malformed_event = True
                        continue
                    if not choices:
                        continue
                    choice = choices[0]
                    if not isinstance(choice, dict):
                        malformed_event = True
                        continue
                    if choice.get("finish_reason") is not None:
                        finish_reason = str(choice["finish_reason"])
                    delta = choice.get("delta") or {}
                    if not isinstance(delta, dict):
                        malformed_event = True
                        continue
                    calls = delta.get("tool_calls") or []
                    if not isinstance(calls, list):
                        malformed_event = True
                        continue
                    for call in calls:
                        if not isinstance(call, dict):
                            malformed_event = True
                            continue
                        index = call.get("index", 0)
                        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
                            malformed_event = True
                            continue
                        function = call.get("function") or {}
                        if not isinstance(function, dict):
                            malformed_event = True
                            continue
                        call_id = call.get("id")
                        call_type = call.get("type")
                        name_fragment = function.get("name", "")
                        argument_fragment = function.get("arguments", "")
                        if (
                            (call_id is not None and not isinstance(call_id, str))
                            or (call_type is not None and not isinstance(call_type, str))
                            or not isinstance(name_fragment, str)
                            or not isinstance(argument_fragment, str)
                        ):
                            malformed_event = True
                            continue
                        part = tool_call_parts.setdefault(index,{"id":"","type":"function","function":{"name":"","arguments":""}})
                        if call_id: part["id"] = call_id
                        if call_type: part["type"] = call_type
                        if name_fragment: part["function"]["name"] += name_fragment
                        if argument_fragment: part["function"]["arguments"] += argument_fragment
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
            raise ProviderHTTPError(exc.code, "Chat completion") from exc
        except TimeoutError as exc:
            if self.transport is None:
                raise ProviderError("Chat completion request failed") from exc
            raise ProviderTimeoutError("Chat completion request timed out") from exc
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            raise ProviderError("Chat completion request failed") from exc
        except ProviderEndpointError as exc:
            if "timed out" in str(exc):
                raise ProviderTimeoutError("Chat completion request timed out") from exc
            raise ProviderError("Chat completion endpoint policy failed") from exc
        final_safe_content = redactor.finish()
        if final_safe_content:
            pieces.append(final_safe_content)
            if on_token:
                on_token(final_safe_content)
        if not saw_event:
            raise ProviderError(f"Server returned no SSE data events (Content-Type: {content_type or 'unknown'})")
        if not valid_event or (malformed_event and self.transport is not None):
            raise ProviderMalformedResponseError(
                f"Server returned malformed SSE data (Content-Type: {content_type or 'unknown'})"
            )
        if not pieces and not tool_call_parts and finish_reason != "length":
            raise ProviderMalformedResponseError("Server returned an empty completion")
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
