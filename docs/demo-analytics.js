/* Demo mode: sample analytics, answered in Zernio's own response shapes, so the real analytics code runs on it.
 * Everything is generated from fixed numbers: the same demo every time. */
(function () {
  'use strict';
  var DAY = 86400000;
  function rnd(i, salt) { var x = Math.sin(i * 12.9898 + salt * 78.233) * 43758.5453; return x - Math.floor(x); } // steady "random"
  var captions = ['5 tips to get more from your week', 'Behind the scenes at the studio', 'Our spring offer is here', 'Meet the team',
                  'The checklist we use with every client', 'How we plan a month of content', 'Customer story: from 0 to 1k', 'New this season'];
  var TYPES = ['carousel', 'reel', 'carousel', 'photo', 'reel', 'carousel', 'carousel', 'reel', 'photo', 'carousel',
               'carousel', 'reel', 'photo', 'carousel', 'reel', 'carousel', 'photo', 'carousel', 'reel', 'carousel'];
  var HOURS = [9, 12, 18, 20, 8, 17];
  var BASE = { carousel: 1700, reel: 4300, photo: 950 };
  var COUNT = 120;

  function posts() {
    var now = Date.now(); var out = [];
    for (var i = 0; i < COUNT; i++) {
      var type = TYPES[i % TYPES.length];
      var when = new Date(now - (i * 3 + 1) * DAY); when.setHours(HOURS[i % HOURS.length], 15, 0, 0);
      var growth = 1.45 - (i / COUNT) * 0.7; // newer posts do better
      var reach = Math.round(BASE[type] * growth * (0.65 + rnd(i, 1) * 0.9) * (i % 11 === 4 ? 2.6 : 1));
      var views = Math.round(reach * (type === 'reel' ? 2.3 : 1.35));
      var likes = Math.round(reach * (0.04 + rnd(i, 2) * 0.03)), comments = Math.round(likes * (0.05 + rnd(i, 3) * 0.06));
      var saves = Math.round(reach * (0.012 + rnd(i, 4) * 0.02)), shares = Math.round(reach * (0.006 + rnd(i, 5) * 0.012));
      var follows = Math.round(reach * (0.002 + rnd(i, 6) * 0.004));
      var caption = captions[i % captions.length] + (i >= captions.length ? ' (' + (Math.floor(i / captions.length) + 1) + ')' : '') + [' #smallbusiness #marketing', ' #marketing', ' #behindthescenes #smallbusiness', ''][i % 4];
      var code = 'DEMO' + (i < 9 ? '00' : i < 99 ? '0' : '') + (i + 1);
      out.push({
        postId: 'zp_' + (i + 1), status: 'published', content: caption, publishedAt: when.toISOString(), mediaType: type === 'reel' ? 'video' : type === 'photo' ? 'image' : 'carousel',
        mediaProductType: type === 'reel' ? 'REELS' : 'FEED', thumbnailUrl: '',
        analytics: { reach: reach, views: views, impressions: views, likes: likes, comments: comments, saves: saves, shares: shares, follows: follows, clicks: 0,
                     engagementRate: Math.round((likes + comments + saves + shares) / reach * 10000) / 100 },
        platformAnalytics: [{ platform: 'instagram', platformPostId: 'demo-p' + (i + 1), accountId: 'demo-acc', platformPostUrl: 'https://www.instagram.com/p/' + code + '/', status: 'published' }],
      });
    }
    return out;
  }
  var cache; function all() { return cache || (cache = posts()); }

  function followerSeries(from, to) {
    var out = []; var d = new Date(from.getTime()); var n = 0; var v = 2840;
    var start = new Date(Date.now() - 88 * DAY);
    while (d <= to) {
      var k = Math.max(0, Math.round((d - start) / DAY));
      v = Math.round(2840 + k * 4.7 + Math.sin(k / 3) * 9 + rnd(k, 9) * 14);
      out.push({ date: d.toISOString().slice(0, 10), value: v }); d = new Date(d.getTime() + DAY); n++;
    }
    return out;
  }

  function params(path) { var o = {}; (path.split('?')[1] || '').split('&').forEach(function (kv) { var p = kv.split('='); if (p[0]) o[p[0]] = decodeURIComponent(p[1] || ''); }); return o; }

  window.MRDemoData = {
    respond: function (method, path) {
      var p = params(path);
      if (path.indexOf('/analytics/instagram/follower-history') === 0) {
        var s = followerSeries(new Date(p.fromDate + 'T00:00:00Z'), new Date(p.toDate + 'T00:00:00Z'));
        return { success: true, accountId: p.accountId, platform: 'instagram', metricType: 'time_series', metrics: { follower_count: { total: s.length ? s[s.length - 1].value : 0, values: s } } };
      }
      if (path.indexOf('/analytics/instagram/account-insights') === 0) {
        var days = Math.round((Date.parse(p.toDate) - Date.parse(p.fromDate)) / DAY) + 1;
        var back = Math.round((Date.now() - Date.parse(p.toDate)) / DAY);
        return { success: true, accountId: p.accountId, platform: 'instagram', metricType: 'total_value', metrics: { reach: { total: Math.round(days * (1750 - back * 9) + rnd(back, 7) * 900) } } };
      }
      if (path.indexOf('/analytics?') === 0) {
        var list = all().filter(function (x) { return x.publishedAt.slice(0, 10) >= p.fromDate && x.publishedAt.slice(0, 10) <= p.toDate; });
        var limit = Number(p.limit) || 50, page = Number(p.page) || 1;
        return { overview: {}, posts: list.slice((page - 1) * limit, page * limit), pagination: { page: page, limit: limit, total: list.length }, hasAnalyticsAccess: true };
      }
      return {};
    },
  };
})();
