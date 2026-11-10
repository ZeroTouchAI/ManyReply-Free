"""Run: python test_manyreply.py"""
from datetime import datetime, timedelta, timezone

from manyreply import versus_typical, STYLES, clean_link, fmt, growth_scores, queue_add, score, slide_html, validate, waiting

good = {
    "repo": "https://github.com/owner/name", "keyword": "AGENT",
    "slides": [{"title": f"Slide {i}", "body": "- a point"} for i in range(4)],
    "caption": "Comment AGENT and I'll DM you the repo.\n\nBlurb.\n\nComment AGENT and follow @me.",
}
ledger = [{"repo": "https://github.com/Old/Repo/", "keyword": "TAKEN", "dir": "posts/old"}]


def rejected(**change):
    try:
        validate({**good, **change}, ledger)
    except ValueError as e:
        return str(e)
    raise AssertionError(f"should have been rejected: {change}")


validate(good, ledger)
assert "already used" in rejected(keyword="TAKEN")
assert "already posted" in rejected(repo="https://github.com/old/repo")
assert "capital letters" in rejected(keyword="two words")
assert "4-8 slides" in rejected(slides=good["slides"][:3])
assert "must open with" in rejected(caption="Blurb first. Comment AGENT. Comment AGENT.")
assert "again at the end" in rejected(caption="Comment AGENT and I'll DM you the repo. Blurb.")
assert "must not contain the link" in rejected(caption=good["caption"] + " https://github.com/owner/name")
validate({**good, "keyword": "TAKEN", "caption": good["caption"].replace("AGENT", "TAKEN")}, ledger, own=ledger[0])  # re-running its own post is fine

today = datetime(2026, 10, 1, tzinfo=timezone.utc)
rising, _ = score(5_000, today - timedelta(days=30), 1, today)
giant, _ = score(50_000, today - timedelta(days=3 * 365), 1, today)
assert rising > giant, "a repo exploding this month should outrank an old giant"
assert score(5_000, today - timedelta(days=30), 1.5, today)[0] > rising, "topic weight lifts the score"

assert fmt("a *b* <c>") == "a <em>b</em> &lt;c&gt;"
for style in STYLES:
    assert ">03 / 05<" in slide_html({"title": "T"}, 2, 5, "me", style=style)
assert "Comment AGENT for the link" in slide_html({"title": "T"}, 0, 5, "me", keyword="AGENT")
q = {"telegram_offset": 0, "items": []}
assert queue_add(q, ledger, "look https://github.com/a/b.git and https://github.com/Old/Repo.", "dashboard") == [
    "https://github.com/a/b: waiting", "https://github.com/Old/Repo: already posted"]
assert queue_add(q, ledger, "again https://github.com/A/B", "telegram") == ["https://github.com/A/B: already in the queue"]
queue_add(q, ledger, "https://github.com/c/d", "telegram")
assert [i["url"] for i in waiting(q)] == ["https://github.com/c/d", "https://github.com/a/b"], "Telegram goes first"
assert clean_link("notion.so/page?fbclid=x&mcp_token=y&utm_source=z&pli=1#top") == "https://notion.so/page?pli=1#top"
assert clean_link("https://github.com/a/b?fbclid=x") == "https://github.com/a/b"
assert growth_scores([{"reach": 100, "follows": 2, "saves": 4, "shares": 1, "comments": 5},
                      {"reach": 100, "follows": 1, "saves": 0, "shares": 0, "comments": 0}, {}]) == [10.0, 1.9, 0.0]
# the DM funnel: every step is reachable from the trigger, and every edge joins two real steps
import json as _json
import manyreply as m
_nodes, _edges = m.funnel_graph(_json.loads((m.ROOT / "data" / "topics.json").read_text(encoding="utf-8")))
_ids = {n["id"] for n in _nodes}
assert len(_ids) == len(_nodes) and all(e["source"] in _ids and e["target"] in _ids for e in _edges)
_seen, _todo = set(), ["t"]
while _todo:
    _n = _todo.pop()
    if _n not in _seen:
        _seen.add(_n)
        _todo += [e["target"] for e in _edges if e["source"] == _n]
