#!/usr/bin/env python3
"""ManyReply: find a hot GitHub repo, post an Instagram carousel about it, and DM the
link to followers who comment the post's keyword (via Zernio's comment automations).

  python manyreply.py telegram               queue the GitHub links the owner sent to the Telegram bot
  python manyreply.py due                    exit 0 when a post is due (last one about a day ago), else 1
  python manyreply.py discover               search GitHub for every topic -> data/candidates.json
  python manyreply.py render  <post_dir>     content.json -> slide-N.png
  python manyreply.py publish <post_dir>     upload, post to Instagram, arm the comment -> DM automation
  python manyreply.py sync                   refresh every post's numbers and the follower history (data/growth.json)
  python manyreply.py review                 print the numbers for the weekly / monthly growth review
  python manyreply.py publish posts/X --now     publish straight away instead of at today's posting time
  python manyreply.py style-previews            redraw the pictures in the dashboard's Current styles section
  python manyreply.py review-email weekly|monthly NOTES.json   build the review email (branded, numbers filled in)
  python manyreply.py reviewed weekly|monthly   record that the review was done
  python manyreply.py dashboard              rebuild the site: site/index.html (public list of words) and
                                             site/dashboard/index.html (the owner's dashboard, behind a password)
  python manyreply.py email   <post_dir>     print the "post is live" email for a published post
  python manyreply.py topics                 take the owner's dashboard edits (data/dashboard.json): topic list, repo requests
  python manyreply.py legacy <KEYWORD> <url> keyword from an older post: reserve it and DM <url> on any post
  python manyreply.py refresh-dms            re-apply the current DM wording and buttons to every automation
  python manyreply.py setup                  guided setup: Zernio key, your AI provider and key, your handle
  python manyreply.py write [--repo URL]     the AI writes the next post's content.json (your own AI key)
  python manyreply.py daily [--publish]      sync, discover, write and render; posts only with --publish

Standard library only. Needs Chrome or Edge installed (used headless to draw the slides).
"""
import hashlib
import html
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.modules.setdefault("manyreply", sys.modules[__name__])  # `import manyreply` from writer.py/llm.py is this same module
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
LEDGER, CONFIG, CANDIDATES = DATA / "posts.json", DATA / "topics.json", DATA / "candidates.json"
GROWTH = DATA / "growth.json"  # follower history, every recent post's reach, and when the last reviews happened
DM_WORDING = DATA / "dm-wording.json"  # which follow-gate wording is live on Zernio (see refresh_gate_if_changed)
EDITS = DATA / "dashboard.json"  # what the owner changed on the dashboard; the site's save function commits it
QUEUE = DATA / "queue.json"  # repos the owner asked for, by Telegram or on the dashboard: posted before anything found
REPO_RE = re.compile(r"https?://github\.com/([\w.-]+)/([\w.-]+)")
ZERNIO = "https://zernio.com/api/v1"
W, H = 1080, 1350  # 4:5, the tallest ratio Instagram shows in the feed


def now():
    return datetime.now(timezone.utc)


def load(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(path, obj):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def env(name):
    if name not in os.environ and (ROOT / ".env").exists():
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            key, _, value = line.strip().partition("=")
            if key and not key.startswith("#"):
                os.environ.setdefault(key, value.strip())
    return os.environ.get(name)


# A cloud machine runs on UTC. Posting times are the owner's, so their zone (`timezone` in data/topics.json) is applied
# wherever the system allows it; Windows has no tzset and simply keeps its own clock zone.
if hasattr(time, "tzset") and "TZ" not in os.environ and (load(CONFIG) or {}).get("timezone"):
    os.environ["TZ"] = load(CONFIG)["timezone"]
    time.tzset()


def http(method, url, body=None, headers=None, raw=None, timeout=120):
    data = raw if raw is not None else json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": "manyreply/1", **(headers or {})}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            text = res.read().decode()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {url.split('?')[0]} -> {e.code}: {e.read().decode()[:600]}") from None
    return json.loads(text) if text.lstrip().startswith(("{", "[")) else text


def zernio(method, path, body=None, **headers):
    # No key here is fine in a Claude cloud environment that holds it as a "network secret" for zernio.com: the key is
    # then attached to the request outside the machine, and nothing that runs on it can read the key.
    key = env("ZERNIO_API_KEY")
    try:
        return http(method, ZERNIO + path, body, {**({"Authorization": f"Bearer {key}"} if key else {}), **headers})
    except RuntimeError as err:
        if not key and "-> 401" in str(err):
            sys.exit("Zernio refused the request and no ZERNIO_API_KEY is set: put it in .env (see .env.example), "
                     "or add it to the cloud environment")
        raise


def doctor():
    """Is this machine (or cloud sandbox) able to do a full run? One line per need; exits 1 if a must-have is missing."""
    bad = []

    def check(name, fn, must=True):
        try:
            print(f"ok       {name}: {fn()}")
        except BaseException as err:  # sys.exit included: every check must get its line
            print(f"{'MISSING' if must else 'optional'}  {name}: {str(err)[:160]}")
            bad.extend([name] * must)

    def need(value, hint):
        return value or (_ for _ in ()).throw(RuntimeError(hint))

    check("Zernio key and Instagram account", lambda: "@" + account()[0]["username"])
    check("browser for the slides", browser)
    check("ffmpeg for Reels and Story clips", lambda: need(encoder(), "pip install --target .tools imageio-ffmpeg"))
    check("music", lambda: f"{need(len(list((ROOT / 'music').glob('*.mp3'))), 'no tracks in music/ (Reels are silent without them)')} tracks", must=False)
    check("AI writer (your own key)", lambda: __import__("llm").describe(), must=False)
    check("Node 22+ for the video Reel", lambda: need(node(), "pip install --target .tools nodejs-wheel-binaries "
                                                      "(without it the Reel is the slideshow)"), must=False)
    check("ElevenLabs voice for the video Reel", lambda: need(env("ELEVENLABS_API_KEY") and "set",
                                                              "set ELEVENLABS_API_KEY (without it the Reel is the slideshow)"), must=False)
    check("GitHub", lambda: http("GET", "https://api.github.com/rate_limit", headers={
        "Authorization": f"Bearer {env('GITHUB_TOKEN')}"} if env("GITHUB_TOKEN") else None)["resources"]["search"])
    check("clock", lambda: f"{local_now():%a %d %b %H:%M %Z} (set TZ if this is not the owner's time)")
    check("report email address", lambda: need(notify_email(), "not set (optional: only used to address the printed report)"), must=False)
    check("Telegram bot", lambda: need(env("TELEGRAM_BOT_TOKEN") and env("TELEGRAM_CHAT_ID") and "set", "not set"), must=False)
    if "Zernio key and Instagram account" in bad:
        import affiliate
        print("\n" + "\n".join(affiliate.signup_lines()))
    sys.exit(f"cannot run: {', '.join(bad)}" if bad else 0)


def notify_email():
    """Where the report goes: NOTIFY_EMAIL, or `notify_email` in data/topics.json (an address is not a secret)."""
    return env("NOTIFY_EMAIL") or load(CONFIG).get("notify_email")


def account():
    """The connected Instagram account named in data/topics.json, plus its Zernio profile id."""
    handle = load(CONFIG)["handle"].lower()
    for a in zernio("GET", "/accounts")["accounts"]:
        if a["platform"] == "instagram" and a["username"].lower() == handle:
            profile = a["profileId"]
            return a, profile["_id"] if isinstance(profile, dict) else profile
    sys.exit(f"Instagram account @{handle} is not connected in Zernio")


def norm(url):
    return url.lower().rstrip("/").removesuffix(".git")


def clean_link(url):
    """Drop the tracking junk links pick up when copied out of Instagram DMs (fbclid, mcp_token, utm_*)."""
    url = url.strip()
    parts = urllib.parse.urlsplit(url if "://" in url else "https://" + url)
    keep = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
            if k not in ("fbclid", "mcp_token") and not k.startswith("utm_")]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(keep)))


# ---------------------------------------------------------------- the owner's requests

def load_queue():
    return load(QUEUE, {"telegram_offset": 0, "items": []})


def github_headers():
    token = env("GITHUB_TOKEN")
    if (not token or token == "proxy-injected") and shutil.which("gh"):
        token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()
    return {"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {token}"} if token else {})}


def rank_repos(items, text):
    """Best match first: a repo whose homepage is the site that was named, then one whose name is the words, then stars."""
    text = text.strip().lower()
    host = urllib.parse.urlsplit(text if "://" in text else "https://" + text).hostname if "." in text and " " not in text else None
    host = host.removeprefix("www.") if host else None
    want = re.sub(r"[^a-z0-9]+", "", (host.split(".")[-2] if host and host.count(".") else text))
    return sorted(items, key=lambda r: (not (host and host in (r.get("homepage") or "").lower()),
                                        re.sub(r"[^a-z0-9]+", "", r["name"].lower()) != want,
                                        -r.get("stargazers_count", 0)))


def find_repo(text):
    """Turn what the owner typed (a website like newpipe.net, owner/name, or a few words from the repo's name) into
    the repo's GitHub link. None when nothing fits, or when GitHub cannot be searched from this machine."""
    t = text.strip()
    if re.fullmatch(r"[\w.-]+/[\w.-]+", t):
        try:
            return http("GET", f"https://api.github.com/repos/{t}", headers=github_headers())["html_url"]
        except RuntimeError:
            pass
    host = urllib.parse.urlsplit(t if "://" in t else "https://" + t).hostname if "." in t and " " not in t else None
    words = host.removeprefix("www.").split(".")[0] if host else t
    try:
        items = http("GET", "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
            {"q": f"{words} in:name,description", "sort": "stars", "per_page": 10}), headers=github_headers())["items"]
    except RuntimeError:
        return None
    best = rank_repos(items, t)[:1]
    return best[0]["html_url"] if best and best[0].get("stargazers_count", 0) >= 50 else None


def resolve_lookups(q, posts):
    """Requests typed as a name or a website wait as `lookup` until a machine that can search GitHub finds them."""
    outcomes = []
    for item in [i for i in q["items"] if i["status"] == "lookup"]:
        url = find_repo(item["query"])
        if url:
            q["items"].remove(item)
            outcomes += [f"'{item['query']}' -> {o}" for o in queue_add(q, posts, url, item["source"])]
    return outcomes


def queue_add(q, posts, text, source, website=False):
    """Queue every GitHub repo link in `text`. Without a link, the text is taken as the repo's name or website and
    looked up. With website=True (the dashboard's "Post this website"), `text` is a web address queued as itself, to be
    posted from the site. Nothing already waiting, skipped or posted is queued twice."""
    outcomes = []
    if website:
        url = text.strip().rstrip("/")
        if any(norm(i["url"]) == norm(url) for i in q["items"]):
            return [f"{url}: already in the queue"]
        status = "already posted" if norm(url) in {norm(p["repo"]) for p in posts} else "waiting"
        q["items"].append({"url": url, "source": source, "added": now().isoformat(timespec="seconds"), "status": status,
                           "website": True})
        return [f"{url}: {status} (a website)"]
    found = REPO_RE.findall(text)
    if not found and text.strip():
        query = text.strip()[:100]
        url = find_repo(query)
        if not url:
            if not any(i.get("query") == query for i in q["items"]):
                q["items"].append({"query": query, "url": "", "source": source,
                                   "added": now().isoformat(timespec="seconds"), "status": "lookup"})
            return [f"'{query}': not found yet, it is looked up again at the next search"]
        found = REPO_RE.findall(url)
        outcomes.append(f"'{query}' is {url}")
    for owner, name in found:
        url = f"https://github.com/{owner}/{name.removesuffix('.git').rstrip('.')}"
        if any(norm(i["url"]) == norm(url) for i in q["items"]):
            outcomes.append(f"{url}: already in the queue")
            continue
        status = "already posted" if norm(url) in {norm(p["repo"]) for p in posts} else "waiting"
        q["items"].append({"url": url, "source": source, "added": now().isoformat(timespec="seconds"), "status": status})
        outcomes.append(f"{url}: {status}")
    return outcomes


def waiting(q):
    """What to post next, in the owner's order: Telegram requests first, then starred favorites, then the other
    dashboard requests, oldest first."""
    return sorted((i for i in q["items"] if i["status"] == "waiting"),
                  key=lambda i: (i["source"] != "telegram", not is_favorite(i["url"]), i["added"]))


def next_pick(posts, q):
    """Whose turn it is. The owner's requests (Telegram, dashboard) and the daily search take turns, one post each,
    so neither crowds out the other. Returns the waiting request to post next, or None for the search's pick."""
    ups = waiting(q)
    made = sorted((p for p in posts if p.get("dir") and p.get("status") in ("live", "scheduled")), key=lambda p: p["date"])
    owners_last = bool(made) and made[-1].get("source", "search") != "search"
    return ups[0] if ups and not owners_last else None


APP_EVERY_DAYS, APP_AGAIN_DAYS = 21, 90


def my_apps():
    """The owner's own apps, added on the dashboard: [{url, site, pitch}]. An app is a GitHub repo (url), a website
    (site), or both."""
    return [a for a in load(EDITS, {}).get("apps", []) if a.get("url") or a.get("site")]


def app_id(a):
    """What a post of this app records as its `repo`: the GitHub link, or the website when there is no repo."""
    return a.get("url") or a["site"]


def app_name(a):
    return a["url"].split("github.com/")[-1] if a.get("url") else re.sub(r"^https://(www\.)?", "", a["site"]).rstrip("/")


def app_due(posts):
    """The owner's app to post now, or None. One app post every 3 weeks at most, on a weekday, on the search's turn
    (the owner's requests keep their turns); apps take turns, never-posted first, and none comes back within 90 days."""
    apps, today = my_apps(), local_now()
    if not apps or today.weekday() >= 5:
        return None
    made = [p for p in posts if p.get("dir") and p.get("status") in ("live", "scheduled")]
    app_dates = [p["date"] for p in made if p.get("source") == "app"]
    if app_dates and (today - datetime.fromisoformat(max(app_dates))).days < APP_EVERY_DAYS:
        return None
    last = lambda a: max((p["date"] for p in made if norm(p["repo"]) in {norm(a.get("url") or a["site"]), norm(a.get("site") or a["url"])}), default="")
    ready = [a for a in apps if not last(a) or (today - datetime.fromisoformat(last(a))).days >= APP_AGAIN_DAYS]
    return min(ready, key=last) if ready else None  # "" sorts first: never-posted apps go first, in list order


FAV_EVERY_DAYS, FAV_AGAIN_DAYS = 4, 30


def my_favorites():
    """The repos (or websites) the owner starred on the dashboard: [url]. They are posted more often than whatever the
    search finds, but less often than the owner's own apps are given priority over them."""
    seen, out = set(), []
    for u in load(EDITS, {}).get("favorites", []):
        if isinstance(u, str) and u.strip() and norm(u) not in seen:
            seen.add(norm(u))
            out.append(u.strip())
    return out


def is_favorite(url):
    return bool(url) and norm(url) in {norm(u) for u in my_favorites()}


def fav_due(posts, q):
    """The favorite to post now, or None. Favorites take the search's turn (after the owner's requests and apps) at most
    once every FAV_EVERY_DAYS days; they take turns, never-posted first and then the one posted longest ago, and none
    comes back within FAV_AGAIN_DAYS of its last post. A favorite still waiting in the queue counts as never posted (so
    it can go on either turn: here, or through the queue where favorites go ahead of other dashboard requests), and a
    skipped one is never posted."""
    favs, today = my_favorites(), local_now()
    if not favs:
        return None
    made = [p for p in posts if p.get("dir") and p.get("status") in ("live", "scheduled")]
    fav_dates = [p["date"] for p in made if p.get("source") == "favorite"]
    if fav_dates and (today - datetime.fromisoformat(max(fav_dates))).days < FAV_EVERY_DAYS:
        return None
    held = {norm(i["url"]) for i in q["items"] if i.get("url") and i["status"] == "skipped"}
    held |= {norm(app_id(a)) for a in my_apps()}  # the owner's apps have their own turn
    ledger = [p for p in posts if p.get("date") and p.get("status") in ("live", "scheduled", "legacy")]  # validate() counts old posts
    last = lambda u: max((p["date"] for p in ledger if norm(p["repo"]) == norm(u)), default="")
    ready = [u for u in favs if norm(u) not in held
             and (not last(u) or (today - datetime.fromisoformat(last(u))).days >= FAV_AGAIN_DAYS)]
    return min(ready, key=last) if ready else None  # "" sorts first: never-posted favorites go first, in list order


def short_count(n):
    """12345 -> 12.3K, 1500000 -> 1.5M: a star count that fits a narrow column."""
    if n is None:
        return ""
    for size, mark in ((1_000_000, "M"), (1_000, "K")):
        if n >= size:
            return f"{n / size:.1f}".removesuffix(".0") + mark
    return str(n)


def stars_wanted():
    """Every GitHub repo the dashboard shows a star count beside: the Up next list, the favorites, the older posts."""
    urls = {i["url"] for i in load_queue()["items"] if i.get("url")} | set(my_favorites()) \
        | {p["repo"] for p in load(LEDGER, []) if p.get("status") == "legacy"}
    return sorted(u for u in urls if REPO_RE.match(u))


def fetch_stars(urls, timeout=8):
    """{norm(url): GitHub stars}, best effort. Stops at the first failure (GitHub's API may be closed from a Claude
    cloud machine, or rate limited): the dashboard just shows what it has. A repo that is gone or private is skipped."""
    out = {}
    for u in urls:
        r = REPO_RE.match(u)
        try:
            repo = http("GET", f"https://api.github.com/repos/{r[1]}/{r[2].removesuffix('.git')}", headers=github_headers(), timeout=timeout)
            out[norm(u)] = int(repo["stargazers_count"])
        except RuntimeError as e:
            if "-> 404" not in str(e):
                break
        except (OSError, KeyError, ValueError, TypeError):
            break
    return out


def refresh_stars(only_missing=False):
    """Keep the star counts in data/candidates.json up to date (the Discover job refreshes them all every day; a new
    request only gets its count when someone runs this: `topics` does, for the ones missing)."""
    cand = load(CANDIDATES)
    if not cand:
        return
    have = cand.get("stars", {})
    got = fetch_stars([u for u in stars_wanted() if not (only_missing and norm(u) in have)])
    if got:
        save(CANDIDATES, {**cand, "stars": {**have, **got}})


def gh_stars(url, cands):
    """The GitHub star count to show beside a repo: the stored count, else what the search saw."""
    n = (cands.get("stars") or {}).get(norm(url))
    return n if n is not None else next((c["stars"] for c in cands.get("candidates", []) if c.get("stars") and norm(c["url"]) == norm(url)), None)


def telegram():
    """Read new messages sent to the bot and queue their GitHub links. Read-only: the bot never replies.
    Telegram keeps unread messages for about a day, so this runs on every daily check, due or not."""
    token, chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
    if not token:
        print("telegram: TELEGRAM_BOT_TOKEN is not set in .env, skipping")
        return
    q = load_queue()
    try:
        updates = http("GET", f"https://api.telegram.org/bot{token}/getUpdates?offset={q['telegram_offset']}")["result"]
    except RuntimeError as e:
        sys.exit("telegram: " + str(e).replace(token, "<token>"))
    outcomes, strangers = [], set()
    for u in updates:
        q["telegram_offset"] = u["update_id"] + 1  # tells Telegram this one is handled, so it is never read twice
        msg = u.get("message") or u.get("channel_post") or {}
        if str(msg.get("chat", {}).get("id")) != chat:  # only the owner's own chat may queue posts
            strangers.add(str(msg.get("chat", {}).get("id")))
            continue
        links = " ".join(e.get("url", "") for e in msg.get("entities", []) + msg.get("caption_entities", []))
        outcomes += queue_add(q, load(LEDGER, []), f"{msg.get('text', '')} {msg.get('caption', '')} {links}", "telegram")
    if updates:
        save(QUEUE, q)
        dashboard()
    print(f"telegram: {len(updates)} new message(s)" + "".join(f"\n  {o}" for o in outcomes))
    if strangers - {"None"}:
        print(f"  ignored messages from other chats: {', '.join(sorted(strangers - {'None'}))} "
              "(set TELEGRAM_CHAT_ID in .env to the one that is yours)")


# ---------------------------------------------------------------- discover

def score(stars, created, weight, today):
    """Blend size with speed: a repo gaining stars fast beats an old giant. Returns (score, stars/day)."""
    per_day = stars / max((today - created).days, 14)
    return round(weight * (math.log10(max(stars, 1)) + 2 * math.log10(1 + per_day)), 2), per_day


def discover():
    cfg = load(CONFIG)
    q = load_queue()
    for line in resolve_lookups(q, load(LEDGER, [])):
        print("found: " + line)
    save(QUEUE, q)
    posted = {norm(p["repo"]) for p in load(LEDGER, [])}
    token = env("GITHUB_TOKEN")
    if not token and shutil.which("gh"):
        token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()
    headers = {"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {token}"} if token else {})}
    today = now()
    # Two looks per search term: established repos still being worked on, and brand-new ones taking off.
    windows = [f"stars:>=500 pushed:>={(today - timedelta(days=60)).date()}",
               f"stars:>=100 created:>={(today - timedelta(days=120)).date()}"]
    found = {}
    for rank, topic in enumerate(cfg["topics"], 1):
        # order is priority: the top topic's scores are lifted 1.5x, sliding down to 1x for the last
        weight = 1.5 - 0.5 * (rank - 1) / max(len(cfg["topics"]) - 1, 1)
        for query in topic["queries"]:
            for window in windows:
                url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
                    {"q": f"{query} {window} archived:false", "sort": "stars", "per_page": 15})
                try:
                    items = http("GET", url, headers=headers)["items"]
                except RuntimeError as e:  # search is rate limited per minute: wait it out once
                    if "-> 403" in str(e) and "rate limit" not in str(e).lower():
                        made = (load(CANDIDATES) or {}).get("generated_at")
                        age = (today - datetime.fromisoformat(made)).total_seconds() / 3600 if made else None
                        if age is not None and age < 36:
                            return print(f"GitHub search is closed from this machine; using the candidates made "
                                         f"{age:.0f} hours ago by the Discover workflow ({CANDIDATES.relative_to(ROOT)})")
                        sys.exit("GitHub search is closed from this machine and data/candidates.json is missing or over "
                                 "36 hours old: check the 'Discover candidates' workflow on GitHub (Actions tab)")
                    print(f"  github said no ({str(e)[:80]}), retrying in 60s")
                    time.sleep(60)
                    items = http("GET", url, headers=headers)["items"]
                time.sleep(2.1 if token else 6.5)
                for r in items:
                    desc = r.get("description") or ""
                    if (norm(r["html_url"]) in posted or len(desc) < 20
                            or sum(ch.isascii() for ch in desc) / len(desc) < 0.85):
                        continue
                    created = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
                    sc, per_day = score(r["stargazers_count"], created, weight, today)
                    if sc > found.get(r["html_url"], {}).get("score", 0):
                        found[r["html_url"]] = {
                            "url": r["html_url"], "name": r["full_name"], "description": desc,
                            "topic": topic["name"], "topic_rank": rank, "query": query,
                            "stars": r["stargazers_count"], "stars_per_day": round(per_day, 1),
                            "created": r["created_at"][:10], "pushed": r["pushed_at"][:10],
                            "language": r.get("language"), "score": sc,
                        }
        print(f"  {topic['name']}: {sum(c['topic'] == topic['name'] for c in found.values())} candidates")
    ranked, per_topic = [], {}
    for c in sorted(found.values(), key=lambda c: -c["score"]):
        per_topic[c["topic"]] = per_topic.get(c["topic"], 0) + 1
        if per_topic[c["topic"]] <= 8:
            ranked.append(c)
    asked = [{"url": i["url"], "name": i["url"].split("github.com/")[-1], "description": "", "score": None,
              "topic": f"You asked for this one ({i['source']})"} for i in waiting(load_queue())]
    stars = {**((load(CANDIDATES) or {}).get("stars") or {}), **fetch_stars(stars_wanted(), timeout=20)}
    save(CANDIDATES, {"generated_at": today.isoformat(timespec="seconds"), "candidates": asked + ranked, "stars": stars})
    dashboard()
    print(f"{len(asked + ranked)} candidates -> {CANDIDATES.relative_to(ROOT)}")


# ---------------------------------------------------------------- content checks

def validate(c, posts, own=None):
    """Refuse anything that would make a broken or duplicate post. `own` = this post's ledger entry on a re-run."""
    others = [p for p in posts if p is not own]
    kw, repo, slides, caption = c.get("keyword", ""), c.get("repo", ""), c.get("slides", []), c.get("caption", "")
    errs = []
    if not re.fullmatch(r"[A-Z]{3,12}", kw):
        errs.append("keyword must be 3-12 capital letters")
    if kw in {p["keyword"].upper() for p in others}:
        errs.append(f"keyword {kw} was already used on another post")
    site_app = norm(repo) in ({norm(a["site"]) for a in my_apps() if a.get("site") and not a.get("url")}
                              | {norm(i["url"]) for i in load_queue()["items"] if i.get("website")}
                              | {norm(u) for u in my_favorites() if u.startswith("https://") and not REPO_RE.search(u)})
    if not site_app and not re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+/?", repo):
        errs.append("repo must be a https://github.com/owner/name URL (or the website of one of the owner's apps or favorites)")
    earlier = [p.get("date") or "9999" for p in others if norm(p["repo"]) == norm(repo)]  # no date: treat as recent
    is_app = norm(repo) in {norm(app_id(a)) for a in my_apps()}
    comes_back = APP_AGAIN_DAYS if is_app else FAV_AGAIN_DAYS if is_favorite(repo) else None  # a wait, then a fresh post
    if earlier and not (comes_back and max(earlier) <= (now() - timedelta(days=comes_back)).isoformat()):
        errs.append("this repo was already posted" + (" (an app can come back 90 days after its last post)" if is_app else
                    f" (a favorite can come back {FAV_AGAIN_DAYS} days after its last post)" if is_favorite(repo) else ""))
    if c.get("link") and not re.fullmatch(r"https://\S+", c["link"]):
        errs.append("link must be a https:// web address")
    # "custom": true = the owner supplied finished images as slide-1.png, slide-2.png...: skip render, go to publish
    if not (c.get("custom") and slides) and not 4 <= len(slides) <= 8:
        errs.append("need 4-8 slides (the comment slide is added automatically, making 5-9)")
    for i, s in enumerate(slides, 1):
        if not s.get("title") or len(s["title"]) > 70:
            errs.append(f"slide {i}: title is required, 70 characters max")
        if len(s.get("body", "")) > 260:
            errs.append(f"slide {i}: body is over 260 characters and will not fit")
    recap = c.get("recap", [])
    if recap and not (3 <= len(recap) <= 6 and all(isinstance(r, str) and 0 < len(r) <= 60 for r in recap)):
        errs.append("recap: 3-6 lines of 60 characters at most")
    if not caption.startswith(f"Comment {kw} "):
        errs.append(f"caption must open with 'Comment {kw} and I'll DM you ...'")
    if caption.count(f"Comment {kw}") < 2:
        errs.append(f"caption must ask for the comment again at the end ('Comment {kw} ...' twice in total)")
    if len(caption) > 2200:
        errs.append("caption is over Instagram's 2,200 characters")
    if "github.com" in caption.lower():
        errs.append("caption must not contain the link: people have to comment to get it")
    if errs:
        raise ValueError("content.json: " + "; ".join(errs))


# ---------------------------------------------------------------- render

SLIDE_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700;800&family=Bricolage+Grotesque:wght@700;800&family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@600;700&display=block');
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1080px;height:1350px;overflow:hidden}
html{--display:'Segoe UI Variable Display','Segoe UI',Inter,'Helvetica Neue',Arial,sans-serif}
body{background:var(--bg);color:var(--fg);padding:72px 80px;display:flex;flex-direction:column;position:relative;
 font-family:'Segoe UI Variable Display','Segoe UI',Inter,'Helvetica Neue',Arial,sans-serif}
body::before{content:"";position:absolute;inset:0;background:var(--deco,none)}
body>*{position:relative}
.top,.foot{display:flex;justify-content:space-between;align-items:center;
 font:600 30px/1 Consolas,'Cascadia Code','JetBrains Mono','DejaVu Sans Mono',monospace;color:var(--muted);letter-spacing:.04em}
.top b{color:var(--fg)}
.main{flex:1;display:flex;flex-direction:column;justify-content:center;gap:44px}
.kicker,.num{font:700 32px/1.2 Consolas,'Cascadia Code','JetBrains Mono','DejaVu Sans Mono',monospace;color:var(--accent);
 letter-spacing:.14em;text-transform:uppercase}
h1{font-family:var(--display);font-weight:var(--dw,800);font-stretch:var(--stretch,normal);
 letter-spacing:var(--ls,-.025em);line-height:var(--lh,1.05);text-transform:var(--case,none);text-wrap:balance}
h1 em,.body em{font-style:normal;color:var(--accent)}
.body{font-size:44px;line-height:1.36;color:var(--soft);display:flex;flex-direction:column;gap:22px}
.body em{font-weight:600}
.li{padding-left:54px;position:relative}
.li::before{content:"";position:absolute;left:0;top:.62em;width:28px;height:6px;border-radius:3px;background:var(--accent)}
.badges{display:flex;flex-wrap:wrap;gap:18px}
.badge{border:2px solid var(--line);border-radius:999px;padding:16px 30px;color:var(--fg);
 font:600 30px/1 Consolas,'Cascadia Code','JetBrains Mono','DejaVu Sans Mono',monospace}
.badge.cta{background:var(--accent);border-color:var(--accent);color:var(--on);font-weight:700}
.word{align-self:flex-start;font-family:var(--display);font-stretch:var(--stretch,normal);font-weight:800;
 line-height:1;letter-spacing:.03em;background:var(--accent);color:var(--on);padding:30px 48px;border-radius:26px}
