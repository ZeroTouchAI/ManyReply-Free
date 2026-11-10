"""Provider-neutral text generation for ManyReply. Standard library only.

You bring your own AI account; nothing here is shared with anyone else. Set LLM_PROVIDER and the matching key in .env
(or as repository secrets on GitHub):

  LLM_PROVIDER      anthropic | openai | gemini | openrouter | ollama | openai-compatible
  ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY / OPENROUTER_API_KEY   (or LLM_API_KEY for any of them)
  LLM_MODEL         the model name. Defaults exist for anthropic, openai and gemini and can go out of date: if a
                    provider says the model is unknown, set LLM_MODEL to a current one from its docs.
  LLM_BASE_URL      ollama (default http://localhost:11434) and openai-compatible servers

Without LLM_PROVIDER the provider is guessed from whichever key is set.
"""
import json
import os
import re
import urllib.error
import urllib.request

PROVIDERS = {
    "anthropic": {"key": "ANTHROPIC_API_KEY", "model": "claude-haiku-5-5"},
    "openai": {"key": "OPENAI_API_KEY", "model": "gpt-4o-mini"},
    "gemini": {"key": "GEMINI_API_KEY", "model": "gemini-2.5-flash"},
    "openrouter": {"key": "OPENROUTER_API_KEY", "model": None},
    "ollama": {"key": None, "model": None},
    "openai-compatible": {"key": "LLM_API_KEY", "model": None},
}


class LLMError(RuntimeError):
    pass


def getenv(name):
    """The same lookup as the rest of ManyReply: the environment first, then .env."""
    try:
        import manyreply
        return manyreply.env(name)
    except ImportError:
        return os.environ.get(name)


def settings():
    """(provider, key, model, base_url), or an LLMError that says exactly what to set."""
    provider = (getenv("LLM_PROVIDER") or "").strip().lower()
    if not provider:
        provider = next((p for p, s in PROVIDERS.items() if s["key"] and getenv(s["key"])), "")
    if not provider:
        raise LLMError("no AI provider set: put LLM_PROVIDER (anthropic, openai, gemini, openrouter, ollama) and its key "
                       "in .env, or run: python manyreply.py setup")
    if provider not in PROVIDERS:
        raise LLMError(f"LLM_PROVIDER={provider!r} is not one of: {', '.join(PROVIDERS)}")
    spec = PROVIDERS[provider]
    key = (spec["key"] and getenv(spec["key"])) or getenv("LLM_API_KEY") or ""
    if spec["key"] and not key:
        raise LLMError(f"{provider} needs {spec['key']} (or LLM_API_KEY) in .env")
    model = getenv("LLM_MODEL") or spec["model"]
    if not model:
        raise LLMError(f"{provider} needs LLM_MODEL (the model's name, from the provider's own docs)")
    base = (getenv("LLM_BASE_URL") or "").rstrip("/")
    if provider == "ollama":
        base = base or "http://localhost:11434"
    if provider == "openai-compatible" and not base:
        raise LLMError("openai-compatible needs LLM_BASE_URL (for example https://host/v1)")
    return provider, key, model, base


def describe():
    provider, key, model, base = settings()
    return f"{provider} / {model}" + (" (key set)" if key else "")


def _post(url, body, headers, timeout=240):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "manyreply/1", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.loads(res.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        for secret in (v for v in headers.values() if len(v) > 12):  # never let a key reach a log
            detail = detail.replace(secret.removeprefix("Bearer "), "***")
        raise LLMError(f"{url.split('?')[0]} -> {e.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise LLMError(f"could not reach {url.split('?')[0]}: {e}") from None


def complete(system, user, max_tokens=4096):
    """One request, one text answer."""
    provider, key, model, base = settings()
    if provider == "anthropic":
        out = _post("https://api.anthropic.com/v1/messages",
                    {"model": model, "max_tokens": max_tokens, "system": system,
                     "messages": [{"role": "user", "content": user}]},
                    {"x-api-key": key, "anthropic-version": "2023-06-01"})
        text = "".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text")
    elif provider == "gemini":
        out = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    {"systemInstruction": {"parts": [{"text": system}]},
                     "contents": [{"role": "user", "parts": [{"text": user}]}],
                     "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": max_tokens}},
                    {"x-goog-api-key": key})
        parts = ((out.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
    elif provider == "ollama":
        out = _post(f"{base}/api/chat",
                    {"model": model, "stream": False, "format": "json",
                     "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}, {})
        text = (out.get("message") or {}).get("content", "")
    else:  # openai, openrouter, openai-compatible all speak the same chat-completions shape
        url = {"openai": "https://api.openai.com/v1", "openrouter": "https://openrouter.ai/api/v1"}.get(provider, base)
        body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if provider == "openai":
            body["response_format"] = {"type": "json_object"}
        out = _post(f"{url}/chat/completions", body, {"Authorization": f"Bearer {key}"} if key else {})
        text = ((out.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    if not text.strip():
        raise LLMError(f"{provider} returned no text")
    return text


def extract_json(text):
    """The first JSON object in a reply, even when the model wrapped it in a code fence or added a sentence."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("the reply had no JSON object in it")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"the reply was not valid JSON: {e}") from None