assert _seen == _ids, _ids - _seen
import re as _re
_word = next(r["value"] for n in _nodes if n["id"] == "mine" for r in n["config"]["rules"] if r["id"] == "word")
assert _re.match(_word, "TASTE") and not _re.match(_word, "hi") and not _re.match(_word, "I need an app")
assert versus_typical(60, [{"reach": 10}, {"reach": 20}, {"reach": 30}, {}]) == 3.0 and versus_typical(5, []) == 0
try:
    validate({**good, "recap": ["only one line"]}, ledger)
    raise SystemExit("a one-line recap should be refused")
except ValueError:
    pass
validate({**good, "recap": ["Reads your brief", "Three dials", "One command"]}, ledger)
# crop_png keeps the top rows of a PNG and the result is still a valid PNG of the new height
import struct as _st, tempfile as _tf, zlib as _z
from pathlib import Path as _P
def _png(w, h):
    raw = b"".join(b"\x00" + bytes([y % 256, 0, 0]) * w for y in range(h))
    ch = lambda k, b: _st.pack(">I", len(b)) + k + b + _st.pack(">I", _z.crc32(k + b))
    return b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", _st.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + ch(b"IDAT", _z.compress(raw)) + ch(b"IEND", b"")
with _tf.TemporaryDirectory() as _d:
    _f = _P(_d) / "a.png"
    _f.write_bytes(_png(4, 10))
    m.crop_png(_f, 6)
    assert _f.read_bytes() == _png(4, 6)
# the repo finder prefers the site that was named, then the exact name, then stars
_r = [{"name": "big", "homepage": "", "stargazers_count": 900}, {"name": "NewPipe", "homepage": "https://newpipe.net", "stargazers_count": 5},
      {"name": "newpipe", "homepage": "", "stargazers_count": 50}]
assert m.rank_repos(_r, "newpipe.net")[0]["homepage"] == "https://newpipe.net"
assert m.rank_repos(_r, "NewPipe")[0]["name"] == "newpipe"
assert m.rank_repos(_r, "something else")[0]["name"] == "big"

# the owner's apps: one every 3 weeks, weekdays only, never-posted first, none again within 90 days
_apps, _saved = [{"url": "https://github.com/me/one"}, {"url": "https://github.com/me/two"}], (m.my_apps, m.local_now)
m.my_apps, _mon = (lambda: _apps), datetime(2026, 10, 19, 10, tzinfo=timezone.utc)
m.local_now = lambda: _mon
_post = lambda repo, days: {"dir": "x", "status": "live", "repo": repo, "date": (_mon - timedelta(days=days)).isoformat(), "source": "app"}
assert m.app_due([])["url"].endswith("one")
assert m.app_due([_post("https://github.com/me/one", 30)])["url"].endswith("two")
assert m.app_due([_post("https://github.com/me/one", 10)]) is None
assert m.app_due([_post("https://github.com/me/one", 40), _post("https://github.com/me/two", 25)]) is None
assert m.app_due([_post("https://github.com/me/one", 95), _post("https://github.com/me/two", 25)])["url"].endswith("one")
m.local_now = lambda: datetime(2026, 10, 18, 10, tzinfo=timezone.utc)  # a Sunday
assert m.app_due([]) is None
# a website-only app is allowed as the post's "repo"; a random website is not
m.my_apps = lambda: [{"url": "", "site": "https://mysite.com"}]
m.local_now = lambda: _mon
assert m.app_due([])["site"] == "https://mysite.com"
validate({**good, "repo": "https://mysite.com"}, ledger)
try:
    validate({**good, "repo": "https://other.com"}, ledger)
    raise AssertionError("a website that is not one of the owner's apps should be refused")
except ValueError:
    pass
m.my_apps, m.local_now = _saved

# a website request from the dashboard is queued as itself, and may then be posted as the post's "repo"
_q = {"items": []}
assert "a website" in queue_add(_q, [], "https://mysite.com/", "dashboard", website=True)[0]
assert _q["items"][0] == {**_q["items"][0], "url": "https://mysite.com", "status": "waiting", "website": True}
assert "already in the queue" in queue_add(_q, [], "https://mysite.com", "dashboard", website=True)[0]
_saved_q = m.load_queue
m.load_queue = lambda: _q
validate({**good, "repo": "https://mysite.com"}, ledger)
m.load_queue = _saved_q

