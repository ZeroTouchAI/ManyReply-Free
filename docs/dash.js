/* The analytics dashboard: facts bar, analytics tiles, performance, top posts, growth, posted, what's working, words.
 * app.js hands over what it owns (state, el, wordRow...); the numbers come from analytics.js. */
(function () {
  'use strict';
  var A = window.MRA;

  function home(ctx) {
    var S = ctx.S, el = ctx.el;
    var st = { days: 7, data: null, autos: null, picks: [], loading: true, error: '', openId: null, all: false, day: null, themeLabel: '' };
    var acct = S.account;
    var call = function (m, p, b) { return S.client.call(m, p, b); };
    var sec = {};
    var NAMES = [['top', 'Dashboard'], ['posted', 'Posted'], ['analytics', 'Analytics'], ['perf', 'Performance'], ['best', 'Top posts'], ['growth', 'Growth'], ['works', 'What’s working'], ['words', 'Comment words']];

    function card(id, title, sub) {
      var body = el('div', { class: 'cbody' });
      var n = el('section', { class: 'card', id: 'sec-' + id, 'aria-labelledby': 'h-' + id }, el('header', null, el('h2', { id: 'h-' + id }, title), sub && el('p', null, sub)), body);
      sec[id] = body; return n;
    }
    var skel = function () { return [el('div', { class: 'skeleton' }), el('div', { class: 'skeleton' })]; };
    var notice = function (err, what) {
      if (A.needsAnalyticsAccess(err)) return el('div', { class: 'notice' }, el('strong', null, 'Analytics are not switched on for this Zernio account'),
        el('span', null, 'Zernio includes analytics on usage-based plans; older plans need its Analytics add-on. Once it is on, press Update now.'));
      return el('div', { class: 'notice' }, el('strong', null, 'Could not load ' + what), el('span', null, err.message || String(err)),
        el('button', { class: 'btn small', type: 'button', onclick: refresh }, 'Try again'));
    };
    var d = st; // alias
    var posts = function () { return (d.data && d.data.posts) || []; };
    var now = function () { return (d.data && d.data.at) || Date.now(); };
    var byPost = function () { return A.wordsByPost(d.autos || []); };
    var safeUrl = function (u) { return typeof u === 'string' && /^https:\/\//.test(u) ? u : ''; };
    var dtime = function (t) { return new Date(t).toLocaleDateString([], { month: 'short', day: 'numeric' }); };
    var delta = function (c, p) { var x = A.delta(c, p); return x.text ? el('span', { class: 'd ' + x.dir }, x.text + (st.days ? ' vs before' : '')) : null; };
    var thumb = function (p, cls) { var u = safeUrl(p.thumb); return u ? el('img', { class: cls || 'mini', src: u, alt: '', loading: 'lazy', referrerpolicy: 'no-referrer' }) : el('span', { class: cls || 'mini' }, p.type === 'reel' ? 'REEL' : p.type === 'carousel' ? 'SET' : 'POST'); };
    var tname = { carousel: 'Carousel', reel: 'Reel', photo: 'Photo', other: 'Post' };

    // ---- facts bar
    var facts = el('div', { class: 'facts' });
    function paintFacts() {
      var f = d.data && d.data.followers, last = f && f.length ? f[f.length - 1].value : null, r = d.data && d.data.reach;
      var rd = r && r.prev != null ? A.delta(r.cur, r.prev) : null;
      var themeNow = window.MRTheme ? window.MRTheme.get() : 'auto';
      facts.replaceChildren(
        el('button', { class: 'btn small', type: 'button', onclick: function () { var n = window.MRTheme.next(); toast('Theme: ' + n); paintFacts(); } }, 'Theme: ' + themeNow[0].toUpperCase() + themeNow.slice(1)),
        el('div', { class: 'fact' }, el('b', null, last == null ? '–' : A.fmt(last)), el('small', null, 'followers · @' + acct.username)),
        el('div', { class: 'fact' }, el('b', null, r && r.cur != null ? A.fmt(r.cur) : '–'), el('small', null, 'reached · last 7 days' + (rd && rd.text ? ' · ' + rd.text : ''))),
        el('div', { class: 'fact' }, el('b', null, d.data ? new Date(d.data.at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : '…'), el('small', null, 'last updated')),
        el('button', { class: 'btn small', type: 'button', disabled: d.loading, onclick: refresh }, d.loading ? 'Updating…' : 'Update now'),
        el('span', { class: 'grow' }),
        el('a', { class: 'btn primary small', href: '#/new' }, 'New word'));
    }
    var toast = ctx.toast;

    // ---- analytics tiles
    function paintAnalytics() {
      var b = sec.analytics;
      if (d.loading && !d.data) return b.replaceChildren(...skel());
      if (d.data.postsError) return b.replaceChildren(notice(d.data.postsError, 'your post numbers'));
      var w = A.period(posts(), d.days, now()), c = w.cur, p = w.prev, f = A.followersChange(d.data.followers, d.days, now());
      var ws = A.wordsWorking(d.autos || []).reduce(function (a, x) { a.c += x.comments; a.d += x.dms; a.k += x.clicks; return a; }, { c: 0, d: 0, k: 0 });
      var tile = function (k, v, dd, sub) { return el('div', { class: 'tile' }, el('span', { class: 'k' }, k), el('span', { class: 'v' }, v), dd || (sub && el('span', { class: 'd' }, sub))); };
      var t = function (k, key) { return tile(k, A.fmt(c[key]), p && delta(c[key], p[key])); };
      var fdd = f ? el('span', { class: 'd ' + (f.change > 0 ? 'up' : f.change < 0 ? 'down' : '') }, (f.change > 0 ? '+' : f.change < 0 ? '−' : '') + A.fmt(Math.abs(f.change)) + (f.partial ? ' since ' + dtime(Date.parse(f.since)) : ' this period')) : null;
      b.replaceChildren(
        el('div', { class: 'tiles' },
          tile('Followers', f ? A.fmt(f.value) : '–', fdd, f ? '' : 'no history yet'), t('Reach', 'reach'), t('Posts', 'posts'), t('Views', 'views'), t('Likes', 'likes'), t('Comments', 'comments'),
          t('Saves', 'saves'), t('Sends', 'shares'), t('Follows from posts', 'follows'), t('Reel views', 'reelViews'),
          tile('Word comments*', A.fmt(ws.c), null, 'all time'), tile('Links sent by DM*', A.fmt(ws.d), null, 'all time'), tile('Link clicks*', A.fmt(ws.k), null, 'all time')),
        el('p', { class: 'note' }, 'Post numbers count each post on the day it was published. *Word numbers are all time: Zernio keeps running totals, not daily ones.' + (d.days === 365 ? ' A year has no “before” to compare with.' : '')));
    }
    var tabs = el('div', { class: 'tabs', role: 'group', 'aria-label': 'Time period' });
    function paintTabs() {
      tabs.replaceChildren(...A.PERIODS.map(function (x) { return el('button', { type: 'button', 'aria-pressed': String(d.days === x[0]), onclick: function () { d.days = x[0]; paintTabs(); paintAnalytics(); } }, x[1]); }));
    }

    // ---- performance by type
    function paintPerf() {
      var b = sec.perf; if (d.loading && !d.data) return b.replaceChildren(...skel());
      if (d.data.postsError) return b.replaceChildren(notice(d.data.postsError, 'performance'));
      var rows = A.perfByType(posts(), now());
      var th = function (x) { return el('th', { scope: 'col' }, x); };
      b.replaceChildren(el('div', { class: 'tbl-wrap' }, el('table', { class: 'tbl' },
        el('thead', null, el('tr', null, th(''), th('Posts'), th('Avg reach'), th('Avg views'), th('Saves'), th('Sends'), th('Follows'))),
        el('tbody', null, rows.filter(function (r) { return r.posts || r.type !== 'other'; }).map(function (r) {
          return el('tr', null, el('td', null, r.label), el('td', null, A.fmt(r.posts)), el('td', null, r.posts ? A.fmt(r.avgReach) : '–'), el('td', null, r.posts ? A.fmt(r.avgViews) : '–'), el('td', null, A.fmt(r.saves)), el('td', null, A.fmt(r.shares)), el('td', null, A.fmt(r.follows)));
        })))), el('p', { class: 'note' }, 'Posts older than 3 days only, so the numbers have settled.'));
    }

    // ---- top posts
    function paintBest() {
      var b = sec.best; if (d.loading && !d.data) return b.replaceChildren(...skel());
      if (d.data.postsError) return b.replaceChildren(notice(d.data.postsError, 'top posts'));
      var top = A.topPosts(posts(), now(), 60, 10);
      if (!top.length) return b.replaceChildren(el('p', { class: 'note' }, 'No posts in the last 60 days yet.'));
      b.replaceChildren(el('div', { class: 'rank' }, top.map(function (x, i) {
        var u = safeUrl(x.post.url);
        return el('div', { class: 'r' }, el('span', { class: 'n' }, String(i + 1)), thumb(x.post),
          el('div', { class: 't' }, u ? el('a', { href: u, target: '_blank', rel: 'noopener' }, el('p', null, ctx.clip(x.post.text || tname[x.post.type], 70))) : el('p', null, ctx.clip(x.post.text || tname[x.post.type], 70)), el('small', null, dtime(x.post.t) + ' · ' + tname[x.post.type])),
          el('div', { class: 'm' }, A.fmt(x.post.reach), el('small', null, x.x.toFixed(1) + '× usual')));
      })));
    }

    // ---- growth chart
    function paintGrowth() {
      var b = sec.growth; if (d.loading && !d.data) return b.replaceChildren(...skel());
      if (d.data.followersError) return b.replaceChildren(notice(d.data.followersError, 'follower history'));
      var g = A.growth(d.data.followers, posts());
      if (g.days.length < 2) return b.replaceChildren(el('p', { class: 'note' }, 'Follower history fills in as Zernio collects it (it needs at least two days).'));
      var NS = 'http://www.w3.org/2000/svg', W = 640, H = 220, L = 44, R = 10, T = 12, B = 46;
      var svg = function (tag, at) { var n = document.createElementNS(NS, tag); for (var k in at) n.setAttribute(k, at[k]); return n; };
      var vals = g.days.map(function (x) { return x.value; }), mn = Math.min.apply(null, vals), mx = Math.max.apply(null, vals);
      var pad = Math.max(2, (mx - mn) * 0.1); mn -= pad; mx += pad;
      var X = function (i) { return L + (i / (g.days.length - 1)) * (W - L - R); }, Y = function (v) { return T + (1 - (v - mn) / (mx - mn)) * (H - T - B); };
      var s = svg('svg', { class: 'chart', viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': 'Followers from ' + g.from + ' to ' + g.to + ', ' + (g.change >= 0 ? 'up ' : 'down ') + Math.abs(g.change) });
      [0, 0.5, 1].forEach(function (f) { var y = T + f * (H - T - B), v = mx - f * (mx - mn); s.append(svg('line', { class: 'grid', x1: L, x2: W - R, y1: y, y2: y })); var t = svg('text', { class: 'lab', x: L - 6, y: y + 4, 'text-anchor': 'end' }); t.textContent = A.fmt(Math.round(v)); s.append(t); });
      var pts = g.days.map(function (x, i) { return X(i) + ',' + Y(x.value); });
      s.append(svg('path', { class: 'area', d: 'M' + X(0) + ',' + (H - B) + ' L' + pts.join(' L') + ' L' + X(g.days.length - 1) + ',' + (H - B) + ' Z' }), svg('polyline', { class: 'line', points: pts.join(' ') }));
      var info = el('div', { class: 'daylist' });
      var showDay = function (x) {
        d.day = x.date;
        info.replaceChildren(el('strong', null, new Date(x.date + 'T12:00:00').toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' }) + ' · ' + A.fmt(x.value) + ' followers'),
          ...x.posts.map(function (p) { return el('span', null, tname[p.type] + ': ' + ctx.clip(p.text || 'Post', 60) + ' · reach ' + A.fmt(p.reach)); }));
        s.querySelectorAll('.bar').forEach(function (r) { r.classList.toggle('on', r.dataset.d === x.date); });
      };
      g.days.forEach(function (x, i) {
        if (!x.posts.length) return;
        var h = 6 + Math.min(3, x.posts.length) * 6;
        var r = svg('rect', { class: 'bar', x: X(i) - 3, y: H - B + 8 + (24 - h), width: 6, height: h, rx: 2, tabindex: 0, role: 'button', 'aria-label': x.date + ': ' + x.posts.length + ' post(s)', 'data-d': x.date });
        r.addEventListener('click', function () { showDay(x); });
        r.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); showDay(x); } });
        s.append(r);
      });
      [0, Math.floor((g.days.length - 1) / 2), g.days.length - 1].forEach(function (i, k) { var t = svg('text', { class: 'lab', x: X(i), y: H - 2, 'text-anchor': k === 0 ? 'start' : k === 2 ? 'end' : 'middle' }); t.textContent = dtime(Date.parse(g.days[i].date + 'T12:00:00')); s.append(t); });
      b.replaceChildren(el('p', { class: 'note' }, (g.change >= 0 ? '+' : '−') + A.fmt(Math.abs(g.change)) + ' followers since ' + dtime(Date.parse(g.from + 'T12:00:00')) + '. Yellow bars are posting days: press one to see its posts.'), s, info);
    }

    // ---- posted
    function paintPosted() {
      var b = sec.posted; if (d.loading && !d.data) return b.replaceChildren(...skel());
      if (d.data.postsError) return b.replaceChildren(notice(d.data.postsError, 'your posts'));
      var list = posts();
      if (!list.length) return b.replaceChildren(el('div', { class: 'notice' }, el('strong', null, 'No posts to show yet'), el('span', null, 'Zernio lists Instagram posts it can read analytics for. If you post outside Zernio, turn on its external-post sync, then press Update now.')));
      var bp = byPost(), shown = d.all ? list : list.slice(0, 5);
      var cell = function (k, v, cls) { return el('div', { class: cls || null }, el('dt', null, k), el('dd', null, v)); };
      b.replaceChildren(el('div', { class: 'posted' }, shown.map(function (p) {
        var w = A.postWords(p, bp), s = w.stats, open = d.openId === p.id, u = safeUrl(p.url);
        var row = el('div', { class: 'prow' });
        row.append(el('button', { type: 'button', 'aria-expanded': String(open), onclick: function () { d.openId = open ? null : p.id; paintPosted(); } },
          el('span', { class: 'when' }, dtime(p.t)), thumb(p), el('span', { class: 'cap' }, p.text || '(no caption)'),
          el('span', { class: 'tags' }, w.words.map(function (x) { return el('span', { class: 'pill word' }, x); }), el('span', { class: 'pill' }, tname[p.type]), el('span', { class: 'pill reach' }, A.fmt(p.reach) + ' reach'), s.clicks > 0 && el('span', { class: 'pill click' }, s.clicks + ' clicks'))));
        if (open) row.append(el('div', { class: 'pdetail' },
          el('dl', null, cell('Posted', new Date(p.t).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })), cell('Reach', A.fmt(p.reach)), cell('Views', A.fmt(p.views)), cell('Likes', A.fmt(p.likes)), cell('Comments', A.fmt(p.comments)),
            cell('Saves', A.fmt(p.saves)), cell('Sends', A.fmt(p.shares)), cell('Follows', A.fmt(p.follows)), p.engagement != null && cell('Engagement', p.engagement + '%'),
            w.words.length > 0 && cell((w.words[0] || 'Word') + ' comments', A.fmt(s.comments), 'sub'), w.words.length > 0 && cell('Links sent by DM', A.fmt(s.dms), 'sub'), w.words.length > 0 && cell('Link clicks', A.fmt(s.clicks), 'sub'),
            w.words.length > 0 && s.gateAsked != null && cell('Follow asked', A.fmt(s.gateAsked), 'sub'), w.words.length > 0 && cell('Followed to get it', A.fmt(s.gatePassed), 'sub')),
          !w.words.length && el('p', { class: 'note' }, 'No comment word on this post. '), u && el('a', { href: u, target: '_blank', rel: 'noopener' }, 'Open on Instagram')));
        return row;
      })), list.length > 5 && el('button', { class: 'btn small more', type: 'button', onclick: function () { d.all = !d.all; paintPosted(); } }, d.all ? 'Show fewer' : 'Show ' + (list.length - 5) + ' more'));
    }

    // ---- what's working
    function paintWorks() {
      var b = sec.works; if (d.loading && !d.data) return b.replaceChildren(...skel());
      var bars = function (title, rows, fmtv) {
        var top = rows.length ? rows[0].v : 0;
        return el('div', null, el('h3', null, title), rows.length ? el('div', { class: 'bars' }, rows.map(function (r, i) {
          return el('div', { class: 'b' + (i === 0 ? ' first' : '') }, el('span', null, r.label), el('span', null, fmtv(r)), el('i', { style: 'width:' + Math.max(3, top ? Math.round(r.v / top * 100) : 0) + '%' }));
        })) : el('p', { class: 'note' }, 'Not enough yet.'));
      };
      var ww = A.wordsWorking(d.autos || []).filter(function (x) { return x.dms || x.comments; }).map(function (x) { return { label: x.word + ' (' + x.scope.toLowerCase() + ')', v: x.clicks || x.dms, x: x }; });
      var wh = d.data.postsError ? { day: [], time: [] } : A.whenWorks(posts(), now());
      b.replaceChildren(el('div', { class: 'cols3' },
        bars('By comment word', ww, function (r) { return r.x.clicks + ' clicks · ' + r.x.dms + ' DMs'; }),
        bars('By day of week', wh.day.map(function (x) { return { label: x.label, v: x.avgReach, x: x }; }), function (r) { return A.fmt(r.x.avgReach) + ' avg reach'; }),
        bars('By time of day', wh.time.map(function (x) { return { label: x.label, v: x.avgReach, x: x }; }), function (r) { return A.fmt(r.x.avgReach) + ' avg reach'; })),
        el('p', { class: 'note' }, 'Times are in your own time zone. Best first.'));
    }

    // ---- words
    function paintWords() {
      var b = sec.words; if (!d.autos) return b.replaceChildren(...skel());
      if (!d.autos.length) return b.replaceChildren(el('div', { class: 'empty' }, el('h3', null, 'No words yet'),
        el('p', null, 'Create a word, then end your next post with “Comment GUIDE for the link”. Everyone who comments it gets your link by DM.'), el('a', { class: 'btn primary', href: '#/new' }, 'Create your first word')));
      var by = new Map((d.picks || []).map(function (p) { return [p.id, p]; }));
      b.replaceChildren(el('div', { class: 'words' }, d.autos.map(function (a) { return ctx.wordRow(a, by.get(a.platformPostId)); })));
    }

    // ---- loading
    function paintAll() { paintFacts(); paintAnalytics(); paintPerf(); paintBest(); paintGrowth(); paintPosted(); paintWorks(); paintWords(); }
    async function refresh() {
      d.loading = true; paintFacts();
      var res = await Promise.all([A.load(call, acct), ctx.loadAutomations(true).catch(function (e) { return e; }), ctx.loadPosts()]);
      if (!ctx.isCurrent()) return;
      d.data = res[0]; d.autos = res[1] instanceof Error ? [] : res[1]; d.picks = res[2]; d.loading = false;
      if (res[1] instanceof Error) toast(res[1].message);
      paintAll();
    }

    var picker = S.accounts.length > 1 && el('select', { class: 'select', 'aria-label': 'Instagram account', style: 'width:auto', onchange: function (e) {
      S.account = S.accounts.find(function (a) { return a._id === e.target.value; }); ctx.keep.account(S.account._id); S.automations = null; S.posts = null; ctx.go('#/');
    } }, S.accounts.map(function (a) { return el('option', { value: a._id, selected: a._id === acct._id }, '@' + a.username); }));

    var side = el('nav', { class: 'side', 'aria-label': 'Sections' },
      NAMES.map(function (n) { return el('button', { class: 'nav', type: 'button', onclick: function () { var t = n[0] === 'top' ? document.querySelector('.facts') : document.getElementById('sec-' + n[0]); if (t) t.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' }); } }, n[1]); }),
      el('a', { class: 'nav cta', href: '#/new' }, '+ New word'),
      el('div', { class: 'acct' }, el('strong', null, '@' + acct.username), 'Instagram', picker, el('button', { class: 'btn quiet small', type: 'button', onclick: ctx.signOut }, 'Disconnect')));

    var main = el('div', { class: 'main' }, facts,
      card('analytics', 'Analytics', 'How your posts did'), card('posted', 'Posted', 'Newest first. Press a post for every number'),
      el('div', { class: 'pair' }, card('perf', 'Performance by type', 'Carousels, Reels and photos'), card('best', 'Top posts', 'Last 60 days, by reach')),
      card('growth', 'Growth', 'Followers over the last 12 weeks'), card('works', 'What’s working', 'Which words and times do best'), card('words', 'Comment words', 'Live and paused'));
    sec.analytics.before(tabs); // period tabs sit inside the analytics card, above the tiles
    paintTabs();
    var wrap = el('div', { class: 'dash' }, side, main);
    ctx.mount(wrap);
    paintAll();
    refresh();
  }

  window.MRDash = { home: home };
})();