.bar{display:flex;gap:10px}
.bar i{width:44px;height:8px;border-radius:4px;background:var(--line)}
.bar i.on{background:var(--accent)}
"""

# Looks distilled from the owner's reference screenshots in Styles/. Each is (colours, extra CSS, per-slide colour cycle).
# Posts rotate through them in this order; put "style": "<name>" in content.json to force one.
COND = ("--display:'Bahnschrift','Barlow Condensed','Arial Narrow',Impact,sans-serif;--stretch:condensed;--case:uppercase;"
        "--ls:.01em;--dw:700;--k:1.22;--lh:1.02;")
BIG_NUM = ".num{font:700 200px/.85 var(--display);font-stretch:var(--stretch,normal);letter-spacing:0}"
OUTLINE_NUM = BIG_NUM + ".num{color:transparent;-webkit-text-stroke:4px var(--accent)}"
GHOST_NUM = BIG_NUM + ".num{position:absolute;right:0;top:40px;font-size:340px;color:var(--fg);opacity:.16}"
STYLES = {
    "ember": ("--bg:#0A0C10;--fg:#F4F1EC;--soft:#C9CED6;--muted:#9BA3AF;--accent:#FF6A1A;--on:#0A0C10;--line:#2A2F3A;"
              "--deco:radial-gradient(900px 700px at 100% 0%,rgba(255,106,26,.30),transparent 60%),"
              "radial-gradient(700px 600px at 0% 100%,rgba(77,163,255,.16),transparent 60%),"
              "linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px) 0 0/100% 90px,"
              "linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px) 0 0/90px 100%", "", None),
    "navy-stripe": (COND + "--bg:#0E1433;--fg:#FFFFFF;--soft:#D5D9EA;--muted:#9AA3C7;--accent:#F26A3D;--on:#0E1433;"
                    "--line:#2A3260;--deco:linear-gradient(225deg,#F26A3D 0 10%,rgba(242,106,61,.5) 10% 16%,"
                    "rgba(242,106,61,.22) 16% 21%,transparent 21%),linear-gradient(45deg,rgba(242,106,61,.5) 0 3%,transparent 3%)",
                    OUTLINE_NUM + ".top span{color:#fff}", None),
    "midnight-gold": (COND + "--bg:#0C1230;--fg:#FFFFFF;--soft:#D8DCEC;--muted:#98A1C4;--accent:#FFC627;--on:#0C1230;"
                      "--line:#283057;--deco:linear-gradient(225deg,#FFC627 0 5%,transparent 5%),"
                      "linear-gradient(118deg,transparent 0 74%,rgba(255,198,39,.10) 74% 88%,transparent 88%)",
                      BIG_NUM, None),
    "indigo-pop": (COND + "--bg:#2A1EA6;--fg:#FFFFFF;--soft:#DFDBFF;--muted:#B9B2F0;--accent:#FFE500;--on:#1B1270;"
                   "--line:#4A3FD0;--deco:linear-gradient(225deg,#FFE500 0 5%,transparent 5%),"
                   "linear-gradient(45deg,#FFE500 0 4%,transparent 4%),"
                   "linear-gradient(135deg,transparent 0 55%,rgba(255,255,255,.06) 55% 80%,transparent 80%)", BIG_NUM, None),
    "blueprint": (COND + "--bg:linear-gradient(160deg,#1D4FD8,#12A5C4);--fg:#FFFFFF;--soft:#EAF4FF;--muted:#CFE3FF;"
                  "--accent:#FFD43B;--on:#12307E;--line:rgba(255,255,255,.3);"
                  "--deco:linear-gradient(rgba(255,255,255,.09) 1px,transparent 1px) 0 0/100% 90px,"
                  "linear-gradient(90deg,rgba(255,255,255,.09) 1px,transparent 1px) 0 0/90px 100%", BIG_NUM, None),
    "paper-blue": (COND + "--bg:#FFFFFF;--fg:#0F172A;--soft:#334155;--muted:#64748B;--accent:#2563EB;--on:#FFFFFF;"
                   "--line:#D5DEEE;--deco:radial-gradient(520px 520px at 100% 100%,rgba(37,99,235,.30),transparent 70%),"
                   "radial-gradient(380px 380px at 100% 0%,rgba(37,99,235,.16),transparent 70%)", BIG_NUM,
                   ["", "--bg:#2563EB;--fg:#FFFFFF;--soft:#E3ECFF;--muted:#C7D7FF;--accent:#FFE066;--on:#12307E;"
                        "--line:rgba(255,255,255,.35);--deco:radial-gradient(520px 520px at 100% 0%,rgba(255,255,255,.22),transparent 70%)"]),
    "sunbeam": ("--bg:linear-gradient(160deg,#FFE44D,#F2C500);--fg:#111111;--soft:#2B2B2B;--muted:#5C5200;--accent:#111111;"
                "--on:#FFE44D;--line:rgba(0,0,0,.22);--lh:1.3;--deco:radial-gradient(900px 900px at 110% -10%,rgba(255,255,255,.45),"
                "transparent 60%),radial-gradient(700px 700px at 120% 20%,rgba(255,255,255,.3),transparent 60%)",
                GHOST_NUM + "h1 em{background:#111;color:#FFE44D;padding:0 .14em;box-decoration-break:clone;"
                "-webkit-box-decoration-break:clone}.body em{font-weight:700}", None),
    "charcoal-arrow": (COND + "--bg:#262626;--fg:#FFFFFF;--soft:#D4D4D4;--muted:#A3A3A3;--accent:#FFB81C;--on:#262626;"
                       "--line:#454545", BIG_NUM + ".main{padding-bottom:130px}"
                       "body::after{content:'';position:absolute;left:0;right:80px;bottom:150px;height:84px;"
                       "background:var(--accent);clip-path:polygon(0 42%,90% 42%,90% 0,100% 50%,90% 100%,90% 58%,0 58%)}",
                       None),
    "redline": ("--lh:1.3;--bg:#111111;--fg:#FFFFFF;--soft:#D0D0D0;--muted:#9A9A9A;--accent:#E5202E;--on:#FFFFFF;--line:#333333;"
                "--deco:linear-gradient(105deg,transparent 0 68%,rgba(255,255,255,.05) 68%)",
                BIG_NUM + ".num{color:#fff}h1 em{background:var(--accent);color:#fff;padding:0 .14em;"
                "box-decoration-break:clone;-webkit-box-decoration-break:clone}.body em{color:#FF5C68}"
                ".kicker{align-self:flex-start;background:var(--accent);color:#fff;padding:10px 18px}", None),
    "spectrum": (COND + "--fg:#FFFFFF;--soft:rgba(255,255,255,.94);--muted:rgba(255,255,255,.78);--accent:#FFE66D;"
                 "--on:#3B1D4A;--line:rgba(255,255,255,.35);"
                 "--deco:radial-gradient(700px 700px at 110% 110%,rgba(0,0,0,.18),transparent 65%)", BIG_NUM,
                 ["--bg:#E63462", "--bg:#F26419", "--bg:#C97A1E", "--bg:#B8329E", "--bg:#6A4BC4"]),
    "circuit": ("--bg:linear-gradient(180deg,#07102E,#1B1456 60%,#2A1A6E);--fg:#FFFFFF;--soft:#D6DCF5;--muted:#9FA9D6;"
                "--accent:#5CC8FF;--on:#07102E;--line:#2F3A78;"
                "--deco:radial-gradient(800px 320px at 50% 100%,rgba(92,200,255,.38),transparent 70%),"
                "linear-gradient(rgba(140,160,255,.08) 1px,transparent 1px) 0 0/100% 60px,"
                "linear-gradient(90deg,rgba(140,160,255,.08) 1px,transparent 1px) 0 0/60px 100%", "", None),
    "neon": ("--bg:#0D0B24;--fg:#FFFFFF;--soft:#D9D6F2;--muted:#A19DC9;--accent:#29E0FF;--on:#0D0B24;--line:#2B2850;"
             "--deco:radial-gradient(440px 440px at 100% 0%,rgba(255,61,190,.55),transparent 65%),"
             "radial-gradient(540px 540px at 0% 100%,rgba(41,224,255,.38),transparent 65%),"
             "radial-gradient(260px 260px at 90% 88%,rgba(138,92,255,.5),transparent 70%)",
             OUTLINE_NUM + "h1 em{background:linear-gradient(90deg,#29E0FF,#FF3DBE);-webkit-background-clip:text;"
             "background-clip:text;color:transparent}.word,.badge.cta{background:linear-gradient(90deg,#29E0FF,#FF3DBE);"
             "border-color:transparent}", None),
}


def fmt(text):
    """Escape, then turn *stars* into the accent colour."""
    return re.sub(r"\*(.+?)\*", r"<em>\1</em>", html.escape(text))


def slide_html(s, i, n, handle, badge="", style="ember", keyword="", tall="", foot=None, art=""):
    """One slide as a web page. `tall` (a label such as "NEW POST") switches to the 9:16 Story shape, keeping
    text clear of the top and bottom strips where Instagram draws its own buttons."""
    if style in V2_STYLES:
        return v2_page(s, i, n, handle, badge, style, keyword, tall, art, foot)
    colours, extra, cycle = STYLES[style]
    if tall:
        extra += "html,body{height:1920px}body{padding:270px 80px 400px}"
    if cycle:
        colours += ";" + cycle[i % len(cycle)]
    title = s["title"]
    size = (124, 104, 88) if i == 0 else (100, 86, 74)
    size = size[0] if len(title) <= 24 else size[1] if len(title) <= 42 else size[2]
    body = "".join(f'<div class="li">{fmt(l[2:])}</div>' if l.startswith("- ") else f"<div>{fmt(l)}</div>"
                   for l in (l.strip() for l in s.get("body", "").splitlines()) if l)
    word = s.get("word", "")
    badges = ([f'<div class="badge cta">Comment {keyword} for the link</div>'] if keyword else []) + \
             ([f'<div class="badge">{fmt(badge)}</div>'] if badge else [])
    parts = [
        f'<div class="kicker">{fmt(s["kicker"])}</div>' if s.get("kicker") else
        f'<div class="num">{i:02d}</div>' if 0 < i < n - 1 else "",
        f'<h1 style="font-size:calc({size}px * var(--k,1))">{fmt(title)}</h1>',
        f'<div class="word" style="font-size:{min(170, int(1150 / max(len(word), 1)))}px">{word}</div>' if word else "",
        f'<div class="body">{body}</div>' if body else "",
        f'<div class="badges">{"".join(badges)}</div>' if badges and i == 0 else "",
    ]
    bar = "".join(f'<i class="{"on" if j <= i else ""}"></i>' for j in range(n))
    return (f'<!doctype html><meta charset="utf-8"><style>{SLIDE_CSS}{extra}</style><body style="{colours}">'
            f'<div class="top"><b>@{handle}</b><span>{tall or f"{i + 1:02d} / {n:02d}"}</span></div>'
            f'<div class="main">{"".join(parts)}</div>'
            f'<div class="foot"><div class="bar">{"" if n == 1 else bar}</div><span>'
            f'{foot if foot is not None else "REPLY TO THIS STORY" if tall else "SWIPE →" if i < n - 1 else "FOLLOW + COMMENT"}'
            f'</span></div>')


# ---------------------------------------------------------------- the six looks in rotation since 18 Oct 2026
# Each is its own layout, built from the owner's reference posts. `art` in content.json is an SVG illustration of the
# post's subject that Claude draws for each post: the hero on the cover, inside the app tile or window, and a faint
# pattern behind the other slides.

V2_FONTS = ("https://fonts.googleapis.com/css2?family=Anton&family=Archivo+Black&family=Caveat:wght@600;700"
            "&family=JetBrains+Mono:wght@500;700&family=Permanent+Marker&family=Poppins:wght@500;600;700;800&display=block")

V2_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1080px;height:1350px;overflow:hidden}
.slide{width:1080px;height:1350px;position:relative;overflow:hidden;font-family:'Poppins',sans-serif;text-align:left}
.hl{font-size:30px;font-weight:600;position:absolute;left:70px;top:56px;letter-spacing:.02em;z-index:3}
.pg{position:absolute;right:70px;top:56px;font:600 28px 'JetBrains Mono',monospace;z-index:3}
h1 em{font-style:normal}
.art{position:absolute;z-index:0;pointer-events:none}
.art svg{width:100%;height:100%;display:block}
.wm{opacity:.11}
.hero{z-index:1}
/* 1 terminal neon */
.s1{background:#09090B;color:#F4F4F5;font-family:'JetBrains Mono',monospace}
.s1::before{content:"";position:absolute;inset:0;background-image:linear-gradient(#1A1A1F 1px,transparent 1px),linear-gradient(90deg,#1A1A1F 1px,transparent 1px);background-size:54px 54px;opacity:.7}
.s1 .hl{color:#A1A1AA}.s1 .pg{color:#C6FF3D}
.s1 h1{font:400 var(--h,104px)/0.98 'Archivo Black',sans-serif;text-transform:uppercase;position:absolute;left:70px;right:70px;top:150px;letter-spacing:-.02em;z-index:2}
.s1 h1 em{color:#C6FF3D}.s1 h1 em:nth-of-type(2){color:#FF6B1A}
.s1 .term{position:absolute;left:70px;right:70px;background:#121216;border:2px solid #2A2A31;border-radius:22px;overflow:hidden;z-index:2}
.s1 .bar{display:flex;gap:12px;align-items:center;padding:18px 24px;background:#18181D;border-bottom:2px solid #2A2A31;font-size:24px;color:#A1A1AA}
.s1 .bar i{width:18px;height:18px;border-radius:50%;background:#FF5F57}.s1 .bar i:nth-child(2){background:#FEBC2E}.s1 .bar i:nth-child(3){background:#28C840;margin-right:10px}
.s1 .term pre{padding:32px 34px;font:500 38px/1.5 'JetBrains Mono',monospace;color:#E4E4E7;white-space:pre-wrap}
.s1 .g{color:#C6FF3D}.s1 .c{color:#71717A}.s1 .o{color:#FF6B1A}
.s1 .term em{font-style:normal;color:#C6FF3D}
.s1 .cta{position:absolute;left:70px;right:70px;bottom:70px;display:flex;justify-content:space-between;align-items:center;gap:20px;border:2px solid #2A2A31;border-radius:18px;padding:22px 26px;font-size:28px;color:#A1A1AA;background:#111114;z-index:2}
.s1 .cta b{background:#C6FF3D;color:#09090B;font:400 34px/1 'Archivo Black',sans-serif;padding:16px 22px;border-radius:12px;white-space:nowrap}
/* 2 step cards */
.s2{background:radial-gradient(circle at 80% 0%,#FFD9BF 0,transparent 55%),linear-gradient(180deg,#FFF6EF,#FFE9DB);color:#24150D}
.s2 .hl{color:#B0896F}.s2 .pg{color:#FF6A1F}
.s2 .step{position:absolute;left:0;right:0;top:150px;text-align:center;font:800 60px/1 'Poppins';color:#FF6A1F;z-index:2}
.s2 h1{position:absolute;left:80px;right:80px;top:236px;text-align:center;font:800 var(--h,100px)/1.04 'Poppins';letter-spacing:-.03em;z-index:2}
.s2 h1 em{color:#FF6A1F}
.s2 .card{position:absolute;left:90px;right:90px;background:#fff;border-radius:44px;box-shadow:0 30px 60px rgba(160,80,30,.14);padding:44px 52px;z-index:2}
.s2 .row{display:flex;align-items:center;justify-content:space-between;gap:20px}
.s2 .app{display:flex;flex-direction:column;align-items:center;gap:16px;width:250px;text-align:center;font:700 30px/1.2 'Poppins'}
.s2 .ico{width:130px;height:130px;border-radius:34px;display:grid;place-items:center;font:800 60px/1 'Poppins';color:#fff;background:linear-gradient(135deg,#FF8A3D,#FF5A1F);box-shadow:0 14px 26px rgba(255,90,31,.3);overflow:hidden}
.s2 .ico svg{width:100%;height:100%}
.s2 .ico.w{background:#fff;color:#FF6A1F;border:3px solid #FFE0CC;box-shadow:none}
.s2 .arrow{flex:1;height:6px;background:repeating-linear-gradient(90deg,#FFB48A 0 18px,transparent 18px 30px);position:relative}
.s2 .arrow::after{content:"";position:absolute;right:-4px;top:-11px;border:14px solid transparent;border-left:20px solid #FFB48A}
.s2 ul{list-style:none;display:grid;gap:26px}
.s2 li{display:flex;gap:24px;align-items:center;font:600 40px/1.3 'Poppins'}
.s2 li b{flex:none;width:64px;height:64px;border-radius:50%;background:#FFE9DB;color:#FF6A1F;display:grid;place-items:center;font:800 32px 'Poppins'}
.s2 .body{font:500 42px/1.45 'Poppins';color:#4A3426}
.s2 .body em,.s2 li em{font-style:normal;color:#FF6A1F}
.s2 .ok{position:absolute;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:16px;background:#E6F7EC;color:#147A3D;border:3px solid #BDE8CC;border-radius:999px;padding:20px 36px;font:700 34px 'Poppins';white-space:nowrap;z-index:2}
.s2 .foot{position:absolute;left:0;right:0;bottom:60px;text-align:center;font:500 28px 'Poppins';color:#B0896F}
/* 3 hot take comic */
.s3{background:#FBF2E6;color:#111}
.s3::after{content:"";position:absolute;inset:0;background:radial-gradient(#E9DCCB 2px,transparent 2px);background-size:38px 38px;opacity:.6}
.s3 .hl{color:#7A6A58;font:700 34px 'Caveat',cursive}.s3 .pg{color:#7A6A58}
.s3 h1{position:absolute;left:60px;right:60px;top:120px;text-align:center;font:400 var(--h,140px)/0.94 'Anton',sans-serif;text-transform:uppercase;z-index:2}
.s3 h1 em{color:#E5322D}
.s3 .hand{position:absolute;left:80px;right:80px;text-align:center;font:700 60px/1.1 'Caveat',cursive;color:#2C2C2C;z-index:2}
.s3 .body{position:absolute;left:90px;right:90px;font:600 50px/1.45 'Poppins';text-align:center;z-index:2}
.s3 .body b{background:#FFE15A;padding:0 10px;font-weight:600}
.s3 .body em{font-style:normal;background:#FFE15A}
.s3 .save{position:absolute;right:70px;bottom:70px;font:700 44px 'Caveat',cursive;color:#7A6A58;z-index:2}
/* 4 whiteboard */
.s4{background:#FFFFFF;color:#1B1B1B}
.s4::before{content:"";position:absolute;inset:0;background-image:linear-gradient(#EEF1F6 2px,transparent 2px),linear-gradient(90deg,#EEF1F6 2px,transparent 2px);background-size:60px 60px}
.s4 .hl{color:#8A93A3}.s4 .pg{color:#2B59FF}
.s4 h1{position:absolute;left:70px;right:70px;top:140px;font:400 var(--h,100px)/1.05 'Permanent Marker',cursive;z-index:2}
.s4 h1 em{font-style:normal;color:#2B59FF;text-decoration:underline;text-decoration-thickness:12px;text-underline-offset:14px;text-decoration-color:#FFD43B}
.s4 .bubble{position:absolute;background:#fff;border:5px solid #1B1B1B;border-radius:40px;padding:34px 42px;font:700 58px/1.2 'Caveat',cursive;box-shadow:10px 10px 0 #1B1B1B;z-index:2}
.s4 .bubble::after{content:"";position:absolute;left:70px;bottom:-34px;width:40px;height:40px;background:#fff;border-right:5px solid #1B1B1B;border-bottom:5px solid #1B1B1B;transform:rotate(45deg)}
.s4 .bubble em{font-style:normal;color:#2B59FF}
.s4 .sticky{position:absolute;width:420px;padding:40px 36px;font:700 46px/1.25 'Caveat',cursive;box-shadow:0 18px 30px rgba(0,0,0,.12);z-index:2}
.s4 .frame{position:absolute;border:5px solid #1B1B1B;border-radius:30px;background:#fff;box-shadow:10px 10px 0 #1B1B1B;padding:18px;z-index:1}
.s4 .note{position:absolute;left:80px;right:80px;font:500 40px/1.5 'Poppins';z-index:2}
.s4 .note li{margin:0 0 18px}
/* 5 listicle grid */
.s5{background:#FFFFFF;color:#111}
.s5 .hl{color:#8B8B8B}.s5 .pg{color:#FF5A1F}
.s5 .logos{position:absolute;top:120px;left:0;right:0;display:flex;justify-content:center;align-items:center;gap:30px;font:800 70px 'Poppins';color:#C9C9C9;z-index:2}
.s5 .lg{width:160px;height:160px;border-radius:40px;display:grid;place-items:center;color:#fff;font:800 70px 'Poppins';overflow:hidden;background:#111}
.s5 .lg svg{width:100%;height:100%}
.s5 h1{position:absolute;left:70px;right:70px;top:330px;text-align:center;font:800 var(--h,76px)/1.08 'Poppins';letter-spacing:-.02em;z-index:2}
.s5 h1 em{font-style:normal;color:#FF5A1F}
.s5 .cards{position:absolute;left:60px;right:60px;display:grid;grid-template-columns:repeat(2,1fr);gap:22px;z-index:2}
.s5 .cards.one{grid-template-columns:1fr;gap:26px}
.s5 .card{border:3px solid #EFEFEF;border-radius:30px;padding:28px 30px;display:grid;grid-template-columns:auto 1fr;gap:6px 22px;align-items:center;background:#FAFAFA}
.s5 .cards.one .card{padding:38px 42px}
.s5 .n{grid-row:1/3;width:84px;height:84px;border-radius:22px;background:#111;color:#fff;display:grid;place-items:center;font:800 36px 'Poppins'}
.s5 .cards.one .n{width:104px;height:104px;font-size:44px}
.s5 .card:nth-child(3n+2) .n{background:#FF5A1F}.s5 .card:nth-child(3n) .n{background:#2B59FF}
.s5 .card b{font:800 36px/1.2 'Poppins'}
.s5 .cards.one .card b{font-size:46px}
.s5 .card span{font:500 26px/1.35 'Poppins';color:#666}
.s5 .cards.one .card span{font-size:34px}
.s5 .card em{font-style:normal;color:#FF5A1F}
.s5 .follow{position:absolute;left:0;right:0;bottom:70px;display:flex;justify-content:center;align-items:center;gap:16px;font:700 36px 'Poppins';z-index:2}
.s5 .follow i{font-style:normal;background:#111;color:#fff;border-radius:999px;padding:12px 24px}
/* 6 cinematic dark */
.s6{background:radial-gradient(ellipse at 50% 108%,#B4501A 0,#4A1F0D 26%,transparent 60%),linear-gradient(180deg,#0B0D12,#141821 60%,#0B0D12);color:#fff}
.s6 .hl{color:#9AA3B5}.s6 .pg{color:#FF7A1A}
.s6 h1{position:absolute;left:60px;right:60px;top:120px;text-align:center;font:400 var(--h,148px)/0.92 'Anton',sans-serif;text-transform:uppercase;text-shadow:0 10px 40px rgba(0,0,0,.6);z-index:2}
.s6 h1 em{color:#FF7A1A}
.s6 .stage{position:absolute;left:0;right:0;perspective:1600px;display:flex;justify-content:center;gap:24px;z-index:1}
.s6 .win{width:330px;height:420px;border-radius:20px;background:linear-gradient(180deg,#1C2230,#121620);border:2px solid #2C3446;box-shadow:0 30px 60px rgba(0,0,0,.6),0 0 60px rgba(255,122,26,.15);padding:22px;display:flex;flex-direction:column;gap:14px;overflow:hidden}
.s6 .win:first-child{transform:rotateY(22deg) translateZ(-40px)}.s6 .win:last-child{transform:rotateY(-22deg) translateZ(-40px)}
.s6 .win.mid{padding:0;box-shadow:0 30px 60px rgba(0,0,0,.6),0 0 90px rgba(255,122,26,.35)}
.s6 .win .t{height:20px;width:60%;border-radius:6px;background:#3A4458}
.s6 .win .l{height:14px;border-radius:5px;background:#283044}
.s6 .body{position:absolute;left:90px;right:90px;text-align:center;font:500 46px/1.45 'Poppins';color:#D7DCE6;z-index:2}
.s6 .body em,.s6 .body b{font-style:normal;color:#fff}
.s6 ul{list-style:none;display:grid;gap:22px;position:absolute;left:110px;right:110px;z-index:2}
.s6 li{font:600 42px/1.3 'Poppins';display:flex;gap:22px;align-items:center;background:rgba(13,16,22,.82);border:2px solid #2C3446;border-radius:22px;padding:24px 30px}
.s6 li b{color:#FF7A1A;font:400 50px 'Anton'}
.s6 li em{font-style:normal;color:#FF7A1A}
"""

V2_STYLES = ["terminal-neon", "step-cards", "hot-take", "whiteboard", "listicle", "cinematic"]
# Three looks in the Zero Touch AI site's colours (navy, blue-to-violet, pink), added 31 Oct 2026.
STYLES.update({
    "banner": (COND + "--bg:linear-gradient(135deg,#4C1D95,#6D28D9 45%,#3B6CF6);--fg:#FFFFFF;--soft:#EDE9FE;--muted:#C4B5FD;"
               "--accent:#F9A8D4;--on:#3B0764;--line:rgba(255,255,255,.28);"
               "--deco:radial-gradient(900px 700px at 105% 105%,rgba(236,72,153,.55),transparent 60%)", BIG_NUM, None),
    "bold-band": (COND + "--bg:#0A1023;--fg:#FFFFFF;--soft:#D9DEF5;--muted:#8D99C2;--accent:#60A5FA;--on:#0A1023;--line:#25305A;"
                  "--deco:linear-gradient(172deg,transparent 0 90%,#3B6CF6 90% 93%,#7C3AED 93% 96%,#EC4899 96% 97%,transparent 97%)",
                  GHOST_NUM, None),
    "afterglow": (COND + "--bg:linear-gradient(165deg,#0F172A,#1E1B4B 50%,#701A75);--fg:#FFFFFF;--soft:#F5D0FE;--muted:#C4B5FD;"
                  "--accent:#F472B6;--on:#1E1B4B;--line:rgba(255,255,255,.22);"
                  "--deco:radial-gradient(700px 600px at 0% 0%,rgba(96,165,250,.25),transparent 60%)", OUTLINE_NUM, None),
    # the Zero Touch AI logo on black: purple-magenta -> red -> orange, magenta and orange glows like its two rings
    "logo-glow": ("--bg:#000000;--fg:#FFFFFF;--soft:#E7E2EA;--muted:#A79FB0;--accent:#FF3D5A;--on:#FFFFFF;--line:#2A2230;"
                  "--deco:radial-gradient(620px 560px at 0% 0%,rgba(224,17,154,.40),transparent 65%),"
                  "radial-gradient(680px 600px at 100% 100%,rgba(255,122,0,.38),transparent 65%),"
                  "radial-gradient(300px 300px at 100% 0%,rgba(240,35,74,.22),transparent 70%)",
                  BIG_NUM + ".num,h1 em{background:linear-gradient(90deg,#A21CAF,#E0119A 35%,#F0234A 65%,#FF7A00);"
                  "-webkit-background-clip:text;background-clip:text;color:transparent}"
                  ".word,.badge.cta{background:linear-gradient(90deg,#A21CAF,#E0119A 35%,#F0234A 65%,#FF7A00);"
                  "border-color:transparent;color:#fff}", None),
})
# The looks new posts rotate through. 31 Oct 2026: the owner went back to the original twelve (V2_STYLES paused), then
# swapped indigo-pop, blueprint and sunbeam for banner, bold-band and afterglow, and charcoal-arrow for logo-glow. The dropped ones stay in STYLES so a
# post that names one still renders.
ACTIVE_STYLES = ["ember", "navy-stripe", "midnight-gold", "banner", "bold-band", "paper-blue", "afterglow",
                 "logo-glow", "redline", "spectrum", "circuit", "neon"]
MASCOT = ('<svg viewBox="0 0 300 300" style="position:absolute;left:40px;bottom:40px;width:250px;z-index:2">'
          '<circle cx="150" cy="120" r="80" fill="#F2C9A0" stroke="#111" stroke-width="7"/><path d="M78 98c10-50 134-58 146 0" fill="#3B2A20" stroke="#111" stroke-width="7"/>'
          '<circle cx="122" cy="128" r="22" fill="#fff" stroke="#111" stroke-width="7"/><circle cx="180" cy="128" r="22" fill="#fff" stroke="#111" stroke-width="7"/>'
          '<path d="M144 128h14" stroke="#111" stroke-width="7"/><circle cx="124" cy="130" r="7" fill="#111"/><circle cx="182" cy="130" r="7" fill="#111"/>'
          '<path d="M128 172q22 14 44 0" stroke="#111" stroke-width="7" fill="none" stroke-linecap="round"/>'
          '<path d="M60 300c4-60 46-90 90-90s86 30 90 90" fill="#FF7A1A" stroke="#111" stroke-width="7"/></svg>')


def clean_art(svg):
    """The post's illustration, made safe to render: one plain <svg>, no scripts, no event handlers, no outside links."""
    svg = (svg or "").strip()
    if not svg.lower().startswith("<svg") or len(svg) > 20000:
        return ""
    svg = re.sub(r"(?is)<(script|foreignObject|iframe|image|use)\b.*?(</\1>|/>)", "", svg)
    svg = re.sub(r"(?i)\son\w+\s*=\s*(\"[^\"]*\"|'[^']*')", "", svg)
    return re.sub(r"(?i)\s(xlink:)?href\s*=\s*(\"(?!#)[^\"]*\"|'(?!#)[^']*')", "", svg)


