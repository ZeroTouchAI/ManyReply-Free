# ManyReply Free

A free, open-source "comment a word, get the link" funnel for Instagram, run on your own accounts and your own keys.

Every day it finds a hot GitHub repo, has an AI write and design an Instagram carousel about it, and (when you let it)
posts it with a Story and a Reel. People who comment the post's word, DM it, or reply to the Story with it get the link
by DM if they follow you. If they don't follow yet, they are asked to first. The numbers come back to a dashboard so you
can see what is working.

Nothing here is shared with anyone else: your Instagram, your [Zernio](https://zernio.com) account and your AI account
are the only things involved, and there is no server of ours in the middle.

## What it costs

| Thing | What it does | Cost |
|---|---|---|
| This software | Everything below | Free, MIT licensed |
| An Instagram business or creator account | Where it posts | Free |
| A [Zernio](https://zernio.com) account | Posts to Instagram, runs the comment and DM automations, returns your numbers | Zernio's own pricing. Check their pricing page for what the free plan covers |
| An AI account of your own | Writes the posts | Your provider's pricing. Some have a free tier (for example Gemini), with limits that change; a local Ollama model is free but only runs on your own computer |
| GitHub | Runs the daily job for you | Free for a personal account |

**You bring your own AI key.** Choose Anthropic, OpenAI, Gemini, OpenRouter, a local Ollama model, or any
OpenAI-compatible server. A post is one request of a few thousand words, so a day's post costs very little.

## Set up on GitHub (recommended: no server, no PC switched on)

1. Click **Use this template** at the top of this page, create the copy as **Private** (your ledger and numbers will live
   in it), and open it.
2. Create your Zernio account at [zernio.com](https://zernio.com), connect your Instagram, and create an API key
   (dashboard, API keys).
3. In your copy, open **Settings, Secrets and variables, Actions**.
   - **Secrets:** `ZERNIO_API_KEY`, and the key for your AI provider (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
     `GEMINI_API_KEY` or `OPENROUTER_API_KEY`).
   - **Variables:** `LLM_PROVIDER` (`anthropic`, `openai`, `gemini`, `openrouter`, `ollama` or `openai-compatible`), and
     `LLM_MODEL` if you want a specific model.
4. Edit `data/topics.json`: your Instagram `handle`, your `timezone`, the `topics` you want to post about, and the
   wording of the DM funnel.
5. Open the **Actions** tab, enable workflows, choose **Daily post** and press **Run workflow**.

**The first runs are drafts.** Nothing is posted until you say so. Each run writes the post and draws the slides, then
stops: download the `slides` file from the run's page and look at them. When you are happy, either run the workflow again
with **Post it for real** ticked, or add the variable `MANYREPLY_AUTO_PUBLISH` with the value `true` and every daily run
will post by itself.

If you ever make your copy public, note that GitHub switches off scheduled workflows in public repositories after 60 days
with no activity; the daily run commits its ledger, so a working setup keeps itself alive. A public copy would also
publish your ledger and numbers, which is why a private one is recommended.

## Set up on your own computer

You need Python 3.12+, Chrome or Edge, and ffmpeg (or `pip install --target .tools imageio-ffmpeg`).

```bash
python manyreply.py setup      # asks for your Zernio key, AI provider and key, and handle; checks them
python manyreply.py discover   # find today's candidate repos
python manyreply.py daily      # sync, write and render a draft. Posts nothing
python manyreply.py publish posts/<the folder it names>   # post it, once you have looked at the slides
```

`python manyreply.py doctor` checks everything and says exactly what is missing. `python test_manyreply.py` and
`python test_writer.py` run the tests; they need no keys.

## The DM funnel

```bash
python manyreply.py funnel
```

creates the funnel on Zernio as a **draft**. Look at it there, then activate it. `python manyreply.py funnel facebook`
does the same for a Facebook page, and `python manyreply.py icebreakers` sets the questions people see when they first
open a chat with you. Run them again after you change the wording in `data/topics.json`. The follow-up "did that link
help?" message is off by default (`funnel.checkin.enabled`); turn it on only if you want it.

Automated messages must follow Meta's rules and your local law. You are responsible for what your account sends.

## Choosing the AI

| `LLM_PROVIDER` | Key | Default model |
|---|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-haiku-5-5` |
| `openai` | `OPENAI_API_KEY` | `gpt-4o-mini` |
| `gemini` | `GEMINI_API_KEY` | `gemini-2.5-flash` |
| `openrouter` | `OPENROUTER_API_KEY` | none: set `LLM_MODEL` |
| `ollama` | none | none: set `LLM_MODEL` (and `LLM_BASE_URL` if it is not on this computer) |
| `openai-compatible` | `LLM_API_KEY` | none: set `LLM_MODEL` and `LLM_BASE_URL` |

Model names change over time. If a provider says a model is unknown, set `LLM_MODEL` to a current one from its docs.
Every post is checked by the same rules before it can go out (a unique keyword, the right slide and caption shapes, no
link in the caption). If the AI breaks one it is told what was wrong and tries again, up to three times, and if it still
cannot it stops instead of posting something broken. Text from READMEs is given to the AI as data, never as instructions.

## Referral disclosure

Zernio runs a partner program. If the maker's referral link is set in `affiliate.py`, it is used in this README and in
`python manyreply.py setup` and `doctor`, wherever you are told to create a Zernio account. If you sign up through it,
the maker earns a commission from Zernio; it does not change your price, and you can just as well go to
[zernio.com](https://zernio.com) directly. The link is never put into the posts, captions, DMs or pages that your own
install publishes. If you fork this project you can put your own link in `affiliate.py`, or leave it empty.

## Files

| File | What it is |
|---|---|
| `manyreply.py` | The pipeline. `python manyreply.py` lists the commands |
| `writer.py`, `llm.py` | The AI writer and the provider connections |
| `affiliate.py` | The one place a Zernio referral link lives (see above) |
| `data/topics.json` | Your settings |
| `data/posts.json` | The ledger: every post, repo and word. Nothing is ever posted twice |
| `.github/workflows/daily.yml` | The daily job |
| `site/` | The public list of your words, and an optional password-protected dashboard (Vercel, free tier) |

## The site (optional)

Deploy `site/` as a Vercel project (root directory `site`, preset "Other", no build). Set `DASHBOARD_PASSWORD` (the
dashboard stays locked without it) and `GITHUB_TOKEN` (a fine-grained token for your repository with Contents: read and
write, so the dashboard can save your edits). Put the two addresses in `data/topics.json` as `dashboard_url` and
`tools_url`.

## Reels and music

Reels are made from your slides. Drop any `.mp3` into `music/` and the Reels and Stories use it (only use music you have
the right to use); without any, they are silent.

## License

MIT. No warranty: you are responsible for what your accounts post.
