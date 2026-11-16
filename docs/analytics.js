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

  return { DAY, PERIODS, TYPE_LABEL, num, iso, fmt, classify, normalizePost, needsAnalyticsAccess, fetchPosts, fetchFollowers, fetchReach, load,
           totals, period, delta, followersChange, topPosts, perfByType, growth, wordsByPost, postWords, wordsWorking, whenWorks };
});