def v2_slide(s, i, n, handle, badge, style, keyword, tall, art):
    """One slide in one of the six looks. Kind: the cover, the comment slide, the recap, or a body slide."""
    st = f"s{V2_STYLES.index(style) + 1}"
    kw = keyword or s.get("word", "")
    word = s.get("word")
    kind = "cta" if word and i > 0 else "cover" if i == 0 else "recap" if s.get("kicker") == "Screenshot this" else "body"
    lines = [l.strip() for l in s.get("body", "").splitlines() if l.strip()]
    items = [fmt(l[2:]) for l in lines if l.startswith("- ")]
    text = "<br>".join(fmt(l) for l in lines if not l.startswith("- "))
    title, kicker = fmt(s["title"]), fmt(s.get("kicker", ""))
    if kind == "cta":
        title = f"Comment <em>{html.escape(kw)}</em>"
    plain = re.sub(r"<[^>]+>", "", title)
    h = lambda big, mid, small: big if len(plain) <= 22 else mid if len(plain) <= 40 else small
    top = f'<span class="hl">@{handle}</span><span class="pg">{tall or f"{i + 1:02d} / {n:02d}"}</span>'
    art_at = lambda css, cls="hero": f'<div class="art {cls}" style="{css}">{art}</div>' if art else ""
    wm = art_at("right:-120px;bottom:-80px;width:760px;height:760px", "wm")
    badge = fmt(badge) if badge else ""

    if st == "s1":
        term = lambda y, name, body: (f'<div class="term" style="top:{y}px"><div class="bar"><i></i><i></i><i></i>{name}</div>'
                                      f'<pre>{body}</pre></div>')
        cta = lambda left: f'<div class="cta"><span>{left}</span><b>COMMENT "{html.escape(kw)}"</b></div>'
        head = f'<h1 style="--h:{h(104, 88, 72)}px">{title}</h1>'
        if kind == "cover":
            return top + wm + head + term(660, "~/" + (kw or "repo").lower(), f'<span class="c">$</span> {kicker or "new tool"}\n{text or ""}') + cta(badge or handle)
        if kind == "recap":
            return top + wm + head + term(400, "recap.md", "\n".join(f'<span class="g">✓</span> {x}' for x in items)) + cta("Screenshot this")
        if kind == "cta":
            return top + art_at("right:70px;bottom:170px;width:280px;height:280px") + head + term(400, "dm.sh", "\n".join(
                f'<span class="g">→</span> {fmt(l[2:] if l.startswith("- ") else l)}' for l in lines)) + cta("@" + handle)
        return top + wm + head + term(520, (kicker or "notes").lower(), ("\n".join(f'<span class="g">✓</span> {x}' for x in items) +
                                                                       ("\n" if items and text else "") + text)) + cta(kicker or "@" + handle)

    if st == "s2":
        tile = f'<span class="ico">{art}</span>' if art else '<span class="ico">★</span>'
        flow = lambda y: (f'<div class="card" style="top:{y}px;padding:34px 40px"><div class="row"><div class="app"><span class="ico w">💬</span>Comment {html.escape(kw)}</div>'
                          f'<span class="arrow"></span><div class="app">{tile}This tool</div><span class="arrow"></span>'
                          f'<div class="app"><span class="ico w">📩</span>In your DMs</div></div></div>')
        step = {"cover": kicker or "New tool", "recap": "Recap", "cta": "Last step"}.get(kind, f"Step {i}")
        head = f'<div class="step">{step}</div><h1 style="--h:{h(104, 88, 74)}px">{title}</h1>'
        listing = (f'<ul>{"".join(f"<li><b>{j + 1}</b>{x}</li>" for j, x in enumerate(items))}</ul>' if items else "") + \
                  (f'<p class="body">{text}</p>' if text else "")
        if kind == "cover":
            return top + head + flow(700) + (f'<div class="ok" style="top:1080px">✓ Comment {html.escape(kw)} for the link</div>') + \
                   f'<div class="foot">{badge}</div>'
        if kind == "cta":
            return top + head + flow(560) + f'<div class="card" style="top:900px">{listing}</div>'
        return top + head + f'<div class="card" style="top:520px">{listing}</div>' + (flow(930) if len(items) <= 3 else "") + \
               f'<div class="foot">Comment {html.escape(kw)} for the link</div>'

    if st == "s3":
        head = f'<h1 style="--h:{h(140, 118, 96)}px">{title}</h1>'
        hand = lambda y, t: f'<div class="hand" style="top:{y}px">({t})</div>' if t else ""
        body = lambda y: f'<div class="body" style="top:{y}px{";font-size:40px" if len(items) > 3 else ""}">{("<br>" if len(items) > 3 else "<br><br>").join(f"<b>{x}</b>" for x in items) if items else text}</div>'
        if kind == "cover":
            return top + head + hand(470, kicker.lower() or "this free tool") + art_at("left:340px;top:610px;width:400px;height:400px") + \
                   MASCOT + f'<div class="save">comment {html.escape(kw)} →</div>'
        if kind == "cta":
            return top + head + hand(400, "and I'll DM you the link") + art_at("left:390px;top:520px;width:300px;height:300px") + \
                   f'<div class="body" style="top:860px">{"<br>".join(fmt(l) for l in lines)}</div>'
        return top + art_at("left:290px;top:480px;width:500px;height:500px", "wm") + head + hand(470, kicker.lower()) + body(620) + ("" if len(items) > 3 else MASCOT) + \
               '<div class="save">save for later</div>'

    if st == "s4":
        head = f'<h1 style="--h:{h(100, 86, 72)}px">{title}</h1>'
        colours = ["#FFE36E", "#BDE7FF", "#FFC6D9", "#C9F2C7", "#FFD8A8", "#E2D4FF"]
        frame = lambda css: f'<div class="frame" style="{css}">{art}</div>' if art else ""
        ask = f'<div class="sticky" style="right:100px;bottom:110px;background:#FFE36E;transform:rotate(-3deg);width:380px">Comment<br>{html.escape(kw)} 👇</div>'
        if kind == "cover":
            return top + head + f'<div class="bubble" style="left:100px;top:620px;max-width:560px">{text or kicker}</div>' + \
                   frame("right:90px;top:560px;width:330px;height:330px;transform:rotate(4deg)") + ask
        if kind == "cta":
            return top + head + f'<div class="bubble" style="left:110px;top:440px">I\'ll DM you the link!</div>' + \
                   f'<div class="note" style="top:700px"><ul>{"".join(f"<li>{fmt(l)}</li>" for l in lines)}</ul></div>' + \
                   frame("right:90px;bottom:90px;width:260px;height:260px;transform:rotate(-4deg)")
        if items:
            stickies = "".join(f'<div class="sticky" style="left:{100 + (j % 2) * 460}px;top:{450 + (j // 2) * 250}px;'
                               f'background:{colours[j % len(colours)]};transform:rotate({3 if j % 2 else -3}deg)">{x}</div>'
                               for j, x in enumerate(items[:6]))
            return top + head + stickies + ("" if len(items) > 4 else ask)
        return top + head + f'<div class="bubble" style="left:100px;right:100px;top:460px">{text}</div>' + \
               frame("left:120px;bottom:110px;width:300px;height:300px;transform:rotate(-4deg)") + ask

    if st == "s5":
        logo = f'<div class="logos"><span class="lg">{art or "★"}</span>+<span class="lg" style="background:#FF5A1F">AI</span></div>'
        follow = f'<div class="follow">Follow <i>@{handle}</i> for more</div>'
        cards = lambda rows, y: (f'<div class="cards{" one" if len(rows) <= 3 else ""}" style="top:{y}px">' + "".join(
            f'<div class="card"><span class="n">{j + 1:02d}</span><b>{a}</b><span>{b}</span></div>' for j, (a, b) in enumerate(rows)) + "</div>")
        if kind == "cover":
            return top + logo + f'<h1 style="--h:{h(80, 70, 60)}px">{title}</h1>' + \
                   cards([(kicker or "New", text or badge)] + ([("Get it", f"Comment {html.escape(kw)} for the link")] if kw else []), 640) + follow
        if kind == "cta":
            return top + logo + f'<h1 style="--h:80px">{title}</h1>' + cards([("Step", fmt(l[2:] if l.startswith("- ") else l)) for l in lines] or
                                                                              [("Follow", "@" + handle)], 620)
        rows = [(x, "" if kind == "recap" else kicker) for x in items] if items else [(kicker or "Why it matters", text)]
        return top + f'<h1 style="--h:{h(80, 70, 60)}px;top:170px">{title}</h1>' + cards(rows, 400) + \
               (f'<div class="art hero" style="left:50%;transform:translateX(-50%);bottom:170px;width:380px;height:380px">{art}</div>'
                if art and len(rows) <= 2 else "") + follow

    # s6 cinematic
    head = f'<h1 style="--h:{h(150, 124, 100)}px">{title}</h1>'
    stage = lambda y: (f'<div class="stage" style="top:{y}px"><div class="win"><span class="t"></span><span class="l"></span>'
                       f'<span class="l" style="width:80%"></span><span class="l" style="width:60%"></span><span class="l"></span></div>'
                       f'<div class="win mid">{art}</div><div class="win"><span class="t" style="width:40%"></span><span class="l"></span>'
                       f'<span class="l" style="width:70%"></span><span class="l"></span><span class="l" style="width:50%"></span></div></div>')
    listing = lambda y: f'<ul style="top:{y}px">{"".join(f"<li><b>{j + 1}</b>{x}</li>" for j, x in enumerate(items))}</ul>'
    if kind == "cover":
        return top + head + (f'<div class="body" style="top:{560 if len(plain) <= 22 else 640}px">{text}</div>' if text else "") + stage(820)
    if kind == "cta":
        return top + head + f'<div class="body" style="top:420px">{"<br>".join(fmt(l) for l in lines)}</div>' + stage(820)
    if kind == "recap" or len(items) > 2:
        return top + head + listing(440)
    return top + head + (listing(480) if items else f'<div class="body" style="top:500px">{text}</div>') + stage(860 if items else 820)


def v2_page(s, i, n, handle, badge, style, keyword, tall, art, foot=None):
    """The slide as a page; a Story or Reel frame (tall) is the same slide centred on a 9:16 canvas. A Reel frame
    (foot set) carries the comment ask in a bright bar above the slide, on every frame from the first second."""
    inner = v2_slide(s, i, n, handle, badge, style, keyword, tall, clean_art(art))
    st = f"s{V2_STYLES.index(style) + 1}"
    size = "html,body{height:1920px}.slide{top:285px}body{position:relative}" if tall else ""
    bar = (f'<div style="position:absolute;left:60px;right:60px;top:150px;height:110px;z-index:9;display:flex;align-items:center;'
           f'justify-content:center;gap:16px;background:#FFE14D;color:#111;border-radius:24px;font:800 46px/1 Poppins,sans-serif;white-space:nowrap;'
           f'box-shadow:0 10px 30px rgba(0,0,0,.25)">💬 Comment <span style="background:#111;color:#FFE14D;padding:8px 16px;'
           f'border-radius:12px">{html.escape(keyword)}</span> for the link</div>') if tall and foot and keyword else ""
    return (f'<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="{V2_FONTS}"><style>{V2_CSS}{size}</style>'
            f'<body class="{st}" style="margin:0">{bar}<div class="slide {st}">{inner}</div></body>')


def crop_png(path, height):
    """Keep the top `height` rows of a PNG. Rows are stored top to bottom and each depends only on the ones above it,
    so the rest can simply be dropped. (Chrome's own PNGs: 8-bit, not interlaced.)"""
    data = path.read_bytes()
    chunks, pos = [], 8
    while pos < len(data):
        size, kind = struct.unpack(">I4s", data[pos:pos + 8])
        chunks.append((kind, data[pos + 8:pos + 8 + size]))
        pos += size + 12
    width, _, depth, colour, _, _, interlace = struct.unpack(">IIBBBBB", chunks[0][1])
    if depth != 8 or interlace:
        sys.exit(f"{path.name}: unexpected PNG format")
    row = 1 + width * {0: 1, 2: 3, 4: 2, 6: 4}[colour]  # a filter byte, then the pixels
    pixels = zlib.decompress(b"".join(body for kind, body in chunks if kind == b"IDAT"))[:row * height]
    out = [(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, 0)),
           *[c for c in chunks[1:] if c[0] not in (b"IDAT", b"IEND")], (b"IDAT", zlib.compress(pixels, 6)), (b"IEND", b"")]
    path.write_bytes(data[:8] + b"".join(
        struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body)) for kind, body in out))


def browser():
    # On Linux the headless shell comes first: from 29 Oct 2026 the full Chromium in the Claude cloud sandbox never
    # finished a --screenshot (it kept calling a Google push endpoint the proxy blocks); the shell takes seconds.
    shells = [*map(str, Path("/opt/pw-browsers").glob("chromium_headless_shell-*/chrome-headless-shell-linux*/chrome-headless-shell")),
              *map(str, Path.home().glob(".cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux*/chrome-headless-shell"))]
    for exe in (env("BROWSER"), *(shells if sys.platform.startswith("linux") else []),
                shutil.which("chrome"), shutil.which("chromium"), shutil.which("google-chrome"),
                shutil.which("chromium-browser"), shutil.which("google-chrome-stable"), shutil.which("msedge"),
                *map(str, Path.home().glob(".cache/ms-playwright/chromium-*/chrome-linux*/chrome")),  # `playwright install chromium`
                "/opt/pw-browsers/chromium", *map(str, Path("/opt/pw-browsers").glob("chromium-*/chrome-linux*/chrome")),  # Claude cloud
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        if exe and Path(exe).exists():
            return exe
    sys.exit("No Chrome or Edge found: set BROWSER=<path to the browser> in .env")


def encoder():
    """ffmpeg, which turns the slides into the Reel. Optional: without it the carousel and Story still go out."""
    exe = env("FFMPEG") or shutil.which("ffmpeg")
    if not exe:
        sys.path.insert(0, str(ROOT / ".tools"))  # `pip install --target .tools imageio-ffmpeg` keeps it in the project
        try:
            import imageio_ffmpeg
            exe = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            exe = None
    return exe


def node_version(exe):
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20).stdout
        return int(out.strip().lstrip("v").split(".")[0])
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0


def node():
    """Node 22+ for reelkit/ (it needs the built-in WebSocket), or None. Like ffmpeg, a cloud sandbox without it
    installs it into the project: `pip install --target .tools nodejs-wheel-binaries`."""
    tools = ROOT / ".tools" / "nodejs_wheel"
    for exe in (env("NODE"), shutil.which("node"), *map(str, tools.glob("**/node")), *map(str, tools.glob("**/node.exe"))):
        if exe and Path(exe).is_file() and node_version(exe) >= 22:
            return exe
    return None


def video_reel(post_dir, handle, track, ffmpeg):
    """The narrated, animated Reel from reelkit/ (voice, word-timed captions, scenes built from content.json).
    False means it could not be made here, and render makes the old slideshow Reel instead."""
    key, exe = env("ELEVENLABS_API_KEY"), node()
    if not exe or not (key or os.name == "nt" or env("REEL_DRY_VOICE")):  # off Windows there is no free voice
        return False
    run_env = {**os.environ, "FFMPEG": ffmpeg, "BROWSER": browser(), "REEL_HANDLE": handle,
               **({"ELEVENLABS_API_KEY": key} if key else {}), **({"REEL_MUSIC": str(track)} if track else {})}
    (post_dir / "reel.mp4").unlink(missing_ok=True)
    try:
        subprocess.run([exe, str(ROOT / "reelkit" / "tools" / "post-reel.mjs"), str(post_dir)],
                       env=run_env, check=True, timeout=1200)
        return (post_dir / "reel.mp4").exists()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as err:
        print(f"video Reel failed, making the slideshow Reel instead: {err}")
        return False


def all_slides(c, handle):
    """The post's own slides, then the recap, then the comment slide."""
    recap = [{"kicker": "Screenshot this", "title": "The *short version*",
              "body": "\n".join(f"- {r}" for r in c["recap"])}] if c.get("recap") else []
    return c["slides"] + recap + [{
        "kicker": "Want the link?", "title": "Comment", "word": c["keyword"],
        "body": f"and I'll DM it to you.\nFollow *@{handle}* first: the link only goes to followers.\n"
                f"Then send this to {c.get('send_to') or 'someone who would use it'}.",
    }]


STYLE_NOTES = {
    "terminal-neon": "Dark code-terminal windows, lime and orange. Feels technical and hacker-ish.",
    "step-cards": "Soft peach background, white cards and a comment-to-DM flow. Friendly how-to look.",
    "hot-take": "Cream paper, huge black and red headlines, a little cartoon guy. Opinion and hype posts.",
    "whiteboard": "Graph paper, marker headings, sticky notes and speech bubbles. Feels hand-made.",
    "listicle": "Clean white with numbered cards. Best for lists of features or steps.",
    "cinematic": "Dark movie-poster look, giant orange headline over glowing app windows.",
    "ember": "Near-black with a warm orange glow; orange highlight words.",
    "navy-stripe": "Deep navy, big capital headline, orange diagonal stripe in the corner.",
    "midnight-gold": "Midnight navy with gold highlights and a gold corner tab.",
    "indigo-pop": "Bright indigo with yellow highlights and yellow corner tabs.",
    "blueprint": "Blue-to-teal gradient, capital headline, yellow highlights.",
    "paper-blue": "Clean white page with blue highlights. The light one.",
    "sunbeam": "Sunny yellow page, black text, the key word in a black box.",
    "charcoal-arrow": "Charcoal grey, gold highlights and a gold arrow along the bottom.",
    "redline": "Black with bold red tags and the key word in a red box.",
    "spectrum": "Hot pink-red page, capital headline, yellow highlights.",
    "circuit": "Deep purple-blue with sky-blue highlights and a soft glow.",
    "neon": "Dark night blue with neon blue and pink highlights.",
    "banner": "Violet fading into blue with pink highlights, like the tools page banner.",
    "bold-band": "Navy with a blue, violet and pink stripe across the bottom corner.",
    "afterglow": "Midnight navy fading into magenta, with pink highlights.",
    "logo-glow": "Black with the logo's purple-to-orange gradient on the key words and magenta and orange glows.",
}


def style_previews():
    """Small pictures of every look in the rotation (cover, a list slide, the comment slide) for the dashboard's
    Current styles section. Uses data/style-sample.json. Run after changing a look: python manyreply.py style-previews"""
    sample, handle = load(DATA / "style-sample.json") or sys.exit("data/style-sample.json not found"), load(CONFIG)["handle"]
    slides, out, exe = all_slides(sample, handle), ROOT / "site" / "dashboard" / "looks", browser()
    out.mkdir(parents=True, exist_ok=True)
    picks = (0, 2, len(slides) - 1)
    with tempfile.TemporaryDirectory() as tmp:
        for style in ACTIVE_STYLES:
            for n, i in enumerate(picks, 1):
                page, png = Path(tmp) / "p.html", out / f"{style}-{n}.png"
                page.write_text(slide_html(slides[i], i, len(slides), handle, sample.get("badge", ""), style, sample["keyword"],
                                           art=sample.get("art", "")), encoding="utf-8")
                subprocess.run([exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=0.3333",
                                "--virtual-time-budget=5000", *(["--no-sandbox"] if os.name != "nt" else []),
                                f"--user-data-dir={tmp}/profile", f"--window-size={W},{H + 300}", f"--screenshot={png}",
                                page.as_uri()], check=True, capture_output=True, timeout=120)
                crop_png(png, H // 3)
    print(f"style previews written to {out}")


def render(post_dir):
    post_dir = post_dir.resolve()  # the browser needs an absolute path for --screenshot
    c = load(post_dir / "content.json") or sys.exit(f"{post_dir}/content.json not found")
    posts = load(LEDGER, [])
    validate(c, posts, entry_for(posts, post_dir))
    handle = load(CONFIG)["handle"]
    if c.get("style") not in STYLES and c.get("style") not in V2_STYLES:
        # next look in the rotation (ACTIVE_STYLES); written back so re-renders and publish agree. A post that
        # names any look, active or paused, keeps it.
        own = entry_for(posts, post_dir)
        c["style"] = ACTIVE_STYLES[sum(1 for p in posts if p.get("dir") and p is not own) % len(ACTIVE_STYLES)]
        save(post_dir / "content.json", c)
    slides = all_slides(c, handle)
    for old in post_dir.glob("slide-*.png"):
        old.unlink()
    exe = browser()
    with tempfile.TemporaryDirectory() as tmp:
        def shot(name, page_html, height):
            page, out = Path(tmp) / f"{name}.html", post_dir / f"{name}.png"
            page.write_text(page_html, encoding="utf-8")
            subprocess.run([exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                            "--virtual-time-budget=5000",  # lets web fonts arrive before the picture is taken
                            *(["--no-sandbox"] if os.name != "nt" else []),  # a cloud container runs as root
                            # the window is taller than the slide and the extra is cut off afterwards: on Linux the
                            # browser's own frame comes out of the window height, which clipped the foot of each slide
                            f"--user-data-dir={tmp}/profile", f"--window-size={W},{height + 300}", f"--screenshot={out}",
                            page.as_uri()], check=True, capture_output=True, timeout=120)
            crop_png(out, height)
            if struct.unpack(">II", out.read_bytes()[16:24]) != (W, height):
                sys.exit(f"{out.name} did not come out at {W}x{height}")

        for i, s in enumerate(slides):
            shot(f"slide-{i + 1}", slide_html(s, i, len(slides), handle, c.get("badge", ""), c["style"], c["keyword"], art=c.get("art", "")), H)
        # the Story that announces the post: the hook, and the word to reply with
        story = {"kicker": c["slides"][0].get("kicker") or "New post", "title": c["slides"][0]["title"], "word": c["keyword"],
                 "body": f"Reply with *{c['keyword']}* and I'll DM you the link.\nFollow *@{handle}* first."}
        shot("story", slide_html(story, 0, 1, handle, style=c["style"], keyword=c["keyword"], tall="NEW POST", art=c.get("art", "")), 1920)
        # the Reel: the same slides in the tall shape, three seconds each. Reels are what Instagram shows non-followers.
        ffmpeg, made = encoder(), "no Reel (no ffmpeg found)"
        for old in list(post_dir.glob("reel-*.png")) + list(post_dir.glob("reel.mp4")):
            old.unlink()
        if ffmpeg:
            listing = ""
            for i, s in enumerate(slides):
                shot(f"reel-{i + 1}", slide_html(s, i, len(slides), handle, c.get("badge", ""), c["style"], c["keyword"],
                                                 tall=f"{i + 1:02d} / {len(slides):02d}", foot=f"COMMENT {c['keyword']}", art=c.get("art", "")), 1920)
                listing += f"file '{(post_dir / f'reel-{i + 1}.png').as_posix()}'\nduration {2 if i in (0, len(slides) - 1) else 3}\n"
            listing += f"file '{(post_dir / f'reel-{len(slides)}.png').as_posix()}'\n"  # ffmpeg needs the last frame named twice
            (Path(tmp) / "reel.txt").write_text(listing, encoding="utf-8")
            # Music is mixed into the file itself: Instagram's own catalogue, asked for through the API, came out silent.
            # Tracks live in music/ (only ones the owner may use commercially) and take turns, one per post.
            seconds = 3 * (len(slides) - 2) + 2 + 4  # hook 2s, each slide 3s, the comment slide held for 4s
            tracks = sorted(f for f in (ROOT / "music").glob("*") if f.suffix.lower() in (".mp3", ".m4a", ".wav", ".ogg"))
            track = tracks[sum(1 for p in posts if p.get("dir") and p is not entry_for(posts, post_dir)) % len(tracks)] if tracks else None
            sound = (["-stream_loop", "-1", "-i", str(track), "-filter_complex",
                      f"[1:a]loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=in:d=0.4,afade=t=out:st={seconds - 1.5}:d=1.5[a]", "-map", "0:v", "-map", "[a]"]
                     if track else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"])
            # the narrated video Reel first; the slideshow of reel-*.png is the fallback
            video = video_reel(post_dir, handle, track, ffmpeg)
            if not video:
                subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(Path(tmp) / "reel.txt"),
                                *sound, "-t", str(seconds), "-vf", "fps=30,format=yuv420p",
                                "-c:v", "libx264", "-crf", "20", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart",
                                str(post_dir / "reel.mp4")], check=True, capture_output=True, timeout=600)
            (post_dir / "story.mp4").unlink(missing_ok=True)
            if track:  # the API cannot add music to a Story, so the Story is a short video with the track inside it
                subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-loop", "1", "-i", str(post_dir / "story.png"),
                                "-stream_loop", "-1", "-i", str(track), "-filter_complex",
                                "[1:a]loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=in:d=0.4,afade=t=out:st=10.5:d=1.5[a]",
                                "-map", "0:v", "-map", "[a]", "-t", "12", "-vf", "fps=30,format=yuv420p",
                                "-c:v", "libx264", "-crf", "20", "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
                                "-movflags", "+faststart", str(post_dir / "story.mp4")],
                               check=True, capture_output=True, timeout=600)
            made = f"reel.mp4 with {track.name}" if track else "reel.mp4 (silent: no tracks in music/)"
            made = f"narrated video {made}: look at reel/sheet.png" if video else f"slideshow {made}"
    print(f"rendered {len(slides)} slides, story.png and {made} ({c['style']} style) in {post_dir}: "
          "look at every slide before publishing")


# ---------------------------------------------------------------- publish

def entry_for(posts, post_dir):
    rel = post_dir.resolve().relative_to(ROOT).as_posix()
    return next((p for p in posts if p.get("dir") == rel), None)


def services_text(cfg):
    """The owner's other products: one per block, a blank line between them and its emoji in front."""
    return "✨ Additional services ✨" + "".join(
        f"\n\n{s.get('tap', '•').split()[0]} {s['label']}\n{s['url']}" for s in cfg.get("services", []))


def services_button():
    """Put the "Additional services" message on Zernio as a tiny workflow that a DM button starts, and remember its
    id in data/topics.json. Run again after changing `services`; then run refresh-dms."""
    cfg = load(CONFIG)
    acct, profile = account()
    name = "ManyReply additional services"
    graph = {"nodes": [{"id": "t", "type": "trigger", "config": {"triggerType": "api_call"}},
                       {"id": "list", "type": "send_message", "config": {"messageType": "text", "text": services_text(cfg)}},
                       {"id": "done", "type": "end", "config": {}}],
             "edges": [{"id": "e0", "source": "t", "target": "list"}, {"id": "e1", "source": "list", "target": "done"}]}
    old = next((w for w in zernio("GET", "/workflows")["workflows"] if w["name"] == name), None)
    if old:
        if old["status"] == "active":
            zernio("POST", f"/workflows/{old['id']}/pause")
        zernio("PATCH", f"/workflows/{old['id']}", graph)
        wid = old["id"]
    else:
        wid = zernio("POST", "/workflows", {"profileId": profile, "accountId": acct["_id"], "platform": "instagram",
                                            "name": name, **graph})["workflow"]["id"]
    zernio("POST", f"/workflows/{wid}/activate")
    cfg["services_workflow"] = wid
    save(CONFIG, cfg)
    print(f"{name}: workflow {wid} is active; now run refresh-dms")


FOLLOW_BUTTON = "Follow me 👉"  # the follow gate's first button: opens the profile (Zernio allows 20 characters)


def dm_fields(url):
    """Everything people are sent. The link DM reads "Here you go" and the link, with two buttons: one opens the link
    (its clicks are counted), one sends the owner's other products (`services` in data/topics.json) as a second
    message. Until `python manyreply.py services` has been run, the products are listed in the text instead.
    Both follow-gate messages read the same, because a non-follower may see either one first."""
    cfg = load(CONFIG)
    text, buttons = f"Here you go 😊✨\n{url}", [{"type": "url", "title": "Open the link", "url": url}]
    if cfg.get("services_workflow"):
        buttons.append({"type": "postback", "title": "Additional services",  # this payload is how a tap starts a workflow
                        "payload": f"zernio:workflow:{cfg['services_workflow']}"})
    elif cfg.get("services"):
        text += "\n\n\n" + services_text(cfg)
    if len(text) > 640:  # Meta's cap for a message with a button: the button still carries the link
        text = text.replace(f"\n{url}", "", 1)
    ask = (f"Tap “Follow me” to open my profile and follow @{cfg['handle']}, "
           f"then come back here and tap “I'm following ✅” and I'll send it right over 👇")
    return {"dmMessage": text[:640], "buttons": buttons,
            # two buttons: "Follow me" opens the profile (Zernio adds that link itself), "I'm following" re-checks and sends it
            "followGate": {"message": f"Almost there! This link is for followers only.\n\n{ask}",
                           "buttonLabel": "I'm following ✅",
                           "profileButtonLabel": FOLLOW_BUTTON,
                           "notFollowingMessage": f"This link is for followers only 🙌\n\n{ask}"}}


def apply_dm_wording(soft=False):
    """Re-apply the current DM wording and buttons to every automation on Zernio. With soft=True an automation Zernio
    refuses (a deleted one, say) is reported and skipped, so the rest still go through. Returns (updated, failed)."""
    posts = [p for p in load(LEDGER, []) if p.get("automation_id")]
    count = {"done": 0, "failed": 0}

    def patch(automation_id, body):
        try:
            zernio("PATCH", f"/comment-automations/{automation_id}", body)
            count["done"] += 1
        except RuntimeError as err:
            if not soft:
                raise
            count["failed"] += 1
            print(f"  could not update {automation_id}: {str(err)[:160]}")

    for p in posts:
        fields = dm_fields(p.get("link", p["repo"]))
        patch(p["automation_id"], {**fields, "alsoMatchInDms": True})
        for extra in ("story", "reel"):
            if p.get(extra, {}).get("automation_id"):
                patch(p[extra]["automation_id"], fields)
        print(f"updated {p['keyword']}")
        time.sleep(1.2)  # Zernio allows 60 calls a minute
    return count["done"], count["failed"]


def refresh_dms():
    apply_dm_wording()


def gate_version():
    gate = dm_fields("https://example.com")["followGate"]
    return hashlib.sha1(json.dumps(gate, sort_keys=True).encode()).hexdigest()[:12]


def refresh_gate_if_changed():
    """The follow gate is the first thing a non-follower sees, and people comment on older posts too. So when its wording
    or buttons change (this is what makes the "Follow me" button appear), it is pushed ONCE to every automation already
    live on Zernio, not only to future posts. data/dm-wording.json remembers what is live. If Zernio takes none of it
    (down, no key), nothing is remembered and the next run tries again. Other DM wording still needs `refresh-dms`."""
    version = gate_version()
    if load(DM_WORDING, {}).get("followGate") == version:
        return
    print("follow-gate wording changed: updating every automation on Zernio")
    done, failed = apply_dm_wording(soft=True)
    if done or not failed:
        save(DM_WORDING, {**load(DM_WORDING, {}), "followGate": version})
    print(f"follow gate: {done} automations updated" + (f", {failed} could not be (see above)" if failed else ""))


def funnel_version():
    nodes, edges = funnel_graph(load(CONFIG), env("FUNNEL_WEBHOOK"))
    return hashlib.sha1(json.dumps([nodes, edges], sort_keys=True).encode()).hexdigest()[:12]


def refresh_funnel_if_changed():
    """Like the follow gate: when the DM funnel's steps or wording change (the check-in is one), the funnel already on
    Zernio is updated once, by the daily run that holds the key. It never creates one (the first is a draft the owner
    makes with `funnel` and activates), and `funnel` leaves it active or paused as it found it. If Zernio takes
    none of it, nothing is remembered and the next run tries again."""
    version = funnel_version()
    if load(DM_WORDING, {}).get("funnel") == version:
        return
    name = "ManyReply DM funnel (instagram)"
    if not any(w["name"] == name for w in zernio("GET", "/workflows")["workflows"]):
        return print("DM funnel changed, but none is on Zernio yet: run `python manyreply.py funnel` to make the draft")
    print("DM funnel changed: updating it on Zernio")
    funnel()
    save(DM_WORDING, {**load(DM_WORDING, {}), "funnel": version})


def funnel_graph(cfg, webhook=None):
    """The DM funnel: someone messages the account, is asked what they are into, and gets the matching product
    (`services` in data/topics.json), or is handed to the owner when they want something built or ask a question.
    Keyword DMs and button taps belong to the comment automations and are left alone. An ice breaker tapped on the
    profile already says what they want and skips the menu (typed first messages do not: too easy to misread). Followers are welcomed first."""
    f, services = cfg["funnel"], [x for x in cfg["services"] if x.get("tap")]
    nodes, edges = [], []

    def node(id, type, **config):
        nodes.append({"id": id, "type": type, "config": config})

    def edge(a, b, handle=None):
        edges.append({"id": f"e{len(edges)}", "source": a, "target": b, **({"sourceHandle": handle} if handle else {})})

    def rule(id, variable, operator, value=None):
        return {"id": id, "variable": variable, "operator": operator, **({"value": value} if value else {})}

    node("t", "trigger", triggerType="inbound_message", keywords=[], matchType="any", onlyFirstMessage=False,
         cooldownHours=f["cooldown_hours"])
    # ponytail: a one-word message that is not a greeting is taken for a post's comment word; a word list from the
    # ledger would be exact but would need the live workflow paused and edited on every post
    node("mine", "condition", default="default", rules=[
        rule("ours", "postback.payload", "starts_with", "funnel:"),  # an ice breaker (see ice_breakers)
        rule("tap", "postback.payload", "exists"),
        rule("share", "lastMessage", "not_exists"),  # a shared post or Reel (no text): never a conversation
        rule("word", "lastMessage", "matches", r"^\s*(?!(hi|hey|hello|yo|sup|hola|info|help)\b)\S+\s*$")])
    node("skip", "end")
    taps = [x["tap"] for x in services] + [f["build_tap"], f["look_tap"]]
    node("fromtap", "set_variable", assignments=[{"name": "pick", "value": "{{postback.payload}}"}])
    # Instagram delivers a tapped ice breaker as an ordinary message holding the question, so those are recognised by text
    node("ice", "condition", default="default", rules=[rule("yes", "lastMessage", "matches", r"^\s*(" + "|".join(
        re.escape(q["question"]) for q in f["ice_breakers"]) + r")\s*$")])
    node("fromice", "set_variable", assignments=[{"name": "pick", "value": "{{lastMessage}}"}])
    node("first", "condition", default="default", rules=[
        *[rule(f"s{i}", "pick", "matches", x["match"]) for i, x in enumerate(services)],
        rule("build", "pick", "matches", f["build_match"])])
    # Instagram never says when someone follows, so the welcome goes to a follower the first time they write in,
    # and only once: it tags them "welcomed" and anyone tagged gets the plain menu after that.
    node("who", "condition", default="default", rules=[rule("seen", "contact.tags", "has_tag", "welcomed"),
                                                        rule("fol", "contact.isFollower", "is_true")])
    node("tagw", "add_tag", tag="welcomed")
    node("welcome", "send_message", messageType="text", text=f["welcome"],
         quickReplies=[{"title": f["welcome_tap"], "payload": f["welcome_tap"]}])
    node("waitw", "wait_for_reply", saveAs="ok", timeoutMinutes=f["wait_minutes"])
    node("ask", "send_message", messageType="text", text=f["question"], quickReplies=[{"title": t, "payload": t} for t in taps])
    node("menu", "send_message", messageType="text", text=f["hello"] + "\n\n" + f["question"],
         quickReplies=[{"title": t, "payload": t} for t in taps])
    node("wait", "wait_for_reply", saveAs="pick", timeoutMinutes=f["wait_minutes"])
    node("nudge", "send_message", messageType="text", text=f["nudge"], quickReplies=[{"title": t, "payload": t} for t in taps])
    node("wait2", "wait_for_reply", saveAs="pick", timeoutMinutes=f["wait_minutes"])
    node("route", "condition", default="default", rules=[
        *[rule(f"s{i}", "pick", "matches", x["match"]) for i, x in enumerate(services)],
        rule("build", "pick", "matches", f["build_match"]), rule("look", "pick", "matches", f["look_match"])])
    node("done", "end")
    node("human", "handoff")
    edge("t", "mine"); edge("mine", "skip", "tap"); edge("mine", "skip", "share"); edge("mine", "skip", "word"); edge("mine", "fromtap", "ours")
    if webhook:  # optional: the owner's own log of who wrote in (FUNNEL_WEBHOOK in .env)
        node("log", "webhook", url=webhook, method="POST")
        edge("mine", "log", "default"); edge("log", "ice", "success"); edge("log", "ice", "error")
    else:
        edge("mine", "ice", "default")
    edge("fromtap", "first"); edge("ice", "fromice", "yes"); edge("fromice", "first"); edge("ice", "who", "default"); edge("first", "who", "default"); edge("first", "tagb", "build")
    edge("who", "menu", "seen"); edge("who", "welcome", "fol"); edge("who", "menu", "default")
    edge("welcome", "tagw"); edge("tagw", "waitw"); edge("waitw", "ask", "reply"); edge("waitw", "done", "timeout"); edge("ask", "wait")
    edge("menu", "wait"); edge("wait", "route", "reply"); edge("wait", "nudge", "timeout")
    edge("nudge", "wait2"); edge("wait2", "route", "reply"); edge("wait2", "done", "timeout")
    ci = f.get("checkin") or {}
    after_link = "cwait" if ci.get("enabled") else "done"  # with the check-in on, a sent link waits for it before the end
    for i, x in enumerate(services):
        edge("first", f"tag{i}", f"s{i}")
        node(f"tag{i}", "add_tag", tag="interest:" + re.sub(r"[^a-z0-9]+", "-", x["label"].lower()).strip("-"))
        node(f"send{i}", "send_message", messageType="text", text=x["pitch"],
             buttons=[{"type": "url", "title": f["button"], "url": x["url"]}])
        edge("route", f"tag{i}", f"s{i}"); edge(f"tag{i}", f"send{i}"); edge(f"send{i}", after_link)
    node("tagb", "add_tag", tag="lead:build")
    node("askb", "send_message", messageType="text", text=f["build_ask"])
    node("waitb", "wait_for_reply", saveAs="brief", timeoutMinutes=f["wait_minutes"])
    node("thanks", "send_message", messageType="text", text=f["build_thanks"])
    edge("route", "tagb", "build"); edge("tagb", "askb"); edge("askb", "waitb")
    edge("waitb", "thanks", "reply"); edge("waitb", "human", "timeout"); edge("thanks", "human")
    node("tools", "send_message", messageType="text", text=f["look"],
         buttons=[{"type": "url", "title": f["look_button"], "url": cfg["tools_url"]}])
    edge("route", "tools", "look"); edge("tools", "done")
    edge("route", "human", "default")  # a real question: the owner answers it
    if ci.get("enabled"):
        checkin_nodes(ci, f, node, edge, rule)
    return nodes, edges


