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
