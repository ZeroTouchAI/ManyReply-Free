/* ManyReply DM analytics: fetches from Zernio and turns the answers into the numbers the dashboard shows.
 * No page in here, so it runs in the browser (window.MRA) and in Node (the tests).
 * Endpoints (Zernio docs): GET /analytics, /analytics/instagram/follower-history, /analytics/instagram/account-insights. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.MRA = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const DAY = 86400000;
  const PERIODS = [[1, '24 hours'], [7, '7 days'], [14, '14 days'], [30, '30 days'], [60, '60 days'], [90, '90 days'], [365, '1 year']];
  const TYPE_LABEL = { carousel: 'Carousels', reel: 'Reels', photo: 'Photos', other: 'Everything else' };

  const num = (v) => { const n = Number(v); return Number.isFinite(n) ? n : 0; };
  const iso = (d) => new Date(d).toISOString().slice(0, 10);
  const q = (o) => Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== '').map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&');
  const fmt = (n) => (n == null || !Number.isFinite(n) ? '–' : Math.abs(n) >= 100000 ? Math.round(n / 1000) + 'K' : Math.round(n).toLocaleString('en-US'));

  // ---------------------------------------------------------------- reading what Zernio returns

  /** Zernio's list items are only partly documented, so every field is read with a fallback. */
  function classify(raw) {
    const prod = String(raw.mediaProductType || '').toLowerCase();
    const mt = String(raw.mediaType || '').toLowerCase();
    const items = Array.isArray(raw.mediaItems) ? raw.mediaItems.length : 0;
    if (/reel/.test(prod)) return 'reel';
    if (/story/.test(prod)) return 'other';
    if (/carousel/.test(prod) || mt === 'carousel' || items > 1) return 'carousel';
    if (mt === 'image' || /feed/.test(prod) && mt !== 'video') return 'photo';
    return 'other';
  }

  /** One post, in one shape. Returns null for anything that is not a published post with a date. */
  function normalizePost(raw) {
    if (!raw || typeof raw !== 'object') return null;
    const status = String(raw.status || 'published').toLowerCase();
    if (status !== 'published' && status !== 'partial') return null;
    const pa = (Array.isArray(raw.platformAnalytics) && raw.platformAnalytics[0]) || {};
    const an = raw.analytics || pa.analytics || {};
    const date = raw.publishedAt || raw.scheduledFor || raw.createdAt || raw.createdTime || '';
    const t = Date.parse(date);
    if (!Number.isFinite(t)) return null;
    const media = Array.isArray(raw.mediaItems) && raw.mediaItems[0] ? raw.mediaItems[0] : {};
    return {
      id: String(raw.postId || raw._id || raw.id || pa.platformPostId || t),
      platformPostId: pa.platformPostId || raw.platformPostId || null,
      url: pa.platformPostUrl || raw.platformPostUrl || raw.permalink || '',
      t, date: new Date(t).toISOString(),
      text: String(raw.content || raw.caption || raw.message || '').trim(),
      thumb: raw.thumbnailUrl || media.thumbnail || media.url || '',
      type: classify(raw),
      reach: num(an.reach), views: num(an.views || an.totalViews || an.impressions), likes: num(an.likes), comments: num(an.comments),
      saves: num(an.saves), shares: num(an.shares), follows: num(an.follows), clicks: num(an.clicks),
      engagement: an.engagementRate == null ? null : num(an.engagementRate),
    };
  }

  // ---------------------------------------------------------------- fetching

  /** Whether an error means "this plan does not include analytics" (402, or 403 with requiresAddon). */
  function needsAnalyticsAccess(err) { return !!err && (err.status === 402 || err.status === 403); }

  async function fetchPosts(call, accountId, now) {
    const seen = new Set(); const out = [];
    for (let page = 1; page <= 12; page++) {
      const d = await call('GET', '/analytics?' + q({ accountId, platform: 'instagram', fromDate: iso(now - 365 * DAY), toDate: iso(now), limit: 50, page }));
      const list = Array.isArray(d && d.posts) ? d.posts : [];
      let fresh = 0;
      for (const raw of list) { const p = normalizePost(raw); if (p && !seen.has(p.id)) { seen.add(p.id); out.push(p); fresh++; } }
      if (list.length < 50 || !fresh) break;
    }
    return out.sort((a, b) => b.t - a.t);
  }

  async function fetchFollowers(call, accountId, now) {
    const d = await call('GET', '/analytics/instagram/follower-history?' + q({ accountId, metrics: 'follower_count', metricType: 'time_series', fromDate: iso(now - 88 * DAY), toDate: iso(now) }));
    const vals = (d && d.metrics && d.metrics.follower_count && d.metrics.follower_count.values) || [];
    return vals.map((v) => ({ date: String(v.date).slice(0, 10), value: num(v.value) })).filter((v) => v.date).sort((a, b) => a.date.localeCompare(b.date));
  }

  async function fetchReach(call, accountId, now) {
    const get = async (from, to) => {
      const d = await call('GET', '/analytics/instagram/account-insights?' + q({ accountId, metrics: 'reach', metricType: 'total_value', fromDate: iso(from), toDate: iso(to) }));
      const m = d && d.metrics && d.metrics.reach;
      return m && Number.isFinite(Number(m.total)) ? Number(m.total) : null;
    };
    const [cur, prev] = await Promise.all([get(now - 6 * DAY, now), get(now - 13 * DAY, now - 7 * DAY)]);
    return { cur, prev };
  }

  /** Everything the dashboard needs. Each part can fail on its own, so one problem never blanks the page. */
  async function load(call, account, now) {
    now = now || Date.now();
    const settle = (p) => p.then((value) => ({ value }), (error) => ({ error }));
    const [posts, followers, reach] = await Promise.all([
      settle(fetchPosts(call, account._id, now)), settle(fetchFollowers(call, account._id, now)), settle(fetchReach(call, account._id, now))]);
    return { at: now, posts: posts.value || [], postsError: posts.error || null, followers: followers.value || [], followersError: followers.error || null,
             reach: reach.value || null, reachError: reach.error || null };
  }

  // ---------------------------------------------------------------- the numbers

  function totals(posts) {
    const t = { posts: posts.length, reach: 0, views: 0, likes: 0, comments: 0, saves: 0, shares: 0, follows: 0, reelViews: 0 };
    for (const p of posts) {
      t.reach += p.reach; t.views += p.views; t.likes += p.likes; t.comments += p.comments; t.saves += p.saves; t.shares += p.shares; t.follows += p.follows;
      if (p.type === 'reel') t.reelViews += p.views;
    }
    return t;
  }
  const between = (posts, from, to) => posts.filter((p) => p.t > from && p.t <= to);

  /** This period's totals against the period before it (no "before" for the year: Zernio only goes back 366 days). */
  function period(posts, days, now) {
    const cur = totals(between(posts, now - days * DAY, now));
    const prev = days * 2 <= 365 ? totals(between(posts, now - 2 * days * DAY, now - days * DAY)) : null;
    return { cur, prev };
  }

  /** { dir: 'up' | 'down' | 'flat' | 'none', text } for a number against the one before it. */
  function delta(cur, prev) {
    if (prev == null) return { dir: 'none', text: '' };
    if (cur === prev) return { dir: 'flat', text: '= ' + fmt(cur) };
    if (prev === 0) return { dir: 'up', text: 'new' };
    const pct = Math.round(((cur - prev) / prev) * 100);
    if (pct === 0) return { dir: 'flat', text: '= ' + fmt(cur) };
    return { dir: pct > 0 ? 'up' : 'down', text: (pct > 0 ? '+' : '−') + Math.abs(pct) + '%' };
  }

  /** The follower count now, and its change over the last `days` (or since the first day we have, flagged as partial). */
  function followersChange(series, days, now) {
    if (!series || series.length < 2) return null;
    const last = series[series.length - 1];
    const target = iso(now - days * DAY);
    const base = series.find((s) => s.date >= target) || series[0];
    const partial = series[0].date > target;
    const from = base === last ? series[series.length - 2] : base;
    return { value: last.value, change: last.value - from.value, since: from.date, partial };
  }

  function topPosts(posts, now, days, n) {
    const win = between(posts, now - days * DAY, now);
    if (!win.length) return [];
    const avg = win.reduce((s, p) => s + p.reach, 0) / win.length;
    return win.slice().sort((a, b) => b.reach - a.reach).slice(0, n || 10).map((p) => ({ post: p, x: avg > 0 ? p.reach / avg : 0 }));
  }

  const group = (type) => (type === 'carousel' || type === 'reel' || type === 'photo' ? type : 'other');

  /** Posts at least 3 days old, so their numbers have settled. */
  function perfByType(posts, now) {
    const old = posts.filter((p) => p.t <= now - 3 * DAY);
    return ['carousel', 'reel', 'photo', 'other'].map((g) => {
      const ps = old.filter((p) => group(p.type) === g);
      const t = totals(ps);
      return { type: g, label: TYPE_LABEL[g], posts: ps.length, avgReach: ps.length ? t.reach / ps.length : 0, avgViews: ps.length ? t.views / ps.length : 0,
               saves: t.saves, shares: t.shares, follows: t.follows };
    });
  }

  function growth(series, posts) {
    const byDay = {};
    for (const p of posts) { const d = iso(p.t); (byDay[d] = byDay[d] || []).push(p); }
    const days = series.map((s) => ({ date: s.date, value: s.value, posts: byDay[s.date] || [] }));
    const first = series[0], last = series[series.length - 1];
    return { days, change: series.length > 1 ? last.value - first.value : null, from: first && first.date, to: last && last.date };
  }

  // ---------------------------------------------------------------- joining the words

  /** Automations by the post they sit on; "any post" words are returned separately. */
  function wordsByPost(autos) {
    const map = new Map(); const any = [];
    for (const a of autos || []) { if (a.platformPostId) { const l = map.get(a.platformPostId) || []; l.push(a); map.set(a.platformPostId, l); } else any.push(a); }
    return { map, any };
  }
  const st = (a) => { const s = (a && a.stats) || {}; return { comments: num(s.triggered), dms: num(s.dmsSent), clicks: num(s.linkClicks), gatePassed: num(s.followGatePassed), gateAsked: s.followGateSent == null ? null : num(s.followGateSent) }; };

  function postWords(post, byPost) {
    const autos = (post.platformPostId && byPost.map.get(post.platformPostId)) || [];
    const s = { comments: 0, dms: 0, clicks: 0, gatePassed: 0, gateAsked: null };
    for (const a of autos) {
      const x = st(a); s.comments += x.comments; s.dms += x.dms; s.clicks += x.clicks; s.gatePassed += x.gatePassed;
      if (x.gateAsked != null) s.gateAsked = (s.gateAsked || 0) + x.gateAsked;
    }
    return { words: autos.flatMap((a) => a.keywords || []), stats: s };
  }

  /** Which comment words are working, best first (by link clicks, then DMs, then comments). */
  function wordsWorking(autos) {
    return (autos || []).map((a) => {
      const s = st(a);
      return { word: (a.keywords || []).join(', ') || '(any comment)', scope: a.platformPostId ? 'One post' : 'Any post', ...s, rate: s.dms > 0 ? s.clicks / s.dms : null };
    }).sort((a, b) => b.clicks - a.clicks || b.dms - a.dms || b.comments - a.comments);
  }

  const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  const BLOCKS = [[5, 11, 'Morning (5–11)'], [11, 15, 'Midday (11–3)'], [15, 18, 'Afternoon (3–6)'], [18, 23, 'Evening (6–11)']];
  const block = (h) => { const b = BLOCKS.find((x) => h >= x[0] && h < x[1]); return b ? b[2] : 'Night (11–5)'; };

  /** Average reach by weekday and by time of day, best first. Uses the viewer's own time zone. */
  function whenWorks(posts, now) {
    const old = posts.filter((p) => p.t <= now - 3 * DAY);
    const rank = (keyOf) => {
      const m = new Map();
      for (const p of old) { const k = keyOf(new Date(p.t)); const e = m.get(k) || { label: k, posts: 0, reach: 0, saves: 0 }; e.posts++; e.reach += p.reach; e.saves += p.saves; m.set(k, e); }
      return [...m.values()].map((e) => ({ label: e.label, posts: e.posts, avgReach: e.reach / e.posts, avgSaves: e.saves / e.posts })).sort((a, b) => b.avgReach - a.avgReach);
    };
    return { day: rank((d) => DAYS[d.getDay()]), time: rank((d) => block(d.getHours())) };
  }


  // ---------------------------------------------------------------- the tiles, the way the original dashboard counts them

  /** The follower count on or before a day. */
  function followersOn(series, day) { let v = null; for (const s of series || []) { if (s.date <= day) v = s.value; else break; } return v; }

  /** Followers gained over the window that ends `back` days ago. {change, partial, since} or null when there is no history. */
  function followerWindow(series, days, back, now) {
    if (!series || series.length < 2) return null;
    const end = followersOn(series, iso(now - back * DAY));
    let start = followersOn(series, iso(now - (back + days) * DAY));
    let partial = false, since = null;
    if (start == null && back === 0) { start = series[0].value; partial = true; since = series[0].date; }
    return end == null || start == null ? null : { change: end - start, partial, since };
  }

  /** One window of numbers. Word numbers come from the words on the posts published in the window, as in the original. */
  function windowStats(posts, byPost, series, days, back, now) {
    const ps = between(posts, now - (back + days) * DAY, now - back * DAY);
    const t = totals(ps); let words = 0, dms = 0, clicks = 0, gate = 0;
    for (const p of ps) { const s = postWords(p, byPost).stats; words += s.comments; dms += s.dms; clicks += s.clicks; gate += s.gatePassed; }
    const f = followerWindow(series, days, back, now);
    return { followers: f ? f.change : null, since: f && f.partial ? f.since : null, posts: ps.length, reach: t.reach, shares: t.shares, saves: t.saves, follows: t.follows,
             words, dms, clicks, gate, views: t.views, likes: t.likes, comments: t.comments, reelViews: t.reelViews };
  }
  function tileWindows(posts, byPost, series, days, now) {
    return { cur: windowStats(posts, byPost, series, days, 0, now), prev: days * 2 <= 365 ? windowStats(posts, byPost, series, days, days, now) : null };
  }

  const TYPE_NAME = { carousel: 'Carousel', reel: 'Reel', photo: 'Photo', other: 'Post' };

  /** The "What's working" table: posts grouped by type, weekday, time of day and comment word, best average reach first. */
  function whatsWorking(posts, byPost, now) {
    const map = new Map();
    const add = (group, value, p, words) => {
      const k = group + '\u0000' + value; const e = map.get(k) || { group, value, posts: 0, reach: 0, words: 0, follows: 0 };
      e.posts++; e.reach += p.reach; e.words += words; e.follows += p.follows; map.set(k, e);
    };
    for (const p of posts.filter((x) => x.t <= now - 3 * DAY)) {
      const pw = postWords(p, byPost), d = new Date(p.t);
      add('type', TYPE_NAME[group(p.type)], p, pw.stats.comments); add('day', DAYS[d.getDay()], p, pw.stats.comments); add('time', block(d.getHours()), p, pw.stats.comments);
      for (const w of pw.words) add('word', w, p, pw.stats.comments);
    }
    return [...map.values()].map((e) => ({ group: e.group, value: e.value, posts: e.posts, avgReach: e.reach / e.posts, avgWords: e.words / e.posts, follows: e.follows }))
      .sort((a, b) => b.avgReach - a.avgReach || b.posts - a.posts);
  }

  /** Words on posts older than `days` (or no longer in the analytics list), best first: clicks, then DMs, then comments. */
  function olderWords(autos, posts, now, days) {
    const recent = new Set(posts.filter((p) => p.t > now - (days || 30) * DAY && p.platformPostId).map((p) => p.platformPostId));
    return (autos || []).filter((a) => a.platformPostId && !recent.has(a.platformPostId)).map((a) => {
      const s = st(a); const b = (a.buttons || []).find((x) => x && x.url);
      return { word: (a.keywords || []).join(', ') || '(any comment)', link: b ? b.url : '', ...s, active: a.isActive !== false };
    }).sort((a, b) => b.clicks - a.clicks || b.dms - a.dms || b.comments - a.comments);
  }

  // ---------------------------------------------------------------- extra views, all worked out from the same posts and words (no extra services)

  const settled = (posts, now) => posts.filter((p) => p.t <= now - 3 * DAY);
  const avg = (ps, f) => (ps.length ? ps.reduce((s, p) => s + f(p), 0) / ps.length : 0);

  /** Average reach for each weekday and time-of-day block, for a heat grid. */
  function timeGrid(posts, now) {
    const ps = settled(posts, now), order = [1, 2, 3, 4, 5, 6, 0];
    const cells = new Map();
    for (const p of ps) { const d = new Date(p.t); const k = d.getDay() + '|' + block(d.getHours()); const e = cells.get(k) || []; e.push(p); cells.set(k, e); }
    const rows = order.map((dow) => ({ day: DAYS[dow], cells: [...BLOCKS.map((b) => b[2]), 'Night (11–5)'].map((b) => { const e = cells.get(dow + '|' + b) || []; return { block: b, posts: e.length, avgReach: avg(e, (p) => p.reach) }; }) }));
    const all = rows.flatMap((r) => r.cells).filter((c) => c.posts);
    return { rows, max: all.reduce((m, c) => Math.max(m, c.avgReach), 0), best: all.slice().sort((a, b) => b.avgReach - a.avgReach)[0] || null, posts: ps.length };
  }

  /** Short, medium and long captions against average reach, saves and sends. */
  function captionLength(posts, now) {
    const ps = settled(posts, now);
    return [['Short (under 80 characters)', 0, 80], ['Medium (80 to 250)', 80, 250], ['Long (250 or more)', 250, Infinity]].map(([label, lo, hi]) => {
      const e = ps.filter((p) => p.text.length >= lo && p.text.length < hi);
      return { label, posts: e.length, avgReach: avg(e, (p) => p.reach), avgSaves: avg(e, (p) => p.saves), avgShares: avg(e, (p) => p.shares) };
    });
  }

  /** Hashtags used on at least two posts, best average reach first. */
  function hashtags(posts, now, n) {
    const ps = settled(posts, now), m = new Map();
    for (const p of ps) for (const t of new Set((p.text.match(/#[\p{L}\p{N}_]+/gu) || []).map((x) => x.toLowerCase()))) { const e = m.get(t) || []; e.push(p); m.set(t, e); }
    const base = avg(ps, (p) => p.reach);
    return [...m.entries()].filter(([, e]) => e.length >= 2).map(([tag, e]) => ({ tag, posts: e.length, avgReach: avg(e, (p) => p.reach), x: base > 0 ? avg(e, (p) => p.reach) / base : 0 }))
      .sort((a, b) => b.avgReach - a.avgReach).slice(0, n || 10);
  }

  /** Weeks grouped by how many posts went out, against the reach those weeks brought in. */
  function rhythm(posts, now, weeks) {
    const W = 7 * DAY, n = weeks || 12, byWeek = [];
    for (let i = 0; i < n; i++) { const ps = posts.filter((p) => p.t > now - (i + 1) * W && p.t <= now - i * W); byWeek.push({ posts: ps.length, reach: ps.reduce((s, p) => s + p.reach, 0) }); }
    const buckets = [['No posts', 0, 0], ['1 post', 1, 1], ['2 to 3 posts', 2, 3], ['4 or more', 4, Infinity]].map(([label, lo, hi]) => {
      const e = byWeek.filter((w) => w.posts >= lo && w.posts <= hi);
      return { label, weeks: e.length, avgReach: e.length ? e.reduce((s, w) => s + w.reach, 0) / e.length : 0 };
    });
    return { buckets, weeks: n, perWeek: byWeek.reduce((s, w) => s + w.posts, 0) / n };
  }

  /** The posts that reached the fewest people, last `days` days, settled posts only. */
  function worstPosts(posts, now, days, n) {
    const ps = settled(posts, now).filter((p) => p.t > now - (days || 60) * DAY);
    if (ps.length < 4) return [];
    const a = avg(ps, (p) => p.reach);
    return ps.slice().sort((x, y) => x.reach - y.reach).slice(0, n || 5).map((p) => ({ post: p, x: a > 0 ? p.reach / a : 0 }));
  }

  /** Each word as a funnel: comments, then DMs sent, then link clicks, with the share that makes it to each step. */
  function wordFunnel(autos) {
    return wordsWorking(autos).filter((w) => w.comments || w.dms || w.clicks).map((w) => ({ ...w, dmRate: w.comments > 0 ? w.dms / w.comments : null, clickRate: w.dms > 0 ? w.clicks / w.dms : null }))
      .sort((a, b) => b.dms - a.dms || b.comments - a.comments);
  }

  /** Link clicks added up per link, across every word that sends it. */
  function linkClicks(autos) {
    const m = new Map();
    for (const a of autos || []) {
      const b = (a.buttons || []).find((x) => x && x.url); if (!b) continue;
      const s = st(a), e = m.get(b.url) || { url: b.url, words: 0, dms: 0, clicks: 0 }; e.words++; e.dms += s.dms; e.clicks += s.clicks; m.set(b.url, e);
    }
    return [...m.values()].map((e) => ({ ...e, rate: e.dms > 0 ? e.clicks / e.dms : null })).sort((a, b) => b.clicks - a.clicks || b.dms - a.dms);
  }

  /** Live words whose post is at least a week old and that nobody has commented. */
  function unusedWords(autos, posts, now) {
    const old = new Set(posts.filter((p) => p.t <= now - 7 * DAY && p.platformPostId).map((p) => p.platformPostId));
    return (autos || []).filter((a) => a.isActive !== false && a.platformPostId && old.has(a.platformPostId) && st(a).comments === 0)
      .map((a) => ({ word: (a.keywords || []).join(', ') || '(any comment)', id: a._id || a.id }));
  }

  /** How a follower goal is going: the pace so far over the last 30 days against the pace the goal needs. */
  function goalProgress(series, goal, now) {
    if (!goal || !(goal.target > 0) || !series || !series.length) return null;
    const cur = series[series.length - 1].value, due = Date.parse(goal.by + 'T23:59:59');
    const wk = followerWindow(series, 30, 0, now), span = wk ? (wk.partial ? Math.max(1, (now - Date.parse(wk.since + 'T12:00:00')) / DAY) : 30) : 0, pace = wk ? wk.change / span * 7 : null;
    const weeksLeft = Number.isFinite(due) ? Math.max(0, (due - now) / (7 * DAY)) : null;
    const need = weeksLeft > 0 ? Math.max(0, goal.target - cur) / weeksLeft : null;
    const pct = Math.max(0, Math.min(100, cur / goal.target * 100));
    return { cur, target: goal.target, pct,
             pace, need, weeksLeft, done: cur >= goal.target, onTrack: pace != null && need != null ? pace >= need : null };
  }

  return { DAY, PERIODS, TYPE_LABEL, num, iso, fmt, classify, normalizePost, needsAnalyticsAccess, fetchPosts, fetchFollowers, fetchReach, load,
           totals, period, delta, followersChange, topPosts, perfByType, growth, wordsByPost, postWords, wordsWorking, whenWorks,
           followersOn, followerWindow, windowStats, tileWindows, whatsWorking, olderWords, TYPE_NAME,
           timeGrid, captionLength, hashtags, rhythm, worstPosts, wordFunnel, linkClicks, unusedWords, goalProgress };
});