# favorites: the owner's starred repos are posted more often, behind requests and apps, and may come back after a wait
_old_fav, _old_apps, _old_now = m.my_favorites, m.my_apps, m.local_now
m.my_apps, m.local_now = lambda: [], m.now
m.my_favorites = lambda: ["https://github.com/fav/one", "https://github.com/Fav/One/", "https://github.com/fav/two"]
assert m.is_favorite("https://github.com/FAV/two") and not m.is_favorite("https://github.com/x/y") and not m.is_favorite("")
_day = lambda n: (m.now() - timedelta(days=n)).isoformat(timespec="seconds")
_post = lambda repo, days, source="search": {"repo": repo, "dir": "posts/x", "status": "live", "date": _day(days), "source": source}
_none = {"items": []}
assert m.fav_due([], _none) == "https://github.com/fav/one", "a favorite never posted goes first (and the duplicate is ignored)"
assert m.fav_due([_post("https://github.com/fav/one", 40)], _none) == "https://github.com/fav/two", "never-posted before posted"
assert m.fav_due([_post("https://github.com/fav/one", 40), _post("https://github.com/fav/two", 50)], _none) == "https://github.com/fav/two", "the one posted longest ago"
assert m.fav_due([_post("https://github.com/fav/one", 10), _post("https://github.com/fav/two", 12)], _none) is None, "30 days must pass first"
assert m.fav_due([_post("https://github.com/fav/one", 2, "favorite")], _none) is None, "one favorite every few days, not back to back"
assert m.fav_due([_post("https://github.com/fav/one", 9, "favorite")], _none) == "https://github.com/fav/two"
_held = {"items": [{"url": "https://github.com/fav/one", "status": "waiting"}, {"url": "https://github.com/fav/two", "status": "skipped"}]}
assert m.fav_due([], _held) == "https://github.com/fav/one", "a waiting favorite counts as never posted, a skipped one never goes"
m.my_apps = lambda: [{"url": "https://github.com/fav/one", "site": "", "pitch": ""}]
assert m.fav_due([], _none) == "https://github.com/fav/two", "an app keeps its own turn"
m.my_apps = lambda: []
# a waiting favorite goes ahead of other dashboard requests, but never ahead of Telegram
_wq = {"items": [{"url": "https://github.com/plain/a", "source": "dashboard", "added": "2026-10-01", "status": "waiting"},
                 {"url": "https://github.com/fav/two", "source": "dashboard", "added": "2026-10-05", "status": "waiting"},
                 {"url": "https://github.com/tg/b", "source": "telegram", "added": "2026-10-09", "status": "waiting"}]}
assert [i["url"].split("/")[-1] for i in waiting(_wq)] == ["b", "two", "a"]
# a favorite may be posted again after 30 days, a plain repo never
_old_post = {"repo": "https://github.com/fav/two", "keyword": "OLDONE", "dir": "posts/old", "date": _day(40)}
_new_post = {**_old_post, "date": _day(5)}
validate(good | {"repo": "https://github.com/fav/two"}, [_old_post])
try:
    validate(good | {"repo": "https://github.com/fav/two"}, [_new_post])
    raise SystemExit("a favorite posted 5 days ago must not be posted again")
except ValueError as _err:
    assert "favorite can come back 30 days" in str(_err)
try:
    validate(good | {"repo": "https://github.com/plain/z"}, [{**_old_post, "repo": "https://github.com/plain/z"}])
    raise SystemExit("a repo that is not a favorite must never be posted twice")
except ValueError as _err:
    assert "already posted" in str(_err) and "favorite" not in str(_err)
# an old post (from before ManyReply) can be starred and brought back: it counts as last posted, and its page may be a website
m.my_favorites, m.my_apps, m.local_now = (lambda: ["https://github.com/old/gem", "https://www.notion.so/Cheat-Sheet-abc"]), (lambda: []), m.now
_legacy = lambda repo, days: {"repo": repo, "keyword": "OLDWORD", "status": "legacy", "date": _day(days)}
assert m.fav_due([_legacy("https://github.com/old/gem", 60), _legacy("https://www.notion.so/Cheat-Sheet-abc", 5)], _none) == "https://github.com/old/gem"
assert m.fav_due([_legacy("https://github.com/old/gem", 10), _legacy("https://www.notion.so/Cheat-Sheet-abc", 5)], _none) is None, "30 days since the old post"
_site = good | {"repo": "https://www.notion.so/Cheat-Sheet-abc"}
validate(_site, [_legacy("https://www.notion.so/Cheat-Sheet-abc", 60)])
try:
    validate(_site, [_legacy("https://www.notion.so/Cheat-Sheet-abc", 5)])
    raise SystemExit("an old post under 30 days must wait")
