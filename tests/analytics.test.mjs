// Run: node --test tests/analytics.test.mjs   (no network: Zernio is replaced by a fake)
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const A = createRequire(import.meta.url)('../docs/analytics.js');
const DAY = A.DAY;
const NOW = Date.parse('2026-11-15T12:00:00Z');
const ago = (d, h = 0) => new Date(NOW - d * DAY - h * 3600000).toISOString();
const raw = (over = {}) => ({ postId: 'p' + Math.random(), status: 'published', publishedAt: ago(5), content: 'Hello', mediaType: 'carousel',
  platformAnalytics: [{ platform: 'instagram', platformPostId: 'ig1', platformPostUrl: 'https://www.instagram.com/p/AAA/', analytics: { reach: 100, views: 150, likes: 10, comments: 2, saves: 3, shares: 4, follows: 1 } }], ...over });

test('a post is read from the shapes Zernio documents, and bad ones are skipped', () => {
  const p = A.normalizePost(raw());
  assert.equal(p.type, 'carousel'); assert.equal(p.reach, 100); assert.equal(p.shares, 4); assert.equal(p.follows, 1);
  assert.equal(p.platformPostId, 'ig1'); assert.equal(p.url, 'https://www.instagram.com/p/AAA/');
  assert.equal(A.normalizePost(raw({ status: 'scheduled' })), null);
  assert.equal(A.normalizePost(raw({ publishedAt: 'nope', scheduledFor: undefined, createdAt: undefined })), null);
  assert.equal(A.normalizePost(null), null);
  const top = A.normalizePost({ postId: 'x', publishedAt: ago(1), analytics: { reach: '7', likes: null }, mediaProductType: 'REELS' });
  assert.equal(top.type, 'reel'); assert.equal(top.reach, 7); assert.equal(top.likes, 0);
  assert.equal(A.classify({ mediaType: 'image' }), 'photo'); assert.equal(A.classify({ mediaType: 'video' }), 'other');
  assert.equal(A.classify({ mediaItems: [{}, {}] }), 'carousel'); assert.equal(A.classify({ mediaProductType: 'STORY' }), 'other');
});

test('a period is compared with the one before it, and a year has nothing to compare with', () => {
  const posts = [A.normalizePost(raw({ publishedAt: ago(2) })), A.normalizePost(raw({ publishedAt: ago(9) })), A.normalizePost(raw({ publishedAt: ago(10) })), A.normalizePost(raw({ publishedAt: ago(200) }))];
  const w = A.period(posts, 7, NOW);
  assert.equal(w.cur.posts, 1); assert.equal(w.prev.posts, 2); assert.equal(w.cur.reach, 100);
  assert.equal(A.period(posts, 365, NOW).prev, null);
  assert.equal(A.period(posts, 365, NOW).cur.posts, 4);
  assert.equal(A.period(posts, 1, NOW).cur.posts, 0);
});

test('changes read plainly', () => {
  assert.deepEqual(A.delta(5, 5), { dir: 'flat', text: '= 5' });
  assert.deepEqual(A.delta(150, 100), { dir: 'up', text: '+50%' });
  assert.deepEqual(A.delta(50, 100), { dir: 'down', text: '−50%' });
  assert.deepEqual(A.delta(3, 0), { dir: 'up', text: 'new' });
  assert.equal(A.delta(3, null).dir, 'none');
  assert.equal(A.fmt(1234567), '1235K'); assert.equal(A.fmt(1234), '1,234'); assert.equal(A.fmt(null), '–');
});

test('follower change over a period, and "since" when we do not have that much history', () => {
  const s = [{ date: '2026-11-10', value: 100 }, { date: '2026-11-13', value: 110 }, { date: '2026-11-15', value: 130 }];
  const wk = A.followersChange(s, 7, NOW); assert.equal(wk.change, 30); assert.equal(wk.partial, true); assert.equal(wk.since, '2026-11-10');
  const day = A.followersChange(s, 1, NOW); assert.equal(day.change, 20); assert.equal(day.partial, false);
  assert.equal(A.followersChange([{ date: '2026-11-15', value: 1 }], 7, NOW), null);
  assert.equal(A.followersChange([], 7, NOW), null);
});

