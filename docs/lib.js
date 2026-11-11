/* ManyReply DM: the logic, with no page in it. It runs in the browser (window.MR) and in Node (the tests).
 * Everything here follows Zernio's comment-to-DM documentation: https://docs.zernio.com/comment-automations/create-comment-automation */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.MR = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const API_BASE = 'https://zernio.com/api/v1';
  // Zernio's documented limits (a DM with buttons is capped at 640 characters)
  const LIMITS = { dm: 640, button: 20, gate: 640, gateButton: 20, notFollowing: 1000, variations: 5, delay: 86400,
                   wordMin: 2, wordMax: 24 };
  const DELAYS = [[0, 'Right away'], [30, 'After 30 seconds'], [60, 'After 1 minute'], [300, 'After 5 minutes']];

  // ---------------------------------------------------------------- talking to Zernio

  class ZernioError extends Error {
    constructor(message, status, code, detail) {
      super(message);
      this.name = 'ZernioError';
      this.status = status;
      this.code = code;
      this.detail = detail;
    }
  }

  function explain(status, code, detail) {
    let say;
    if (code === 'TOKEN_EXPIRED') say = 'Instagram needs to be reconnected in Zernio.';
    else if (status === 401) say = 'Zernio did not accept this API key. Copy it again from API keys in Zernio.';
    else if (status === 403) say = 'Zernio says this key is not allowed to do that.';
    else if (status === 404) say = 'Zernio could not find that. It may have been deleted.';
    else if (status === 409) say = 'That post already has a word. A post can have only one active word: edit or delete the existing one, or choose “Any post”.';
    else if (status === 429) say = 'Zernio is limiting requests. Wait a minute and try again.';
    else if (status >= 500) say = 'Zernio is temporarily unavailable. Try again in a moment.';
    else say = 'Zernio did not accept this.';
    return detail && !say.includes(detail) ? `${say} Zernio said: “${detail}”` : say;
  }

  /** A client for one API key. `fetchImpl` is for tests. The key travels only in the Authorization header. */
  function createClient(key, fetchImpl) {
    const doFetch = fetchImpl || (typeof fetch === 'function' ? fetch.bind(globalThis) : null);
    async function call(method, path, body) {
      let res;
      try {
        res = await doFetch(API_BASE + path, {
          method, credentials: 'omit', referrerPolicy: 'no-referrer',
          headers: { Authorization: 'Bearer ' + key, Accept: 'application/json', ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
          body: body !== undefined ? JSON.stringify(body) : undefined,
        });
      } catch (e) {
        throw new ZernioError('Could not reach Zernio. Check your connection, and whether an extension is blocking zernio.com.', 0, 'network', '');
      }
      const text = await res.text();
      let data = null;
      try { data = text ? JSON.parse(text) : null; } catch (e) { /* not JSON */ }
      if (!res.ok) {
        const detail = String((data && (data.error || data.message || (typeof data.detail === 'string' && data.detail))) || '').slice(0, 300);
        const code = (data && (data.code || data.errorCode)) || '';
        throw new ZernioError(explain(res.status, code, detail), res.status, code, detail);
      }
      return data;
    }
    const id = (v) => encodeURIComponent(v);
    return {
      call,
      async accounts() { return ((await call('GET', '/accounts')).accounts || []).filter((a) => a.platform === 'instagram'); },
      async posts(accountId) { return (await call('GET', `/accounts/${id(accountId)}/posts`)).posts || []; },
      async automations(profileId) {
        return (await call('GET', '/comment-automations' + (profileId ? `?profileId=${id(profileId)}` : ''))).automations || [];
      },
      async create(body) { return (await call('POST', '/comment-automations', body)).automation; },
      async update(autoId, body) { const d = await call('PATCH', `/comment-automations/${id(autoId)}`, body); return (d && d.automation) || d; },
      async remove(autoId) { await call('DELETE', `/comment-automations/${id(autoId)}`); },
    };
  }

  // ---------------------------------------------------------------- posts

  /** The code in an Instagram post, reel or tv link. Codes are case-sensitive. */
  function shortcodeFromUrl(url) {
    const m = String(url || '').trim().match(/instagram\.com\/(?:[A-Za-z0-9_.]+\/)?(?:p|reels?|tv)\/([A-Za-z0-9_-]+)/i);
    return m ? m[1] : null;
  }
  /** Zernio names a post by an internal id, not its address, so a pasted link is matched against the posts it lists. */
  function findPostByUrl(posts, url) {
    const code = shortcodeFromUrl(url);
    return code ? (posts || []).find((p) => shortcodeFromUrl(p.permalink) === code) || null : null;
  }

  // ---------------------------------------------------------------- the word

  function normalizeWords(input) {
    const seen = new Set();
    return String(input || '').split(/[,\n]/).map((s) => s.trim().replace(/^["'“”‘’]+|["'“”‘’]+$/g, '').toUpperCase())
      .filter((s) => s && !seen.has(s) && seen.add(s));
  }
  function checkWord(w) {
    if (!/^[\p{L}\p{N}]+$/u.test(w)) return `“${w}” has spaces or symbols. Use one word, letters and numbers only.`;
    if (w.length < LIMITS.wordMin || w.length > LIMITS.wordMax) return `“${w}” should be ${LIMITS.wordMin} to ${LIMITS.wordMax} characters.`;
    return '';
  }

  // ---------------------------------------------------------------- the form

  function defaults(account) {
    const handle = (account && account.username) || 'yourhandle';
    const ask = `Tap “Follow me” to open my profile and follow @${handle}, then come back here and tap “I'm following ✅” and I'll send it right over 👇`;
    return {
      scope: 'post', platformPostId: '', postTitle: '', words: '', match: '', alsoDms: true,
      dmMessage: 'Here you go {{first_name}} 😊 Tap the button to open it.',
      linkUrl: '', linkLabel: 'Open the link', link2Url: '', link2Label: '', delay: 0,
      gate: true,
      gateMessage: `Almost there! This link is for followers only.\n\n${ask}`,
      gateButton: "I'm following ✅", gateProfileButton: 'Follow me 👉',
      notFollowingMessage: `This link is for followers only 🙌\n\n${ask}`,
      reply: true, replyText: '@{{username}} Sent to your DMs 📩',
      replyVariations: "@{{username}} Check your DMs 🚀\n@{{username}} It's in your DMs ✅",
    };
  }

  /** Whole-comment matching for "any post" (an everyday word would otherwise fire constantly); word-in-a-sentence on one post. */
  function matchModeFor(form) { return form.match || (form.scope === 'any' ? 'exact' : 'word'); }

  function isHttps(u) { try { return new URL(u).protocol === 'https:'; } catch (e) { return false; } }
  function lines(text) { return String(text || '').split('\n').map((s) => s.trim()).filter(Boolean); }
  function clip(s, n) { s = String(s || '').replace(/\s+/g, ' ').trim(); return s.length > n ? s.slice(0, n - 1) + '…' : s; }

  /** Checks the form, and builds the request Zernio expects. Returns { errors: {field: message}, body }. */
  function buildAutomation(f, account) {
    const errors = {};
    const words = normalizeWords(f.words);
    if (!account) errors.account = 'Connect an Instagram account first.';
    if (f.scope === 'post' && !f.platformPostId) errors.post = 'Choose a post, or switch to “Any post”.';
    if (!words.length) errors.words = 'Type the word people will comment.';
    for (const w of words) { const bad = checkWord(w); if (bad) { errors.words = bad; break; } }

    const msg = String(f.dmMessage || '').trim();
    if (!msg) errors.dmMessage = 'Write the message people receive.';
    else if (msg.length > LIMITS.dm) errors.dmMessage = `Messages with a button can be ${LIMITS.dm} characters. This is ${msg.length}.`;

    const buttons = [];
    const label = (s) => String(s || '').trim();
    if (!isHttps(label(f.linkUrl))) errors.linkUrl = 'Paste the link people should get. It must start with https://';
    if (!label(f.linkLabel)) errors.linkLabel = 'Name the button.';
    else if (label(f.linkLabel).length > LIMITS.button) errors.linkLabel = `Button names can be ${LIMITS.button} characters.`;
    if (!errors.linkUrl && !errors.linkLabel) buttons.push({ type: 'url', title: label(f.linkLabel), url: label(f.linkUrl) });
    if (label(f.link2Url) || label(f.link2Label)) {
      if (!isHttps(label(f.link2Url))) errors.link2Url = 'The second button needs a link starting with https://';
      else if (!label(f.link2Label) || label(f.link2Label).length > LIMITS.button) errors.link2Label = `Name the second button, up to ${LIMITS.button} characters.`;
      else buttons.push({ type: 'url', title: label(f.link2Label), url: label(f.link2Url) });
    }

    if (f.gate) {
      if (!label(f.gateMessage) || label(f.gateMessage).length > LIMITS.gate) errors.gateMessage = `Write the follow request, up to ${LIMITS.gate} characters.`;
      if (!label(f.gateButton) || label(f.gateButton).length > LIMITS.gateButton) errors.gateButton = `Button names can be ${LIMITS.gateButton} characters.`;
      if (!label(f.gateProfileButton) || label(f.gateProfileButton).length > LIMITS.gateButton) errors.gateProfileButton = `Button names can be ${LIMITS.gateButton} characters.`;
      if (label(f.notFollowingMessage).length > LIMITS.notFollowing) errors.notFollowingMessage = `Up to ${LIMITS.notFollowing} characters.`;
    }
    let variations = [];
    if (f.reply) {
      if (!label(f.replyText)) errors.replyText = 'Write the public reply, or turn it off.';
      variations = lines(f.replyVariations).filter((v) => v !== label(f.replyText));
      if (variations.length > LIMITS.variations - 1) errors.replyVariations = `Up to ${LIMITS.variations - 1} extra replies, one per line.`;
    }
    const delay = Number(f.delay) || 0;
    if (!Number.isInteger(delay) || delay < 0 || delay > LIMITS.delay) errors.delay = 'Choose a delay from the list.';

    const mode = matchModeFor(f);
    const body = {
      ...(account ? { profileId: account.profileId, accountId: account._id } : {}),
      name: words[0] ? `${words[0]} - ${f.scope === 'post' && f.postTitle ? clip(f.postTitle, 32) : 'any post'}` : '',
      keywords: words, matchMode: mode, ...(mode === 'word' ? { typoTolerance: true } : {}),
      alsoMatchInDms: !!f.alsoDms, dmMessage: msg, buttons, linkTracking: true,
    };
    if (f.scope === 'post') { body.platformPostId = f.platformPostId; if (f.postTitle) body.postTitle = clip(f.postTitle, 80); }
    if (delay > 0) body.dmDelaySeconds = delay;
    if (f.gate) {
      body.audience = { followerStatus: 'follower', whenUnknown: 'verify' };
      body.followGate = { message: label(f.gateMessage), buttonLabel: label(f.gateButton), profileButtonLabel: label(f.gateProfileButton),
                          ...(label(f.notFollowingMessage) ? { notFollowingMessage: label(f.notFollowingMessage) } : {}) };
    } else {
      body.audience = { followerStatus: 'any' };
    }
    if (f.reply) {
      body.commentReply = label(f.replyText);
      if (variations.length) body.commentReplyVariations = variations;
      body.publicReplyPolicy = 'always';
    }
    return { errors, body };
  }

  /** What may change on a word that already exists: not which post it is on. */
  function toPatch(body) {
    const { profileId, accountId, platformPostId, postTitle, ...rest } = body; // eslint-disable-line no-unused-vars
    return rest;
  }

  /** Whether the dashboard made (and so can edit) this automation. Story and template automations are left alone. */
  function isEditable(a) {
    return (!a.trigger || a.trigger === 'comment') && !a.template && !(a.quickReplies && a.quickReplies.length)
      && (a.buttons || []).every((b) => b.type === 'url') && (a.buttons || []).length > 0;
  }

  function fromAutomation(a, account) {
    const base = defaults(account);
    const [b1, b2] = a.buttons || [];
    const gated = !!(a.followGate || (a.audience && a.audience.whenUnknown === 'verify'));
    const g = a.followGate || {};
    const variations = a.commentReplyVariations || [];
    return {
      ...base, scope: a.platformPostId ? 'post' : 'any', platformPostId: a.platformPostId || '', postTitle: a.postTitle || '',
      words: (a.keywords || []).join(', '), match: a.matchMode === 'contains' ? 'word' : a.matchMode || '', alsoDms: !!a.alsoMatchInDms,
      dmMessage: a.dmMessage || '', linkUrl: (b1 && b1.url) || '', linkLabel: (b1 && b1.title) || base.linkLabel,
      link2Url: (b2 && b2.url) || '', link2Label: (b2 && b2.title) || '', delay: a.dmDelaySeconds || 0,
      gate: gated, gateMessage: g.message || base.gateMessage, gateButton: g.buttonLabel || base.gateButton,
      gateProfileButton: g.profileButtonLabel || base.gateProfileButton, notFollowingMessage: g.notFollowingMessage || base.notFollowingMessage,
      reply: !!a.commentReply, replyText: a.commentReply || base.replyText, replyVariations: variations.join('\n'),
    };
  }

  // ---------------------------------------------------------------- what people see

  const SAMPLE = { first_name: 'Alex', name: 'Alex Rivera', username: 'alex.rivera' };
  function personalize(text, who) {
    const v = who || SAMPLE;
    return String(text || '').replace(/\{\{\s*(first_name|name|username)\s*\}\}/g, (_, k) => v[k] || '').replace(/\{\{[^}]*\}\}/g, '');
  }

  function delayLabel(seconds) { const hit = DELAYS.find((d) => d[0] === Number(seconds)); return hit ? hit[1] : `After ${seconds} seconds`; }

  /** The steps a word runs, in order, for the flow strip. */
  function flowSteps(f) {
    const word = normalizeWords(f.words)[0] || 'WORD';
    return [
      { id: 'comment', on: true, title: `Comment ${word}`, note: f.scope === 'post' ? 'On the post you chose' : 'On any of your posts' },
      { id: 'reply', on: !!f.reply, title: 'Public reply', note: f.reply ? 'Under their comment' : 'Off' },
      { id: 'check', on: !!f.gate, title: 'Follow check', note: f.gate ? 'Non-followers are asked to follow first' : 'Off: everyone gets the link' },
      { id: 'dm', on: true, title: 'DM with the link', note: delayLabel(f.delay) },
    ];
  }

  function previewModel(f, account) {
    const word = normalizeWords(f.words)[0] || 'WORD';
    const first = (f.reply && personalize(f.replyText)) || '';
    const btns = [String(f.linkLabel || '').trim() || 'Open the link'];
    if (String(f.link2Label || '').trim() && String(f.link2Url || '').trim()) btns.push(f.link2Label.trim());
    return {
      handle: (account && account.username) || 'yourhandle', word, commenter: SAMPLE.username, reply: first,
      dm: { text: personalize(f.dmMessage), buttons: btns.map((b) => personalize(b)) },
      gate: f.gate ? { text: personalize(f.gateMessage), buttons: [personalize(f.gateProfileButton), personalize(f.gateButton)],
                       retry: personalize(f.notFollowingMessage) } : null,
    };
  }

  // ---------------------------------------------------------------- numbers

  function statsOf(a) {
    const s = a.stats || {};
    return { comments: s.triggered || 0, dms: s.dmsSent || 0, clicks: s.linkClicks || 0, followed: s.followGatePassed || 0 };
  }

  return { API_BASE, LIMITS, DELAYS, ZernioError, createClient, shortcodeFromUrl, findPostByUrl, normalizeWords, checkWord, defaults,
           matchModeFor, buildAutomation, toPatch, isEditable, fromAutomation, personalize, delayLabel, flowSteps, previewModel,
           statsOf, clip };
});