except ValueError as _err:
    assert "favorite can come back" in str(_err)
m.my_favorites = lambda: []
try:
    validate(_site, [])
    raise SystemExit("a website that is not a favorite, app or queued website must still be refused")
except ValueError as _err:
    assert "repo must be" in str(_err)
# GitHub star counts beside the repos: compact numbers, best-effort lookup that never breaks a run
assert [m.short_count(n) for n in (None, 0, 950, 1000, 12345, 294000, 1500000)] == ["", "0", "950", "1K", "12.3K", "294K", "1.5M"]
_cands = {"stars": {"https://github.com/a/b": 1200}, "candidates": [{"url": "https://github.com/c/d", "stars": 77}, {"url": "https://github.com/e/f", "stars": 0}]}
assert m.gh_stars("https://github.com/A/B/", _cands) == 1200 and m.gh_stars("https://github.com/c/d", _cands) == 77
assert m.gh_stars("https://github.com/e/f", _cands) is None and m.gh_stars("https://github.com/x/y", {}) is None
_old_http, _calls = m.http, []
def _fake(method, url, body=None, headers=None, raw=None, timeout=120):
    _calls.append((url, timeout))
    if url.endswith("/gone/x"):
        raise RuntimeError("GET https://api.github.com/repos/gone/x -> 404: Not Found")
    if url.endswith("/limit/y"):
        raise RuntimeError("GET https://api.github.com/repos/limit/y -> 403: rate limit")
    return {"stargazers_count": 4321}
m.http = _fake
assert m.fetch_stars(["https://github.com/a/b", "https://github.com/gone/x", "https://github.com/c/d.git"]) == \
    {m.norm("https://github.com/a/b"): 4321, m.norm("https://github.com/c/d.git"): 4321}, "a 404 is skipped, the rest are counted"
_calls.clear()
assert m.fetch_stars(["https://github.com/limit/y", "https://github.com/a/b"]) == {} and len(_calls) == 1, "stops at the first real failure"
def _closed(*a, **k):
    raise OSError("network is closed")
m.http = _closed
assert m.fetch_stars(["https://github.com/a/b"]) == {}, "a closed network is not an error"
m.http = _old_http
m.my_favorites, m.my_apps, m.local_now = _old_fav, _old_apps, _old_now
# the follow gate asks a non-follower for two taps: "Follow me" (opens the profile), then "I'm following"
_gate = m.dm_fields("https://github.com/a/b")["followGate"]
assert 0 < len(_gate["profileButtonLabel"]) <= 20 and 0 < len(_gate["buttonLabel"]) <= 20, "Zernio allows 20 characters"
assert len(_gate["message"]) <= 640 and len(_gate["notFollowingMessage"]) <= 640, "Meta's cap for a message with buttons"
assert "Follow me" in _gate["message"] and "I'm following" in _gate["message"] and "Follow me" in _gate["notFollowingMessage"]
# a changed gate is pushed to the automations already live, once; nothing is remembered if Zernio took none of it
import pathlib as _pl, tempfile as _tf
_tmp = _pl.Path(_tf.mkdtemp())
_o = (m.DM_WORDING, m.apply_dm_wording, m.dm_fields)
m.DM_WORDING, _runs = _tmp / "wording.json", []
m.apply_dm_wording = lambda soft=False: (_runs.append(soft) or (3, 0))
m.refresh_gate_if_changed()
assert _runs == [True] and m.load(m.DM_WORDING)["followGate"] == m.gate_version(), "first run: update all, soft, and remember"
m.refresh_gate_if_changed()
assert _runs == [True], "the same wording is never pushed twice"
m.dm_fields = lambda url: {**_o[2](url), "followGate": {**_o[2](url)["followGate"], "profileButtonLabel": "Follow"}}
m.refresh_gate_if_changed()
assert len(_runs) == 2 and m.gate_version() == m.load(m.DM_WORDING)["followGate"], "new wording is pushed again"
m.dm_fields = _o[2]
m.DM_WORDING = _tmp / "down.json"
m.apply_dm_wording = lambda soft=False: (0, 5)
m.refresh_gate_if_changed()
assert not m.DM_WORDING.exists(), "Zernio took nothing: try again at the next run"
m.apply_dm_wording = lambda soft=False: (0, 0)
m.refresh_gate_if_changed()
assert m.DM_WORDING.exists(), "nothing to update is also done"
m.DM_WORDING, m.apply_dm_wording, m.dm_fields = _o
# one automation Zernio refuses must not stop the rest (soft), but a plain refresh-dms still stops on it
_oz, _ol, _os, _calls = m.zernio, m.LEDGER, m.time.sleep, []
m.LEDGER = _tmp / "ledger.json"
m.save(m.LEDGER, [{"automation_id": "A1", "keyword": "ONE", "repo": "https://github.com/a/b", "story": {"automation_id": "S1"}},
                  {"automation_id": "A2", "keyword": "TWO", "repo": "https://github.com/c/d"}])