CHECKIN_MAX_HOURS = 22  # Instagram only allows a promotional message within 24 hours of the person's last message


def checkin_nodes(ci, f, node, edge, rule):
    """A touch base after a link was sent. It waits `hours` for the person to write back: if they do, the owner is
    handed the conversation (nobody should write to a bot and be ignored); if not, one friendly question goes out.
    A yes goes into the "build me an app" branch, "just exploring" gets the tools page, anything else ends it.
    It cannot be set for days later: Instagram only lets an account send a promotional message within 24 hours of the
    person's last message (there is no 7-day or one-time-notification route for it), so the hours are capped."""
    hours = float(ci.get("hours", 20))
    if not 1 <= hours <= CHECKIN_MAX_HOURS:
        raise ValueError(f"funnel.checkin.hours must be 1 to {CHECKIN_MAX_HOURS}: Instagram only allows this message within 24 hours "
                         "of the person's last message")
    taps = [ci["yes_tap"], ci["maybe_tap"], ci["no_tap"]]
    if any(len(t) > 20 for t in taps):
        raise ValueError("funnel.checkin taps are 20 characters at most (an Instagram limit)")
    node("cwait", "wait_for_reply", saveAs="cireply", timeoutMinutes=round(hours * 60))
    node("cbusy", "add_tag", tag="replied-after-link")
    node("ctag", "add_tag", tag="checkin-sent")
    node("cask", "send_message", messageType="text", text=ci["text"], quickReplies=[{"title": t, "payload": t} for t in taps])
    node("cwait2", "wait_for_reply", saveAs="cipick", timeoutMinutes=f["wait_minutes"])
    node("croute", "condition", default="default", rules=[rule("yes", "cipick", "matches", ci["yes_match"]),
                                                          rule("maybe", "cipick", "matches", ci["maybe_match"])])
    node("cyes", "add_tag", tag="interest:automation")
    node("cmaybe", "add_tag", tag="interest:exploring")
    edge("cwait", "cbusy", "reply"); edge("cbusy", "human"); edge("cwait", "ctag", "timeout"); edge("ctag", "cask")
    edge("cask", "cwait2"); edge("cwait2", "croute", "reply"); edge("cwait2", "done", "timeout")
    edge("croute", "cyes", "yes"); edge("cyes", "tagb"); edge("croute", "cmaybe", "maybe"); edge("cmaybe", "tools")
    edge("croute", "done", "default")


def funnel_account(platform):
    acct, profile = account()
    if platform == "facebook":  # the Facebook page connected under the same Zernio profile
        pages = [a for a in zernio("GET", "/accounts")["accounts"] if a["platform"] == "facebook"
                 and (a["profileId"]["_id"] if isinstance(a["profileId"], dict) else a["profileId"]) == profile]
        acct = pages[0] if len(pages) == 1 else sys.exit(f"expected one Facebook page in this profile, found {len(pages)}")
    return acct, profile


def funnel(platform="instagram"):
    """Put the DM funnel on Zernio. The first time it is created as a DRAFT (the owner activates it); after that
    the same workflow is updated in place and left in the state it was in."""
    acct, profile = funnel_account(platform)
    nodes, edges = funnel_graph(load(CONFIG), env("FUNNEL_WEBHOOK") if platform == "instagram" else None)
    name = f"ManyReply DM funnel ({platform})"
    old = next((w for w in zernio("GET", "/workflows")["workflows"] if w["name"] == name), None)
    if not old:
        made = zernio("POST", "/workflows", {"profileId": profile, "accountId": acct["_id"], "platform": platform,
                                             "name": name, "nodes": nodes, "edges": edges,
                                             "description": "Asks what the person is into and sends the matching product."})
        return print(f"draft workflow {made['workflow']['id']} on {platform} ({len(nodes)} steps). It is NOT active.")
    if old["status"] == "active":  # Zernio only lets a paused workflow be edited
        zernio("POST", f"/workflows/{old['id']}/pause")
    try:
        zernio("PATCH", f"/workflows/{old['id']}", {"nodes": nodes, "edges": edges})
    finally:  # a refused edit must never leave a live funnel switched off
        if old["status"] == "active":
            zernio("POST", f"/workflows/{old['id']}/activate")
    print(f"updated {name} ({len(nodes)} steps), left {old['status']}")


def ice_breakers(platform="instagram"):
    """The questions shown to someone opening a chat with the account for the first time. A tap goes into the funnel."""
    acct, _ = funnel_account(platform)
    path = "instagram-ice-breakers" if platform == "instagram" else "messenger-ice-breakers"
    asks = [{"question": q["question"][:80], "payload": "funnel:" + q["means"]} for q in load(CONFIG)["funnel"]["ice_breakers"]][:4]
    if platform == "facebook":  # Messenger wants them grouped by language
        asks = [{"locale": "default", "call_to_actions": asks}]
    zernio("PUT", f"/accounts/{acct['_id']}/{path}", {"ice_breakers": asks})
    print(f"{platform}: ice breakers set")


# The public reply under a word comment. "always": it goes up the moment the person is messaged (the link, or the
# follow-first message), so everyone who comments the word is told to look in their DMs. ("after_dm" waited for
# the link itself, which left anyone at the follow step with no reply.)
# {{username}} becomes the commenter's handle, so the @mention pings them.
COMMENT_REPLY = {"publicReplyPolicy": "always", "commentReply": "@{{username}} Sent to your DMs 📩",
                 "commentReplyVariations": ["@{{username}} Check your DMs 🚀", "@{{username}} It's in your DMs ✅",
                                            "@{{username}} Sent to your DMs 👀 (look in message requests too)"]}


def create_automation(keyword, url, name, post_id=None, story=False, dms=True):
    """Comment the keyword (or DM it, or reply to a Story with it) -> followers get the link by DM; everyone else
    is asked to follow first."""
    acct, profile = account()
    body = {
        "profileId": profile, "accountId": acct["_id"], "name": name, "keywords": [keyword],
        # On its own post the word may sit inside a sentence, typos forgiven. A word that answers on EVERY post
        # (older posts) must be the whole comment, or everyday words like FREE or VIDEO would fire constantly.
        **({"matchMode": "word", "typoTolerance": True} if post_id or story else {"matchMode": "exact"}),
        **dm_fields(url),
        "audience": {"followerStatus": "follower", "whenUnknown": "verify"},
    }
    if story:  # answers the word as a reply to any Story of the account (the word itself is unique to one post)
        body["trigger"] = "story_reply"
    else:
        body.update(alsoMatchInDms=dms, **COMMENT_REPLY)
    if post_id:  # bound to one Zernio post: arms itself the moment that post goes live
        body["postId"] = post_id
    return zernio("POST", "/comment-automations", body)["automation"]["id"]


def local_now():
    return datetime.now().astimezone()  # the owner's time: see the TZ lines under `env`


def go_live_at(times, n):
    """When post number n goes out: today's slot in the owner's rotation of posting times (local time), or two
    minutes from now if that time has already passed. Rotating the time is how we learn which hour works."""
    soon = local_now() + timedelta(minutes=2)
    if not times:
        return soon
    hour, minute = map(int, times[n % len(times)].split(":"))
    return max(local_now().replace(hour=hour, minute=minute, second=0, microsecond=0), soon)


def upload(file):
    kind = {"png": ("image/png", "image"), "mp4": ("video/mp4", "video")}[file.suffix[1:]]
    up = zernio("POST", "/media/presign", {"filename": file.name, "contentType": kind[0]})
    http("PUT", up["uploadUrl"], raw=file.read_bytes(), headers={"Content-Type": kind[0]})
    return {"url": up["publicUrl"], "type": kind[1]}


def schedule(text, media, when, key, options=None):
    acct, _ = account()
    target = {"platform": "instagram", "accountId": acct["_id"], **({"platformSpecificData": options} if options else {})}
    return zernio("POST", "/posts", {
        "content": text, "mediaItems": media, "platforms": [target],
        "scheduledFor": when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), "timezone": "UTC",
    }, **{"Idempotency-Key": key})["post"]["_id"]


def settle(item, link="instagram_url"):
    """Ask Zernio whether a scheduled post (or Reel) has gone out, and record its link once it has."""
    post = zernio("GET", f"/posts/{item['zernio_post_id']}")["post"]
    platform = (post.get("platforms") or [{}])[0]
    if post["status"] == "published":
        item.update({"status": "live", link: platform.get("platformPostUrl")})
    elif post["status"] in ("failed", "partial", "cancelled"):
        item.update(status=post["status"], error=str(platform.get("errorMessage"))[:300])
    return platform


def mark_posted(entry):
    """A requested repo that has gone live is ticked off the queue, so it can never be posted twice."""
    q = load_queue()
    for item in q["items"]:
        if norm(item["url"]) == norm(entry["repo"]) and item["status"] == "waiting":
            item.update(status="posted", posted=entry["date"])
            save(QUEUE, q)


def reel_time(times, when):
    """The Reel goes out at the next posting time at least two hours after the carousel, else three hours after it,
    so the two do not compete for the same viewers."""
    local = when.astimezone()
    for t in sorted(times):
        hour, minute = map(int, t.split(":"))
        slot = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if slot >= local + timedelta(hours=2):
            return slot
    return local + timedelta(hours=3)


def reel_options(cfg):
    """Keep the Reel off the profile grid unless the owner wants it there, and add music when Instagram allows it."""
    options = {"shareToFeed": bool(cfg.get("reel_on_grid"))}
    if cfg.get("reel_trial"):
        options["trialParams"] = {"graduationStrategy": "SS_PERFORMANCE"}
    if cfg.get("reel_music") is not None:
        acct, _ = account()
        try:  # the music catalogue only opens to accounts connected to Zernio through Facebook Login
            query = urllib.parse.urlencode({"audioType": "music", **({"q": cfg["reel_music"]} if cfg["reel_music"] else {})})
            tracks = zernio("GET", f"/accounts/{acct['_id']}/instagram/audio?{query}").get("audio", [])
            if tracks:
                options["audioConfiguration"] = {"audioId": tracks[0]["audioId"], "audioVolume": 100, "videoVolume": 0}
        except RuntimeError:
            pass  # silent Reel
    return options


def publish(post_dir, right_away=False):
    c = load(post_dir / "content.json") or sys.exit(f"{post_dir}/content.json not found")
    posts, cfg = load(LEDGER, []), load(CONFIG)
    entry = entry_for(posts, post_dir)
    validate(c, posts, entry)
    pngs = sorted(post_dir.glob("slide-*.png"), key=lambda p: int(p.stem.split("-")[1]))
    if len(pngs) != len(c["slides"]) + 1 + bool(c.get("recap")):
        sys.exit("slides are missing or stale: run render first")
    if not entry:
        when = (local_now() + timedelta(minutes=2) if right_away  # --now: the owner asked for it straight away
                else go_live_at(cfg.get("post_times", []), sum(1 for p in posts if p.get("dir"))))
        asked = next((i["source"] for i in waiting(load_queue()) if norm(i["url"]) == norm(c["repo"])), None)  # who requested it
        mine = norm(c["repo"]) in {norm(app_id(a)) for a in my_apps()}
        starred = is_favorite(c["repo"]) and not mine and asked != "telegram"  # a Telegram request keeps its top place
        source = "favorite" if starred else asked or ("app" if mine else "search")
        entry = {"date": when.astimezone(timezone.utc).isoformat(timespec="seconds"), "repo": c["repo"],
                 "keyword": c["keyword"], "title": c.get("title") or c["repo"].split("/")[-1], "topic": c.get("topic", ""),
                 "why": c.get("why", ""), "style": c.get("style", ""), "reel_look": c.get("reelLook", ""), "hook": c.get("hook", ""), "source": source,
                 "slot": when.strftime("%H:%M"),
                 "dir": post_dir.resolve().relative_to(ROOT).as_posix(), "status": "publishing",
                 **({"link": c["link"]} if c.get("link") else {})}
        posts.append(entry)
    if entry["status"] in ("failed", "partial", "cancelled"):  # Instagram refused it: clear the dead bookings and go again
        for old in (entry, entry.get("story", {}), entry.get("reel", {})):
            if old.get("automation_id"):
                try:
                    zernio("DELETE", f"/comment-automations/{old['automation_id']}")
                except RuntimeError:
                    pass
        again = go_live_at([], 0)
        entry["no_collab"] = True  # if a collaborator invite was the problem, do not repeat it
        for stale in ("zernio_post_id", "automation_id", "story", "reel", "error", "instagram_url"):
            entry.pop(stale, None)
        entry.update(status="publishing", date=again.astimezone(timezone.utc).isoformat(timespec="seconds"),
                     slot=again.strftime("%H:%M"))
        save(LEDGER, posts)
    when = max(datetime.fromisoformat(entry["date"]), now() + timedelta(minutes=2))
    # The ledger is saved after every step, so a crashed run picks up where it stopped instead of posting twice.
    # Zernio also refuses to book the same key twice; the date keeps a deliberate repost from being mistaken for one.
    key = f"{entry['dir']}@{entry['date']}"
    if not entry.get("zernio_post_id"):
        media = [upload(p) for p in pngs]
        invited = [u.lstrip("@") for u in c.get("collaborators", [])][:3] if not entry.get("no_collab") else []
        try:
            entry["zernio_post_id"] = schedule(c["caption"], media, when, key, {"collaborators": invited} if invited else None)
        except RuntimeError as err:  # a collaborator Instagram will not accept must never cost the day's post
            if not invited:
                raise
            print(f"posting without collaborators ({str(err)[-160:]})")
            entry["no_collab"] = True
            entry["zernio_post_id"] = schedule(c["caption"], media, when, key + "/solo")
        save(LEDGER, posts)
    if not entry.get("automation_id"):
        entry["automation_id"] = create_automation(c["keyword"], c.get("link") or c["repo"], f"{c['keyword']} -> {c.get('link') or c['repo']}",
                                                   entry["zernio_post_id"])
        save(LEDGER, posts)
    story = entry.setdefault("story", {})
    if (post_dir / "story.png").exists():  # a Story five minutes behind the post, answered when someone replies the word
        if not story.get("zernio_post_id"):
            clip = post_dir / "story.mp4"  # the Story with music, when render could make one
            story["zernio_post_id"] = schedule(f"Story for {c['keyword']}", [upload(clip if clip.exists() else post_dir / "story.png")],
                                               when + timedelta(minutes=5), key + "/story", {"contentType": "story"})
            save(LEDGER, posts)
        if not story.get("automation_id"):
            story["automation_id"] = create_automation(c["keyword"], c.get("link") or c["repo"], f"{c['keyword']} (story reply)", story=True)
            save(LEDGER, posts)
    reel = entry.setdefault("reel", {})
    if (post_dir / "reel.mp4").exists():  # never allowed to sink the post: the carousel and Story are already booked
        try:
            if not reel.get("zernio_post_id"):
                later = when + timedelta(minutes=15) if right_away else reel_time(cfg.get("post_times", []), when)
                head, cut, tags = c["caption"].rpartition("\n\n#")  # Zernio refuses two posts with identical text
                text = f"{head}\n\nThe swipe-through version with every detail is on my page.\n\n#{tags}" if cut else c["caption"]
                reel["zernio_post_id"] = schedule(text, [upload(post_dir / "reel.mp4")], later, key + "/reel",
                                                  reel_options(cfg))
                reel.update(slot=later.strftime("%H:%M"), status="scheduled")
                save(LEDGER, posts)
            if not reel.get("automation_id"):
                reel["automation_id"] = create_automation(c["keyword"], c.get("link") or c["repo"], f"{c['keyword']} (reel) -> {c.get('link') or c['repo']}",
                                                          reel["zernio_post_id"], dms=False)
                save(LEDGER, posts)
        except RuntimeError as err:
            reel["error"] = str(err)[:300]
            save(LEDGER, posts)
            print(f"The Reel was not scheduled: {reel['error']}")
    platform = {}
    if entry["status"] != "live":
        entry["status"] = "scheduled"
        for _ in range(60 if when - now() < timedelta(minutes=6) else 0):  # a post going out now is watched until live
            platform = settle(entry)
            if entry["status"] != "scheduled":
                break
            time.sleep(10)
        if entry["status"] == "live":
            mark_posted(entry)
        save(LEDGER, posts)
    dashboard()
    if entry["status"] not in ("live", "scheduled"):
        sys.exit(f"Instagram did not publish it (status {entry['status']}): {json.dumps(platform)[:600]}")
    print(f"{entry['status'].upper()}: {entry.get('instagram_url') or 'goes out at ' + entry['slot']}  "
          f"(comment, DM or story-reply {c['keyword']} -> DM with {c['repo']})\n")
    email(post_dir)


def email(post_dir):
    """Write the 'your post is live' email as email.html (spaced, with headings) and print it as plain text too.
    Claude sends it with the Gmail connector: the HTML file as the rich body, the printed text as the fallback."""
    cfg, c = load(CONFIG), load(post_dir / "content.json")
    e = entry_for(load(LEDGER, []), post_dir) or sys.exit("that post is not in the ledger yet")
    esc, name, kw = html.escape, c["repo"].split("github.com/")[-1], c["keyword"]
    clock = lambda t: datetime.strptime(t, "%H:%M").strftime("%I:%M %p").lstrip("0") if t else "now"
    live = e.get("instagram_url")
    headline = "Your new carousel is live" if live else f"Your new carousel goes out today at {clock(e.get('slot'))}"
    when = [("Carousel", "live now" if live else clock(e.get("slot"))),
            ("Story", "five minutes after the carousel")]
    if e.get("reel", {}).get("slot"):
        when.append(("Reel", clock(e["reel"]["slot"])))
    facts = [("Repo", c["repo"]), ("Comment word", kw), ("Topic", c.get("topic", "")),
             ("Style", e.get("style") or c.get("style", "")), ("Slides", str(len(c["slides"]) + 1 + bool(c.get("recap"))))]
    slides = ([re.sub(r"[*]", "", sl["title"]) for sl in c["slides"]] + ["The short version"] * bool(c.get("recap"))
              + [f"Comment {kw}"])
    link = live or f"https://www.instagram.com/{cfg['handle']}/"
    subject = f"ManyReply {'is live' if live else 'is scheduled'}: {name} (comment {kw})"

    text = "\n\n\n".join([
        headline.upper(),
        "WHERE TO SEE IT\n\n" + link + ("" if live else "\n(the exact post link appears on the dashboard once it is live)"),
        "WHEN\n\n" + "\n".join(f"{k}: {v}" for k, v in when),
        "THE POST\n\n" + "\n".join(f"{k}: {v}" for k, v in facts),
        "WHY THIS ONE\n\n" + c.get("why", ""),
        "THE SLIDES\n\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(slides, 1)),
        "HOW THE CAPTION OPENS\n\n" + c["caption"].splitlines()[0],
        "DASHBOARD\n\n" + cfg["dashboard_url"],
    ] + (["PUBLIC TOOLS PAGE (for your bio)\n\n" + cfg["tools_url"]] if cfg.get("tools_url") else []))
    h2 = lambda t: f'<h2 style="font:700 13px Arial,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:#6A4CF0;margin:28px 0 10px">{t}</h2>'
    rows = lambda pairs: '<table style="border-collapse:collapse;font:15px/1.5 Arial,sans-serif">' + "".join(
        f'<tr><td style="padding:4px 18px 4px 0;color:#5E5568;vertical-align:top;white-space:nowrap">{esc(k)}</td>'
        f'<td style="padding:4px 0;color:#16131C">{esc(v)}</td></tr>' for k, v in pairs) + "</table>"
    page = (
        '<div style="max-width:560px;margin:0 auto;padding:8px 4px;font:15px/1.6 Arial,sans-serif;color:#16131C">'
        f'<h1 style="font:700 22px/1.3 Arial,sans-serif;margin:0 0 6px">{esc(headline)}</h1>'
        f'<p style="margin:0 0 20px;color:#5E5568">{esc(name)} &middot; comment word <b style="color:#16131C">{esc(kw)}</b></p>'
        f'<p style="margin:0"><a href="{esc(link)}" style="display:inline-block;background:#6A4CF0;color:#fff;text-decoration:none;'
        f'font-weight:700;padding:12px 20px;border-radius:999px">{"Open the post" if live else "Open your Instagram"}</a></p>'
        + ("" if live else '<p style="margin:10px 0 0;color:#5E5568;font-size:13px">The exact post link appears on the dashboard once it is live.</p>')
        + h2("When") + rows(when) + h2("The post") + rows(facts)
        + h2("Why this one") + f'<p style="margin:0">{esc(c.get("why", ""))}</p>'
        + h2("The slides") + '<ol style="margin:0;padding-left:22px">' + "".join(f'<li style="margin:0 0 6px">{esc(t)}</li>' for t in slides) + "</ol>"
        + h2("How the caption opens") + f'<p style="margin:0">{esc(c["caption"].splitlines()[0])}</p>'
        + h2("Dashboard") + f'<p style="margin:0"><a href="{esc(cfg["dashboard_url"])}" style="color:#6A4CF0">{esc(cfg["dashboard_url"])}</a></p>'
        + (h2("Public tools page (for your bio)") + f'<p style="margin:0"><a href="{esc(cfg["tools_url"])}" style="color:#6A4CF0">'
           f'{esc(cfg["tools_url"])}</a></p>' if cfg.get("tools_url") else "") + "</div>")
    (post_dir / "email.html").write_text(page, encoding="utf-8")
    print(f"TO: {notify_email() or 'NOTIFY_EMAIL is not set in .env'}\nSUBJECT: {subject}\n"
          f"HTML BODY: {post_dir / 'email.html'}\nPLAIN BODY:\n{text}\n")


def pull_topics():
    """Apply what the owner changed on the dashboard (after `git pull`): the topic list becomes the search list,
    and each requested repo joins the queue behind anything sent by Telegram."""
    cfg, q = load(CONFIG), load_queue()
    edits = load(EDITS, {"topics": cfg["topics"], "requests": []})
    outcomes = []
    for url in edits.get("requests", []):
        url = str(url)
        outcomes += queue_add(q, load(LEDGER, []), url, "dashboard",
                              website=url.startswith("https://") and not REPO_RE.search(url))
    for url in edits.get("removed", []):  # the owner pressed Remove on a waiting repo
        for item in q["items"]:
            if item["url"] and norm(item["url"]) == norm(str(url)) and item["status"] == "waiting":
                item.update(status="skipped", note="removed on the dashboard")
                outcomes.append(f"{url}: removed")
    save(QUEUE, q)
    topics = [{"name": t["name"].strip(), "queries": [x.strip() for x in t["queries"] if x.strip()]}
              for t in edits.get("topics", []) if t.get("name") and t.get("queries")]
    if topics:
        cfg["topics"] = topics
        save(CONFIG, cfg)
    save(EDITS, {"topics": cfg["topics"], "requests": [], "removed": [], "apps": edits.get("apps", []),
                 "favorites": edits.get("favorites", [])})  # applied now (favorites are kept: they are a standing list)
    refresh_stars(only_missing=True)  # the star count of anything new, if GitHub can be reached from here
    print(f"dashboard requests: {len(outcomes)}" + "".join(f"\n  {o}" for o in outcomes))
    print("topics, in priority order: " + ", ".join(t["name"] for t in cfg["topics"]))


def legacy(keyword, url):
    """A keyword promised on an older post: reserve it, and answer it on ANY post of the account."""
    posts = load(LEDGER, [])
    keyword, link = keyword.upper(), clean_link(url)
    if keyword in {p["keyword"].upper() for p in posts}:
        print(f"{keyword} is already in the ledger, left as it is")
        return
    repo = REPO_RE.match(link)  # a GitHub repo is also recorded by its root, so it is never posted again
    posts.append({"date": now().isoformat(timespec="seconds"), "keyword": keyword, "status": "legacy", "link": link,
                  "repo": f"https://github.com/{repo[1]}/{repo[2].removesuffix('.git')}" if repo else link,
                  "automation_id": create_automation(keyword, link, f"{keyword} (older post)")})
    save(LEDGER, posts)
    print(f"{keyword} now sends {link}")


def sync():
    """Pull everything measurable: DM funnel numbers per word, Instagram numbers per post, follower history."""
    posts = load(LEDGER, [])
    acct, profile = account()
    aid = acct["_id"]
    autos = {a["id"]: a.get("stats", {}) for a in zernio("GET", f"/comment-automations?profileId={profile}")["automations"]}
    analytics = zernio("GET", f"/analytics?accountId={aid}&platform=instagram&limit=100")["posts"]
    by_url = {(a.get("platformPostUrl") or "").rstrip("/"): a for a in analytics}
    for e in posts:
        if e.get("status") in ("scheduled", "publishing") and e.get("zernio_post_id"):
            settle(e)  # a post scheduled for later in the day: has it gone out?
            if e["status"] == "live":
                mark_posted(e)
            elif e["status"] != "scheduled":
                print(f"POST FAILED: {e['keyword']} did not go out ({e.get('error')}). Run: python manyreply.py publish {e['dir']}")
        reel = e.get("reel", {})
        if reel.get("zernio_post_id") and (reel.get("status") == "scheduled" or (reel.get("status") == "live" and not reel.get("url"))):
            settle(reel, "url")
        story = e.get("story", {})  # Stories vanish after a day, so only fresh ones are worth a link
        if (story.get("zernio_post_id") and not story.get("url") and e.get("status") == "live"
                and datetime.fromisoformat(e["date"]) > now() - timedelta(days=2)):
            try:
                settle(story, "url")
            except RuntimeError:
                pass
        seen = by_url.get((reel.get("url") or "").rstrip("/"), {}).get("analytics")
        if seen:
            reel["stats"] = {k: (seen.get(k) or 0) for k in ("likes", "comments", "reach", "views", "saves", "shares", "follows")}
            reel["stats"]["keyword_comments"] = autos.get(reel.get("automation_id"), {}).get("triggered", 0)
        stats = e.setdefault("stats", {})
        replies = autos.get(e.get("story", {}).get("automation_id"))
        if replies:
            stats.update(story_replies=replies.get("triggered", 0))
        if e.get("automation_id") in autos:
            a = autos[e["automation_id"]]
            stats.update(keyword_comments=a.get("triggered", 0), dms_sent=a.get("dmsSent", 0),
                         link_clicks=a.get("linkClicks", 0), gate_sent=a.get("followGateSent", 0),
                         gate_passed=a.get("followGatePassed", 0))
        ig = by_url.get((e.get("instagram_url") or "").rstrip("/"), {}).get("analytics")
        if ig:
            stats.update({k: (ig.get(k) or 0) for k in ("likes", "comments", "reach", "views", "saves", "shares", "follows")})
    save(LEDGER, posts)

    today = str(now().date())
    growth = load(GROWTH, {"followers": {}, "reviews": {"weekly": today, "monthly": today}})
    history = zernio("GET", f"/analytics/instagram/follower-history?accountId={aid}&metricType=time_series")["metrics"]
    growth["followers"].update({v["date"]: v["value"] for v in history.get("follower_count", {}).get("values", [])})
    growth["followers"][today] = acct.get("followersCount") or growth["followers"].get(today)
    window = f"since={(now() - timedelta(days=28)).date()}&until={now().date()}"  # Instagram refuses more than 30 days
    try:
        month = zernio("GET", f"/analytics/instagram/follower-history?accountId={aid}")["metrics"]
        reach = zernio("GET", f"/analytics/instagram/account-insights?accountId={aid}&{window}")["metrics"]
        growth["last_30_days"] = {**growth.get("last_30_days", {}),
                                  **{k: reach.get(k, {}).get("total") for k in ("reach", "views", "accounts_engaged")}}
        if month.get("followers_gained", {}).get("total") or month.get("followers_lost", {}).get("total"):
            growth["last_30_days"].update(gained=month["followers_gained"].get("total"), lost=month["followers_lost"].get("total"))
    except RuntimeError as err:
        print(f"account totals not refreshed this time: {str(err)[:160]}")
    ours = {p["instagram_url"].rstrip("/") for p in posts if p["status"] == "live" and p.get("instagram_url")}
    reels = {p["reel"]["url"].rstrip("/") for p in posts if p.get("reel", {}).get("url")}
    seen = {r["url"]: {**r, "gone": True} for r in growth.get("posts", []) if r.get("url")}  # gone unless listed again
    for a in analytics:
        url = a.get("platformPostUrl")
        if url and a.get("publishedAt"):
            seen[url] = {"date": a["publishedAt"][:10], "url": url, "kind": a.get("mediaType"),
                         "ours": url.rstrip("/") in ours, "reel": url.rstrip("/") in reels,
                         "caption": (a.get("content") or "")[:90],
                         **{k: (a["analytics"].get(k) or 0) for k in ("reach", "views", "likes", "comments", "saves", "shares", "follows")}}
    growth["posts"] = sorted(seen.values(), key=lambda r: r["date"], reverse=True)[:600]
    growth["synced"] = now().isoformat(timespec="seconds")
    save(GROWTH, growth)
    try:
        refresh_gate_if_changed()  # a changed follow-gate wording reaches the automations already live, once
    except (RuntimeError, OSError) as err:
        print(f"follow gate not updated ({str(err)[:160]}): it is tried again at the next run")
    try:
        refresh_funnel_if_changed()
    except (RuntimeError, OSError, ValueError, KeyError) as err:
        print(f"DM funnel not updated ({str(err)[:160]}): it is tried again at the next run")
    dashboard()
    print(f"synced {len(posts)} ledger entries, {len(growth['posts'])} Instagram posts, {len(growth['followers'])} days of followers")


