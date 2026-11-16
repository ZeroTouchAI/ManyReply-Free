/* Demo mode: the real dashboard running on sample data, in memory. Nothing is sent to Zernio and no key is needed.
 * It swaps in a fake client when the stored key is the demo marker, so every screen is the real one. */
(function () {
  'use strict';
  var MR = window.MR;
  var MARK = 'demo-key';
  function on() { try { return sessionStorage.getItem('mrdm.key') === MARK; } catch (e) { return false; } }
  function start() { try { sessionStorage.setItem('mrdm.key', MARK); } catch (e) { return false; } return true; }
  function stop() { try { sessionStorage.removeItem('mrdm.key'); } catch (e) { /* nothing to clear */ } }
  window.MRDemo = { on: on, start: start, stop: stop };

  // ---- the "start the demo" link on the connect screen: only while the connect screen is showing
  var link = document.getElementById('demo-link');
  var app = document.getElementById('app');
  if (link) {
    link.addEventListener('click', function (e) { e.preventDefault(); if (start()) { location.hash = '#/'; location.reload(); } });
    var sync = function () { link.hidden = on() || !app.querySelector('.connect'); };
    new MutationObserver(sync).observe(app, { childList: true });
    sync();
  }
  if (!on()) return;

  // ---- a bar that says so, with the way out
  var bar = document.createElement('div');
  bar.className = 'demo-bar';
  bar.setAttribute('role', 'status');
  var txt = document.createElement('span');
  txt.textContent = 'Demo mode: sample data, nothing is sent to Zernio. Try pasting a post link like instagram.com/p/DEMO003/';
  var out = document.createElement('button');
  out.type = 'button'; out.textContent = 'Exit demo';
  out.addEventListener('click', function () { stop(); location.hash = '#/'; location.reload(); });
  bar.append(txt, out);
  document.body.prepend(bar);

  // ---- sample data
  function thumb(a, b, label) {
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="' + a + '"/><stop offset="1" stop-color="' + b + '"/></linearGradient></defs><rect width="120" height="120" fill="url(#g)"/><text x="60" y="70" text-anchor="middle" font-family="sans-serif" font-size="30" font-weight="800" fill="#fff" fill-opacity=".92">' + label + '</text></svg>';
    return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
  }
  var account = { _id: 'demo-acc', profileId: 'demo-prof', platform: 'instagram', username: 'yourbrand' };
  var captions = ['5 tips to get more from your week', 'Behind the scenes at the studio', 'Our spring offer is here', 'Meet the team',
                  'The checklist we use with every client', 'How we plan a month of content', 'Customer story: from 0 to 1k', 'New this season'];
  var colors = [['#1A6BFF', '#6E9BFF'], ['#FF7A59', '#FFB199'], ['#14B8A6', '#6EE7D8'], ['#8B5CF6', '#C4B5FD'],
                ['#F59E0B', '#FCD34D'], ['#EC4899', '#F9A8D4'], ['#0EA5E9', '#7DD3FC'], ['#22C55E', '#86EFAC']];
  var now = Date.now();
  var posts = captions.map(function (c, i) {
    return { id: 'demo-p' + (i + 1), message: c, picture: thumb(colors[i][0], colors[i][1], String(i + 1)),
             createdTime: new Date(now - (i * 3 + 1) * 86400000).toISOString(),
             permalink: 'https://www.instagram.com/p/DEMO00' + (i + 1) + '/' };
  });

  function made(over, post, stats, active) {
    var form = Object.assign(MR.defaults(account), { linkUrl: 'https://example.com/free-guide' }, over);
    if (post) { form.platformPostId = post.id; form.postTitle = post.message; form.scope = 'post'; } else { form.scope = 'any'; }
    var body = MR.buildAutomation(form, account).body;
    return Object.assign({}, body, { id: 'demo-a' + Math.random().toString(36).slice(2, 8), platform: 'instagram', isActive: active !== false, stats: stats });
  }
  var autos = [
    made({ words: 'GUIDE' }, posts[4], { triggered: 128, dmsSent: 119, linkClicks: 64, followGatePassed: 37 }),
    made({ words: 'FREE', gate: false, linkLabel: 'Get it free' }, null, { triggered: 41, dmsSent: 40, linkClicks: 22, followGatePassed: 0 }),
    Object.assign(made({ words: 'PRICE' }, posts[2], { triggered: 9, dmsSent: 9, linkClicks: 3, followGatePassed: 2 }, false),
                  { buttons: [{ type: 'postback', title: 'See prices', payload: 'prices' }] }), // made elsewhere: shows the "Made elsewhere" state
  ];

  // ---- a fake client with the same shape as the real one
  var wait = function (v) { return new Promise(function (r) { setTimeout(function () { r(v); }, 220); }); };
  var clone = function (o) { return JSON.parse(JSON.stringify(o)); };
  var fail = function (status, msg) { return new MR.ZernioError(msg, status, '', ''); };
  var real = MR.createClient;
  MR.createClient = function (key) {
    if (key !== MARK) return real.apply(MR, arguments);
    return {
      call: function (method, path) {
        var D = window.MRDemoData;
        return wait(D ? D.respond(method, path) : {});
      },
      accounts: function () { return wait([clone(account)]); },
      posts: function () { return wait(clone(posts)); },
      automations: function () { return wait(clone(autos)); },
      create: function (body) {
        if (body.platformPostId && autos.some(function (a) { return a.isActive !== false && a.platformPostId === body.platformPostId; })) {
          return Promise.reject(fail(409, 'That post already has a word. A post can have only one active word: edit or delete the existing one, or choose “Any post”.'));
        }
        var a = Object.assign({}, clone(body), { id: 'demo-a' + Math.random().toString(36).slice(2, 8), platform: 'instagram', isActive: true, stats: {} });
        autos.push(a); return wait(clone(a));
      },
      update: function (id, body) {
        var a = autos.find(function (x) { return x.id === id; });
        if (!a) return Promise.reject(fail(404, 'Zernio could not find that. It may have been deleted.'));
        ['followGate', 'commentReply', 'commentReplyVariations', 'dmDelaySeconds'].forEach(function (k) { if (!(k in body) && 'keywords' in body) delete a[k]; });
        Object.assign(a, clone(body)); return wait(clone(a));
      },
      remove: function (id) { autos = autos.filter(function (x) { return x.id !== id; }); return wait(); },
    };
  };
})();