def _zern(method, path, body=None, **headers):
    _calls.append((path.rsplit("/", 1)[-1], body.get("followGate", {}).get("profileButtonLabel")))
    if path.endswith("/S1"):
        raise RuntimeError("PATCH .../S1 -> 404: not found")
    return {}
m.zernio, m.time.sleep = _zern, lambda s: None
assert m.apply_dm_wording(soft=True) == (2, 1) and [c[0] for c in _calls] == ["A1", "S1", "A2"]
assert all(c[1] == m.FOLLOW_BUTTON for c in _calls), "every automation gets the Follow me button"
_calls.clear()
try:
    m.apply_dm_wording()
    raise SystemExit("a plain refresh must stop on a refused automation")
except RuntimeError:
    pass
m.zernio, m.LEDGER, m.time.sleep = _oz, _ol, _os
# a missed day: nothing posted, nothing recorded; the bar and the retry work it out from the posts that exist
from datetime import date as _d
_days = {_d(2026, 11, 2), _d(2026, 11, 3)}
assert m.missed_days(_days, _d(2026, 11, 4), False) == [], "today is not missed before its last posting time"
assert m.missed_days(_days, _d(2026, 11, 4), True) == [_d(2026, 11, 4)], "today is missed once its last slot has passed"
assert m.missed_days(_days, _d(2026, 11, 6), False) == [_d(2026, 11, 4), _d(2026, 11, 5)], "three days of silence is two missed days"
assert m.missed_days({_d(2026, 11, 7)}, _d(2026, 11, 6), True) == [], "a post booked ahead is not a gap"
assert m.missed_days(_days | {_d(2026, 11, 6)}, _d(2026, 11, 6), False) == [], "the retry going live clears the bar"
assert m.missed_days(set(), _d(2026, 11, 6), True) == [], "a brand new account has nothing to miss"
assert len(m.missed_days({_d(2026, 1, 1)}, _d(2026, 11, 6), True)) == 15, "looks back at most 14 days plus today"
assert m.past_last_slot({"post_times": ["10:00", "20:30"]}, datetime(2026, 11, 4, 20, 30)) is True
assert m.past_last_slot({"post_times": ["10:00", "20:30"]}, datetime(2026, 11, 4, 20, 29)) is False
assert m.past_last_slot({}, datetime(2026, 11, 4, 23, 0)) is False
# a half-finished post (content.json written, never published) is found, a published one is not
_root = m.ROOT
m.ROOT = _tmp / "repo"
(m.ROOT / "posts" / "2026-11-04-half").mkdir(parents=True)
(m.ROOT / "posts" / "2026-11-04-half" / "content.json").write_text("{}")
(m.ROOT / "posts" / "2026-11-03-done").mkdir(parents=True)
(m.ROOT / "posts" / "2026-11-03-done" / "content.json").write_text("{}")
assert m.unfinished_drafts([{"dir": "posts/2026-11-03-done"}]) == ["posts/2026-11-04-half"]
assert m.unfinished_drafts([{"dir": "posts/2026-11-03-done"}, {"dir": "posts/2026-11-04-half"}]) == []
m.ROOT = _root
# the touch base after a link: inside Instagram's 24 hours, never "a couple of days later"
import copy as _copy
_cfg = m.load(m.CONFIG)
_cfg["funnel"]["checkin"]["enabled"] = True  # off in the shipped config; the checks below are about its shape
def _graph(**change):
    c = _copy.deepcopy(_cfg); c["funnel"]["checkin"] = {**c["funnel"]["checkin"], **change}
    return m.funnel_graph(c)
