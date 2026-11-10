"""Run: python test_writer.py   (no keys, no network: the AI provider is replaced by a fake)"""
import json
import os
import tempfile
from pathlib import Path

import llm
import manyreply as m
import writer

ENV_KEYS = ("LLM_PROVIDER", "LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
            "GEMINI_API_KEY", "OPENROUTER_API_KEY")


def clear_env():
    for k in ENV_KEYS:
        os.environ[k] = ""  # empty counts as unset, and stops .env from filling it in


# ---- reading the model's reply
assert llm.extract_json('{"a": 1}') == {"a": 1}
assert llm.extract_json('```json\n{"a": {"b": 2}}\n```') == {"a": {"b": 2}}
assert llm.extract_json('Sure! Here it is: {"a": 1} Hope that helps.') == {"a": 1}
for bad in ("no json here", '{"a": ', ""):
    try:
        llm.extract_json(bad)
        raise SystemExit(f"should have refused: {bad!r}")
    except ValueError:
        pass

# ---- choosing the provider: say exactly what is missing
clear_env()
try:
    llm.settings()
    raise SystemExit("no provider set must be an error")
except llm.LLMError as e:
    assert "setup" in str(e)
os.environ["OPENAI_API_KEY"] = "test-openai-key-123456"
assert llm.settings()[0] == "openai" and llm.settings()[2] == "gpt-4o-mini", "provider is guessed from the key that is set"
clear_env()
os.environ.update(LLM_PROVIDER="openrouter", OPENROUTER_API_KEY="test-openrouter-key-123456")
try:
    llm.settings()
    raise SystemExit("openrouter has no default model: it must ask for one")
except llm.LLMError as e:
    assert "LLM_MODEL" in str(e)
clear_env()
os.environ.update(LLM_PROVIDER="anthropic")
try:
    llm.settings()
    raise SystemExit("a missing key must be an error")
except llm.LLMError as e:
    assert "ANTHROPIC_API_KEY" in str(e)
os.environ.update(LLM_PROVIDER="nonsense")
try:
    llm.settings()
    raise SystemExit("an unknown provider must be an error")
except llm.LLMError:
    pass

# ---- what each provider is sent, and that a key only ever travels in a header
calls = []
llm._post = lambda url, body, headers, timeout=240: (calls.append((url, body, headers)), REPLY[0])[1]
KEY = "test-secret-key-0123456789"


def run(provider, reply, **env):
    clear_env()
    os.environ.update(LLM_PROVIDER=provider, **env)
    REPLY[:] = [reply]
    calls.clear()
    text = llm.complete("SYSTEM", "USER")
    url, body, headers = calls[0]
    assert KEY not in url, "a key must never be in a URL"
    return text, url, body, headers


REPLY = [None]
text, url, body, headers = run("anthropic", {"content": [{"type": "text", "text": "hi"}]}, ANTHROPIC_API_KEY=KEY)
assert text == "hi" and url == "https://api.anthropic.com/v1/messages" and headers["x-api-key"] == KEY
assert body["system"] == "SYSTEM" and body["messages"] == [{"role": "user", "content": "USER"}] and body["max_tokens"]
text, url, body, headers = run("openai", {"choices": [{"message": {"content": "yo"}}]}, OPENAI_API_KEY=KEY)
assert text == "yo" and url.endswith("/v1/chat/completions") and headers["Authorization"] == f"Bearer {KEY}"
assert body["messages"][0] == {"role": "system", "content": "SYSTEM"} and body["response_format"] == {"type": "json_object"}
text, url, body, headers = run("gemini", {"candidates": [{"content": {"parts": [{"text": "g"}, {"text": "h"}]}}]}, GEMINI_API_KEY=KEY)
assert text == "gh" and ":generateContent" in url and headers["x-goog-api-key"] == KEY
assert body["systemInstruction"]["parts"][0]["text"] == "SYSTEM"
text, url, body, headers = run("ollama", {"message": {"content": "local"}}, LLM_MODEL="llama-x")
assert text == "local" and url == "http://localhost:11434/api/chat" and body["model"] == "llama-x" and body["format"] == "json"
text, url, body, headers = run("openrouter", {"choices": [{"message": {"content": "r"}}]}, OPENROUTER_API_KEY=KEY, LLM_MODEL="x/y")
assert url == "https://openrouter.ai/api/v1/chat/completions" and "response_format" not in body
text, url, body, headers = run("openai-compatible", {"choices": [{"message": {"content": "c"}}]}, LLM_API_KEY=KEY,
                               LLM_MODEL="z", LLM_BASE_URL="https://my.host/v1/")
assert url == "https://my.host/v1/chat/completions"
try:
    run("anthropic", {"content": []}, ANTHROPIC_API_KEY=KEY)
    raise SystemExit("an empty answer must be an error")
except llm.LLMError:
    pass

# ---- writing a post, in a scratch copy of the project
tmp = Path(tempfile.mkdtemp())
root = tmp / "repo"
(root / "data").mkdir(parents=True)
(root / "posts").mkdir()
m.ROOT, m.DATA = root, root / "data"
m.LEDGER, m.CONFIG, m.CANDIDATES = m.DATA / "posts.json", m.DATA / "topics.json", m.DATA / "candidates.json"
m.QUEUE, m.EDITS = m.DATA / "queue.json", m.DATA / "dashboard.json"
m.save(m.CONFIG, {"handle": "demo", "timezone": "America/Toronto", "post_times": ["09:00"], "services": [], "topics": [],
                  "hashtags": ["#AITools", "#OpenSource"]})