def growth_scores(rows):
    """0-10 per post, relative to the best post in `rows`: follows 35, saves 25, shares 20, comments 10, each as a
    rate per person reached. (The owner's formula gives 10 to non-follower reach; Instagram does not report that
    per post, so the other four are scaled up to fill the 10.)"""
    weights = {"follows": 35, "saves": 25, "shares": 20, "comments": 10}
    rate = lambda r, k: (r.get(k) or 0) / r["reach"] if r.get("reach") else 0
    best = {k: max((rate(r, k) for r in rows), default=0) for k in weights}
    return [round(sum(w * rate(r, k) / best[k] for k, w in weights.items() if best[k]) / 9, 1) for r in rows]


def versus_typical(reach, rows):
    """How many times the account's own typical (median) post this one reached: 1.0 is a normal day, 3.0 a real hit."""
    usual = sorted(r["reach"] for r in rows if r.get("reach"))
    return round(reach / usual[len(usual) // 2], 1) if usual and reach else 0


def average(rows, key):
    return round(sum(r.get(key) or 0 for r in rows) / len(rows), 1) if rows else 0


def review():
    """Print the numbers for the growth review. Claude reads them, updates data/playbook.md and emails the owner."""
    growth, posts = load(GROWTH) or sys.exit("run sync first"), load(LEDGER, [])
    today, followers = now().date(), growth["followers"]

    def back(days):  # follower count on or before that day
        earlier = [d for d in sorted(followers) if d <= str(today - timedelta(days=days))]
        return followers[earlier[-1]] if earlier else None

    current = back(0)
    change = lambda days: "n/a" if back(days) is None else f"{current - back(days):+d}"
    last = growth.get("reviews", {})
    weekly = (today - datetime.fromisoformat(last.get("weekly", str(today))).date()).days >= 7
    monthly = last.get("monthly", str(today))[:7] != str(today)[:7]
    print(f"WEEKLY REVIEW: {'DUE' if weekly else 'not due'} (last {last.get('weekly')})")
    print(f"MONTHLY REVIEW: {'DUE' if monthly else 'not due'} (last {last.get('monthly')})\n")
    print(f"Followers: {current:,}   7 days: {change(7)}   30 days: {change(30)}")
    print(f"Last 30 days on the account: {growth.get('last_30_days')}\n")

    settled = [r for r in growth["posts"] if r["date"] <= str(today - timedelta(days=3))]  # Instagram lags ~48h
    print("Posts at least 3 days old, last 60 days (numbers have settled):")
    for label, rows in (("ManyReply carousels", [r for r in settled if r["ours"]]),
                        ("ManyReply Reels", [r for r in settled if r.get("reel")]),
                        ("Everything else", [r for r in settled if not r["ours"] and not r.get("reel")])):
        print(f"  {label}: {len(rows)} posts | avg reach {average(rows, 'reach')} | avg views {average(rows, 'views')} | "
              f"saves {sum(r['saves'] for r in rows)} | shares {sum(r['shares'] for r in rows)} | follows {sum(r['follows'] for r in rows)}")

    live = [p for p in posts if p["status"] == "live"]
    scores = growth_scores([p.get("stats", {}) for p in live])
    print("\nManyReply posts (newest first):")
    for p, sc in sorted(zip(live, scores), key=lambda x: x[0]["date"], reverse=True):
        st = p.get("stats", {})
        print(f"  {p['date'][:10]} {p['keyword']:<12} topic={p.get('topic')} style={p.get('style')} picked_by={p.get('source', 'search')} "
              f"| reach {st.get('reach', 0)} views {st.get('views', 0)} saves {st.get('saves', 0)} shares {st.get('shares', 0)} "
              f"follows {st.get('follows', 0)} | {versus_typical(st.get('reach', 0), settled)}x a typical post "
              f"| sends per 1,000 reached {round(1000 * st.get('shares', 0) / st['reach'], 1) if st.get('reach') else 0} "
              f"| posted at {p.get('slot', '?')} | story replies {st.get('story_replies', 0)} "
              f"| reel views {p.get('reel', {}).get('stats', {}).get('views', 0)} reach {p.get('reel', {}).get('stats', {}).get('reach', 0)} "
              f"follows {p.get('reel', {}).get('stats', {}).get('follows', 0)} "
              f"| word comments {st.get('keyword_comments', 0)} follow-gate sent {st.get('gate_sent', 0)} "
              f"passed {st.get('gate_passed', 0)} links sent {st.get('dms_sent', 0)} clicks {st.get('link_clicks', 0)} | score {sc}")
    for field in ("topic", "style", "hook", "slot"):
        print(f"\nBy {field}:")
        for value in sorted({p.get(field) or "-" for p in live}):
            rows = [p.get("stats", {}) for p in live if (p.get(field) or "-") == value]
            print(f"  {value}: {len(rows)} posts | avg reach {average(rows, 'reach')} | avg word comments "
                  f"{average(rows, 'keyword_comments')} | follows {sum(r.get('follows', 0) for r in rows)}")
    reeled = [p for p in live if p.get("reel") and p.get("reel_look")]
    print("\nBy Reel look (the Reel's own numbers; each look needs 3+ Reels before it means anything):")
    for value in sorted({p["reel_look"] for p in reeled}):
        rows = [p["reel"].get("stats", {}) for p in reeled if p["reel_look"] == value]
        print(f"  {value}: {len(rows)} Reels | avg reach {average(rows, 'reach')} | avg views {average(rows, 'views')} | "
              f"saves {sum(r.get('saves', 0) for r in rows)} | shares {sum(r.get('shares', 0) for r in rows)} | follows {sum(r.get('follows', 0) for r in rows)}")
    if not reeled:
        print("  (none yet: Reels made before looks existed have no look recorded)")
    older = [p for p in posts if p["status"] == "legacy" and p.get("stats", {}).get("keyword_comments")]
    print("\nOlder-post words that got comments: " + (", ".join(
        f"{p['keyword']} ({p['stats']['keyword_comments']})" for p in older) or "none"))


def reviewed(kind):
    growth = load(GROWTH) or sys.exit("run sync first")
    growth.setdefault("reviews", {})[kind] = str(now().date())
    save(GROWTH, growth)
    print(f"{kind} review recorded")


def review_email(kind, notes_path):
    """The weekly or monthly review as a finished email: a branded header with the dates, the numbers against the
    period before (filled in here), the best and worst post, then Claude's own findings from notes_path, a JSON file:
    {"headline": "...", "sections": [{"heading": "What worked", "points": ["...", "..."]}, ...]}."""
    cfg, growth, posts = load(CONFIG), load(GROWTH) or sys.exit("run sync first"), load(LEDGER, [])
    notes = load(Path(notes_path)) or sys.exit(f"{notes_path} not found")
    days, esc, today = (7 if kind == "weekly" else 30), html.escape, local_now().date()
    start, prev = today - timedelta(days=days), today - timedelta(days=2 * days)
    nice = lambda d: f"{d.day} {d:%b}"
    period = f"{nice(start)}–{nice(today)} {today.year}"
    followers = growth["followers"]
    on = lambda d: next((followers[k] for k in sorted(followers, reverse=True) if k <= str(d)), None)
    inside = lambda a, b: [r for r in growth["posts"] if str(a) < r["date"] <= str(b)]
    now_rows, was_rows = inside(start, today), inside(prev, start)
    total = lambda rows, k: sum(r.get(k) or 0 for r in rows)

    def change(v, w):  # the number, then its change in green or red
        if v is None:
            return "–", ""
        if w is None:
            return f"{v:,}", ""
        d = v - w
        colour = "#16A34A" if d > 0 else "#DC2626" if d < 0 else "#6B7280"
        return f"{v:,}", f'<span style="color:{colour};font-weight:700">{"▲" if d > 0 else "▼" if d < 0 else "="} {abs(d):,}</span>'

    f_now, f_start, f_prev = on(today), on(start), on(prev)
    gained = None if f_now is None or f_start is None else f_now - f_start
    gained_before = None if f_start is None or f_prev is None else f_start - f_prev
    table = [("Followers", f"{f_now:,}" if f_now is not None else "–",
              "" if gained is None else f'<span style="color:{"#16A34A" if gained > 0 else "#DC2626" if gained < 0 else "#6B7280"};'
              f'font-weight:700">{gained:+,} this {"week" if days == 7 else "month"}</span>'
              + ("" if gained_before is None else f' <span style="color:#6B7280">({gained_before:+,} the {"week" if days == 7 else "month"} before)</span>'))]
    for label, key in (("People reached", "reach"), ("Views", "views"), ("Saves", "saves"), ("Sends", "shares"),
                       ("Follows from posts", "follows"), ("Likes", "likes")):
        table.append((label, *change(total(now_rows, key), total(was_rows, key))))
    table.append(("Posts that went out", *change(len(now_rows), len(was_rows))))

    ours = [p for p in posts if p["status"] == "live" and str(start) < p["date"][:10] <= str(today)]
    ranked = sorted(ours, key=lambda p: (p.get("stats", {}).get("follows") or 0, p.get("stats", {}).get("reach") or 0), reverse=True)
    pick = lambda p, label: (label, p["keyword"], p["repo"].split("github.com/")[-1], p.get("instagram_url") or p["repo"],
                             p.get("stats", {}))
    standouts = [pick(ranked[0], "Best")] + ([pick(ranked[-1], "Weakest")] if len(ranked) > 1 else []) if ranked else []

    st = lambda k: sum(p.get("stats", {}).get(k) or 0 for p in ours)
    funnel = [("People reached by your carousels", st("reach"), "Instagram showed the posts to this many accounts."),
              ("Commented the word", st("keyword_comments"), "They asked for the link by commenting the post's word."),
              ("Asked to follow first", st("gate_sent"), "Non-followers get a follow request before the link."),
              ("Followed to unlock", st("gate_passed"), "New followers won by the link offer."),
              ("Links sent by DM", st("dms_sent"), "Each one is a person who now has the repo."),
              ("Clicked the link", st("link_clicks"), "They opened it: real interest.")]
    q = load_queue()
    pick = next_pick(posts, q)
    app = None if pick else app_due(posts)
    fav = None if pick or app else fav_due(posts, q)
    turn = (f"Your request {pick['url'].split('github.com/')[-1]} is next, then the search picks one." if pick else
            f"Your own app {app_name(app)} is next (one every 3 weeks)." if app else
            f"Your favorite {fav.split('github.com/')[-1]} is next (favorites come around every {FAV_EVERY_DAYS} days)." if fav else
            "The search picks the next post, then your next request goes." if waiting(q) else
            "Nothing of yours is waiting, so the search picks until you send a link (Telegram or the dashboard).")
    queued = {norm(i["url"]) for i in q["items"] if i["url"]} | {norm(p["repo"]) for p in posts}
    found = [c for c in (load(CANDIDATES, {}) or {}).get("candidates", []) if norm(c["url"]) not in queued][:3]
    accent, ink, muted, line = "#5B4CF6", "#111833", "#5B6688", "#E2E7F3"
    h2 = lambda t: (f'<h2 style="font:700 12px Arial,sans-serif;letter-spacing:.1em;text-transform:uppercase;color:{accent};'
                    f'margin:30px 0 10px">{esc(t)}</h2>')
    cell = f"padding:9px 12px;border-bottom:1px solid {line};font:14px/1.4 Arial,sans-serif"
    numbers = (f'<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse;border:1px solid {line};'
               f'border-radius:10px">' + "".join(
                   f'<tr><td style="{cell};color:{muted}">{esc(k)}</td><td style="{cell};color:{ink};font-weight:700;text-align:right">{v}</td>'
                   f'<td style="{cell};text-align:right;white-space:nowrap">{d}</td></tr>' for k, v, d in table) + "</table>")
    stand = "".join(
        f'<tr><td style="{cell};width:80px;color:{"#16A34A" if lab == "Best" else "#DC2626"};font-weight:700">{lab}</td>'
        f'<td style="{cell}"><a href="{esc(url)}" style="color:{ink};font-weight:700;text-decoration:none">{esc(name)}</a>'
        f'<br><span style="color:{muted};font-size:13px">{st.get("reach") or 0:,} reached &middot; {st.get("follows") or 0} follows &middot; '
        f'{st.get("saves") or 0} saves &middot; comment word {esc(kw)}</span></td></tr>' for lab, kw, name, url, st in standouts)
    sections = "".join(h2(s["heading"]) + '<ul style="margin:0;padding-left:20px">' + "".join(
        f'<li style="margin:0 0 8px">{esc(pt)}</li>' for pt in s.get("points", [])) + "</ul>" for s in notes.get("sections", []))
    title = f"ManyReply {kind} review"
    page = (
        f'<div style="background:#F3F5FB;padding:24px 10px;font:15px/1.6 Arial,sans-serif;color:{ink}">'
        '<div style="max-width:600px;margin:0 auto;background:#FFFFFF;border-radius:16px;overflow:hidden;border:1px solid #E2E7F3">'
        '<div style="background:#4C1D95;background-image:linear-gradient(135deg,#4C1D95,#6D28D9 50%,#3B6CF6);padding:26px 28px;color:#FFFFFF">'
        '<div style="font:800 20px/1 Arial,sans-serif;letter-spacing:-.01em">Many<span style="color:#C4B5FD">Reply</span></div>'
        f'<div style="font:700 12px Arial,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:#DDD6FE;margin:18px 0 4px">'
        f'{esc(kind.capitalize())} review &middot; {esc(period)}</div>'
        f'<div style="font:800 24px/1.25 Arial,sans-serif">{esc(notes.get("headline", title))}</div>'
        # the owner asked for the dashboard link up top, not only as the button at the end
        f'<div style="margin:14px 0 0;font:13px Arial,sans-serif;color:#DDD6FE">Dashboard: <a href="{esc(cfg["dashboard_url"])}" '
        f'style="color:#FFFFFF;font-weight:700">{esc(cfg["dashboard_url"])}</a></div></div>'
        '<div style="padding:6px 28px 28px">'
        + h2("The numbers") + numbers
        + f'<p style="margin:8px 0 0;color:{muted};font-size:12px">Against the {days} days before. Instagram\'s numbers lag about two days.</p>'
        + (h2("Standout posts") + f'<table role="presentation" style="width:100%;border-collapse:collapse">{stand}</table>' if stand else "")
        + sections
        + h2("How the system did") + f'<p style="margin:0 0 10px;color:{muted};font-size:13px">Every post walks people down '
          'the same path: see it, comment the word, follow, get the link. Where the numbers drop is what to fix.</p>'
        + f'<table role="presentation" style="width:100%;border-collapse:collapse">' + "".join(
            f'<tr><td style="{cell};width:56px;font-weight:800;color:{ink if n else muted};text-align:right">{n:,}</td>'
            f'<td style="{cell}"><b>{esc(label)}</b><br><span style="color:{muted};font-size:13px">{esc(why)}</span></td></tr>'
            for label, n, why in funnel) + "</table>"
        + h2("Whose turn") + f'<p style="margin:0">Your requests and the search take turns, one post each. {esc(turn)}</p>'
        + (h2("Worth posting soon") + f'<p style="margin:0 0 10px;color:{muted};font-size:13px">The best of what the daily '
           'search found. Send one to the Telegram bot or add it on the dashboard to post it on your turn.</p>'
           + "".join(f'<p style="margin:0 0 12px"><a href="{esc(c["url"])}" style="color:{ink};font-weight:700">{esc(c["name"])}</a>'
                     + (f' &middot; {c["stars"]:,} stars' if c.get("stars") else "")
                     + f'<br><span style="color:{muted};font-size:13px">{esc((c.get("description") or "")[:140])}</span></p>' for c in found)
           if found else "")
        + f'<p style="margin:30px 0 0"><a href="{esc(cfg["dashboard_url"])}" style="display:inline-block;background:{accent};color:#FFFFFF;'
          'text-decoration:none;font-weight:700;padding:12px 22px;border-radius:999px">Open the dashboard</a></p>'
        + '</div></div>'
        f'<p style="max-width:600px;margin:14px auto 0;text-align:center;color:{muted};font-size:12px">ManyReply v{VERSION} &middot; '
        f'Made with <a href="{PROJECT_URL}" style="color:{accent}">ManyReply</a></p></div>')
    out = ROOT / "reviews" / f"{today}-{kind}.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(page, encoding="utf-8")
    text = "\n\n".join([f"{title.upper()} · {period}", notes.get("headline", ""), "DASHBOARD\n" + cfg["dashboard_url"],
                        "THE NUMBERS\n" + "\n".join(f"{k}: {v} {re.sub(r'<[^>]+>', '', d)}" for k, v, d in table)]
                       + [s["heading"].upper() + "\n" + "\n".join(f"- {pt}" for pt in s.get("points", [])) for s in notes.get("sections", [])]
                       + ["HOW THE SYSTEM DID\n" + "\n".join(f"{n:,}  {label}" for label, n, _ in funnel),
                          "WHOSE TURN\n" + turn,
                          "WORTH POSTING SOON\n" + "\n".join(f"{c['name']}: {c['url']}" for c in found)])
    print(f"TO: {notify_email() or 'NOTIFY_EMAIL is not set'}\nSUBJECT: {title} · {period}\nHTML BODY: {out}\nPLAIN BODY:\n{text}\n")


def live_or_booked(posts):
    return [p for p in posts if p.get("dir") and p.get("status") in ("live", "scheduled")]


def last_live(posts):
    dates = [p["date"] for p in posts if p.get("status") in ("live", "scheduled")]
    return datetime.fromisoformat(max(dates)) if dates else None


def posted_days(posts):
    """The calendar days (owner's local time) that have a live or booked post."""
    return {datetime.fromisoformat(p["date"]).astimezone().date()
            for p in posts if p.get("dir") and p.get("status") in ("live", "scheduled")}


def missed_days(days, today, past_last_slot, lookback=14):
    """Days after the newest post on which nothing went out. A day is not 'missed' until it is over, except today,
    which counts once its last posting time has passed with no post. A day with nothing posted is not recorded
    anywhere (when the AI credits run out the run cannot even start), so it is worked out from the posts that exist.
    The next post that goes live clears them: a missed day is retried by the next run, never skipped."""
    if not days:
        return []
    start = max(max(days) + timedelta(days=1), today - timedelta(days=lookback))
    end = today if past_last_slot else today - timedelta(days=1)
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def past_last_slot(cfg, now=None):
    """True once the day's last posting time (`post_times` in data/topics.json) has gone by."""
    times = cfg.get("post_times") or []
    if not times:
        return False
    hour, minute = map(int, max(times).split(":"))
    now = now or local_now()
    return (now.hour, now.minute) >= (hour, minute)


def unfinished_drafts(posts):
    """Post folders whose content.json was written but that never reached the ledger: a run that stopped halfway
    (typically out of AI credits). The next run finishes that post instead of picking a new repo."""
    booked = {p.get("dir") for p in posts}
    folder = ROOT / "posts"
    return sorted(f"posts/{d.name}" for d in folder.iterdir()
                  if d.is_dir() and (d / "content.json").exists() and f"posts/{d.name}" not in booked) if folder.is_dir() else []


def due():
    """One post per calendar day, in the owner's local time. (Not "24 hours since the last one": posting times
    rotate, so an evening post must not cancel the next day's.)"""
    posts = load(LEDGER, [])
    broken = [p for p in posts if p.get("status") in ("failed", "partial", "cancelled")]
    if broken:
        print(f"due: {broken[0]['keyword']} failed to publish. Re-run: python manyreply.py publish {broken[0]['dir']}")
        return 0
    last, today = last_live(posts), local_now().date()
    # a catch-up day: "extra_posts": {"YYYY-MM-DD": n} in data/topics.json allows n more posts on that date
    allowed = 1 + int(load(CONFIG).get("extra_posts", {}).get(str(today), 0))
    made = sum(1 for p in posts if p.get("dir") and p.get("status") in ("live", "scheduled")
               and datetime.fromisoformat(p["date"]).astimezone().date() == today)
    if (last and last.astimezone().date() > today) or made >= allowed:
        print("not due: today's post is already out or scheduled" + (f" ({made} of {allowed} today)" if allowed > 1 else ""))
        return 1
    print("due: time to post" + (f" (catch-up day: post {made + 1} of {allowed})" if allowed > 1 else ""))
    missed = missed_days(posted_days(posts), today, past_last_slot(load(CONFIG)))
    if missed:
        print(f"MISSED: nothing went out on {', '.join(d.strftime('%a %d %b') for d in missed)} (a run that stopped, usually AI "
              "credits). This run is the retry: post as normal, and never skip the owner's waiting requests because of the gap")
    drafts = unfinished_drafts(posts)
    if drafts:
        print(f"RESUME: {drafts[-1]} was written but never published. Finish it (render if its slides are missing, then publish) "
              "instead of picking a new repo; it is today's post")
    q = load_queue()
    pick = next_pick(posts, q)
    app = None if pick else app_due(posts)
    fav = None if pick or app else fav_due(posts, q)
    if pick:
        print(f"NEXT PICK: the owner's request {pick['url']} (from {pick['source']})"
              + (" -- a website, no GitHub repo: put it in \"repo\" and write the post from the site itself" if pick.get("website") else ""))
    elif app:
        print(f"NEXT PICK: the owner's own app {app_name(app)}: use \"repo\": \"{app_id(app)}\""
              + (f" and \"link\": \"{app['site']}\" (the DM sends the website)" if app.get("site") and app.get("url") else "")
              + ("" if app.get("url") else " (a website, no GitHub repo: write from the site itself)")
              + (f"; the owner's pitch: {app['pitch']}" if app.get("pitch") else "") + ". Write it as 'I built this' (see CLAUDE.md)")
    elif fav:
        before = [p["date"][:10] for p in posts if p.get("status") in ("live", "scheduled", "legacy") and p.get("date")
                  and norm(p["repo"]) == norm(fav)]  # an older post (from before ManyReply) counts: its keyword is taken
        print(f"NEXT PICK: the owner's favorite {fav}: use \"repo\": \"{fav}\""
              + ("" if REPO_RE.search(fav) else " (a website, no GitHub repo: write from the site itself)")
              + (f". It was posted on {max(before)}: give it a fresh angle and a new keyword (the old one is taken), never the old slides" if before else
                 ". It has not been posted yet")
              + ". The owner starred it to see it more often (see CLAUDE.md)")
    else:
        print("NEXT PICK: the search's turn: choose from data/candidates.json, skipping the owner's waiting requests")
    return 0


# ---------------------------------------------------------------- dashboard

MISSED_JS = """(() => {  // the red bar beside Schedule: days with no post. Worked out here, when the page is opened, because a run
  // that never started (out of AI credits) never rebuilt this page.
  const el = document.getElementById("missed");
  if (!el || !window.POST_DAYS || !window.POST_DAYS.length) return;
  const zone = window.SCHED_TZ || undefined;
  let now;
  try {
    now = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hourCycle: "h23"}).formatToParts(new Date()).map(x => [x.type, x.value]));
  } catch (e) { return; }
  const iso = (ms) => new Date(ms).toISOString().slice(0, 10);
  const ms = (d) => Date.parse(d + "T00:00:00Z");
  const today = now.year + "-" + now.month + "-" + now.day;
  const last = window.POST_DAYS.reduce((a, b) => (a > b ? a : b));
  const slot = window.LAST_SLOT ? window.LAST_SLOT.split(":").map(Number) : null;
  const pastSlot = !!slot && (+now.hour > slot[0] || (+now.hour === slot[0] && +now.minute >= slot[1]));
  const start = Math.max(ms(last) + 864e5, ms(today) - 14 * 864e5);
  const end = pastSlot ? ms(today) : ms(today) - 864e5;
  const label = (d) => new Date(ms(d)).toLocaleDateString("en-US", {weekday: "short", month: "short", day: "numeric", timeZone: "UTC"});
  const days = [];
  for (let t = start; t <= end; t += 864e5) days.push(iso(t));
  if (!days.length) { el.hidden = true; return; }
  el.querySelector("span").textContent = "No post went out on " + days.map(label).join(", ") +
    ". The next daily run retries it until it is live.";
  el.hidden = false;
})();"""

SORT_JS = """(() => {  // little up / down arrows in the column heads of the Repositories and older-words tables
  document.querySelectorAll("[data-sortable]").forEach(card => {
    const tables = [...card.querySelectorAll("table")];
    if (!tables.length) return;
    const body = t => t.tBodies[0] || t;
    const rowsOf = t => [...body(t).rows].filter(r => !r.querySelector("th"));
    const groupUp = rows => rows.reduce((gs, r) => { r.classList.contains("res-row") && gs.length ? gs[gs.length - 1].push(r) : gs.push([r]); return gs; }, []);
    const first = groupUp(rowsOf(tables[0]));
    const cap = first.length, groups = groupUp(tables.flatMap(rowsOf));
    groups.forEach((g, i) => { g.order = i; });
    const val = td => {
      const t = (td ? td.textContent : "").replace(/^[\\u2606\\u2605\\s]+/, "").trim();
      if (!t || /^[\\u2013-]$/.test(t)) return null;
      const m = t.replace(/,/g, "").match(/^(\\d+(?:\\.\\d+)?)\\s*([KkMm])?$/);
      return m ? parseFloat(m[1]) * ({k: 1e3, m: 1e6}[(m[2] || "").toLowerCase()] || 1) : t.toLowerCase();
    };
    const state = {col: -1, dir: 0};
    const buttons = [];
    const apply = () => {
      const list = [...groups];
      if (state.dir) {
        const keyed = list.map(g => [g, val(g[0].cells[state.col])]);
        keyed.sort(([a, x], [b, y]) => {
          if (x === null || y === null) return (x === null) - (y === null) || a.order - b.order;
          const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), undefined, {numeric: true});
          return c * state.dir || a.order - b.order;
        });
        keyed.forEach(([g], i) => { list[i] = g; });
      } else list.sort((a, b) => a.order - b.order);
      list.forEach((g, i) => g.forEach(r => body(i < cap || !tables[1] ? tables[0] : tables[1]).appendChild(r)));
      buttons.forEach(b => { const on = +b.dataset.col === state.col && +b.dataset.dir === state.dir; b.classList.toggle("on", on); b.setAttribute("aria-pressed", on); });
    };
    tables.forEach(t => [...t.rows[0].cells].forEach(th => {
      const name = th.textContent.trim() || "column", box = document.createElement("span");
      box.className = "sort";
      [[1, "\\u25B2", "low to high"], [-1, "\\u25BC", "high to low"]].forEach(([dir, mark, words]) => {
        const b = document.createElement("button");
        b.type = "button"; b.textContent = mark; b.dataset.col = th.cellIndex; b.dataset.dir = dir;
        b.title = "Sort " + name + " " + words; b.setAttribute("aria-label", b.title); b.setAttribute("aria-pressed", "false");
        b.onclick = () => { const same = state.col === th.cellIndex && state.dir === dir; state.col = same ? -1 : th.cellIndex; state.dir = same ? 0 : dir; apply(); };
        buttons.push(b); box.appendChild(b);
      });
      th.appendChild(box);
    }));
  });
})();"""

DASH_CSS = """
/* one full-width column of sections (the owner's choice; keep it). Layout: a navy sidebar, a strip of account facts on top, then cards on a two-column grid
   (schedule and growth beside a tall analytics card, then tables, posts and the editors). One column on phones. */
:root{--bg:#F3F5FB;--surface:#FFFFFF;--raise:#F6F8FD;--fg:#111833;--muted:#5B6688;--line:#E2E7F3;
 --accent:#3B6CF6;--accent-strong:#2550D9;--accent-soft:#E8EEFF;--side:#0B1229;--side-fg:#C7CFEA;--side-active:#3B6CF6;
 --good:#16A34A;--warn:#B45309;--bad:#E5484D;--sky:#2563EB;--on-accent:#FFFFFF;
 --display:'Plus Jakarta Sans','Segoe UI',system-ui,sans-serif;--body:'Plus Jakarta Sans','Segoe UI',system-ui,sans-serif;
 --mono:'JetBrains Mono',Consolas,monospace;--r:16px;--grad:linear-gradient(90deg,#7C3AED,#3B6CF6)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0A1023;--surface:#0F1731;--raise:#142043;--fg:#E9EDFA;--muted:#8D99C2;--line:#1F2B52;
 --accent:#4F8BFF;--accent-strong:#7AA7FF;--accent-soft:#16244D;--side:#0A1023;--side-fg:#C7CFEA;--side-active:#3B6CF6;
 --good:#16A34A;--warn:#E3A23B;--bad:#EF4444;--sky:#5B8DEF;--on-accent:#FFFFFF;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0A1023;--surface:#0F1731;--raise:#142043;--fg:#E9EDFA;--muted:#8D99C2;--line:#1F2B52;
 --accent:#4F8BFF;--accent-strong:#7AA7FF;--accent-soft:#16244D;--side:#0A1023;--side-fg:#C7CFEA;--side-active:#3B6CF6;
 --good:#16A34A;--warn:#E3A23B;--bad:#EF4444;--sky:#5B8DEF;--on-accent:#FFFFFF;color-scheme:dark}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--fg);font:14px/1.5 var(--body);margin:0}
svg.i{width:20px;height:20px;flex:none;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
a{color:var(--accent);text-underline-offset:3px}
a:focus-visible,button:focus-visible,summary:focus-visible,input:focus-visible,textarea:focus-visible,label:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.app{display:grid;grid-template-columns:240px minmax(0,1fr);min-height:100vh}
.side{background:var(--side);color:var(--side-fg);position:sticky;top:0;height:100vh;display:flex;flex-direction:column;gap:22px;padding:22px 14px;overflow-y:auto}
@media (max-height:860px){.promo{display:none}}
.brand{display:flex;align-items:center;gap:10px;color:#fff;text-decoration:none;font:800 24px/1 var(--display);letter-spacing:-.02em;padding:4px 8px}
.brand b{background:linear-gradient(90deg,#60A5FA,#A78BFA);-webkit-background-clip:text;background-clip:text;color:transparent;font-weight:800}
.brand svg{width:46px;height:46px}
.side nav{display:flex;flex-direction:column;gap:4px}
.side nav a{display:flex;align-items:center;gap:12px;color:var(--side-fg);text-decoration:none;font-weight:600;padding:11px 14px;border-radius:12px}
.side nav a:hover{background:rgba(255,255,255,.07);color:#fff}
.side nav a.on{background:var(--grad);color:#fff;box-shadow:0 6px 18px rgba(91,76,246,.35)}
.side{border-right:1px solid rgba(255,255,255,.06)}
.promo{margin-top:auto;border:0;border-radius:var(--r);padding:18px;display:grid;gap:8px;color:#F3E8FF;background:radial-gradient(120% 80% at 100% 100%,#EC4899 0,transparent 55%),linear-gradient(160deg,#4C1D95,#6D28D9 60%,#9333EA)}
.promo b{color:#fff;font:800 17px/1.25 var(--display)}
.promo p{margin:0;font-size:13px}
.promo svg{width:40px;height:40px;color:#fff;background:linear-gradient(45deg,#F58529,#DD2A7B,#8134AF);border-radius:11px;padding:7px}
.main{padding:18px max(16px,env(safe-area-inset-right,0px)) 48px max(16px,env(safe-area-inset-left,0px));min-width:0}
.topbar{display:flex;justify-content:flex-end;margin-bottom:18px}
button.fact.theme{background:none;border:0;border-radius:0;font:inherit;color:inherit;cursor:pointer;text-align:left}
button.fact.theme:hover{color:var(--accent)}
.facts{display:flex;flex-wrap:wrap;background:var(--surface);border:1px solid var(--line);border-radius:var(--r)}
.fact{display:flex;align-items:center;gap:12px;padding:12px 18px;border-left:1px solid var(--line);min-width:0}
.fact:first-child{border-left:0}
.fact:first-child+.fact{border-left:1px solid var(--line)}
.fact svg{color:var(--muted)}
.fact b{display:block;font-weight:700}
.fact span{display:block;font-size:12px;color:var(--muted)}
.fact .ig{width:30px;height:30px;color:#fff;background:linear-gradient(45deg,#F58529,#DD2A7B,#8134AF);border-radius:9px;padding:5px}
.grid{display:grid;grid-template-columns:minmax(0,1fr);gap:18px;align-items:start;
 grid-template-areas:"sched" "posts" "anal" "perf" "top" "growth" "next" "apps" "work" "topics" "found" "older" "styles" "words"}
.col{display:contents}
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:18px 20px;min-width:0;scroll-margin-top:16px}
.head{display:flex;align-items:flex-start;gap:12px;margin-bottom:14px}
.head>svg{width:38px;height:38px;color:#fff;background:var(--grad);border-radius:11px;padding:8px;margin-top:0}
.head h2{font:800 19px/1.2 var(--display);margin:0;letter-spacing:-.01em;text-wrap:balance}
.head p{margin:2px 0 0;color:var(--muted);font-size:13px}
.head .aside{margin-left:auto;display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end}
.note{color:var(--muted);font-size:13px;margin:0 0 12px;max-width:70ch}
.info{display:flex;gap:10px;background:var(--accent-soft);border-radius:12px;padding:12px 14px;margin-top:14px;font-size:13px;color:var(--fg)}
.info svg{color:var(--accent)}
.sched{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px}
.sched div{border:1px solid var(--line);border-radius:14px;padding:14px;display:flex;flex-direction:column;align-items:flex-start;gap:4px;min-width:0}
.sched .ic{margin-bottom:6px;width:38px;height:38px;border-radius:10px;display:grid;place-items:center;color:#fff;background:var(--accent)}
.sched .ic.carousel{background:linear-gradient(45deg,#F58529,#DD2A7B,#8134AF)}.sched .ic.story{background:linear-gradient(45deg,#EC4899,#8B5CF6)}.sched .ic.reel{background:#16A34A}.sched .ic.next{background:#475A8C}
.sched b{font-weight:700}
.sched span{color:var(--muted);font-size:13px}
.sched small{color:var(--muted);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:100%}
.sched .pill{margin-top:6px}
.pill{display:inline-block;font:700 11px/1 var(--body);padding:5px 10px;border-radius:999px;background:var(--raise);color:var(--muted);white-space:nowrap;justify-self:start}
.pill.live,.pill.posted{background:var(--accent-soft);color:var(--good)}
.pill.scheduled,.pill.waiting,.pill.publishing,.pill.lookup{background:#FEF3C7;color:#92400E}
.pill.planned{background:#E0E7FF;color:#3730A3}
.pill.failed,.pill.partial,.pill.cancelled{background:#FDE2E1;color:var(--bad)}
.pill.skipped,.pill.already-posted,.pill.legacy{background:var(--raise);color:var(--muted)}
.sort{display:inline-flex;flex-direction:column;margin-left:6px;vertical-align:middle;line-height:1}
.sort button{all:unset;cursor:pointer;font-size:8px;line-height:10px;padding:0 4px;color:var(--muted);opacity:.7}
.sort button:hover,.sort button.on{color:var(--accent);opacity:1}
.sort button:focus-visible{outline:2px solid var(--accent);outline-offset:1px;border-radius:3px}
.alert{display:inline-flex;align-items:center;gap:8px;max-width:340px;padding:8px 12px;border-radius:10px;background:#FDE2E1;color:#B42318;border:1px solid #F5B5B2;font:700 12px/1.35 var(--body)}
.alert[hidden]{display:none}
.alert svg{width:16px;height:16px}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .alert{background:rgba(239,68,68,.16);color:#FCA5A5;border-color:rgba(239,68,68,.4)}}
:root[data-theme="dark"] .alert{background:rgba(239,68,68,.16);color:#FCA5A5;border-color:rgba(239,68,68,.4)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .pill.scheduled,:root:not([data-theme="light"]) .pill.waiting,:root:not([data-theme="light"]) .pill.publishing,:root:not([data-theme="light"]) .pill.lookup{background:#3A2A0C;color:#F2C46B}
 :root:not([data-theme="light"]) .pill.planned{background:#1E2350;color:#B4BCFF}:root:not([data-theme="light"]) .pill.failed,:root:not([data-theme="light"]) .pill.partial,:root:not([data-theme="light"]) .pill.cancelled{background:#3B1416;color:#FF9B9B}}
:root[data-theme="dark"] .pill.scheduled,:root[data-theme="dark"] .pill.waiting,:root[data-theme="dark"] .pill.publishing,:root[data-theme="dark"] .pill.lookup{background:#3A2A0C;color:#F2C46B}
:root[data-theme="dark"] .pill.planned{background:#1E2350;color:#B4BCFF}
:root[data-theme="dark"] .pill.failed,:root[data-theme="dark"] .pill.partial,:root[data-theme="dark"] .pill.cancelled{background:#3B1416;color:#FF9B9B}
.periods>input{position:absolute;opacity:0;pointer-events:none}
.tabs{display:flex;gap:4px;background:var(--raise);border:1px solid var(--line);border-radius:999px;padding:4px;width:max-content;max-width:100%;flex-wrap:wrap}
.tabs label{font-weight:700;font-size:13px;padding:7px 16px;border-radius:999px;cursor:pointer;color:var(--muted)}
.tabs label:hover{color:var(--fg)}
#p1:checked~.tabs label[for=p1],#p7:checked~.tabs label[for=p7],#p14:checked~.tabs label[for=p14],#p30:checked~.tabs label[for=p30],#p60:checked~.tabs label[for=p60],#p90:checked~.tabs label[for=p90],#p365:checked~.tabs label[for=p365]{background:var(--accent);color:var(--on-accent)}
#p1:focus-visible~.tabs label[for=p1],#p7:focus-visible~.tabs label[for=p7],#p14:focus-visible~.tabs label[for=p14],#p30:focus-visible~.tabs label[for=p30],#p60:focus-visible~.tabs label[for=p60],#p90:focus-visible~.tabs label[for=p90],#p365:focus-visible~.tabs label[for=p365]{outline:2px solid var(--accent);outline-offset:2px}
.tiles{display:none;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px;margin-top:14px}
#p1:checked~.p1,#p7:checked~.p7,#p14:checked~.p14,#p30:checked~.p30,#p60:checked~.p60,#p90:checked~.p90,#p365:checked~.p365{display:grid}
.tiles div{border:1px solid var(--line);border-radius:14px;padding:12px 14px;display:grid;grid-template-columns:auto 1fr;gap:6px 8px;align-items:center}
.tiles svg{width:30px;height:30px;padding:6px;border-radius:9px;color:#fff;background:var(--c,#3B6CF6)}
.tiles div:nth-child(7n+1) svg{--c:#F97316}.tiles div:nth-child(7n+2) svg{--c:#3B6CF6}.tiles div:nth-child(7n+3) svg{--c:#0EA5E9}.tiles div:nth-child(7n+4) svg{--c:#EC4899}.tiles div:nth-child(7n+5) svg{--c:#10B981}.tiles div:nth-child(7n+6) svg{--c:#6366F1}.tiles div:nth-child(7n) svg{--c:#A855F7}
.tiles span{font-size:12px;font-weight:600;color:var(--muted);line-height:1.3}
.tiles b{grid-column:1/-1;font:800 22px/1 var(--display);font-variant-numeric:tabular-nums;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.tiles small{grid-column:1/-1;font-size:11px;color:var(--muted)}
.tiles i{font-style:normal;font:700 11px/1 var(--body);padding:4px 8px;border-radius:999px;color:#fff;background:var(--muted)}
.tiles i.up{background:var(--good);color:var(--on-accent)}.tiles i.down{background:var(--bad)}
.gbody{display:grid;grid-template-columns:minmax(0,1fr);gap:14px;grid-template-areas:"chart" "pick" "around" "tbl"}
.chart{grid-area:chart;position:relative;align-self:start}
.chart svg{display:block;width:100%;height:auto;touch-action:pan-y;cursor:pointer}
.chart .grid{stroke:var(--line);stroke-width:1}
.chart .line{fill:none;stroke:var(--accent);stroke-width:2.5;stroke-linejoin:round;stroke-linecap:round}
.chart .area{fill:var(--accent);opacity:.12}
.chart .end,.chart .hover-dot{fill:var(--accent);stroke:var(--surface);stroke-width:2}
.chart .cross{stroke:var(--muted);stroke-width:1;stroke-dasharray:3 3}
.chart .cross,.chart .hover-dot,.chart .pick{opacity:0}
.chart .pick{fill:none;stroke:var(--accent-strong);stroke-width:3}
.chart .tick{fill:var(--accent);opacity:.55}
.chart text{fill:var(--muted);font:500 12px var(--mono)}
.chart text.now{fill:var(--fg);font-weight:700}
#ftip{position:absolute;top:8px;background:var(--surface);color:var(--fg);border:1px solid var(--line);box-shadow:0 4px 14px rgba(0,0,0,.08);font:600 12px/1.2 var(--mono);padding:8px 10px;border-radius:10px;white-space:nowrap;pointer-events:none}
.pick-row{grid-area:pick;margin:0;display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-size:13px;color:var(--muted)}
.pick-row input{width:auto;padding:6px 10px;font-weight:600}
#around{grid-area:around;min-width:0}
#around>p{margin:0 0 12px;font-size:14px;font-weight:600;color:var(--fg);max-width:none;background:color-mix(in srgb,#F5B301 16%,transparent);border:1px solid color-mix(in srgb,#F5B301 55%,transparent);border-left:5px solid #F5B301;border-radius:10px;padding:10px 14px}
.gbody>details{grid-area:tbl}
.wk{display:grid;gap:6px}
.wk a,.wk div{display:grid;grid-template-columns:62px minmax(0,1fr) auto;gap:10px;align-items:center;border:1px solid var(--line);border-radius:12px;padding:8px 12px;text-decoration:none;color:var(--fg);font-size:13px}
.wk a:hover{border-color:var(--accent)}
.wk span{color:var(--muted);font-size:12px}
.wk em{font-style:normal;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wk b{font-size:12px;color:var(--muted);font-weight:600;white-space:nowrap}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:12px}
table{border-collapse:collapse;width:100%;min-width:520px;font-size:13px}
th{font-size:12px;font-weight:700;color:var(--muted);text-align:left;padding:10px 12px;background:var(--raise);border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:0}
td.n,th.n{text-align:right;font-family:var(--mono);font-variant-numeric:tabular-nums;white-space:nowrap}
td small{display:block;color:var(--muted);max-width:60ch}
details{margin-top:10px}
summary{cursor:pointer;list-style:none}
summary::-webkit-details-marker{display:none}
details:not(.post)>summary{display:inline-flex;align-items:center;gap:6px;font-weight:700;font-size:13px;color:var(--accent);border:1px solid var(--line);background:var(--surface);border-radius:999px;padding:7px 14px}
details:not(.post)>summary::before{content:"";width:7px;height:7px;border-right:2px solid currentColor;border-bottom:2px solid currentColor;transform:rotate(-45deg);transition:transform .15s}
details[open]:not(.post)>summary::before{transform:rotate(45deg)}
details:not(.post)>summary:hover{border-color:var(--accent);background:var(--accent-soft)}
details.more>summary{margin-bottom:8px}
.word{display:inline-block;font:700 11px/1 var(--mono);letter-spacing:.04em;padding:6px 10px;border-radius:999px;background:var(--accent-soft);color:var(--accent-strong);white-space:nowrap}
.words{display:flex;flex-wrap:wrap;gap:8px}
.clk{display:inline-block;min-width:30px;text-align:center;font:700 12px/1 var(--mono);padding:5px 8px;border-radius:999px;background:var(--raise);color:var(--muted)}
.clk.hot{background:var(--bad);color:#fff}
.posts{display:grid;border:1px solid var(--line);border-radius:12px;overflow:hidden}
.post{margin:0;border-bottom:1px solid var(--line)}
.post:last-child{border-bottom:0}
.post summary,.planned-row{display:grid;grid-template-columns:96px minmax(0,1.4fr) auto minmax(0,.9fr) auto auto 42px 56px;gap:12px;align-items:center;padding:11px 14px;font-size:13px}
.post summary:hover{background:var(--raise)}
.planned-row{grid-template-columns:150px minmax(0,1fr) auto;background:var(--accent-soft);border-bottom:1px solid var(--line)}
.planned-row b{font-weight:800;color:var(--accent-strong);font-size:12px;display:block}
.post .d,.planned-row .d{font-size:12px;color:var(--muted)}
.post .r{font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.post .t{color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.post .ig a{font-weight:700;text-decoration:none}
.post dl{display:grid;grid-template-columns:max-content 1fr;gap:6px 18px;margin:0;padding:6px 14px 16px 110px;font-size:13px}
.post dt{color:var(--muted);font-weight:600}
.post dd{margin:0}
input,textarea{font:inherit;color:var(--fg);background:var(--surface);border:1.5px solid var(--line);border-radius:10px;padding:9px 12px;width:100%;min-width:0}
input:hover,textarea:hover{border-color:var(--muted)}
textarea{font:400 13px/1.6 var(--mono);resize:vertical}
button{font:700 13px/1 var(--body);color:var(--fg);background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:9px 14px;cursor:pointer}
button:hover:not(:disabled){border-color:var(--accent);color:var(--accent)}
button:disabled{opacity:.4;cursor:default}
button.primary,#add-topic button,#add-repo button{background:var(--accent);border-color:var(--accent);color:var(--on-accent)}
button.primary:hover:not(:disabled),#add-topic button:hover,#add-repo button:hover{background:var(--accent-strong);color:var(--on-accent)}
button.remove{background:var(--bad);border-color:var(--bad);color:#fff;padding:6px 11px;font-size:12px;margin-left:6px}
button.remove:hover:not(:disabled){color:#fff;filter:brightness(1.08)}
button.star{background:none;border:0;border-radius:6px;padding:0 4px;margin:0 6px 0 0;font-size:17px;line-height:1;color:var(--muted);cursor:pointer;vertical-align:-1px}
button.star:hover:not(:disabled),button.star.on{background:none;color:#E8A317}
#add-repo{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:10px}
#add-repo label{flex-basis:100%;font-size:12px;font-weight:700;color:var(--muted)}
#add-repo input{flex:1 1 220px}
#matches{list-style:none;margin:0 0 10px;padding:0;display:grid;gap:8px}
#matches:empty{display:none}
#matches li{display:grid;grid-template-columns:1fr auto;gap:2px 12px;align-items:center;border:1px solid var(--line);border-radius:12px;padding:10px 12px}
#matches small{grid-column:1;color:var(--muted)}
#matches button{grid-row:1/3;grid-column:2}
table.queue td small{display:block;color:var(--muted)}
.msg{font-size:13px;color:var(--muted);min-height:1.4em;margin:8px 0 0}
.topics{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px;margin:0;padding:0;list-style:none}
.topics li{border:1px solid var(--line);border-radius:14px;padding:12px 14px;min-width:0;background:var(--raise)}
.topics li:first-child{border:2px solid var(--accent)}
.topics b{font-weight:800}
.topics i{font:600 12px/1 var(--mono);color:var(--muted);font-style:normal;margin-right:8px}
.topics p{margin:6px 0 0;color:var(--muted);font:400 12px/1.6 var(--mono)}
.topics.edit li{display:flex;flex-direction:column;gap:8px}
.topics.edit li.dirty{border-color:var(--warn)}
.topics input,.topics textarea{background:var(--surface)}
.rank{font-size:12px;font-weight:700;color:var(--muted)}
.acts{display:flex;flex-wrap:wrap;gap:6px}
.acts button{padding:7px 10px;font-size:12px}
#add-topic{display:grid;gap:8px;margin-top:14px;padding:14px;border:1px dashed var(--line);border-radius:14px;max-width:460px}
#add-topic h3{font:800 15px/1.3 var(--display);margin:0}
#add-topic label{font-size:12px;font-weight:700;color:var(--muted)}
#add-topic button{justify-self:start}
.empty{color:var(--muted);padding:16px;border:1px dashed var(--line);border-radius:12px}
@media (max-width:900px){
 .app{grid-template-columns:minmax(0,1fr)}
 .side{position:sticky;top:env(safe-area-inset-top,0px);z-index:3;height:auto;flex-direction:row;align-items:center;gap:12px;padding:10px max(16px,env(safe-area-inset-left,0px));overflow-x:auto}
 .side nav{flex-direction:row}
 .side nav a{padding:8px 12px;white-space:nowrap}
 .side nav a svg{display:none}
 .brand{font-size:19px}.brand svg{width:28px;height:28px}
 .promo{display:none}
 .topbar{justify-content:stretch}.facts{width:100%}.fact{flex:1 1 50%;border-left:0;border-top:1px solid var(--line)}
 .gbody{grid-template-columns:minmax(0,1fr);grid-template-areas:"chart" "pick" "around" "tbl"}
 .post summary{grid-template-columns:80px minmax(0,1fr) auto;row-gap:6px}.post .t,.post .ig,.post .clk{display:none}
 .post dl{padding-left:14px}
}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}details>summary::before{transition:none}}
@media (min-width:1181px){.sched{grid-template-columns:repeat(4,minmax(0,1fr))}}
.credit{color:var(--muted);font-size:13px;text-align:center;margin-top:22px}.credit a{font-weight:700}
.res{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;max-width:640px}.res span{display:inline-flex;align-items:center;gap:4px;font:500 12px var(--body);color:var(--muted);background:var(--raise);border:1px solid var(--line);border-radius:8px;padding:3px 7px;white-space:nowrap}.res svg.i{width:13px;height:13px;color:var(--accent)}.res b{color:var(--fg);font-family:var(--mono)}
.fact em{font-style:normal;font-weight:700}.fact em.up{color:var(--good)}.fact em.down{color:var(--bad)}
tr:has(+tr.res-row) td{border-bottom:0;padding-bottom:4px}tr.res-row td{padding-top:0}
.res{flex-wrap:nowrap;overflow-x:auto;max-width:none;margin-top:0;scrollbar-width:thin}
.qnote{font-size:12px;color:var(--muted);white-space:nowrap;margin-left:6px}
.sched a.open{margin-top:6px;font-size:12px;font-weight:700;text-decoration:none}.sched a.open:hover{text-decoration:underline}
.qnote{color:var(--bad)!important;font-weight:600}
.tiles b.up{color:var(--good)}.tiles b.down{color:var(--bad)}
.fact em.flat{color:var(--muted)}#around b.up{color:var(--good)}#around b.down{color:var(--bad)}
.rch{font:600 12px/1 var(--mono);padding:5px 8px;border-radius:999px;background:var(--raise);color:var(--muted);white-space:nowrap}
.rch.hi{background:color-mix(in srgb,var(--good) 18%,transparent);color:var(--good)}.rch.lo{background:color-mix(in srgb,var(--bad) 16%,transparent);color:var(--bad)}
.res span.lead{background:none;border-color:transparent;padding-left:0;font-weight:600;color:var(--text)}.res span.z{opacity:.45}.res span.win{border-color:var(--good)}.res span.win b{color:var(--good)}
td.zero{color:var(--muted);opacity:.6}td.best{color:var(--good);font-weight:800}
@media (max-width:900px){.post .rch{display:none}}
.tiles b>span{font:inherit;color:inherit}.tiles b i{font-size:12px;vertical-align:middle}
.style{border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin:0 0 12px}
.st-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.st-head b{font-size:16px}
.st-used{margin-left:auto;color:var(--muted);font-size:12px}.style p{margin:4px 0 12px;color:var(--muted);font-size:13px}
.st-pics{display:grid;grid-template-columns:repeat(3,minmax(0,220px));gap:10px}
.st-pics img{width:100%;height:auto;border-radius:10px;border:1px solid var(--line);display:block}
details.more>.style:first-of-type{margin-top:12px}
.apps{list-style:none;margin:0 0 14px;padding:0;display:grid;gap:8px}
.apps li{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;border:1px solid var(--line);border-radius:12px;padding:10px 14px}
.apps li small{flex-basis:100%;color:var(--muted)}.apps li .pill{margin-left:auto}.apps li.none{color:var(--muted)}
#add-app{display:grid;gap:8px;max-width:520px}#add-app label{font-size:12px;font-weight:700;color:var(--muted)}#add-app button{justify-self:start;background:var(--accent);border-color:var(--accent);color:var(--on-accent)}
.apps li .res{flex-basis:100%;margin-top:2px}
#matches a.name{font-weight:700;text-decoration:none}#matches a.name:hover{text-decoration:underline}
"""

# Line icons for the dashboard (24px grid, drawn with the current text colour)
ICONS = {
    "home": "M3 11l9-7 9 7M5 10v10h5v-6h4v6h5V10", "calendar": "M4 6h16v14H4zM4 10h16M8 3v4M16 3v4",
    "bars": "M5 20V11M10 20V5M15 20v-7M20 20V8", "trend": "M3 17l6-6 4 4 8-8M15 7h6v6",
    "file": "M6 3h9l4 4v14H6zM14 3v5h5M9 13h7M9 17h7", "list": "M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01",
    "repo": "M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3zM5 17a3 3 0 0 1 3-3h11", "search": "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-5-5",
    "chat": "M4 5h16v11H9l-5 4z", "user": "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
    "eye": "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
    "heart": "M12 20s-8-5-8-11a4 4 0 0 1 8-1 4 4 0 0 1 8 1c0 6-8 11-8 11z", "send": "M21 3L10 14M21 3l-7 18-4-8-8-4z",
    "bookmark": "M6 3h12v18l-6-4-6 4z", "star": "M12 3l2.7 5.6 6.3.9-4.5 4.4 1 6.1L12 17l-5.5 3 1-6.1L3 9.5l6.3-.9z",
    "link": "M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1",
    "click": "M9 9l11 4-5 2-2 5zM5 3v3M3 5h3", "play": "M7 4v16l13-8z", "lock": "M6 11h12v10H6zM8 11V7a4 4 0 0 1 8 0v4",
    "clock": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2", "image": "M4 5h16v14H4zM4 15l5-5 4 4 3-3 4 4",
    "story": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
    "info": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v6M12 7h.01",
}
LOGO = ('<svg viewBox="0 0 48 48" aria-hidden="true"><defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#3B82F6"/><stop offset="1" stop-color="#A855F7"/></linearGradient></defs>'
        '<rect x="19" y="1" width="10" height="6" rx="3" fill="url(#lg)"/>'  # the bump on top of the head
        '<rect x="18" y="38" width="12" height="8" rx="2.5" fill="url(#lg)"/>'  # the neck
        '<rect x="2" y="15" width="5" height="13" rx="2.5" fill="url(#lg)"/><rect x="41" y="15" width="5" height="13" rx="2.5" fill="url(#lg)"/>'
        '<rect x="7" y="7" width="34" height="32" rx="11" fill="#0B1229" stroke="url(#lg)" stroke-width="4"/>'
        '<rect x="17" y="17" width="4" height="7" rx="2" fill="#7DD3FC"/><rect x="27" y="17" width="4" height="7" rx="2" fill="#7DD3FC"/>'
        '<path d="M18 29c3.5 2.6 8.5 2.6 12 0" stroke="#7DD3FC" stroke-width="2.6" fill="none" stroke-linecap="round"/></svg>')
VERSION = "2.14.0"  # shown on the dashboard and the tools page; bump it when either page changes
FAVICON = ('<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,'
           + urllib.parse.quote(LOGO.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)) + '">')
PROJECT_URL = "https://github.com/ZeroTouchAI/ManyReply-Free"  # where the free, open-source project lives; credits link here
CREDIT = (f'ManyReply v{VERSION} &middot; <a href="{PROJECT_URL}" target="_blank" rel="noopener">Free &amp; open source</a>')


def icon(name):
    return f'<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="{ICONS[name]}"/></svg>'



# The topic list lives in the page's shared database so the owner can edit it from any device.
# Without that database (file opened locally, signed out) the static list rendered by dashboard() stays as it is.
CHART_JS = """
(() => {
  const svg = document.getElementById("fchart");
  if (!svg) return;
  const pts = JSON.parse(svg.dataset.points), posts = window.GROWTH_POSTS || [], tip = document.getElementById("ftip"),
        cross = svg.querySelector(".cross"), dot = svg.querySelector(".hover-dot"), pick = svg.querySelector(".pick"),
        panel = document.getElementById("around"), dateBox = document.getElementById("fdate"), toBox = document.getElementById("fto"),
        W = 1000, DAY = 864e5;
  const nearest = x => pts.reduce((p, q) => Math.abs(q[2] - x) < Math.abs(p[2] - x) ? q : p);
  const xOf = ev => { const box = svg.getBoundingClientRect(); return [(ev.clientX - box.left) / box.width * W, box]; };
  const nice = d => new Date(d + "T12:00:00").toLocaleDateString(undefined, {day: "numeric", month: "short"});
  const cell = (tag, text, cls) => { const c = document.createElement(tag); c.textContent = text; if (cls) c.className = cls; return c; };
  svg.addEventListener("pointermove", ev => {
    const [x, box] = xOf(ev), p = nearest(x);
    cross.setAttribute("x1", p[2]); cross.setAttribute("x2", p[2]); cross.style.opacity = 1;
    dot.setAttribute("cx", p[2]); dot.setAttribute("cy", p[3]); dot.style.opacity = 1;
    tip.hidden = false;
    tip.textContent = nice(p[0]) + ": " + p[1].toLocaleString() + " followers. Click to see the posts.";
    tip.style.left = Math.min(box.width - 330, Math.max(16, p[2] / W * box.width - 120)) + "px";
  });
  svg.addEventListener("pointerleave", () => { cross.style.opacity = 0; dot.style.opacity = 0; tip.hidden = true; });

  // The list under the chart: every post in the chart's range, or just the week around a clicked day.
  function table(rows) {  // one compact line per post: date, caption, type and reach
    const wrap = cell("div", "", "wk");
    for (const r of rows) {
      const row = r.gone ? cell("div") : Object.assign(cell("a"), {href: r.url, target: "_blank", rel: "noopener"});
      row.append(cell("span", nice(r.date)), cell("em", r.caption || "(no caption)"),
                 cell("b", (r.ours ? "Carousel" : r.reel ? "Reel" : (r.kind || "post")) + " · " + (r.reach || 0).toLocaleString() + " reach"));
      wrap.append(row);
    }
    return wrap;
  }
  function summary(first, last, rows, lead) {
    const change = last[1] - first[1];
    const p = cell("p", lead + nice(first[0]) + " to " + nice(last[0]) + ": followers went from " + first[1].toLocaleString() + " to " +
      last[1].toLocaleString() + " (", "note");
    p.append(cell("b", (change > 0 ? "+" : "") + change, change > 0 ? "up" : change < 0 ? "down" : ""),
             "). " + (rows.length ? rows.length + (rows.length === 1 ? " post" : " posts") + " went out in those days." : "Nothing was posted in those days."));
    return p;
  }
  function showAll() {
    const rows = posts.filter(r => r.date >= pts[0][0] && r.date <= pts[pts.length - 1][0]).sort((a, b) => a.date < b.date ? 1 : -1);
    pick.style.opacity = 0; dateBox.value = toBox.value = ""; allBtn.hidden = true;
    // the whole range is long: folded until asked for; a clicked week is short and shows open
    const fold = document.createElement("details");
    fold.className = "more";
    fold.append(cell("summary", "Show " + (rows.length - 5) + " more"), table(rows.slice(5)));
    panel.replaceChildren(summary(pts[0], pts[pts.length - 1], rows, "Whole chart, "),
                          ...(rows.length ? [table(rows.slice(0, 5))] : []), ...(rows.length > 5 ? [fold] : []));
  }
  function range(from, to) {  // every post from one day to another; the same day twice is just that day
    if (to < from) [from, to] = [to, from];
    const near = d => pts.reduce((p, q) => Math.abs(new Date(q[0]) - new Date(d)) < Math.abs(new Date(p[0]) - new Date(d)) ? q : p);
    const inside = pts.filter(q => q[0] >= from && q[0] <= to), first = inside[0] || near(from), last = inside[inside.length - 1] || near(to);
    const rows = posts.filter(r => r.date >= from && r.date <= to).sort((a, b) => a.date < b.date ? -1 : 1);
    pick.setAttribute("cx", first[2]); pick.setAttribute("cy", first[3]); pick.style.opacity = 1;
    dateBox.value = from; toBox.value = to; allBtn.hidden = false;
    const lead = from === to ? nice(from) + ": " : "";
    panel.replaceChildren(from === to
      ? cell("p", lead + (rows.length ? rows.length + (rows.length === 1 ? " post" : " posts") + " went out that day." : "Nothing was posted that day.") +
                 " Followers that day: " + near(from)[1].toLocaleString() + ".", "note")
      : summary(first, last, rows, ""), ...(rows.length ? [table(rows)] : []));
  }
  function show(day) {  // a click on the chart: the week around that day
    const t = new Date(day + "T12:00:00").getTime(), iso = ms => new Date(ms).toISOString().slice(0, 10);
    range(iso(t - 3 * DAY), iso(t + 3 * DAY));
  }
  const allBtn = document.getElementById("fall");
  allBtn.addEventListener("click", showAll);
  svg.addEventListener("click", ev => show(nearest(xOf(ev)[0])[0]));
  const picked = () => { if (dateBox.value) range(dateBox.value, toBox.value || dateBox.value); };
  dateBox.addEventListener("change", picked);
  toBox.addEventListener("change", () => { if (toBox.value) range(dateBox.value || toBox.value, toBox.value); });
  document.getElementById("fday").addEventListener("click", () => {
    const d = dateBox.value || toBox.value || pts[pts.length - 1][0];
    range(d, d);
  });
  showAll();
})();
"""


def follower_chart(followers, posts):
    """One series, so one hue and no legend: line, faint area, the latest value labelled, hover for any day.
    Ticks along the bottom mark days with posts; clicking a day lists what went out in the week around it."""
    days = sorted(followers)[-120:]
    shown = [r["date"] for r in posts if days and r["date"] >= days[0]]
    if shown:  # start at the first post in range: the stretch before it is empty
        days = [d for d in days if d >= min(shown)]
    if len(days) < 2:
        return '<div class="empty">The follower chart appears after two days of data.</div>'
    values = [followers[d] for d in days]
    lo, hi = min(values), max(values)
    pad = max((hi - lo) * 0.15, 2)
    lo, hi = lo - pad, hi + pad
    x = lambda i: round(56 + i * (1000 - 56 - 70) / (len(days) - 1), 1)
    y = lambda v: round(20 + (hi - v) * 200 / (hi - lo), 1)
    pts = [[d, v, x(i), y(v)] for i, (d, v) in enumerate(zip(days, values))]
    path = " ".join(f"{p[2]},{p[3]}" for p in pts)
    grid = "".join(f'<line class="grid" x1="56" x2="930" y1="{y(v)}" y2="{y(v)}"/><text x="48" y="{y(v) + 4}" text-anchor="end">{round(v):,}</text>'
                   for v in (min(values), (min(values) + max(values)) / 2, max(values)))
    per_day = {}
    for r in posts:
        per_day[r["date"]] = per_day.get(r["date"], 0) + 1
    ticks = "".join(f'<rect class="tick" x="{p[2] - 2}" y="{226 - min(per_day[p[0]], 7) * 3}" width="4" height="{min(per_day[p[0]], 7) * 3}" rx="1"/>'
                    for p in pts if p[0] in per_day)
    slim = [{k: r.get(k) for k in ("date", "url", "kind", "ours", "reel", "gone", "caption", "reach", "likes", "comments", "saves", "shares", "follows")}
            for r in posts if days[0] <= r["date"] <= days[-1]]
    data = json.dumps(slim, ensure_ascii=False).replace("</", "<\\/")  # outside the f-string: Python 3.11 needs that
    return (f'<div class="chart"><svg id="fchart" viewBox="0 0 1000 250" role="img" aria-label="Followers per day, '
            f'{days[0]} to {days[-1]}" data-points="{html.escape(json.dumps(pts))}">{grid}'
            f'<polygon class="area" points="56,220 {path} {pts[-1][2]},220"/><polyline class="line" points="{path}"/>{ticks}'
            f'<line class="cross" y1="20" y2="220"/><circle class="end" cx="{pts[-1][2]}" cy="{pts[-1][3]}" r="5"/>'
            f'<circle class="pick" r="7"/><circle class="hover-dot" r="5"/>'
            f'<text class="now" x="{pts[-1][2] + 10}" y="{pts[-1][3] + 4}">{values[-1]:,}</text>'
            f'<text x="56" y="246">{days[0]}</text><text x="930" y="246" text-anchor="end">{days[-1]}</text></svg>'
            f'<div id="ftip" hidden></div></div>'
            f'<p class="pick-row"><label for="fdate">From</label> <input type="date" id="fdate" min="{days[0]}" max="{days[-1]}"> '
            f'<label for="fto">To</label> <input type="date" id="fto" min="{days[0]}" max="{days[-1]}"> '
            f'<button type="button" id="fday">Just that day</button> <button type="button" id="fall" hidden>Show all posts</button></p>'
            f'<div id="around" aria-live="polite"></div>'
            f'<details><summary>Show follower numbers as a table</summary><div class="scroll"><table><tr><th>Date</th>'
            f'<th class="n">Followers</th></tr>' + "".join(f"<tr><td>{d}</td><td class='n'>{v:,}</td></tr>" for d, v in reversed(list(zip(days, values))))
            + f'</table></div></details><script>window.GROWTH_POSTS = {data};</script>'
            f'<script>{CHART_JS}</script>')


DASH_JS = """
(async () => {
  const list = document.getElementById("topics"), form = document.getElementById("add-topic"),
        msg = document.getElementById("topics-msg"), rform = document.getElementById("add-repo"),
        rmsg = document.getElementById("requests-msg"),
        known = new Set(window.KNOWN_REPOS || []), key = u => u.toLowerCase().replace(/\\/+$/, "");
  let state;
  try {  // opened as a plain file, or the site has no GitHub token yet: stay a read-only page
    const res = await fetch("/dashboard/api/state");
    if (!res.ok) throw new Error();
    state = await res.json();
  } catch (err) { return; }
  let busy = false;
  const say = (t, where) => { (where || msg).textContent = t; };
  const lines = t => t.split("\\n").map(s => s.trim()).filter(Boolean);
  const el = (tag, props) => Object.assign(document.createElement(tag), props || {});
  async function save(done, where) {
    if (busy) return;
    busy = true;
    say("Saving...", where);
    try {
      const res = await fetch("/dashboard/api/state", {method: "POST", headers: {"Content-Type": "application/json"},
                                                       body: JSON.stringify({topics: state.topics, requests: state.requests, removed: state.removed || [], apps: state.apps || [], favorites: state.favorites || []})});
      const body = await res.json();
      if (!res.ok) throw new Error(body.error || res.status);
      state = body;
      say(done, where);
    } catch (err) { say("Could not save: " + err.message, where); }
    busy = false;
    draw();
  }
  (() => {  // My apps: add one, remove one
    const form = document.getElementById("add-app"), list = document.getElementById("app-list"), amsg = document.getElementById("apps-msg");
    if (!form) return;
    form.hidden = false;
    const key = u => u.toLowerCase().replace(/\\/+$/, "");
    const drawApps = () => {
      for (const li of list.querySelectorAll("li[data-url]")) {
        if (li.querySelector("button")) continue;
        const b = el("button", {type: "button", className: "remove", textContent: "Remove"});
        b.onclick = () => { state.apps = (state.apps || []).filter(a => key(a.url || a.site) !== key(li.dataset.url)); li.remove(); save("Removed.", amsg); };
        li.append(b);
      }
    };
    form.addEventListener("submit", ev => {
      ev.preventDefault();
      // forgiving: "mysite.com", "www.mysite.com" and "http://..." all become https://...
      const web = v => { v = v.trim().replace(/\\/+$/, ""); return !v ? "" : /^https?:\\/\\//i.test(v) ? v.replace(/^http:/i, "https:") : "https://" + v; };
      const url = web(document.getElementById("app-url").value).replace(/\\.git$/, ""),
            site = web(document.getElementById("app-site").value), pitch = document.getElementById("app-pitch").value.trim();
      if (!url && !site) return say("Add a GitHub link, a website, or both.", amsg);
      if (url && !/^https:\\/\\/github\\.com\\/[\\w.-]+\\/[\\w.-]+$/.test(url)) return say("The GitHub link should look like https://github.com/you/app.", amsg);
      if (site && !/^https:\\/\\/\\S+$/.test(site)) return say("The website must start with https://", amsg);
      const id = url || site;
      if ((state.apps || []).some(a => key(a.url || a.site) === key(id))) return say("That app is already in the list.", amsg);
      state.apps = [...(state.apps || []), {url, site, pitch}];
      const li = el("li"); li.dataset.url = id;
      li.append(Object.assign(el("a", {href: id, target: "_blank", rel: "noopener", textContent: url ? url.split("github.com/")[1] : site.replace(/^https:\\/\\/(www\\.)?/, "")})));
      if (pitch) li.append(el("small", {textContent: pitch}));
      li.append(el("span", {className: "pill planned", textContent: "not posted yet"}));
      list.querySelector("li.none")?.remove(); list.append(li); drawApps(); form.reset();
      save("Added. It joins the rotation at the next run.", amsg);
    });
    // the saved list is the truth: add apps saved since this page was built, drop ones removed since
    const saved = state.apps || [], ids = new Set(saved.map(a => key(a.url || a.site)));
    for (const li of list.querySelectorAll("li[data-url]")) if (!ids.has(key(li.dataset.url))) li.remove();
    const shown = new Set([...list.querySelectorAll("li[data-url]")].map(li => key(li.dataset.url)));
    for (const a of saved) {
      const id = a.url || a.site;
      if (shown.has(key(id))) continue;
      const li = el("li"); li.dataset.url = id;
      li.append(el("a", {href: id, target: "_blank", rel: "noopener",
                         textContent: a.url ? a.url.split("github.com/")[1] : a.site.replace(/^https:\\/\\/(www\\.)?/, "")}));
      if (a.pitch) li.append(el("small", {textContent: a.pitch}));
      li.append(el("span", {className: "pill planned", textContent: "not posted yet"}));
      list.append(li);
    }
    if (saved.length) list.querySelector("li.none")?.remove();
    drawApps();
  })();
  function card(r, i) {
    const li = el("li"), name = el("input", {value: r.name, id: "t-name-" + i, maxLength: 60}),
          qs = el("textarea", {id: "t-q-" + i, rows: Math.max(3, r.queries.length), value: r.queries.join("\\n")}),
          acts = el("div", {className: "acts"}), t = state.topics;
    name.setAttribute("aria-label", "Topic name");
    qs.setAttribute("aria-label", "GitHub search terms, one per line");
    const dirty = () => li.classList.add("dirty");
    name.addEventListener("input", dirty); qs.addEventListener("input", dirty);
    const btn = (label, fn, off, cls) => {
      const b = el("button", {type: "button", textContent: label, disabled: !!off, className: cls || ""});
      b.addEventListener("click", fn); acts.append(b); return b;
    };
    const move = (to, done) => { t.splice(to, 0, t.splice(i, 1)[0]); save(done); };
    btn("Save", () => {
      const q = lines(qs.value);
      if (!name.value.trim() || !q.length) return say("A topic needs a name and at least one search term.");
      li.classList.remove("dirty");
      t[i] = {name: name.value.trim(), queries: q};
      save("Saved. It applies at the next run.");
    }, false, "primary");
    btn("To top", () => move(0, "Moved to the top."), i === 0);
    btn("Up", () => move(i - 1, "Order saved. It applies at the next run."), i === 0);
    btn("Down", () => move(i + 1, "Order saved. It applies at the next run."), i === t.length - 1);
    const del = btn("Delete", () => {
      if (del.dataset.armed) { t.splice(i, 1); return save("Deleted."); }
      del.dataset.armed = "1"; del.textContent = "Really delete?";
    }, t.length === 1, "remove");
    li.append(el("span", {className: "rank", textContent: "Priority " + (i + 1)}), name, qs, acts);
    return li;
  }
  // Favorites: the star beside a repo. Starred repos are posted more often (see CLAUDE.md); it applies at the next run.
  const starBtn = u => {
    const b = el("button", {type: "button", className: "star", title: "Favorite: posted more often"});
    b.dataset.fav = u;
    return b;
  };
  function paintStars() {
    const on = new Set((state.favorites || []).map(key));
    document.querySelectorAll("button.star[data-fav]").forEach(b => {
      const f = on.has(key(b.dataset.fav));
      b.hidden = false;
      b.textContent = f ? "★" : "☆";
      b.classList.toggle("on", f);
      b.setAttribute("aria-pressed", String(f));
      if (b.dataset.wired) return;
      b.dataset.wired = "1";
      b.addEventListener("click", ev => {
        ev.preventDefault(); ev.stopPropagation();  // inside a post's summary: do not open or close the details
        const u = b.dataset.fav, had = (state.favorites || []).some(x => key(x) === key(u));
        state.favorites = had ? state.favorites.filter(x => key(x) !== key(u)) : [...(state.favorites || []), u];
        paintStars();
        save(had ? "Removed from your favorites." : "Favorite saved. It is posted more often from the next run.", rmsg);
      });
    });
  }
  function draw() {
    if (!list.querySelector(".dirty")) {  // never wipe out something being typed
      list.classList.add("edit");
      list.replaceChildren(...state.topics.map(card));
    }
    // the Up next table: requests saved here but not yet queued go on top as "waiting", each with a Remove button,
    // and waiting rows already in the queue get a Remove button too (it takes effect at the next run)
    const qt = document.querySelector("table.queue");
    if (!qt) return paintStars();
    qt.querySelectorAll("tr[data-pending], tr.none").forEach(r => r.remove());
    const removed = new Set((state.removed || []).map(key));
    const removeBtn = fn => {
      const b = el("button", {type: "button", textContent: "Remove", className: "remove"});
      b.addEventListener("click", fn);
      return b;
    };
    const head = qt.querySelector("tr");
    for (const u of state.requests.filter(u => !known.has(key(u))).reverse()) {
      const tr = el("tr"), a = el("a", {href: u, textContent: u.replace("https://github.com/", "")}), st = el("td");
      tr.dataset.pending = u;
      st.append(el("span", {className: "pill waiting", textContent: "waiting"}), " ",
                removeBtn(() => { state.requests = state.requests.filter(x => x !== u); save("Removed.", rmsg); }),
                el("small", {textContent: "joins the queue at the next run"}));
      const c1 = el("td"); c1.append(starBtn(u), a);
      tr.append(c1, el("td", {textContent: "dashboard"}), el("td", {className: "n", textContent: ""}), el("td", {className: "n", textContent: "just now"}), st);
      head.after(tr);
    }
    document.querySelectorAll("table.queue tr[data-waiting]").forEach(tr => {
      const u = tr.dataset.waiting, st = tr.lastElementChild;
      st.querySelectorAll("button.remove, small.gone").forEach(x => x.remove());
      if (removed.has(key(u))) return st.append(el("small", {className: "gone", textContent: "removed: it leaves the queue at the next run"}));
      st.append(" ", removeBtn(() => { state.removed = [...(state.removed || []), u]; save("Removed. It leaves the queue at the next run.", rmsg); }));
    });
    paintStars();
  }
  form.hidden = false; rform.hidden = false;
  draw();
  form.addEventListener("submit", ev => {
    ev.preventDefault();
    const name = document.getElementById("new-name"), qs = document.getElementById("new-queries"), q = lines(qs.value);
    if (!name.value.trim() || !q.length) return say("A topic needs a name and at least one search term.");
    state.topics.unshift({name: name.value.trim(), queries: q});
    name.value = ""; qs.value = "";
    save("Added at the top. It applies at the next run.");
  });
  function add(url) {
    if (known.has(key(url)) || state.requests.some(u => key(u) === key(url)))
      return say("That one is already queued or was already posted.", rmsg);
    state.requests.push(url);
    document.getElementById("new-repo").value = "";
    document.getElementById("matches").replaceChildren();
    save("Added. It joins the queue at the next run.", rmsg);
  }
  rform.addEventListener("submit", async ev => {
    ev.preventDefault();
    const box = document.getElementById("new-repo"), out = document.getElementById("matches"),
          m = box.value.match(/github\\.com\\/([\\w.-]+)\\/([\\w.-]+)/i);  // anywhere in the paste: tracking junk is fine
    if (m) return add("https://github.com/" + m[1] + "/" + m[2].replace(/\\.git$/, "").replace(/\\.+$/, ""));
    if (!box.value.trim()) return say("Type a GitHub link, a website, or the repo's name.", rmsg);
    say("Looking it up on GitHub...", rmsg);
    let found = [];
    try {
      const r = await fetch("api/find?q=" + encodeURIComponent(box.value.trim()));
      found = r.ok ? await r.json() : [];
    } catch (e) { found = []; }
    // something that looks like a web address can also be posted as a website, with no GitHub repo
    const typed = box.value.trim(), looksWeb = /^(https?:\\/\\/)?[\\w-]+(\\.[\\w-]+)+(\\/\\S*)?$/i.test(typed);
    const site = looksWeb ? (/^https?:\\/\\//i.test(typed) ? typed.replace(/^http:/i, "https:") : "https://" + typed).replace(/\\/+$/, "") : "";
    const choices = found.map(f => {
      const li = el("li"), b = el("button", {type: "button", textContent: "Add this one", className: "primary"});
      b.addEventListener("click", () => add(f.url));
      li.append(el("a", {href: f.url, target: "_blank", rel: "noopener", className: "name", textContent: f.name + " ↗"}),
                el("small", {textContent: "★ " + f.stars.toLocaleString() + " · " + (f.description || "")}), b);
      return li;
    });
    if (site) {
      const li = el("li"), b = el("button", {type: "button", textContent: "Post this website", className: "primary"});
      b.addEventListener("click", () => add(site));
      li.append(el("a", {href: site, target: "_blank", rel: "noopener", className: "name", textContent: site.replace(/^https:\\/\\//, "") + " ↗"}),
                el("small", {textContent: "The website itself, no GitHub repo: the post is written from the site."}), b);
      choices.push(li);
    }
    if (!choices.length) return say("Nothing on GitHub matched that. Try the repo's name, its link, or a website address.", rmsg);
    say(found.length ? "Is it one of these? Click a name to open it, then add the right one." : "No GitHub repo matched, but you can post the website itself.", rmsg);
    out.replaceChildren(...choices);
  });
})();
(() => {  // colour cues for every table: zeros fade; in ranked tables the best of each column turns green
  for (const td of document.querySelectorAll("td.n")) if (/^[-–]?$|^0([.]0+)?$/.test(td.textContent.trim())) td.classList.add("zero");
  for (const td of document.querySelectorAll("table.wins td.n")) if (!td.classList.contains("zero")) td.classList.add("best");
  for (const t of document.querySelectorAll("table.rank")) {
    const rows = [...t.querySelectorAll("tr")].slice(1), cols = rows[0] ? rows[0].children.length : 0;
    for (let c = 0; c < cols; c++) {
      const cells = rows.map(r => r.children[c]).filter(td => td && td.classList.contains("n") && !td.closest("tr").querySelector("th"));
      const val = td => parseFloat(td.textContent.replace(/,/g, "")) || 0, best = Math.max(0, ...cells.map(val));
      if (best > 0 && t.querySelector("tr").children[c].textContent !== "Posts") cells.forEach(td => { if (val(td) === best) td.classList.add("best"); });
    }
  }
})();
"""


def dashboard():
    e = html.escape
    cfg, posts, cands = load(CONFIG), load(LEDGER, []), load(CANDIDATES, {"candidates": []})
    queue = load_queue()["items"]
    growth = load(GROWTH, {"followers": {}, "posts": [], "last_30_days": {}})
    live = [p for p in posts if p["status"] == "live"]
    score = dict(zip((p["dir"] for p in live), growth_scores([p.get("stats", {}) for p in live])))
    month = growth.get("last_30_days", {})
    followers_now = growth["followers"][max(growth["followers"])] if growth["followers"] else None
    month_ago = [d for d in sorted(growth["followers"]) if d <= str((now() - timedelta(days=30)).date())] or sorted(growth["followers"])[:1]
    net_change = (f"{followers_now - growth['followers'][month_ago[-1]]:+d} since {month_ago[-1]}" if month_ago else "")
    settled = [r for r in growth.get("posts", []) if r["date"] <= str((now() - timedelta(days=3)).date())]
    # Top posts: the account's best of the last 60 days, so it is clear what kind of post works
    recent = [r for r in growth.get("posts", []) if not r.get("gone") and r["date"] >= str((now() - timedelta(days=60)).date())]
    med = sorted(r.get("reach") or 0 for r in recent)[len(recent) // 2] if recent else 0
    def caption_link(r):
        text = e((r.get("caption") or "(no caption)")[:70])
        return f'<a href="{e(r["url"])}" target="_blank" rel="noopener">{text}</a>' if r.get("url") else text

    top_rows = "".join(
        f"<tr><td style='font-family:var(--mono);white-space:nowrap'>{e(r['date'][5:])}</td>"
        f"<td>{'ManyReply carousel' if r.get('ours') else 'ManyReply Reel' if r.get('reel') else e((r.get('kind') or 'post').capitalize())}</td>"
        f"<td>{caption_link(r)}</td>"
        f"<td class='n'>{r.get('reach') or 0:,}</td><td class='n'>{round((r.get('reach') or 0) / med, 1) if med else '–'}x</td>"
        f"<td class='n'>{r.get('saves') or 0}</td><td class='n'>{r.get('shares') or 0}</td><td class='n'>{r.get('follows') or 0}</td></tr>"
        for r in sorted(recent, key=lambda r: (r.get("reach") or 0, r.get("follows") or 0), reverse=True)[:10])
    compare_rows = "".join(
        f"<tr><td>{label}</td><td class='n'>{len(rows)}</td><td class='n'>{average(rows, 'reach')}</td>"
        f"<td class='n'>{average(rows, 'views')}</td><td class='n'>{sum(r['saves'] for r in rows)}</td>"
        f"<td class='n'>{sum(r['shares'] for r in rows)}</td><td class='n'>{sum(r['follows'] for r in rows)}</td></tr>"
        for label, rows in (("ManyReply carousels", [r for r in settled if r["ours"]]),
                            ("ManyReply Reels", [r for r in settled if r.get("reel")]),
                            ("Everything else", [r for r in settled if not r["ours"] and not r.get("reel")])))
    mean = lambda rows, k: sum(r.get(k) or 0 for r in rows) / len(rows) if rows else 0
    groups = [(name, value, rows)
              for field, name in (("topic", "topic"), ("style", "style"), ("hook", "hook"), ("slot", "posting time"))
              for value in sorted({p[field] for p in live if p.get(field)})
              for rows in [[p.get("stats", {}) for p in live if p.get(field) == value]]]
    groups.sort(key=lambda g: (sum(r.get("follows") or 0 for r in g[2]), mean(g[2], "reach"), mean(g[2], "keyword_comments")),
                reverse=True)  # what is working best comes first
    working_rows = "".join(
        f"<tr><td>{name}</td><td>{e(value)}</td><td class='n'>{len(rows)}</td><td class='n'>{average(rows, 'reach')}</td>"
        f"<td class='n'>{average(rows, 'keyword_comments')}</td><td class='n'>{sum(r.get('follows', 0) for r in rows)}</td></tr>"
        for name, value, rows in groups)
    stat = lambda p, k: p.get("stats", {}).get(k)
    total = lambda k: sum(stat(p, k) or 0 for p in posts)
    num = lambda v: "–" if v is None else f"{v:,}"
    last = last_live(posts)
    done_today = bool(last and last.astimezone().date() >= local_now().date())
    clock = lambda dt: dt.astimezone().strftime("%a %d %b, %I:%M %p").replace(", 0", ", ")
    plan = []  # (when, what, status, link on Instagram once it is out)
    booked = live_or_booked(posts)
    newest = max(booked, key=lambda p: p["date"]) if booked else None
    for p in booked:
        when = datetime.fromisoformat(p["date"])
        if p is newest or when.astimezone().date() >= local_now().date():
            name = p["repo"].split("github.com/")[-1]
            plan.append((clock(when), f"Carousel: {name} ({p['keyword']})", p["status"], p.get("instagram_url")))
            if p.get("story", {}).get("zernio_post_id"):
                plan.append((clock(when + timedelta(minutes=5)), "Story for it", "live" if p["status"] == "live" else p["status"],
                             p["story"].get("url") or (f"https://www.instagram.com/stories/{cfg['handle']}/" if p["status"] == "live" else None)))
            reel = p.get("reel", {})
            if reel.get("slot"):
                hour, minute = map(int, reel["slot"].split(":"))
                plan.append((clock(when.astimezone().replace(hour=hour, minute=minute)), "Reel for it", reel.get("status", ""), reel.get("url")))
    times = cfg.get("post_times", [])
    if times:
        slot = times[sum(1 for p in posts if p.get("dir")) % len(times)]
        day = local_now() + timedelta(days=1 if done_today else 0)
        hour, minute = map(int, slot.split(":"))
        upcoming = next_pick(posts, load_queue())
        app = None if upcoming else app_due(posts)
        fav = None if upcoming or app else fav_due(posts, load_queue())
        what = (f"{upcoming['url'].split('github.com/')[-1]} (your turn: you asked, via {upcoming['source']})" if upcoming
                else f"your app {app_name(app)}" if app
                else f"your favorite {fav.split('github.com/')[-1]}" if fav else "the search's pick (its turn)")
        plan.append((clock(day.replace(hour=hour, minute=minute)), f"Next carousel: {what}", "planned", None))
    next_due = plan[-1][0] if plan else "today"
    plan_rows = "".join(f"<tr><td class='n' style='text-align:left'>{e(w)}</td><td>{e(x)}</td>"
                        f"<td><span class='pill {e(st)}'>{e(st)}</span></td></tr>" for w, x, st, _ in plan)

    def link(url, text):
        return f'<a href="{e(url)}">{e(text)}</a>' if url else e(text)

    favs_now = {norm(u) for u in my_favorites()}

    def star(url):  # the favorite switch beside a repo; the page's script makes it work (hidden on a read-only page)
        on = norm(url) in favs_now
        return (f"<button type='button' class='star{' on' if on else ''}' data-fav='{e(url)}' aria-pressed='{str(on).lower()}'"
                f"{'' if on else ' hidden'} title='Favorite: posted more often'>{'★' if on else '☆'}</button>")

    short = lambda u: u.split("github.com/")[-1] if "github.com/" in u else urllib.parse.urlsplit(u).netloc + urllib.parse.urlsplit(u).path[:38]
    cand_rows = "".join(
        f"<tr><td class='n'>{i}</td><td>{star(c['url'])}{link(c['url'], c['name'])}<small>{e(c['description'])}</small></td>"
        f"<td>{e(c['topic'])}</td><td class='n'>{num(c.get('stars'))}</td><td class='n'>{num(c.get('stars_per_day'))}</td>"
        f"<td class='n'>{e(c.get('created', ''))}</td><td class='n'>{num(c['score'])}</td></tr>"
        for i, c in enumerate((c for c in cands["candidates"]
                               if norm(c["url"]) not in {norm(p["repo"]) for p in posts} | {norm(q["url"]) for q in queue if q["url"]}), 1))
    def chips(repo, label=""):  # how a repo's newest live post is doing, one line of numbers (Up next, My apps, older posts)
        hits = [q for q in posts if q["status"] == "live" and repo and norm(q["repo"]) == norm(repo)]
        st = max(hits, key=lambda q: q["date"]).get("stats", {}) if hits else None
        if not st:
            return ""
        lead = f"<span class='lead'>{e(label.format(date=max(hits, key=lambda q: q['date'])['date'][:10]))}</span>" if label else ""
        return "<div class='res'>" + lead + "".join(
            f"<span class='{'z' if not st.get(k) else 'win' if k in ('follows', 'shares', 'saves', 'keyword_comments', 'link_clicks') else ''}'>"
            f"{icon(ic)}<b>{st.get(k) or 0:,}</b> {t}</span>"
            for k, ic, t in (("reach", "trend", "reached"), ("views", "eye", "views"), ("likes", "heart", "likes"),
                             ("comments", "chat", "comments"), ("saves", "bookmark", "saves"), ("shares", "send", "sends"),
                             ("follows", "user", "follows"), ("keyword_comments", "star", "word comments"),
                             ("link_clicks", "click", "link clicks"))) + "</div>"

    def results(item):  # a posted request's numbers, as a row under it in the Up next table
        line = chips(item["url"])
        return f"<tr class='res-row'><td colspan='5'>{line}</td></tr>" if line else ""

    def note(text):  # a few words beside the status; the whole note when you hover it
        if not text:
            return ""
        short = text.split(":")[0].split(".")[0]
        short = short if len(short) <= 40 else short[:38].rsplit(" ", 1)[0] + "…"
        return f" <span class='qnote' title='{e(text)}'>{e(short)}</span>"

    queue_rows = "".join(
        f"<tr{' data-waiting=' + chr(34) + e(i['url']) + chr(34) if i['status'] == 'waiting' and i['url'] else ''}>"
        f"<td>{star(i['url']) if i['url'] and i['status'] != 'skipped' else ''}"
        f"{link(i['url'], i['url'].split('github.com/')[-1]) if i['url'] else e(repr(i.get('query', '')))}</td><td>{e(i['source'])}</td>"
        f"<td class='n' title='GitHub stars'>{short_count(gh_stars(i['url'], cands)) if i['url'] else ''}</td>"
        f"<td class='n'>{e(i['added'][:10])}</td>"
        f"<td><span class='pill {e(i['status'].replace(' ', '-'))}'>{e(i['status'])}</span>"
        f"{note(i.get('note'))}</td></tr>{results(i)}"
        for i in sorted(queue, key=lambda i: (i["status"] != "waiting", i["source"] != "telegram", not is_favorite(i["url"]), i["added"])))
    known = json.dumps(sorted({norm(i["url"]) for i in queue if i["url"]} | {norm(p["repo"]) for p in posts})).replace("</", "<\\/")
    topics = "".join(f"<li><b><i>{i}</i>{e(t['name'])}</b><p>{'<br>'.join(e(q) for q in t['queries'])}</p></li>"
                     for i, t in enumerate(cfg["topics"], 1))
    tools_link = f'<br><a href="{e(cfg["tools_url"])}" style="color:var(--mint)">public tools page</a>' if cfg.get("tools_url") else ""
    words = "".join(f"<span class='word'>{e(p['keyword'])}</span>" for p in sorted(posts, key=lambda p: p["keyword"]))
    # ---- analytics over 7, 14 and 30 days, each against the period before it
    today = local_now().date()

    def followers_on(day):  # the count on or before that day
        known = [d for d in sorted(growth["followers"]) if d <= str(day)]
        return growth["followers"][known[-1]] if known else None

    def window(days, back=0):
        end, start = today - timedelta(days=back), today - timedelta(days=back + days)
        f_end, f_start = followers_on(end), followers_on(start)
        acct = [r for r in growth.get("posts", []) if str(start) < r["date"] <= str(end)]
        mine = [p for p in posts if p.get("dir") and str(start) < p["date"][:10] <= str(end)]
        add = lambda rows, k: sum((r.get(k) or 0) for r in rows)
        return {"followers": f_end - f_start if f_end is not None and f_start is not None else None,
                "reach": add(acct, "reach"), "shares": add(acct, "shares"), "saves": add(acct, "saves"),
                "follows": add(acct, "follows"), "carousels": len(mine),
                "words": add([q.get("stats", {}) for q in mine], "keyword_comments"),
                "dms": add([q.get("stats", {}) for q in mine], "dms_sent"),
                "clicks": add([q.get("stats", {}) for q in mine], "link_clicks"),
                "views": add(acct, "views"), "likes": add(acct, "likes"), "comments": add(acct, "comments"),
                "reel_views": add([q.get("reel", {}).get("stats", {}) for q in mine], "views"),
                "gate": add([q.get("stats", {}) for q in mine], "gate_passed")}

    tiles_meta = [("followers", "Followers", True), ("carousels", "Carousels posted", False), ("shares", "Sends", False),
                  ("saves", "Saves", False), ("follows", "Follows from posts", False),
                  ("words", "Word comments", False), ("dms", "Links sent by DM", False), ("clicks", "Link clicks", False),
                  ("views", "Views", False), ("likes", "Likes", False), ("comments", "Comments", False),
                  ("reel_views", "Reel views", False)]

    def tiles(days):
        cur, prev = window(days), window(days, days)
        out = ""
        for key, label, signed in tiles_meta:
            v, w = cur[key], prev[key]
            shown = "–" if v is None else (f"{v:+,}" if signed else f"{v:,}")
            trend = "" if v is None or w is None or v == w else "up" if v > w else "down"
            if key == "followers" and v is not None:
                trend = "up" if v > 0 else "down" if v < 0 else ""  # followers: gained or lost, not more than last time
            if v is None or w is None:
                pill, note = "", "no earlier data"
            else:
                d = v - w
                pill = (f"<i class='{'up' if d > 0 else 'down' if d < 0 else 'flat'}'>{'▲' if d > 0 else '▼' if d < 0 else '='} "
                        f"{abs(d):,}</i>")
                note = {1: "vs the 24 hours before", 365: "vs the year before"}.get(days, f"vs previous {days}d")
            ic = {"followers": "user", "reach": "trend", "shares": "send", "saves": "bookmark", "follows": "star",
                  "carousels": "image", "words": "chat", "dms": "link", "clicks": "click", "views": "eye", "likes": "heart",
                  "comments": "chat", "reel_views": "play", "gate": "lock"}[key]
            out += f"<div>{icon(ic)}<span>{label}</span><b class='{trend}'><span>{shown}</span>{pill}</b><small>{note}</small></div>"
        return out

    periods = (1, 7, 14, 30, 60, 90, 365)
    # the top bar's key number: people reached this week, against the week before (the tiles leave it out)
    r_now, r_was = window(7)["reach"], window(7, 7)["reach"]
    r_d = None if r_now is None or r_was is None else r_now - r_was
    reach_fact = (f'<div class="fact">{icon("trend")}<div><b>{"–" if r_now is None else f"{r_now:,}"} reached</b><span>last 7 days'
                  + ("" if r_d is None else f' · <em class="{"up" if r_d > 0 else "down" if r_d < 0 else "flat"}">'
                     f'{"▲" if r_d > 0 else "▼" if r_d < 0 else "="} {abs(r_d):,}</em> vs week before') + '</span></div></div>')
    tabs = "".join(f'<input type="radio" name="period" id="p{d}"{" checked" if d == 1 else ""}>' for d in periods)
    tab_labels = "".join(f'<label for="p{d}">{"24 hours" if d == 1 else "1 year" if d == 365 else f"{d} days"}</label>' for d in periods)
    panels = "".join(f'<div class="tiles p{d}">{tiles(d)}</div>' for d in periods)

    # ---- one line per post, newest first, with the next planned one on top; details open on a click
    def clicks(v):
        return f"<span class='clk{' hot' if v else ''}'>{v or 0}</span>"

    reaches = [stat(q, "reach") for q in posts if q["status"] == "live" and stat(q, "reach") is not None]
    usual = sum(reaches) / len(reaches) if reaches else 0

    def reach_chip(p):
        r = stat(p, "reach")
        if r is None:
            return ""
        cls = "hi" if usual and r >= usual * 1.25 else "lo" if usual and r <= usual * 0.6 else ""
        return f"<span class='rch {cls}' title='Reach; the usual post reaches {usual:.0f}'>{r:,} reach</span>"

    def post_line(p):
        st = p.get("stats", {})
        reel = p.get("reel", {})
        detail = [("Why", p.get("why", "")), ("Picked by", p.get("source", "search")), ("Style", p.get("style", "")),
                  ("Posted at", p.get("slot", "")), ("Likes", num(stat(p, "likes"))), ("Comments", num(stat(p, "comments"))),
                  ("Word comments", num(stat(p, "keyword_comments"))), ("Story replies", num(stat(p, "story_replies"))),
                  ("Follow gate: asked / passed", f"{num(stat(p, 'gate_sent'))} / {num(stat(p, 'gate_passed'))}"),
                  ("Links sent by DM", num(stat(p, "dms_sent"))), ("Reach", num(stat(p, "reach"))),
                  ("Saves", num(stat(p, "saves"))), ("Sends", num(stat(p, "shares"))), ("Follows", num(stat(p, "follows"))),
                  ("Score", num(score.get(p.get("dir")))),
                  ("Reel", f"{num(reel.get('stats', {}).get('views'))} views, {num(reel.get('stats', {}).get('reach'))} reached"
                   + (f" · {link(reel.get('instagram_url'), 'open')}" if reel.get("instagram_url") else ""))]
        rows = "".join(f"<dt>{e(k)}</dt><dd>{v if k == 'Reel' else e(str(v))}</dd>" for k, v in detail if v not in ("", None))
        return (f"<details class='post'><summary><span class='d'>{e(p['date'][:10])}</span>"
                f"<span class='r'>{star(p['repo']) if p.get('source') != 'app' else ''}{e(p['repo'].split('github.com/')[-1])}</span><span class='word'>{e(p['keyword'])}</span>"
                f"<span class='t'>{e(p.get('topic', ''))}</span><span class='pill {e(p['status'])}'>{e(p['status'])}</span>"
                f"{reach_chip(p)}{clicks(stat(p, 'link_clicks'))}"
                f"<span class='ig'>{link(p.get('instagram_url'), 'Instagram') if p.get('instagram_url') else ''}</span></summary>"
                f"<dl>{rows}<dt>Repo</dt><dd>{link(p['repo'], p['repo'])}</dd></dl></details>")

    planned = [x for x in plan if x[2] == "planned"]
    next_line = (f"<div class='post planned-row'><span class='d'><b>Next post</b>{e(planned[0][0])}</span><span class='r'>{e(planned[0][1])}</span>"
                 f"<span class='pill planned'>planned</span></div>" if planned else "")
    post_lines = "".join(post_line(p) for p in sorted(posts, key=lambda p: p["date"], reverse=True)
                                     if p["status"] == "live")
    def again(p):  # an older post that was starred and posted again: its new numbers, as a row under it (or when it is booked)
        line = chips(p["repo"], "Posted again {date}")
        booked = [q for q in posts if q["status"] == "scheduled" and norm(q["repo"]) == norm(p["repo"])]
        if not line and booked:
            line = f"<div class='res'><span class='lead'>Posting again {e(max(q['date'] for q in booked)[:10])}</span></div>"
        return f"<tr class='res-row'><td colspan='6'>{line}</td></tr>" if line else ""

    legacy_rows = "".join(
        f"<tr><td><span class='word'>{e(p['keyword'])}</span></td><td>{star(p['repo'])}{link(p.get('link', p['repo']), short(p.get('link', p['repo'])))}</td>"
        f"<td class='n' title='GitHub stars'>{short_count(gh_stars(p['repo'], cands)) if REPO_RE.match(p['repo']) else ''}</td>"
        f"<td class='n'>{num(stat(p, 'keyword_comments'))}</td><td class='n'>{num(stat(p, 'dms_sent'))}</td>"
        f"<td class='n'>{clicks(stat(p, 'link_clicks'))}</td></tr>{again(p)}"
        for p in sorted(posts, key=lambda p: (-(stat(p, 'link_clicks') or 0), -(stat(p, 'dms_sent') or 0),
                                              -(stat(p, 'keyword_comments') or 0), p["keyword"])) if p["status"] == "legacy")
    legacy_clicks = sum(stat(p, "link_clicks") or 0 for p in posts if p["status"] == "legacy")
    week = window(7)["followers"]
    def five(rows_html, start, wrap, empty):
        """The first five items, then the rest behind a "show more" toggle. `start` is a regex where each item begins."""
        items = [x for x in re.split(f"(?={start})", rows_html) if x.strip()]
        if not items:
            return f'<div class="empty">{empty}</div>'
        more = (f"<details class='more'><summary>Show {len(items) - 5} more</summary>{wrap(''.join(items[5:]))}</details>"
                if len(items) > 5 else "")
        return wrap("".join(items[:5])) + more

    table = lambda head: (lambda rows: f'<div class="scroll"><table><tr>{head}</tr>{rows}</table></div>')
    plan_html = five(plan_rows, "<tr>", table("<th>When</th><th>What</th><th>Status</th>"), "Nothing booked yet.")
    posts_html = five(post_lines, "<details class='post'>|<div class='post planned-row'>",
                      lambda r: f'<div class="posts">{r}</div>', "Nothing posted yet.")
    queue_table = lambda rows: (f'<div class="scroll"><table class="queue"><tr><th>Repo</th><th>Sent by</th>'
                                f'<th class="n" title="GitHub stars">Stars</th><th class="n">Added</th><th>Status</th></tr>{rows}</table></div>')
    queue_html = (five(queue_rows, "<tr(?! class='res-row')[ >]", queue_table, "") if queue_rows else
                  queue_table("<tr class='none'><td colspan='5'>Nothing requested. The next post comes from the search.</td></tr>"))
    cand_html = five(cand_rows, "<tr>", table('<th class="n">#</th><th>Repo</th><th>Topic</th><th class="n">Stars</th>'
                                              '<th class="n">Stars / day</th><th class="n">Created</th><th class="n">Score</th>'),
                     "No search has run yet.")
    legacy_html = five(legacy_rows, "<tr>", lambda r: table('<th>Comment word</th><th>Link sent</th><th class="n">Stars</th><th class="n">Word comments</th>'
                       '<th class="n">DMs</th><th class="n">Clicks</th>')(r).replace("<table>", "<table class='wins'>", 1), "None.")
    words_html = f'<div class="words">{words}</div>' if words else '<div class="empty">None yet.</div>'
    app_posts = [p for p in posts if p.get("source") == "app" and p.get("status") in ("live", "scheduled")]
    app_last = max((p["date"] for p in app_posts), default=None)
    app_next = (datetime.fromisoformat(app_last) + timedelta(days=APP_EVERY_DAYS)).astimezone() if app_last else None
    app_note = ("Next one is due now (first weekday on the search's turn)." if not app_next or app_next <= local_now()
                else f"Next one from {app_next:%a %d %b}.")
    app_rows = "".join(
        f"<li data-url='{e(app_id(a))}'><a href='{e(app_id(a))}' target='_blank' rel='noopener'>{e(app_name(a))}</a>"
        + (f" · <a href='{e(a['site'])}' target='_blank' rel='noopener'>website</a>" if a.get("site") and a.get("url") else "")
        + (f"<small>{e(a['pitch'])}</small>" if a.get("pitch") else "")
        + f"<span class='pill {'live' if any(norm(p['repo']) == norm(app_id(a)) for p in app_posts) else 'planned'}'>"
        + (f"posted {max(p['date'] for p in app_posts if norm(p['repo']) == norm(app_id(a)))[:10]}"
           if any(norm(p['repo']) == norm(app_id(a)) for p in app_posts) else "not posted yet") + "</span>"
        + chips(app_id(a)) + "</li>"
        for a in my_apps()) or "<li class='none'>No apps yet. Add your first one below.</li>"
    upcoming = ACTIVE_STYLES[sum(1 for p in posts if p.get("dir")) % len(ACTIVE_STYLES)]
    used = lambda st: sum(1 for p in posts if p.get("style") == st and p["status"] == "live")

    def style_card(st):
        pics = "".join(f'<img src="/dashboard/looks/{st}-{n}.png" alt="" loading="lazy" width="360" height="450">' for n in (1, 2, 3))
        tag = "<span class='pill planned'>next post</span>" if st == upcoming else ""
        return (f"<div class='style'><div class='st-head'><b>{e(st.replace('-', ' ').title())}</b>{tag}"
                f"<span class='st-used'>used on {used(st)} live post{'s' if used(st) != 1 else ''}</span></div>"
                f"<p>{e(STYLE_NOTES.get(st, ''))}</p><div class='st-pics'>{pics}</div></div>")

    others = [st for st in ACTIVE_STYLES if st != upcoming]
    styles_html = (style_card(upcoming) + f"<details class='more'><summary>See all {len(ACTIVE_STYLES)} styles</summary>"
                   + "".join(style_card(st) for st in others) + "</details>")

    def head(ic, title, sub="", aside=""):
        return (f'<div class="head">{icon(ic)}<div><h2>{title}</h2>{f"<p>{sub}</p>" if sub else ""}</div>'
                f'{f"<div class=aside>{aside}</div>" if aside else ""}</div>')

    def sched_card(w, x, st, url):
        kind = ("story" if x.startswith("Story") else "reel" if x.startswith("Reel")
                else "next" if x.startswith("Next") else "carousel")
        title = {"story": "Story", "reel": "Reel", "next": "Next post", "carousel": "Carousel"}[kind]
        what = x.split(": ", 1)[1] if ": " in x else ""
        ic = {"story": "story", "reel": "play", "next": "calendar", "carousel": "image"}[kind]
        return (f"<div><span class='ic {kind}'>{icon(ic)}</span><b>{e(title)}</b><span>{e(w)}</span>"
                f"{f'<small title={chr(34)}{e(what)}{chr(34)}>{e(what)}</small>' if what else ''}"
                f"<span class='pill {e(st)}'>{e(st)}</span>"
                f"{f'<a class=open href={chr(34)}{e(url)}{chr(34)} target=_blank rel=noopener>Open on Instagram ↗</a>' if url else ''}</div>")

    missed = missed_days(posted_days(posts), local_now().date(), past_last_slot(cfg))
    missed_bar = (f'<div class="alert" id="missed" role="status"{"" if missed else " hidden"}>{icon("info")}<span>'
                  + (("No post went out on " + ", ".join(d.strftime("%a %b ") + str(d.day) for d in missed)
                      + ". The next daily run retries it until it is live.") if missed else "")
                  + "</span></div>")
    sched_cards = "".join(sched_card(*x) for x in plan) or '<div class="empty">Nothing booked yet.</div>'
    nav = "".join(f'<a href="#{a}"{" class=on" if a == "top" else ""}>{icon(i)}{t}</a>' for a, i, t in (
        ("top", "home", "Dashboard"), ("schedule", "calendar", "Schedule"), ("posts", "file", "Posted"),
        ("analytics", "bars", "Analytics"), ("perf", "bars", "Performance by Type"), ("top-posts", "star", "Top Posts"), ("growth", "trend", "Growth"),
        ("upnext", "list", "Up Next"), ("apps", "repo", "My Apps"), ("working", "star", "What's Working"), ("topics-card", "search", "Search Topics"),
        ("repos", "repo", "Repositories"), *([("older", "link", "Words from Older Posts")] if legacy_rows else []),
        ("styles", "image", "Current Styles"), ("words", "chat", "Comment Words")))
    tools_fact = (f'<a class="fact" href="{e(cfg["tools_url"])}">{icon("link")}<div><b>Tools</b><span>Public page</span></div></a>'
                  if cfg.get("tools_url") else "")
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>ManyReply Dashboard</title>{FAVICON}
<meta name="robots" content="noindex"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap">
<style>{DASH_CSS}</style>
<script>try{{const t=localStorage.getItem('theme');if(t)document.documentElement.dataset.theme=t}}catch(e){{}}</script></head><body>
<div class="app">
<aside class="side"><a class="brand" href="#top">{LOGO}<span>Many<b>Reply</b></span></a>
<nav aria-label="Sections">{nav}</nav>
<div class="promo"><svg class="i" viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="5"/><circle cx="12" cy="12" r="3.5"/><path d="M17 7h.01"/></svg><b>Automate. Engage. Grow.</b><p>Find great GitHub repos, turn them into Instagram posts, and turn comments into new followers.</p></div></aside>
<div class="main" id="top">
<div class="topbar"><div class="facts">
<button type="button" class="fact theme" id="theme" aria-label="Switch light or dark mode"><svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 13A9 9 0 1 1 11 3a7 7 0 0 0 10 10z"/></svg><div><b>Theme</b><span id="theme-name">Auto</span></div></button>
<div class="fact"><svg class="i ig" viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="5"/><circle cx="12" cy="12" r="3.5"/><path d="M17 7h.01"/></svg><div><b>@{e(cfg['handle'])}</b><span>{num(followers_now)} followers{f' · <em class="{"up" if week > 0 else "down" if week < 0 else "flat"}">{week:+,}</em> (7d)' if week is not None else ""}</span></div></div>
{reach_fact}
<button type="button" class="fact theme" id="refresh" title="Pull the latest numbers now (free, about 2 minutes)">{icon("clock")}<div><b>Last updated</b><span id="refresh-note">{local_now():%b %d, %I:%M %p} ET · Update now</span></div></button>
{tools_fact}</div></div>
<div class="grid">
<div class="col">
<section class="card" id="schedule" style="grid-area:sched">{head("clock", "Schedule", f"What goes out next, in your local time ({local_now():%Z})", missed_bar)}
<div class="sched">{sched_cards}</div></section>
<section class="card growth" id="growth" style="grid-area:growth">{head("trend", "Growth", "Follower history. The small bars along the bottom are days you posted (taller means more posts). Click a day to see those posts.")}
<div class="gbody">{follower_chart(growth["followers"], growth.get("posts", []))}</div></section>
<section class="card" id="perf" style="grid-area:perf">{head("bars", "Performance by type", "Posts at least 3 days old")}
<div class="scroll"><table class="rank"><tr><th>Type</th><th class="n">Posts</th><th class="n">Avg reach</th><th class="n">Avg views</th><th class="n">Saves</th><th class="n">Shares</th><th class="n">Follows</th></tr>{compare_rows}</table></div></section>
<section class="card" id="top-posts" style="grid-area:top">{head("star", "Top posts", "Your 10 best posts of the last 60 days by reach. The x column is reach against your usual post: copy what the top ones have in common.")}
{five(top_rows, "<tr>", lambda r: table('<th>Date</th><th>Type</th><th>Post</th><th class="n">Reach</th><th class="n">x usual</th><th class="n">Saves</th><th class="n">Sends</th><th class="n">Follows</th>')(r).replace("<table>", "<table class='rank'>", 1), "Shows up once posts have numbers.")}</section>
<section class="card" id="posts" style="grid-area:posts">{head("file", "Posted", "What went out, newest first. Click a line for its details; a red number means people clicked the link.")}
{posts_html}</section>
<section class="card" id="topics-card" style="grid-area:topics">{head("search", "Search topics", "What it searches GitHub for. The higher a topic sits, the more its repos are favoured.")}
<ul class="topics" id="topics">{topics}</ul>
<form id="add-topic" hidden><h3>Add a topic</h3>
<label for="new-name">Name</label><input id="new-name" required maxlength="60" placeholder="e.g. Claude skills">
<label for="new-queries">GitHub search terms, one per line</label><textarea id="new-queries" required rows="3" placeholder="claude skills&#10;agent skills"></textarea>
<button type="submit">Add to the top</button></form>
<p id="topics-msg" class="msg" role="status"></p></section>
<section class="card" id="repos" data-sortable style="grid-area:found">{head("repo", "Repositories", f"What the latest search found, {e(cands.get('generated_at', 'not run yet')[:10])}. Repos already posted are left out. Click a star to make one a favorite: it goes out in your next favorite slot.")}
{cand_html}</section>
</div><div class="col">
<section class="card" id="analytics" style="grid-area:anal">{head("bars", "Analytics", "Each period against the one before it")}
<div class="periods">{tabs}<div class="tabs">{tab_labels}</div>{panels}</div>
<div class="info">{icon("info")}<span>Reach, sends, saves and follows cover everything the account posted. Word comments, links and clicks cover the ManyReply carousels only. Instagram's numbers lag about two days. In the last 30 days the account reached {num(month.get('reach'))} people and {num(month.get('accounts_engaged'))} of them engaged.</span></div></section>
<section class="card" id="apps" style="grid-area:apps">{head("repo", "My apps", f"Your own apps. One goes out every 3 weeks on a weekday, taking the search's turn; each comes back after 90 days at the earliest. {e(app_note)}")}
<ul class="apps" id="app-list">{app_rows}</ul>
<form id="add-app" hidden><p class="note">A GitHub repo, a website, or both. With both, the post links people to the website.</p>
<label for="app-url">GitHub link</label><input id="app-url" placeholder="https://github.com/you/your-app">
<label for="app-site">Website</label><input id="app-site" placeholder="https://yourapp.com">
<label for="app-pitch">One line about it (optional)</label><input id="app-pitch" maxlength="120" placeholder="What it does and who it's for">
<button type="submit">Add app</button></form><p id="apps-msg" class="msg" role="status"></p></section>
<section class="card" id="working" style="grid-area:work">{head("star", "What's working", "ManyReply posts by topic, style and posting time, best first")}
{five(working_rows, "<tr>", lambda r: table('<th>Group</th><th>Value</th><th class="n">Posts</th><th class="n">Avg reach</th><th class="n">Avg word comments</th><th class="n">Follows</th>')(r).replace("<table>", "<table class='rank'>", 1), "Shows up once posts have numbers.")}</section>
<section class="card" id="upnext" style="grid-area:next">{head("list", "Up next", f"Posted before anything the search finds: Telegram first, then this list. Click a star to make a repo a favorite: favorites go ahead of other requests here, and come around again every {FAV_EVERY_DAYS} days or so, even ones you have already posted (each can return {FAV_AGAIN_DAYS} days after its last post, with a fresh angle). The Posted list has stars too.")}
<form id="add-repo" hidden><label for="new-repo">A GitHub link, a website, or the repo's name</label>
<input id="new-repo" required placeholder="github.com/owner/name, newpipe.net, or NewPipe"><button type="submit">Search</button></form>
<ul id="matches"></ul><p id="requests-msg" class="msg" role="status"></p>
{queue_html}</section>
<section class="card" id="styles" style="grid-area:styles">{head("image", "Current styles", f"The {len(ACTIVE_STYLES)} looks posts rotate through, one per post. Tell Claude which one to change and how.")}
{styles_html}</section>
<section class="card" id="words" style="grid-area:words">{head("chat", "Comment words", "Used already: a new post can never reuse one")}
{words_html}</section>
{f'''<section class="card" id="older" data-sortable style="grid-area:older">{head("link", f"Words from older posts {clicks(legacy_clicks)}", "Words on your posts from before ManyReply that still DM a link. Best first: link clicks, then links sent, then word comments. Click a star to bring one back as a new post (a fresh angle, a new word); its new numbers show under it.")}
{legacy_html}</section>''' if legacy_rows else ""}
</div>
</div>
<footer class="credit">{CREDIT}</footer></div></div>
<script>window.KNOWN_REPOS = {known};</script>
<script>(() => {{  // light / dark switch: Auto follows the device, then Light, then Dark
  const btn = document.getElementById("theme"), name = document.getElementById("theme-name"), root = document.documentElement;
  const show = () => name.textContent = {{light: "Light", dark: "Dark"}}[root.dataset.theme] || "Auto";
  btn.onclick = () => {{
    const dark = matchMedia("(prefers-color-scheme: dark)").matches;  // Auto, the opposite of the device, the device, Auto
    const order = dark ? ["", "light", "dark"] : ["", "dark", "light"], next = order[(order.indexOf(root.dataset.theme || "") + 1) % 3];
    if (next) root.dataset.theme = next; else delete root.dataset.theme;
    try {{ next ? localStorage.setItem("theme", next) : localStorage.removeItem("theme"); }} catch (e) {{}}
    show();
  }};
  show();
}})();</script>
<script>(() => {{  // "Update now": starts the free GitHub refresh; the new page is live about two minutes later
  const btn = document.getElementById("refresh"), note = document.getElementById("refresh-note");
  btn.onclick = async () => {{
    btn.disabled = true; note.textContent = "Starting the update…";
    try {{
      const r = await fetch("/dashboard/api/refresh", {{method: "POST"}}), j = await r.json().catch(() => ({{}}));
      if (!r.ok) throw new Error(j.error || "Update could not start.");
      let left = 150;
      const tick = setInterval(() => {{
        note.textContent = "Updating… reloads in " + Math.floor(left / 60) + ":" + String(left % 60).padStart(2, "0");
        if (--left < 0) {{ clearInterval(tick); location.reload(); }}
      }}, 1000);
    }} catch (e) {{ note.textContent = e.message; btn.disabled = false; }}
  }};
}})();</script>
<script>window.POST_DAYS = {json.dumps(sorted(d.isoformat() for d in posted_days(posts)))}; window.SCHED_TZ = {json.dumps(cfg.get("timezone"))}; window.LAST_SLOT = {json.dumps(max(cfg.get("post_times") or [""]) or None)};</script>
<script>{MISSED_JS}</script>
<script>{SORT_JS}</script>
<script>{DASH_JS}</script>
</body></html>
"""
    (ROOT / "site" / "dashboard").mkdir(parents=True, exist_ok=True)
    (ROOT / "site" / "dashboard" / "index.html").write_text(page, encoding="utf-8")
    tools_page(cfg, posts)


TOOLS_CSS = """
/* the same look as the dashboard: navy, blue and violet; light when the device asks for it */
:root{--bg:#F3F5FB;--surface:#FFFFFF;--raise:#F6F8FD;--fg:#111833;--muted:#5B6688;--line:#E2E7F3;--accent:#3B6CF6;
 --grad:linear-gradient(90deg,#7C3AED,#3B6CF6);--chip:#E8EEFF;--chip-ink:#2550D9;
 --body:'Plus Jakarta Sans','Segoe UI',system-ui,sans-serif;--mono:'JetBrains Mono',Consolas,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0A1023;--surface:#0F1731;--raise:#142043;--fg:#E9EDFA;
 --muted:#8D99C2;--line:#1F2B52;--accent:#4F8BFF;--chip:#16244D;--chip-ink:#9DBBFF;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0A1023;--surface:#0F1731;--raise:#142043;--fg:#E9EDFA;--muted:#8D99C2;--line:#1F2B52;
 --accent:#4F8BFF;--chip:#16244D;--chip-ink:#9DBBFF;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 var(--body);padding:16px clamp(16px,4vw,40px) 56px}
main{max-width:1100px;margin:0 auto;display:flex;flex-direction:column;gap:22px}
.top{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:10px;font:800 26px/1 var(--body);letter-spacing:-.02em;color:var(--fg);text-decoration:none}
.brand svg{width:46px;height:46px}
.brand b{background:linear-gradient(90deg,#60A5FA,#A78BFA);-webkit-background-clip:text;background-clip:text;color:transparent}
#theme{font:600 13px var(--body);color:var(--fg);background:var(--surface);border:1px solid var(--line);border-radius:999px;padding:9px 16px;cursor:pointer}
header{color:#fff;border-radius:22px;padding:clamp(24px,5vw,44px);overflow:hidden;
 background:radial-gradient(120% 90% at 100% 100%,#EC4899 0,transparent 50%),linear-gradient(135deg,#4C1D95,#6D28D9 45%,#3B6CF6)}
h1{font:800 clamp(32px,7vw,54px)/1.05 var(--body);letter-spacing:-.03em;margin:0 0 12px;max-width:16ch;text-wrap:balance}
header p{margin:0 0 22px;max-width:48ch;font-size:17px;color:#EDE9FE}
.btn{display:inline-flex;align-items:center;gap:10px;background:#fff;color:#4C1D95;font:700 15px/1 var(--body);padding:14px 20px;border-radius:12px;text-decoration:none}
.btn svg{width:22px;height:22px;color:#fff;background:linear-gradient(45deg,#F58529,#DD2A7B,#8134AF);border-radius:7px;padding:3px}
.btn.ghost{background:rgba(255,255,255,.14);color:#fff;border:1px solid rgba(255,255,255,.45);margin-left:8px}
.btn.ghost svg{background:none;padding:0}
@media (max-width:520px){.btn{display:flex;justify-content:center}.btn.ghost{margin:10px 0 0}}
.btn:focus-visible,input:focus-visible,a:focus-visible,button:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:18px 20px}
ol{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;counter-reset:step}
ol li{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:18px 20px;counter-increment:step;display:grid;grid-template-columns:auto 1fr;gap:4px 14px;align-items:center}
ol li::before{content:counter(step);grid-row:1/3;width:42px;height:42px;border-radius:11px;display:grid;place-items:center;
 color:#fff;font:800 19px/1 var(--body);background:var(--c,#3B6CF6)}
ol li:nth-child(2){--c:#A855F7}ol li:nth-child(3){--c:#16A34A}
ol li span{color:var(--muted);font-size:14px}
h2{font:800 20px/1.2 var(--body);letter-spacing:-.01em;margin:0}
.find{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px}
input{font:inherit;color:var(--fg);background:var(--raise);border:1px solid var(--line);border-radius:12px;padding:11px 16px;flex:1 1 220px;max-width:360px;min-width:0}
.grid{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}
.grid li{background:var(--raise);border:1px solid var(--line);border-radius:14px;padding:16px 18px;display:flex;flex-direction:column;gap:10px;min-width:0}
.word{align-self:flex-start;font:700 13px/1 var(--mono);letter-spacing:.06em;background:var(--chip);color:var(--chip-ink);padding:7px 11px;border-radius:8px}
.grid p{margin:0;font-size:15px}
.more{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;list-style:none;margin:14px 0 0;padding:0}
.more a{display:block;background:var(--raise);border:1px solid var(--line);border-radius:12px;padding:14px 18px;color:var(--fg);text-decoration:none;font-weight:700}
.more a:hover,.grid li:hover{border-color:var(--accent)}
footer{color:var(--muted);font:500 13px/1.6 var(--body);text-align:center}
footer a{color:var(--accent);font-weight:700}
"""


def tools_page(cfg, posts):
    """site/index.html: the public page for the Instagram bio. It lists every word and what it unlocks, never the
    link itself: following and commenting (or DMing) the word is still the only way to get that."""
    e, handle = html.escape, cfg["handle"]
    seen, cards = set(), ""
    for p in sorted(posts, key=lambda p: p["date"] if p["status"] != "legacy" else "", reverse=True):
        if p["status"] not in ("live", "legacy") or not p.get("title"):
            continue
        twin = next((w for w, link in seen if link == p.get("link", p["repo"])), None)  # two words, one freebie
        seen.add((p["keyword"], p.get("link", p["repo"])))
        if not twin:
            words = [p["keyword"]] + [q["keyword"] for q in posts if q is not p and q.get("link", q["repo"]) == p.get("link", p["repo"])
                                      and q["status"] in ("live", "legacy")]
            cards += (f'<li data-find="{e((" ".join(words) + " " + p["title"]).lower())}"><span class="word">{e(" / ".join(words))}</span>'
                      f'<p>{e(p["title"])}</p></li>')
    services = "".join(f'<li><a href="{e(s["url"])}">{e(s["label"])}</a></li>' for s in cfg.get("services", []))
    services += "".join(f'<li><a href="{e(a.get("site") or a["url"])}">{e(app_name(a).split("/")[-1])}</a></li>'
                        for a in my_apps() if (a.get("site") or a["url"]) not in {s["url"] for s in cfg.get("services", [])})
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Free AI tools from @{e(handle)}</title>{FAVICON}
<meta name="description" content="Every free AI tool, guide and repo shared by @{e(handle)} on Instagram. Follow, comment the word, get the link in your DMs.">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap">
<style>{TOOLS_CSS}</style>
<script>try{{const t=localStorage.getItem('theme');if(t)document.documentElement.dataset.theme=t}}catch(e){{}}</script></head><body><main>
<div class="top"><span class="brand">{LOGO}<span>Many<b>Reply</b></span></span>
<button type="button" id="theme" aria-label="Switch light or dark mode">Theme: Auto</button></div>
<header><h1>Every free AI tool I've shared</h1>
<p>Each one has a word. Send me the word on Instagram and the link lands in your DMs.</p>
<a class="btn" href="https://www.instagram.com/{e(handle)}/"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="5"/><circle cx="12" cy="12" r="3.5"/></svg>Open @{e(handle)} on Instagram</a>
<a class="btn ghost" href="/dashboard"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>Open the dashboard</a></header>
<ol><li><b>Follow @{e(handle)}</b><span>The links only go to followers.</span></li>
<li><b>Send the word</b><span>Comment it on any post, or DM it to me.</span></li>
<li><b>Check your DMs</b><span>The link arrives in seconds.</span></li></ol>
<section class="card"><div class="find"><h2>{cards.count("<li")} tools and guides</h2>
<input id="find" type="search" placeholder="Search: claude, video, voice..." aria-label="Search the tools"></div>
<ul class="grid" id="grid">{cards}</ul></section>
<section class="card"><h2>Built by Zero Touch AI</h2><ul class="more">{services}</ul></section>
<footer>Updated {now():%d %B %Y}. New tool every day on Instagram.<br>{CREDIT}</footer></main>
<script>
(() => {{  // light / dark switch, shared with the dashboard: Auto follows the device
  const btn = document.getElementById("theme"), root = document.documentElement;
  const show = () => btn.textContent = "Theme: " + ({{light: "Light", dark: "Dark"}}[root.dataset.theme] || "Auto");
  btn.onclick = () => {{
    const dark = matchMedia("(prefers-color-scheme: dark)").matches;  // Auto, the opposite of the device, the device, Auto
    const order = dark ? ["", "light", "dark"] : ["", "dark", "light"], next = order[(order.indexOf(root.dataset.theme || "") + 1) % 3];
    if (next) root.dataset.theme = next; else delete root.dataset.theme;
    try {{ next ? localStorage.setItem("theme", next) : localStorage.removeItem("theme"); }} catch (e) {{}}
    show();
  }};
  show();
}})();
const box = document.getElementById("find"), items = [...document.querySelectorAll("#grid li")];
box.addEventListener("input", () => {{
  const q = box.value.trim().toLowerCase();
  for (const li of items) li.hidden = q && !li.dataset.find.includes(q);
}});
</script></body></html>
"""
    (ROOT / "site").mkdir(exist_ok=True)
    (ROOT / "site" / "index.html").write_text(page, encoding="utf-8")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles choke on emoji otherwise
    cmd, args = (sys.argv[1] if len(sys.argv) > 1 else ""), sys.argv[2:]
    if cmd == "publish" and len(args) == 2 and args[1] == "--now":
        publish(Path(args[0]), right_away=True)
    elif cmd in ("render", "publish") and len(args) == 1:
        {"render": render, "publish": publish}[cmd](Path(args[0]))
    elif cmd == "email" and len(args) == 1:
        email(Path(args[0]).resolve())
    elif cmd == "legacy" and len(args) == 2:
        legacy(*args)
    elif cmd == "style-previews" and not args:
        style_previews()
    elif cmd == "review-email" and len(args) == 2 and args[0] in ("weekly", "monthly"):
        review_email(*args)
    elif cmd == "reviewed" and args in (["weekly"], ["monthly"]):
        reviewed(args[0])
    elif cmd in ("funnel", "icebreakers") and args in ([], ["facebook"]):
        (funnel if cmd == "funnel" else ice_breakers)(*args)
    elif cmd in ("setup", "write", "daily"):
        import writer
        sys.exit({"setup": writer.setup, "write": writer.write_cmd, "daily": writer.daily}[cmd](args))
    elif cmd in ("due", "discover", "sync", "dashboard", "refresh-dms", "telegram", "review", "topics", "doctor", "services") and not args:
        sys.exit({"due": due, "discover": discover, "sync": sync, "dashboard": dashboard, "topics": pull_topics,
                  "refresh-dms": refresh_dms, "telegram": telegram, "review": review, "doctor": doctor, "services": services_button}[cmd]())
    else:
        sys.exit(__doc__)