test('top posts are ranked by reach against a usual post', () => {
  const mk = (d, reach) => A.normalizePost(raw({ publishedAt: ago(d), platformAnalytics: [{ platformPostId: 'i' + d, analytics: { reach } }] }));
  const t = A.topPosts([mk(1, 300), mk(2, 100), mk(3, 200), mk(90, 9999)], NOW, 60, 2);
  assert.deepEqual(t.map((x) => x.post.reach), [300, 200]); assert.equal(Math.round(t[0].x * 10), 15);
  assert.deepEqual(A.topPosts([], NOW, 60), []);
});

test('performance by type only counts posts at least 3 days old', () => {
  const mk = (d, type, reach) => A.normalizePost(raw({ publishedAt: ago(d), mediaType: type, platformAnalytics: [{ platformPostId: 'i' + d + type, analytics: { reach, views: reach * 2, saves: 1, shares: 2, follows: 3 } }] }));
  const rows = A.perfByType([mk(10, 'carousel', 100), mk(11, 'carousel', 300), mk(1, 'carousel', 9999), mk(12, 'image', 50)], NOW);
  const c = rows.find((r) => r.type === 'carousel');
  assert.equal(c.posts, 2); assert.equal(c.avgReach, 200); assert.equal(c.avgViews, 400); assert.equal(c.saves, 2); assert.equal(c.follows, 6);
  assert.equal(rows.find((r) => r.type === 'photo').posts, 1); assert.equal(rows.find((r) => r.type === 'reel').posts, 0);
});

test('words are joined to their post and ranked by what they earn', () => {
  const autos = [
    { keywords: ['GUIDE'], platformPostId: 'ig1', stats: { triggered: 10, dmsSent: 9, linkClicks: 4, followGatePassed: 2 } },
    { keywords: ['FREE'], stats: { triggered: 5, dmsSent: 5, linkClicks: 5 } },
    { keywords: ['NONE'], platformPostId: 'ig2' }];
  const by = A.wordsByPost(autos);
  const pw = A.postWords({ platformPostId: 'ig1' }, by);
  assert.deepEqual(pw.words, ['GUIDE']); assert.equal(pw.stats.clicks, 4); assert.equal(pw.stats.gateAsked, null);
  assert.deepEqual(A.postWords({ platformPostId: 'zzz' }, by).words, []);
  const w = A.wordsWorking(autos);
  assert.deepEqual(w.map((x) => x.word), ['FREE', 'GUIDE', 'NONE']); assert.equal(w[0].rate, 1); assert.equal(w[2].rate, null);
});

test('growth ties follower days to the posts made on them', () => {
  const p = A.normalizePost(raw({ publishedAt: '2026-11-14T10:00:00Z' }));
  const g = A.growth([{ date: '2026-11-13', value: 5 }, { date: '2026-11-14', value: 8 }], [p]);
  assert.equal(g.change, 3); assert.equal(g.days[1].posts.length, 1); assert.equal(g.days[0].posts.length, 0);
});

test('when works: best weekday and time of day first', () => {
  const mk = (iso, reach) => A.normalizePost(raw({ publishedAt: iso, platformAnalytics: [{ platformPostId: iso, analytics: { reach } }] }));
  const r = A.whenWorks([mk('2026-11-02T12:00:00Z', 100), mk('2026-11-03T12:00:00Z', 500)], NOW);
  assert.equal(r.day.length, 2); assert.ok(r.day[0].avgReach >= r.day[1].avgReach); assert.ok(r.time.length >= 1);
});

test('loading: each part fails on its own, and a missing analytics plan is recognised', async () => {
  const account = { _id: 'acc1' };
  const calls = [];
  const call = async (m, path) => {
    calls.push(path);
    if (path.startsWith('/analytics?')) { const e = new Error('x'); e.status = 402; throw e; }
    if (path.includes('follower-history')) return { metrics: { follower_count: { values: [{ date: '2026-11-14', value: 5 }, { date: '2026-11-13', value: 4 }] } } };
    return { metrics: { reach: { total: 77 } } };
  };
  const d = await A.load(call, account, NOW);
  assert.equal(A.needsAnalyticsAccess(d.postsError), true); assert.deepEqual(d.posts, []);
  assert.deepEqual(d.followers.map((f) => f.value), [4, 5]); assert.equal(d.reach.cur, 77); assert.equal(d.reach.prev, 77);
  assert.ok(calls.every((c) => !c.includes('undefined')));
  assert.ok(calls.some((c) => c.includes('accountId=acc1') && c.includes('platform=instagram')));
});