m.save(m.LEDGER, [{"keyword": "TAKEN", "repo": "https://github.com/old/one", "status": "live", "dir": "posts/x",
                   "date": "2026-11-01T13:00:00+00:00", "source": "search", "title": "One"}])
m.save(m.QUEUE, {"telegram_offset": 0, "items": []})
m.save(m.EDITS, {"topics": [], "requests": []})
m.save(m.CANDIDATES, {"candidates": [
    {"name": "old/one", "url": "https://github.com/old/one", "stars": 50000, "description": "already posted"},
    {"name": "acme/tool", "url": "https://github.com/acme/tool", "stars": 9400, "description": "does a thing"}], "stars": {}})


def good(keyword="RAPID", **extra):
    cap = (f"Comment {keyword} and I'll DM you the repo for the tool that saved me an hour. "
           "Everyone loses time to this, about 40 minutes a week. Tool fixes it. You install it with one command and it "
           "runs. It reads your files and fixes them. The README shows a real before and after. It is MIT licensed. "
           f"Comment {keyword} and I'll send it straight to your DMs. Follow @demo so the DM actually reaches you, and so "
           "you catch whatever I share next. Send this to a friend who codes.\n\n#AITools #OpenSource #Dev")
    return {"keyword": keyword, "title": "Tool: fix it in one command",
            "slides": [{"title": f"Slide {i} — *idea*", "body": "- one\n- two"} for i in range(1, 6)],
            "recap": ["What it is", "Why it matters", "How to start"], "caption": cap, "hook": "stars",
            "send_to": "a friend who codes", "why": "popular", "badge": "★ FAKE stars", "style": "ember", **extra}


replies = []
asked = []
writer.read_up = lambda url: "README of the tool"
llm.describe = lambda: "fake / model"


def fake_complete(system, user, max_tokens=4096):
    asked.append((system, user))
    return replies.pop(0)


llm.complete = fake_complete
cwd = os.getcwd()
try:
    # the first try breaks the rules (a keyword that was used before); the second is good
    replies[:] = [json.dumps(good("TAKEN")), "```json\n" + json.dumps(good("RAPID")) + "\n```"]
    folder = writer.make_post()
    assert len(asked) == 2 and "TAKEN" in asked[1][1] and "rejected" in asked[1][1], "the AI is told what was wrong"
    assert "KEYWORDS ALREADY USED" in asked[0][1] and "TAKEN" in asked[0][1]
    assert "@demo" in asked[0][0] and "#AITools #OpenSource" in asked[0][0] and "@HANDLE@" not in asked[0][0]
    assert "<<<" in asked[0][1] and "untrusted" in asked[0][0], "internet text is marked as data"
    assert folder.name.endswith("-acme-tool"), "the posted repo is skipped and the next candidate is used"
    c = json.loads((folder / "content.json").read_text(encoding="utf-8"))
    assert c["repo"] == "https://github.com/acme/tool" and c["keyword"] == "RAPID"
    assert c["badge"] == "★ 9.4K stars on GitHub", "the badge comes from the real star count, not the model"
    assert "style" not in c and all("—" not in s["title"] for s in c["slides"]), "model-set fields are dropped, em dashes removed"
    m.validate(c, m.load(m.LEDGER, []))

    # under 5,000 stars there is no badge at all
    m.save(m.CANDIDATES, {"candidates": [{"name": "small/thing", "url": "https://github.com/small/thing", "stars": 800}], "stars": {}})
    replies[:] = [json.dumps(good("SMALLY", badge="★ 800 stars"))]
    c = json.loads((writer.make_post() / "content.json").read_text(encoding="utf-8"))
    assert "badge" not in c

    # three bad answers in a row: it stops, and says why, instead of posting something broken
    replies[:] = [json.dumps(good("TAKEN"))] * 3
    try:
        writer.make_post("https://github.com/other/repo")
        raise SystemExit("three bad tries must stop")
    except SystemExit as e:
        assert "3 tries" in str(e.code)
finally:
    os.chdir(cwd)

# ---- the affiliate link: plain and undisclosed until one is set, disclosed everywhere once it is
import affiliate
_shipped = affiliate.ZERNIO_AFFILIATE_URL
affiliate.ZERNIO_AFFILIATE_URL = ""
assert affiliate.signup_url() == "https://zernio.com" and not affiliate.is_affiliate()
assert not any("disclosure" in line.lower() for line in affiliate.signup_lines()), "nothing to disclose yet"
affiliate.ZERNIO_AFFILIATE_URL = "https://zernio.com/?via=maker"
assert affiliate.signup_url().endswith("via=maker")
assert any(line.startswith("Affiliate disclosure") for line in affiliate.signup_lines())
affiliate.ZERNIO_AFFILIATE_URL = _shipped
if affiliate.is_affiliate():  # a referral link that is shipped must be disclosed where people are told to sign up
    assert "referral" in (Path(__file__).parent / "README.md").read_text(encoding="utf-8").lower(), "disclose it in the README"
assert "affiliate" not in writer.SYSTEM.lower(), "the link never reaches a post prompt"

print("ok")
