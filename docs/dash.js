/* The dashboard, built from the original ManyReply design: sidebar, facts strip, then Analytics, Comment words, Top posts and the rest (see paint()). app.js hands over what it owns; numbers come from analytics.js. */
(function () {
  'use strict';
  var A = window.MRA;
  var ICONS = {
    home: 'M3 11l9-7 9 7M5 10v10h5v-6h4v6h5V10', bars: 'M5 20V11M10 20V5M15 20v-7M20 20V8', trend: 'M3 17l6-6 4 4 8-8M15 7h6v6',
    file: 'M6 3h9l4 4v14H6zM14 3v5h5M9 13h7M9 17h7', chat: 'M4 5h16v11H9l-5 4z', user: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0',
    eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z', heart: 'M12 20s-8-5-8-11a4 4 0 0 1 8-1 4 4 0 0 1 8 1c0 6-8 11-8 11z',
    send: 'M21 3L10 14M21 3l-7 18-4-8-8-4z', bookmark: 'M6 3h12v18l-6-4-6 4z', star: 'M12 3l2.7 5.6 6.3.9-4.5 4.4 1 6.1L12 17l-5.5 3 1-6.1L3 9.5l6.3-.9z',
    link: 'M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1', click: 'M9 9l11 4-5 2-2 5zM5 3v3M3 5h3',
    play: 'M7 4v16l13-8z', clock: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2', image: 'M4 5h16v14H4zM4 15l5-5 4 4 3-3 4 4',
    moon: 'M21 13A9 9 0 1 1 11 3a7 7 0 0 0 10 10z', plus: 'M12 5v14M5 12h14', info: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v6M12 7h.01',
  };
  var LOGO = '<svg viewBox="0 0 48 48" aria-hidden="true"><defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#3B82F6"/><stop offset="1" stop-color="#A855F7"/></linearGradient></defs><rect x="19" y="1" width="10" height="6" rx="3" fill="url(#lg)"/><rect x="18" y="38" width="12" height="8" rx="2.5" fill="url(#lg)"/><rect x="2" y="15" width="5" height="13" rx="2.5" fill="url(#lg)"/><rect x="41" y="15" width="5" height="13" rx="2.5" fill="url(#lg)"/><rect x="7" y="7" width="34" height="32" rx="11" fill="#0B1229" stroke="url(#lg)" stroke-width="4"/><rect x="17" y="17" width="4" height="7" rx="2" fill="#7DD3FC"/><rect x="27" y="17" width="4" height="7" rx="2" fill="#7DD3FC"/><path d="M18 29c3.5 2.6 8.5 2.6 12 0" stroke="#7DD3FC" stroke-width="2.6" fill="none" stroke-linecap="round"/></svg>';
  var IG = '<svg class="i ig" viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="5"/><circle cx="12" cy="12" r="3.5"/><path d="M17 7h.01"/></svg>';
  function svgNode(s) { var t = document.createElement('template'); t.innerHTML = s; return t.content.firstChild; }
  function ico(name) { return svgNode('<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="' + ICONS[name] + '"/></svg>'); }

  var NAV = [['top', 'home', 'Dashboard'], ['analytics', 'bars', 'Analytics'], ['words', 'chat', 'Comment Words'], ['top-posts', 'star', 'Top Posts'], ['worst', 'eye', 'Posts to Learn From'], ['perf', 'bars', 'Performance by Type'],
             ['when', 'clock', 'Best Time to Post'], ['captions', 'file', 'Caption Length'], ['tags', 'link', 'Hashtags'], ['rhythm', 'trend', 'Posting Rhythm'],
             ['growth', 'trend', 'Growth'], ['goal', 'star', 'Goal'], ['funnel', 'chat', 'Word Funnel'], ['links', 'link', 'Link Clicks'], ['unused', 'chat', 'Words Nobody Used'], ['posts', 'file', 'Posted'], ['working', 'star', 'What’s Working']];

  // ------------------------------------------------------------------ the frame: sidebar (brand, sections, your account) + main
  function frame(ctx, content, onHome) {
    var el = ctx.el, S = ctx.S, acct = S.account;
    var go = function (id) {
      if (onHome) { var t = id === 'top' ? document.getElementById('top') : document.getElementById(id); if (t) t.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' }); }
      else { S.scrollTo = id; ctx.go('#/'); }
    };
    var picker = S.accounts.length > 1 && el('select', { class: 'select', 'aria-label': 'Instagram account', onchange: function (e) {
      S.account = S.accounts.find(function (a) { return a._id === e.target.value; }); ctx.keep.account(S.account._id); S.automations = null; S.posts = null; ctx.go('#/');
    } }, S.accounts.map(function (a) { return el('option', { value: a._id, selected: a._id === acct._id }, '@' + a.username); }));
    var side = el('aside', { class: 'side' },
      el('a', { class: 'brand', href: '#/' }, svgNode(LOGO), el('span', null, 'Many', el('b', null, 'Reply')), el('small', null, 'DM')),
      el('nav', { 'aria-label': 'Sections' }, NAV.map(function (n, i) {
        return el('a', { href: '#/', class: i === 0 ? 'on' : null, onclick: function (e) { e.preventDefault(); go(n[0]); } }, ico(n[1]), n[2]);
      }), el('a', { href: '#/new' }, ico('plus'), 'New word')),
      el('div', { class: 'promo' },
        el('div', { class: 'who2' }, svgNode(IG), el('div', { style: 'min-width:0' }, el('b', null, '@' + acct.username), el('span', null, 'Connected on Instagram'))),
        picker, el('button', { class: 'dashbtn', type: 'button', onclick: ctx.signOut }, 'Disconnect')));
    return el('div', { class: 'app' }, side, el('div', { class: 'main', id: 'top' }, content));
  }

  // ------------------------------------------------------------------ the dashboard
  function home(ctx) {
    var S = ctx.S, el = ctx.el, acct = S.account, d = { data: null, autos: null, picks: [], loading: true };
    var call = function (m, p, b) { return S.client.call(m, p, b); };
    var safeUrl = function (u) { return typeof u === 'string' && /^https:\/\//.test(u) ? u : ''; };
    var f0 = A.fmt, f1 = function (n) { return Number.isFinite(n) ? n.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) : '–'; };
    var two = function (n) { return (n < 10 ? '0' : '') + n; };
    var ldate = function (t) { var x = new Date(t); return x.getFullYear() + '-' + two(x.getMonth() + 1) + '-' + two(x.getDate()); };
    var nice = function (day) { return new Date(day + 'T12:00:00').toLocaleDateString(undefined, { day: 'numeric', month: 'short' }); };
    var tname = A.TYPE_NAME;
    var posts = function () { return (d.data && d.data.posts) || []; };
    var now = function () { return (d.data && d.data.at) || Date.now(); };
    var table = function (cls, head, rows) {
      return el('div', { class: 'scroll' }, el('table', { class: cls || null },
        el('thead', null, el('tr', null, head.map(function (h) { return el('th', { class: h[1] ? 'n' : null }, h[0]); }))), el('tbody', null, rows)));
    };
    var more = function (rows, make, shown) { // the first few lines, then the rest folded away, as in the original
      if (rows.length <= shown) return make(rows);
      return el('div', null, make(rows.slice(0, shown)), el('details', { class: 'more' }, el('summary', null, 'Show ' + (rows.length - shown) + ' more'), make(rows.slice(shown))));
    };
    function card(id, icon, title, sub, aside, body) {
      return el('section', { class: 'card', id: id }, el('div', { class: 'head' }, ico(icon), el('div', null, el('h2', null, title), el('p', null, sub)), aside && el('div', { class: 'aside' }, aside)), body);
    }
    var notice = function (err, what) {
      if (A.needsAnalyticsAccess(err)) return el('div', { class: 'empty' }, el('b', null, 'Analytics are not switched on for this Zernio account. '), 'Zernio includes them on usage-based plans; older plans need its Analytics add-on. Once it is on, press Update now.');
      return el('div', { class: 'empty' }, 'Could not load ' + what + ': ' + (err.message || err) + ' ', el('button', { class: 'dashbtn', type: 'button', onclick: refresh }, 'Try again'));
    };

    // ---- the strip across the top: theme, your account and its numbers, last updated
    function facts() {
      var s = d.data && d.data.followers, last = s && s.length ? s[s.length - 1].value : null;
      var w7 = d.data && !d.data.postsError || (d.data && s && s.length) ? A.followerWindow(s, 7, 0, now()) : null;
      var r = d.data && d.data.reach, rd = r && r.cur != null && r.prev != null ? r.cur - r.prev : null;
      var th = window.MRTheme ? window.MRTheme.get() : 'auto';
      var em = function (v, suffix) { return el('em', { class: v > 0 ? 'up' : v < 0 ? 'down' : 'flat' }, (v > 0 ? '+' : v < 0 ? '−' : '') + f0(Math.abs(v)) + (suffix || '')); };
      var themeBtn = el('button', { type: 'button', class: 'fact theme', 'aria-label': 'Switch light or dark mode', onclick: function () { window.MRTheme.next(); stripe.replaceChildren(facts()); } },
        ico('moon'), el('div', null, el('b', null, 'Theme'), el('span', null, th[0].toUpperCase() + th.slice(1))));
      var upd = el('button', { type: 'button', class: 'fact theme', title: 'Pull the latest numbers now', disabled: d.loading, onclick: refresh }, ico('clock'),
        el('div', null, el('b', null, 'Last updated'), el('span', null, d.data ? new Date(d.data.at).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) + ' · ' + (d.loading ? 'Updating…' : 'Update now') : 'Loading…')));
      return el('div', { class: 'facts' }, themeBtn,
        el('div', { class: 'fact' }, svgNode(IG), el('div', null, el('b', null, '@' + acct.username),
          el('span', null, last == null ? 'followers loading…' : [f0(last) + ' followers', w7 ? [' · ', em(w7.change), ' (7d)'] : null]))),
        el('div', { class: 'fact' }, ico('trend'), el('div', null, el('b', null, (r && r.cur != null ? f0(r.cur) : '–') + ' reached'),
          el('span', null, ['last 7 days', rd == null ? null : [' · ', el('em', { class: rd > 0 ? 'up' : rd < 0 ? 'down' : 'flat' }, (rd > 0 ? '▲ ' : rd < 0 ? '▼ ' : '= ') + f0(Math.abs(rd))), ' vs week before']]))),
        upd);
    }
    var stripe = el('div', { class: 'topbar' }, facts());

    // ---- Posted: one line per post, the numbers under it, details on a click
    function chips(p, w) {
      var s = w.stats, hasWord = w.words.length > 0;
      var rows = [['trend', p.reach, 'reached'], ['eye', p.views, 'views'], ['heart', p.likes, 'likes'], ['chat', p.comments, 'comments'], ['bookmark', p.saves, 'saves'], ['send', p.shares, 'sends'],
                  ['user', p.follows, 'follows'], ['star', hasWord ? s.comments : 0, 'word comments'], ['click', hasWord ? s.clicks : 0, 'link clicks']];
      return el('div', { class: 'res' }, rows.map(function (r) {
        var win = r[1] && ['follows', 'sends', 'saves', 'word comments', 'link clicks'].indexOf(r[2]) >= 0;
        return el('span', { class: !r[1] ? 'z' : win ? 'win' : null }, ico(r[0]), el('b', null, f0(r[1])), ' ' + r[2]);
      }));
    }
    function postLine(p, bp, usual) {
      var w = A.postWords(p, bp), s = w.stats, u = safeUrl(p.url), hasWord = w.words.length > 0;
      var auto = hasWord ? (bp.map.get(p.platformPostId) || []) : [];
      var live = auto.some(function (a) { return a.isActive !== false; });
      var cls = usual && p.reach >= usual * 1.25 ? 'hi' : usual && p.reach <= usual * 0.6 ? 'lo' : '';
      var dl = [['Post', p.text || '(no caption)'], ['Type', tname[p.type]], ['Posted at', new Date(p.t).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })],
        ['Reach', f0(p.reach)], ['Views', f0(p.views)], ['Likes', f0(p.likes)], ['Comments', f0(p.comments)], ['Saves', f0(p.saves)], ['Sends', f0(p.shares)], ['Follows', f0(p.follows)]];
      if (p.engagement != null) dl.push(['Engagement', p.engagement + '%']);
      if (hasWord) {
        dl.push(['Word', w.words.join(', ')], ['Word comments', f0(s.comments)]);
        if (s.gateAsked != null || s.gatePassed) dl.push(['Follow gate: asked / passed', (s.gateAsked == null ? '–' : f0(s.gateAsked)) + ' / ' + f0(s.gatePassed)]);
        dl.push(['Links sent by DM', f0(s.dms)], ['Link clicks', f0(s.clicks)]);
      }
      var kids = [];
      dl.forEach(function (r) { kids.push(el('dt', null, r[0]), el('dd', null, r[1])); });
      if (u) kids.push(el('dt', null, 'Instagram'), el('dd', null, el('a', { href: u, target: '_blank', rel: 'noopener' }, u)));
      return el('details', { class: 'post' }, el('summary', null,
        el('span', { class: 'd' }, ldate(p.t)), el('span', { class: 'r' }, p.text ? ctx.clip(p.text, 80) : '(no caption)'),
        hasWord ? el('span', { class: 'word' }, w.words[0]) : el('span'), el('span', { class: 't' }, tname[p.type]),
        hasWord ? el('span', { class: 'pill ' + (live ? 'live' : 'paused') }, live ? 'live' : 'paused') : el('span'),
        el('span', { class: 'rch ' + cls, title: 'Reach; the usual post reaches ' + Math.round(usual) }, f0(p.reach) + ' reach'),
        el('span', { class: 'clk' + (s.clicks ? ' hot' : '') }, String(hasWord ? s.clicks : 0)),
        el('span', { class: 'ig' }, u ? el('a', { href: u, target: '_blank', rel: 'noopener', onclick: function (e) { e.stopPropagation(); } }, 'Instagram') : null),
        chips(p, w)), el('dl', null, kids));
    }
    function postedCard() {
      var body;
      if (d.loading && !d.data) body = el('div', null, el('div', { class: 'skeleton' }));
      else if (d.data.postsError) body = notice(d.data.postsError, 'your posts');
      else if (!posts().length) body = el('div', { class: 'empty' }, 'No posts to show yet. Zernio lists the Instagram posts it can read analytics for. If you post outside Zernio, turn on its external-post sync, then press Update now.');
      else {
        var bp = A.wordsByPost(d.autos || []), list = posts(), usual = list.reduce(function (a, p) { return a + p.reach; }, 0) / list.length;
        body = more(list, function (rows) { return el('div', { class: 'posts' }, rows.map(function (p) { return postLine(p, bp, usual); })); }, 10);
      }
      return card('posts', 'file', 'Posted', 'What went out, newest first. Each line shows how people reacted; click it for the details. A red number means people clicked the link.', null, body);
    }

    // ---- Analytics: the tiles, each period against the one before
    var TILES = [['followers', 'Followers', 'user'], ['posts', 'Posts', 'image'], ['shares', 'Sends', 'send'], ['saves', 'Saves', 'bookmark'], ['follows', 'Follows from posts', 'star'],
                 ['words', 'Word comments', 'chat'], ['dms', 'Links sent by DM', 'link'], ['clicks', 'Link clicks', 'click'], ['views', 'Views', 'eye'], ['likes', 'Likes', 'heart'],
                 ['comments', 'Comments', 'chat'], ['reelViews', 'Reel views', 'play']];
    function tilePanel(days) {
      var w = A.tileWindows(posts(), A.wordsByPost(d.autos || []), d.data.followers, days, now());
      return el('div', { class: 'tiles p' + days }, TILES.map(function (t) {
        var v = w.cur[t[0]], pv = w.prev ? w.prev[t[0]] : null, signed = t[0] === 'followers';
        var shown = v == null ? '–' : signed && v > 0 ? '+' + f0(v) : f0(v);
        var trend = v == null || pv == null || v === pv ? '' : v > pv ? 'up' : 'down';
        if (signed && v != null) trend = v > 0 ? 'up' : v < 0 ? 'down' : '';
        var pill = null, note;
        if (v == null || pv == null) note = signed && v != null && w.cur.since ? 'since ' + nice(w.cur.since) + ' (all the history there is)' : 'no earlier data';
        else { var diff = v - pv; pill = el('i', { class: diff > 0 ? 'up' : diff < 0 ? 'down' : 'flat' }, (diff > 0 ? '▲ ' : diff < 0 ? '▼ ' : '= ') + f0(Math.abs(diff))); note = days === 1 ? 'vs the 24 hours before' : 'vs previous ' + days + 'd'; }
        return el('div', null, ico(t[2]), el('span', null, t[1]), el('b', { class: trend }, el('span', null, shown), pill), el('small', null, note));
      }));
    }
    function analyticsCard() {
      var body;
      if (d.loading && !d.data) body = el('div', { class: 'skeleton' });
      else if (d.data.postsError) body = notice(d.data.postsError, 'your numbers');
      else {
        var PER = [1, 7, 14, 30, 60, 90, 365];
        body = el('div', { class: 'periods' }, PER.map(function (n) { return el('input', { type: 'radio', name: 'period', id: 'p' + n, checked: n === 7, 'aria-label': n + ' days' }); }),
          el('div', { class: 'tabs' }, PER.map(function (n) { return el('label', { for: 'p' + n }, n === 1 ? '24 hours' : n === 365 ? '1 year' : n + ' days'); })), PER.map(tilePanel));
      }
      return card('analytics', 'bars', 'Analytics', 'Each period against the one before it. Word numbers count the words on posts published in that period.', null, body);
    }

    // ---- Performance by type, Top posts
    function perfCard() {
      var body;
      if (d.loading && !d.data) body = el('div', { class: 'skeleton' });
      else if (d.data.postsError) body = notice(d.data.postsError, 'performance');
      else body = table('rank', [['Type'], ['Posts', 1], ['Avg reach', 1], ['Avg views', 1], ['Saves', 1], ['Shares', 1], ['Follows', 1]],
        A.perfByType(posts(), now()).filter(function (r) { return r.posts || r.type !== 'other'; }).map(function (r) {
          return el('tr', null, el('td', null, r.label), [r.posts, r.posts ? f1(r.avgReach) : '–', r.posts ? f1(r.avgViews) : '–', r.saves, r.shares, r.follows].map(function (v) { return el('td', { class: 'n' }, typeof v === 'number' ? f0(v) : v); }));
        }));
      return card('perf', 'bars', 'Performance by type', 'Posts at least 3 days old', null, body);
    }
    function topCard() {
      var body;
      if (d.loading && !d.data) body = el('div', { class: 'skeleton' });
      else if (d.data.postsError) body = notice(d.data.postsError, 'top posts');
      else {
        var top = A.topPosts(posts(), now(), 60, 10);
        body = !top.length ? el('div', { class: 'empty' }, 'No posts in the last 60 days yet.') : more(top, function (rows) {
          return table('rank', [['Date'], ['Type'], ['Post'], ['Reach', 1], ['x usual', 1], ['Saves', 1], ['Sends', 1], ['Follows', 1]], rows.map(function (x) {
            var u = safeUrl(x.post.url), txt = ctx.clip(x.post.text || tname[x.post.type], 70);
            var x0 = new Date(x.post.t);
            return el('tr', null, el('td', { style: 'font-family:var(--mono);white-space:nowrap' }, two(x0.getMonth() + 1) + '-' + two(x0.getDate())), el('td', null, tname[x.post.type]),
              el('td', null, u ? el('a', { href: u, target: '_blank', rel: 'noopener' }, txt) : txt),
              [x.post.reach, null, x.post.saves, x.post.shares, x.post.follows].map(function (v, i) { return el('td', { class: 'n' }, i === 1 ? x.x.toFixed(1) + 'x' : f0(v)); }));
          }));
        }, 5);
      }
      return card('top-posts', 'star', 'Top posts', 'Your 10 best posts of the last 60 days by reach. The x column is reach against your usual post: copy what the top ones have in common.', null, body);
    }

    // ---- Growth: the follower chart, click a day or pick dates to see the posts around it
    function growthCard() {
      var body, sub = 'Follower history. The small bars along the bottom are days you posted (taller means more posts). Click a day to see those posts.';
      if (d.loading && !d.data) return card('growth', 'trend', 'Growth', sub, null, el('div', { class: 'skeleton' }));
      if (d.data.followersError) return card('growth', 'trend', 'Growth', sub, null, notice(d.data.followersError, 'follower history'));
      var series = d.data.followers;
      if (series.length < 2) return card('growth', 'trend', 'Growth', sub, null, el('div', { class: 'empty' }, 'The follower chart appears after two days of data.'));
      var NS = 'http://www.w3.org/2000/svg', W = 1000, DAY = 864e5;
      var sv = function (tag, at, text) { var n = document.createElementNS(NS, tag); for (var k in at) n.setAttribute(k, at[k]); if (text != null) n.textContent = text; return n; };
      var vals = series.map(function (s) { return s.value; }), lo0 = Math.min.apply(null, vals), hi0 = Math.max.apply(null, vals), pad = Math.max((hi0 - lo0) * 0.15, 2), lo = lo0 - pad, hi = hi0 + pad;
      var X = function (i) { return Math.round((56 + i * (1000 - 56 - 70) / (series.length - 1)) * 10) / 10; }, Y = function (v) { return Math.round((20 + (hi - v) * 200 / (hi - lo)) * 10) / 10; };
      var pts = series.map(function (s, i) { return [s.date, s.value, X(i), Y(s.value)]; });
      var rows = posts().map(function (p) { return { date: A.iso(p.t), url: safeUrl(p.url), kind: tname[p.type], caption: p.text, reach: p.reach }; });
      var perDay = {}; rows.forEach(function (r) { perDay[r.date] = (perDay[r.date] || 0) + 1; });
      var path = pts.map(function (p) { return p[2] + ',' + p[3]; }).join(' '), last = pts[pts.length - 1];
      var svg = sv('svg', { id: 'fchart', viewBox: '0 0 1000 250', role: 'img', 'aria-label': 'Followers per day, ' + pts[0][0] + ' to ' + last[0] });
      [lo0, (lo0 + hi0) / 2, hi0].forEach(function (v) { svg.append(sv('line', { class: 'grid', x1: 56, x2: 930, y1: Y(v), y2: Y(v) }), sv('text', { x: 48, y: Y(v) + 4, 'text-anchor': 'end' }, Math.round(v).toLocaleString('en-US'))); });
      svg.append(sv('polygon', { class: 'area', points: '56,220 ' + path + ' ' + last[2] + ',220' }), sv('polyline', { class: 'line', points: path }));
      pts.forEach(function (p) { if (perDay[p[0]]) { var h = Math.min(perDay[p[0]], 7) * 3; svg.append(sv('rect', { class: 'tick', x: p[2] - 2, y: 226 - h, width: 4, height: h, rx: 1 })); } });
      var cross = sv('line', { class: 'cross', y1: 20, y2: 220 }), pickC = sv('circle', { class: 'pick', r: 7 }), dot = sv('circle', { class: 'hover-dot', r: 5 });
      svg.append(cross, sv('circle', { class: 'end', cx: last[2], cy: last[3], r: 5 }), pickC, dot, sv('text', { class: 'now', x: last[2] + 10, y: last[3] + 4 }, last[1].toLocaleString('en-US')),
        sv('text', { x: 56, y: 246 }, pts[0][0]), sv('text', { x: 930, y: 246, 'text-anchor': 'end' }, last[0]));
      var tip = el('div', { id: 'ftip', hidden: true }), panel = el('div', { id: 'around', 'aria-live': 'polite' });
      var fdate = el('input', { type: 'date', id: 'fdate', min: pts[0][0], max: last[0] }), fto = el('input', { type: 'date', id: 'fto', min: pts[0][0], max: last[0] });
      var allBtn = el('button', { type: 'button', class: 'dashbtn', id: 'fall', hidden: true, onclick: showAll }, 'Show all posts');
      var cell = function (tag, text, cls) { var c = document.createElement(tag); c.textContent = text; if (cls) c.className = cls; return c; };
      var nearest = function (x) { return pts.reduce(function (p, q) { return Math.abs(q[2] - x) < Math.abs(p[2] - x) ? q : p; }); };
      var xOf = function (ev) { var box = svg.getBoundingClientRect(); return [(ev.clientX - box.left) / box.width * W, box]; };
      svg.addEventListener('pointermove', function (ev) { var r = xOf(ev), p = nearest(r[0]);
        cross.setAttribute('x1', p[2]); cross.setAttribute('x2', p[2]); cross.style.opacity = 1; dot.setAttribute('cx', p[2]); dot.setAttribute('cy', p[3]); dot.style.opacity = 1;
        tip.hidden = false; tip.textContent = nice(p[0]) + ': ' + p[1].toLocaleString('en-US') + ' followers. Click to see the posts.'; tip.style.left = Math.min(r[1].width - 330, Math.max(16, p[2] / W * r[1].width - 120)) + 'px'; });
      svg.addEventListener('pointerleave', function () { cross.style.opacity = 0; dot.style.opacity = 0; tip.hidden = true; });
      function list(rs) {
        var wrap = cell('div', '', 'wk');
        rs.forEach(function (r) { var row = r.url ? Object.assign(cell('a'), { href: r.url, target: '_blank', rel: 'noopener' }) : cell('div');
          row.append(cell('span', nice(r.date)), cell('em', r.caption || '(no caption)'), cell('b', r.kind + ' · ' + (r.reach || 0).toLocaleString('en-US') + ' reach')); wrap.append(row); });
        return wrap;
      }
      function summary(first, lastp, rs, lead) {
        var change = lastp[1] - first[1];
        var p = cell('p', lead + nice(first[0]) + ' to ' + nice(lastp[0]) + ': followers went from ' + first[1].toLocaleString('en-US') + ' to ' + lastp[1].toLocaleString('en-US') + ' (', 'note');
        p.append(cell('b', (change > 0 ? '+' : '') + change, change > 0 ? 'up' : change < 0 ? 'down' : ''), '). ' + (rs.length ? rs.length + (rs.length === 1 ? ' post' : ' posts') + ' went out in those days.' : 'Nothing was posted in those days.'));
        return p;
      }
      function showAll() {
        var rs = rows.filter(function (r) { return r.date >= pts[0][0] && r.date <= last[0]; }).sort(function (a, b) { return a.date < b.date ? 1 : -1; });
        pickC.style.opacity = 0; fdate.value = fto.value = ''; allBtn.hidden = true;
        var fold = document.createElement('details'); fold.className = 'more'; fold.append(cell('summary', 'Show ' + (rs.length - 5) + ' more'), list(rs.slice(5)));
        panel.replaceChildren(summary(pts[0], last, rs, 'Whole chart, '), ...(rs.length ? [list(rs.slice(0, 5))] : []), ...(rs.length > 5 ? [fold] : []));
      }
      function range(from, to) {
        if (to < from) { var t0 = from; from = to; to = t0; }
        var near = function (day) { return pts.reduce(function (p, q) { return Math.abs(new Date(q[0]) - new Date(day)) < Math.abs(new Date(p[0]) - new Date(day)) ? q : p; }); };
        var inside = pts.filter(function (q) { return q[0] >= from && q[0] <= to; }), first = inside[0] || near(from), lastp = inside[inside.length - 1] || near(to);
        var rs = rows.filter(function (r) { return r.date >= from && r.date <= to; }).sort(function (a, b) { return a.date < b.date ? -1 : 1; });
        pickC.setAttribute('cx', first[2]); pickC.setAttribute('cy', first[3]); pickC.style.opacity = 1; fdate.value = from; fto.value = to; allBtn.hidden = false;
        panel.replaceChildren(from === to ? cell('p', nice(from) + ': ' + (rs.length ? rs.length + (rs.length === 1 ? ' post' : ' posts') + ' went out that day.' : 'Nothing was posted that day.') + ' Followers that day: ' + near(from)[1].toLocaleString('en-US') + '.', 'note') : summary(first, lastp, rs, ''), ...(rs.length ? [list(rs)] : []));
      }
      svg.addEventListener('click', function (ev) { var t = new Date(nearest(xOf(ev)[0])[0] + 'T12:00:00').getTime(), iso = function (ms) { return new Date(ms).toISOString().slice(0, 10); }; range(iso(t - 3 * DAY), iso(t + 3 * DAY)); });
      fdate.addEventListener('change', function () { if (fdate.value) range(fdate.value, fto.value || fdate.value); });
      fto.addEventListener('change', function () { if (fto.value) range(fdate.value || fto.value, fto.value); });
      var dayBtn = el('button', { type: 'button', class: 'dashbtn', onclick: function () { var x = fdate.value || fto.value || last[0]; range(x, x); } }, 'Just that day');
      body = el('div', { class: 'gbody' }, el('div', { class: 'chart' }, svg, tip),
        el('p', { class: 'pick-row' }, el('label', { for: 'fdate' }, 'From'), ' ', fdate, ' ', el('label', { for: 'fto' }, 'To'), ' ', fto, ' ', dayBtn, ' ', allBtn), panel,
        el('details', null, el('summary', null, 'Show follower numbers as a table'), table(null, [['Date'], ['Followers', 1]], series.slice().reverse().map(function (s) { return el('tr', null, el('td', null, s.date), el('td', { class: 'n' }, s.value.toLocaleString('en-US'))); }))));
      showAll();
      return card('growth', 'trend', 'Growth', sub, null, body);
    }

    // ---- What's working, Comment words
    function workingCard() {
      var body;
      if (d.loading && !d.data) body = el('div', { class: 'skeleton' });
      else if (d.data.postsError) body = notice(d.data.postsError, 'what is working');
      else {
        var rs = A.whatsWorking(posts(), A.wordsByPost(d.autos || []), now());
        body = !rs.length ? el('div', { class: 'empty' }, 'Not enough posts yet. This fills in once you have posts at least 3 days old.') : more(rs, function (r) {
          return table('rank', [['Group'], ['Value'], ['Posts', 1], ['Avg reach', 1], ['Avg word comments', 1], ['Follows', 1]], r.map(function (x) {
            return el('tr', null, el('td', null, x.group === 'day' ? 'weekday' : x.group === 'time' ? 'posting time' : x.group), el('td', null, x.value), [f0(x.posts), f1(x.avgReach), f1(x.avgWords), f0(x.follows)].map(function (v) { return el('td', { class: 'n' }, v); }));
          }));
        }, 5);
      }
      return card('working', 'star', 'What’s working', 'Your posts by type, weekday, posting time and comment word, best first', null, body);
    }
    function wordsCard() {
      var body;
      if (!d.autos) body = el('div', { class: 'skeleton' });
      else if (!d.autos.length) body = el('div', { class: 'empty' }, 'No words yet. Create a word, then end your next post with “Comment GUIDE for the link”. Everyone who comments it gets your link by DM.');
      else {
        var by = new Map((d.picks || []).map(function (p) { return [p.id, p]; }));
        body = el('div', null, el('div', { class: 'wordchips' }, d.autos.map(function (a) { return (a.keywords && a.keywords.length ? a.keywords : ['(any comment)']).map(function (k) { return el('span', { class: 'word' }, k); }); })),
          el('div', { class: 'words wlist' }, d.autos.map(function (a) { return ctx.wordRow(a, by.get(a.platformPostId)); })));
      }
      return card('words', 'chat', 'Comment words', 'Pause, edit or delete a word. A post can have one live word.', el('a', { class: 'dashbtn primary', href: '#/new' }, 'New word'), body);
    }

    // ---- Worst posts, Best time to post, Caption length, Hashtags, Posting rhythm (all worked out from the posts above)
    function guard(id, icon, title, sub, make) {
      if (d.loading && !d.data) return card(id, icon, title, sub, null, el('div', { class: 'skeleton' }));
      if (d.data.postsError) return card(id, icon, title, sub, null, notice(d.data.postsError, title.toLowerCase()));
      return card(id, icon, title, sub, null, make());
    }
    var empty = function (t) { return el('div', { class: 'empty' }, t); };
    function worstCard() {
      return guard('worst', 'eye', 'Posts to learn from', 'Your 5 lowest-reach posts of the last 60 days (at least 3 days old). Look for what they share and do less of it.', function () {
        var w = A.worstPosts(posts(), now(), 60, 5);
        return !w.length ? empty('This needs at least 4 posts from the last 60 days.') : table('rank', [['Date'], ['Type'], ['Post'], ['Reach', 1], ['x usual', 1]], w.map(function (x) {
          var u = safeUrl(x.post.url), txt = ctx.clip(x.post.text || tname[x.post.type], 70), x0 = new Date(x.post.t);
          return el('tr', null, el('td', { style: 'font-family:var(--mono);white-space:nowrap' }, two(x0.getMonth() + 1) + '-' + two(x0.getDate())), el('td', null, tname[x.post.type]),
            el('td', null, u ? el('a', { href: u, target: '_blank', rel: 'noopener' }, txt) : txt), el('td', { class: 'n' }, f0(x.post.reach)), el('td', { class: 'n' }, x.x.toFixed(1) + 'x'));
        }));
      });
    }
    function timeCard() {
      return guard('when', 'clock', 'Best time to post', 'Average reach for each weekday and time of day, in your own time zone. Green is best, red is lowest. Needs a few posts in each slot to mean much.', function () {
        var g = A.timeGrid(posts(), now());
        if (g.posts < 5) return empty('This fills in once you have 5 posts that are at least 3 days old.');
        var vals = g.rows.reduce(function (a, r) { return a.concat(r.cells.filter(function (c) { return c.posts; }).map(function (c) { return c.avgReach; })); }, []), lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
        var head = ['Weekday'].concat(g.rows[0].cells.map(function (c) { return c.block; }));
        var tbl = el('div', { class: 'scroll' }, el('table', { class: 'heat' }, el('thead', null, el('tr', null, head.map(function (h) { return el('th', null, h); }))),
          el('tbody', null, g.rows.map(function (r) {
            return el('tr', null, el('th', null, r.day), r.cells.map(function (c) {
              var hue = Math.round(Math.max(0, Math.min(1, hi > lo ? (c.avgReach - lo) / (hi - lo) : 1)) * 120); // red (lowest) through yellow to green (highest)
              return el('td', { class: c.posts ? 'hv' : 'no', title: c.posts ? c.posts + (c.posts === 1 ? ' post' : ' posts') : 'No posts', style: c.posts ? 'background:hsl(' + hue + ' 75% 50% / .42)' : '' }, c.posts ? f0(c.avgReach) : '–');
            }));
          }))));
        return el('div', null, g.best ? el('p', { class: 'hint' }, 'Best slot so far: ', el('b', null, g.rows.filter(function (r) { return r.cells.indexOf(g.best) >= 0; })[0].day + ', ' + g.best.block), ' with ' + f0(g.best.avgReach) + ' average reach over ' + g.best.posts + (g.best.posts === 1 ? ' post.' : ' posts.')) : null, tbl);
      });
    }
    function captionCard() {
      return guard('captions', 'file', 'Caption length', 'Short, medium and long captions against average reach, saves and sends.', function () {
        var c = A.captionLength(posts(), now());
        return c.every(function (x) { return !x.posts; }) ? empty('This fills in once you have posts that are at least 3 days old.') :
          table('rank', [['Caption'], ['Posts', 1], ['Avg reach', 1], ['Avg saves', 1], ['Avg sends', 1]], c.map(function (x) {
            return el('tr', null, el('td', null, x.label), el('td', { class: 'n' }, f0(x.posts)), [x.avgReach, x.avgSaves, x.avgShares].map(function (v) { return el('td', { class: 'n' }, x.posts ? f1(v) : '–'); }));
          }));
      });
    }
    function tagsCard() {
      return guard('tags', 'link', 'Hashtags', 'Hashtags you used on at least 2 posts, best average reach first. The x column is against your usual post.', function () {
        var h = A.hashtags(posts(), now(), 10);
        return !h.length ? empty('No hashtag has been used on 2 or more posts yet.') : table('rank', [['Hashtag'], ['Posts', 1], ['Avg reach', 1], ['x usual', 1]], h.map(function (x) {
          return el('tr', null, el('td', null, x.tag), el('td', { class: 'n' }, f0(x.posts)), el('td', { class: 'n' }, f1(x.avgReach)), el('td', { class: 'n' }, x.x.toFixed(1) + 'x'));
        }));
      });
    }
    function rhythmCard() {
      return guard('rhythm', 'trend', 'Posting rhythm', 'The last 12 weeks, grouped by how many posts went out that week, against the reach the week brought in.', function () {
        var r = A.rhythm(posts(), now(), 12);
        return el('div', null, el('p', { class: 'hint' }, 'You averaged ', el('b', null, f1(r.perWeek)), ' posts a week.'),
          table('rank', [['Posts in the week'], ['Weeks', 1], ['Avg reach for the week', 1]], r.buckets.filter(function (b) { return b.weeks; }).map(function (b) {
            return el('tr', null, el('td', null, b.label), el('td', { class: 'n' }, f0(b.weeks)), el('td', { class: 'n' }, f1(b.avgReach)));
          })));
      });
    }

    // ---- Goal: a follower target, kept in this browser only
    var goalKey = 'mrdm.goal.' + (acct._id || acct.username);
    function loadGoal() { try { var g = JSON.parse(localStorage.getItem(goalKey) || 'null'); return g && g.target > 0 && /^\d{4}-\d\d-\d\d$/.test(g.by) ? g : null; } catch (e) { return null; } }
    function saveGoal(g) { try { if (g) localStorage.setItem(goalKey, JSON.stringify(g)); else localStorage.removeItem(goalKey); } catch (e) { ctx.toast('This browser would not save the goal.'); } }
    function goalCard() {
      var sub = 'Set a follower target and a date. It is saved in this browser only.';
      var goal = loadGoal(), series = d.data && d.data.followers;
      var tIn = el('input', { type: 'number', min: 1, inputmode: 'numeric', 'aria-label': 'Follower target', placeholder: 'Followers', value: goal ? goal.target : '' });
      var bIn = el('input', { type: 'date', 'aria-label': 'Reach it by', value: goal ? goal.by : '' });
      var form = el('div', { class: 'goalform' }, el('label', null, 'Target', tIn), el('label', null, 'By', bIn),
        el('button', { class: 'dashbtn primary', type: 'button', onclick: function () {
          var t = Math.round(Number(tIn.value)), last = series && series.length ? series[series.length - 1].value : 0;
          if (!(t > 0) || !bIn.value) { ctx.toast('Add a target and a date.'); return; }
          saveGoal({ target: t, by: bIn.value, start: last }); paint();
        } }, goal ? 'Update goal' : 'Set goal'), goal ? el('button', { class: 'dashbtn', type: 'button', onclick: function () { saveGoal(null); paint(); } }, 'Clear') : null);
      var body;
      if (d.loading && !d.data) return card('goal', 'star', 'Goal', sub, null, el('div', { class: 'skeleton' }));
      var gp = goal && A.goalProgress(series || [], goal, now());
      if (!gp) body = el('div', null, empty(series && series.length ? 'No goal yet. Pick a number you can reach and a date.' : 'Follower history has not loaded yet, so there is nothing to measure a goal against.'), form);
      else {
        var msg = gp.done ? 'Goal reached. Set a new one when you are ready.' : gp.weeksLeft === 0 ? 'The date has passed. Update the goal to keep going.' :
          gp.need == null ? '' : 'You need about ' + f1(gp.need) + ' new followers a week. Over the last 30 days you gained ' + (gp.pace == null ? 'an unknown number' : f1(gp.pace)) + ' a week' + (gp.onTrack == null ? '.' : gp.onTrack ? ', so you are on track.' : ', so you are behind.');
        body = el('div', null, el('p', { class: 'hint' }, el('b', null, f0(gp.cur)), ' of ' + f0(gp.target) + ' followers by ' + nice(goal.by) + ' (' + Math.round(gp.pct) + '%)'),
          el('div', { class: 'meter', role: 'img', 'aria-label': Math.round(gp.pct) + ' percent of the way' }, el('i', { style: 'width:' + Math.round(gp.pct) + '%' })), el('p', { class: 'hint' }, msg), form);
      }
      return card('goal', 'star', 'Goal', sub, null, body);
    }

    // ---- Word funnel, Link clicks, Words nobody used
    function funnelCard() {
      var sub = 'For each word: comments, then DMs sent, then link clicks. The percentages show how many make it to the next step.';
      if (!d.autos) return card('funnel', 'chat', 'Word funnel', sub, null, el('div', { class: 'skeleton' }));
      var f = A.wordFunnel(d.autos), pc = function (v) { return v == null ? '–' : Math.round(v * 100) + '%'; };
      return card('funnel', 'chat', 'Word funnel', sub, null, !f.length ? empty('Nothing to show until a word has had its first comment.') :
        table('rank', [['Word'], ['Comments', 1], ['DMs sent', 1], ['Got a DM', 1], ['Link clicks', 1], ['Clicked', 1]], f.map(function (x) {
          return el('tr', null, el('td', null, el('span', { class: 'word' }, x.word)), [f0(x.comments), f0(x.dms), pc(x.dmRate), f0(x.clicks), pc(x.clickRate)].map(function (v) { return el('td', { class: 'n' }, v); }));
        })));
    }
    function linksCard() {
      var sub = 'Clicks for each link you send, added up across every word that sends it.';
      if (!d.autos) return card('links', 'link', 'Link clicks', sub, null, el('div', { class: 'skeleton' }));
      var l = A.linkClicks(d.autos);
      return card('links', 'link', 'Link clicks', sub, null, !l.length ? empty('No word sends a link yet.') : table('rank', [['Link'], ['Words', 1], ['DMs sent', 1], ['Clicks', 1], ['Clicked', 1]], l.map(function (x) {
        var u = safeUrl(x.url);
        return el('tr', null, el('td', null, u ? el('a', { href: u, target: '_blank', rel: 'noopener' }, ctx.clip(u.replace(/^https:\/\//, ''), 50)) : ctx.clip(x.url, 50)),
          [f0(x.words), f0(x.dms), f0(x.clicks), x.rate == null ? '–' : Math.round(x.rate * 100) + '%'].map(function (v) { return el('td', { class: 'n' }, v); }));
      })));
    }
    function unusedCard() {
      var sub = 'Live words on posts that are over a week old and have had no comments. Rewrite the call to action, pause them or delete them.';
      if (!d.autos) return card('unused', 'chat', 'Words nobody used', sub, null, el('div', { class: 'skeleton' }));
      var u = A.unusedWords(d.autos, posts(), now());
      return card('unused', 'chat', 'Words nobody used', sub, null, !u.length ? empty('Every live word has been used at least once. Nice.') : el('div', { class: 'wordchips' }, u.map(function (x) { return el('span', { class: 'word' }, x.word); })));
    }

    var grid = el('div', { class: 'grid' });
    function paint() { stripe.replaceChildren(facts()); grid.replaceChildren(analyticsCard(), wordsCard(), topCard(), worstCard(), perfCard(), timeCard(), captionCard(), tagsCard(), rhythmCard(), growthCard(), goalCard(),
        funnelCard(), linksCard(), unusedCard(), postedCard(), workingCard()); }
    async function refresh() {
      d.loading = true; stripe.replaceChildren(facts());
      var res = await Promise.all([A.load(call, acct), ctx.loadAutomations(true).catch(function (e) { return e; }), ctx.loadPosts()]);
      if (!ctx.isCurrent()) return;
      d.data = res[0]; d.autos = res[1] instanceof Error ? [] : res[1]; d.picks = res[2]; d.loading = false;
      if (res[1] instanceof Error) ctx.toast(res[1].message);
      var keepOpen = Array.prototype.map.call(grid.querySelectorAll('details.post[open]'), function (n) { return n.querySelector('.d') && n.querySelector('.d').textContent; });
      paint();
      if (S.scrollTo) { var t = document.getElementById(S.scrollTo); S.scrollTo = null; if (t) t.scrollIntoView(); }
    }
    ctx.mountApp(frame(ctx, [stripe, grid], true));
    paint();
    refresh();
  }

  window.MRDash = { home: home, frame: frame };
})();