test('posts are paged until a short page, and a repeated page stops the loop', async () => {
  const page = (n) => Array.from({ length: n }, (_, i) => raw({ postId: 'a' + i }));
  let n = 0;
  const call = async () => { n++; return { posts: n === 1 ? page(50) : page(3) }; };
  assert.equal((await A.fetchPosts(call, 'a', NOW)).length, 50, 'the second page repeats the first 3 ids, so nothing new is added');
  let k = 0;
  const call2 = async () => { k++; return { posts: k === 1 ? page(50) : Array.from({ length: 4 }, (_, i) => raw({ postId: 'b' + i })) }; };
  assert.equal((await A.fetchPosts(call2, 'a', NOW)).length, 54);
});

test('tiles: word numbers follow the posts published in the window, and followers come from the history', () => {
  const mk = (d, id) => A.normalizePost(raw({ publishedAt: ago(d), platformAnalytics: [{ platformPostId: id, analytics: { reach: 10, views: 20, likes: 1, comments: 1, saves: 1, shares: 1, follows: 1 } }] }));
  const posts = [mk(2, 'a'), mk(9, 'b'), mk(40, 'c')];
  const autos = [{ keywords: ['A'], platformPostId: 'a', stats: { triggered: 5, dmsSent: 4, linkClicks: 3, followGatePassed: 2 } }, { keywords: ['B'], platformPostId: 'b', stats: { triggered: 9, dmsSent: 9, linkClicks: 9 } }];
  const series = [{ date: '2026-11-01', value: 100 }, { date: '2026-11-08', value: 110 }, { date: '2026-11-15', value: 125 }];
  const w = A.tileWindows(posts, A.wordsByPost(autos), series, 7, NOW);
  assert.equal(w.cur.posts, 1); assert.equal(w.cur.words, 5); assert.equal(w.cur.dms, 4); assert.equal(w.cur.clicks, 3); assert.equal(w.cur.gate, 2);
  assert.equal(w.prev.words, 9); assert.equal(w.cur.followers, 15); assert.equal(w.prev.followers, 10);
  const yr = A.tileWindows(posts, A.wordsByPost(autos), series, 365, NOW);
  assert.equal(yr.prev, null); assert.equal(yr.cur.followers, 25); assert.equal(yr.cur.since, '2026-11-01');
  assert.equal(A.followerWindow([], 7, 0, NOW), null);
});

test("what's working groups by type, weekday, time and word; older words skip recent posts", () => {
  const mk = (d, id, type, reach) => A.normalizePost(raw({ publishedAt: ago(d), mediaType: type, platformAnalytics: [{ platformPostId: id, analytics: { reach, follows: 1 } }] }));
  const posts = [mk(10, 'a', 'carousel', 100), mk(11, 'b', 'image', 300), mk(1, 'c', 'carousel', 9999)];
  const autos = [{ keywords: ['A'], platformPostId: 'a', stats: { triggered: 4 } }, { keywords: ['C'], platformPostId: 'c', stats: { triggered: 1 } }, { keywords: ['ANY'] }];
  const rows = A.whatsWorking(posts, A.wordsByPost(autos), NOW);
  assert.ok(rows.every((r) => ['type', 'day', 'time', 'word'].includes(r.group)));
  const car = rows.find((r) => r.group === 'type' && r.value === 'Carousel'); assert.equal(car.posts, 1); assert.equal(car.avgWords, 4);
  assert.equal(rows[0].value === 'Photo' || rows[0].avgReach === 300, true);
  assert.deepEqual(A.olderWords(autos, posts, NOW, 5).map((x) => x.word), ['A']);
});