_nodes, _edges = _graph()
_ids = [x["id"] for x in _nodes]
assert len(_ids) == len(set(_ids)), "node ids are unique"
assert not [x for x in _edges if x["source"] not in _ids or x["target"] not in _ids], "every edge points at a real step"
_by = {x["id"]: x for x in _nodes}
assert _by["cwait"]["config"]["timeoutMinutes"] == 20 * 60 < 24 * 60, "the check-in goes out inside the 24 hour window"
assert {x["target"] for x in _edges if x["source"].startswith("send")} == {"cwait"}, "every sent link leads into the check-in"
assert {(x["sourceHandle"], x["target"]) for x in _edges if x["source"] == "cwait"} == {("reply", "cbusy"), ("timeout", "ctag")}
assert ("cbusy", "human") in {(x["source"], x["target"]) for x in _edges}, "someone who writes back is handed to the owner"
assert all(len(q["title"]) <= 20 for q in _by["cask"]["config"]["quickReplies"])
assert "cwait" not in {x["id"] for x in _graph(enabled=False)[0]} and \
       {x["target"] for x in _graph(enabled=False)[1] if x["source"].startswith("send")} == {"done"}, "off means the old funnel"
for bad_hours in (23, 24, 48, 0):
    try:
        _graph(hours=bad_hours); raise SystemExit(f"{bad_hours}h must be refused: past Instagram's window")
    except ValueError as err:
        assert "24 hours" in str(err)
try:
    _graph(yes_tap="a tap that is far too long to fit"); raise SystemExit("long taps must be refused")
except ValueError:
    pass
# applied once, only to a funnel that already exists, and the remembered gate survives
_o = (m.DM_WORDING, m.zernio, m.funnel)
m.DM_WORDING = _tmp / "wording2.json"
m.save(m.DM_WORDING, {"followGate": "keepme"})
_log = []
m.funnel = lambda platform="instagram": _log.append("funnel")
m.zernio = lambda method, path, body=None, **h: {"workflows": []}
m.refresh_funnel_if_changed()
assert _log == [] and "funnel" not in m.load(m.DM_WORDING), "no funnel on Zernio yet: nothing is created behind the owner's back"
m.zernio = lambda method, path, body=None, **h: {"workflows": [{"name": "ManyReply DM funnel (instagram)", "id": "W", "status": "active"}]}
m.refresh_funnel_if_changed()
assert _log == ["funnel"] and m.load(m.DM_WORDING) == {"followGate": "keepme", "funnel": m.funnel_version()}
m.refresh_funnel_if_changed()
assert _log == ["funnel"], "an unchanged funnel is not pushed again"
m.save(m.DM_WORDING, {"followGate": "keepme"})
def _refused():
    raise RuntimeError("PATCH -> 400")
m.funnel = lambda platform="instagram": _refused()
try:
    m.refresh_funnel_if_changed(); raise SystemExit("a refused funnel must surface (sync prints it)")
except RuntimeError:
    assert "funnel" not in m.load(m.DM_WORDING), "a refused update is retried next run"
m.DM_WORDING, m.zernio, m.funnel = _o
# the dashboard: GitHub stars and sort arrows on the older words and the repositories
_page = (m.ROOT / "site" / "dashboard" / "index.html").read_text(encoding="utf-8")
if m.load(m.LEDGER, []):  # the tables only exist once there are posts; a fresh install just has to render
    assert _page.count("data-sortable") >= 2 and '<th class="n">Stars</th><th class="n">Word comments</th>' in _page
else:
    assert "<html" in _page.lower() and "Repositories" in _page
print("ok")
