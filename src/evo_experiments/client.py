import json
import time
import urllib.error
import urllib.request

class ModelRequestError(RuntimeError):
    pass

def _request(url, api_key):
    return urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}",
        "Accept": "application/json"})

def list_models(*, base_url, api_key, timeout):
    request = _request(f"{base_url}/v1/models", api_key)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return [item.get("id") for item in payload.get("data", []) if item.get("id")]
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise ModelRequestError(f"HTTP {exc.code} from /v1/models: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise ModelRequestError(str(exc)) from exc

def stream_chat_completion(*, base_url, api_key, model, system_prompt, prompt,
                           max_tokens, temperature, timeout):
    payload = {"model": model, "messages": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}],
        "stream": True, "stream_options": {"include_usage": True},
        "max_tokens": max_tokens, "temperature": temperature}
    request = urllib.request.Request(f"{base_url}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST")
    started = time.perf_counter()
    first_content_at, usage, pieces = None, {}, []
    content_type, saw_event = "", False
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            for raw in response:
                line = raw.decode("utf-8", errors="replace").strip()
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
                if choices:
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if isinstance(content, list):
                        content = "".join(part.get("text", "") for part in content
                                          if isinstance(part, dict))
                    if isinstance(content, str) and content:
                        if first_content_at is None:
                            first_content_at = time.perf_counter()
                        pieces.append(content)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise ModelRequestError(f"HTTP {exc.code} from chat completions: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ModelRequestError(str(exc)) from exc
    if not saw_event:
        raise ModelRequestError(f"Server returned no SSE data events (Content-Type: {content_type or 'unknown'})")
    finished = time.perf_counter()
    elapsed = finished - started
    completion_tokens, prompt_tokens = usage.get("completion_tokens"), usage.get("prompt_tokens")
    generation_window = finished - first_content_at if first_content_at else None
    rate = (float(completion_tokens) / generation_window
            if completion_tokens is not None and generation_window and generation_window > 0 else None)
    return {"response": "".join(pieces), "elapsed_seconds": elapsed,
        "time_to_first_token_seconds": first_content_at - started if first_content_at else None,
        "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
        "tokens_per_second": rate}