test('extra views: grid, captions, hashtags, rhythm, worst posts, funnel, links, unused words, goal', async () => {
  const now = Date.parse('2026-11-16T12:00:00Z'), D = A.DAY;
  const mk = (i, reach, text) => ({ id: 'p' + i, platformPostId: 'x' + i, t: now - (4 + i * 3) * D, type: 'photo', text, reach, views: reach, likes: 0, comments: 0, saves: 1, shares: 0, follows: 0, clicks: 0 });
  const posts = [mk(0, 100, '#a #b short'), mk(1, 300, '#a ' + 'x'.repeat(120)), mk(2, 50, '#b #a ' + 'y'.repeat(300)), mk(3, 500, 'plain'), mk(4, 10, 'plain two')];
  const g = A.timeGrid(posts, now); assert.equal(g.rows.length, 7); assert.equal(g.posts, 5); assert.ok(g.max >= 500 / 1 || g.max > 0);
  const c = A.captionLength(posts, now); assert.deepEqual(c.map((x) => x.posts), [3, 1, 1]);
  const h = A.hashtags(posts, now); assert.equal(h[0].tag, '#a'); assert.equal(h[0].posts, 3); assert.equal(h.find((x) => x.tag === '#b').posts, 2);
  const r = A.rhythm(posts, now, 12); assert.equal(r.buckets.reduce((s, b) => s + b.weeks, 0), 12); assert.ok(r.perWeek > 0);
  const w = A.worstPosts(posts, now, 60, 2); assert.deepEqual(w.map((x) => x.post.reach), [10, 50]); assert.deepEqual(A.worstPosts(posts.slice(0, 3), now, 60, 2), []);
  const autos = [{ _id: 'a1', keywords: ['GUIDE'], platformPostId: 'x0', isActive: true, buttons: [{ url: 'https://e.com/g' }], stats: { triggered: 10, dmsSent: 8, linkClicks: 4 } },
                 { _id: 'a2', keywords: ['LIST'], platformPostId: 'x1', isActive: true, buttons: [{ url: 'https://e.com/g' }], stats: { triggered: 5, dmsSent: 4, linkClicks: 2 } },
                 { _id: 'a3', keywords: ['NONE'], platformPostId: 'x2', isActive: true, stats: { triggered: 0 } }];
  const f = A.wordFunnel(autos); assert.equal(f.length, 2); assert.equal(f[0].dmRate, 0.8); assert.equal(f[0].clickRate, 0.5);
  const l = A.linkClicks(autos); assert.equal(l.length, 1); assert.equal(l[0].words, 2); assert.equal(l[0].clicks, 6);
  assert.deepEqual(A.unusedWords(autos, posts, now).map((x) => x.word), ['NONE']);
  const series = [{ date: '2026-10-17', value: 1000 }, { date: '2026-11-16', value: 1100 }];
  const gp = A.goalProgress(series, { target: 1300, by: '2027-01-16', start: 1000 }, now);
  assert.equal(gp.cur, 1100); assert.equal(Math.round(gp.pct), 85); assert.ok(gp.pace > 20 && gp.pace < 30); assert.equal(gp.done, false);
  assert.equal(A.goalProgress(series, null, now), null);
});

test('scheduled posts: Instagram only, soonest first, unusable ones dropped', async () => {
  const raw = [
    { _id: 'b', status: 'scheduled', content: ' Later ', platforms: [{ platform: 'instagram', scheduledFor: '2030-01-02T10:00:00Z' }] },
    { _id: 'a', status: 'scheduled', content: 'Soon', mediaItems: [{}, {}], platforms: [{ platform: 'instagram', scheduledFor: '2030-01-01T10:00:00Z' }] },
    { _id: 'x', status: 'scheduled', platforms: [{ platform: 'twitter', scheduledFor: '2030-01-01T09:00:00Z' }] },
    { _id: 'n', status: 'scheduled', platforms: [{ platform: 'instagram' }] },
    { _id: 'p', status: 'published', platforms: [{ platform: 'instagram', scheduledFor: '2030-01-01T09:00:00Z' }] },
  ];
  const got = await A.fetchScheduled(async (m, p) => { assert.equal(m, 'GET'); assert.ok(p.startsWith('/posts?status=scheduled&accountId=acc1')); return { posts: raw }; }, { _id: 'acc1' });
  assert.deepEqual(got.map((x) => x.id), ['a', 'b']);
  assert.equal(got[0].media, 2); assert.equal(got[1].text, 'Later');
});
