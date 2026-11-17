/* The inbox: read and answer Instagram DMs from the dashboard, with saved replies and private contact tags.
 * Messages live in Zernio (its inbox endpoints); saved replies, tags and notes live only in this browser (localStorage). No server of ours.
 * The pure helpers at the top also run in Node (tests/inbox.test.mjs); the page code is in mount(). */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.MRInbox = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  var H = 3600000;

  function ago(t, now) {
    var s = (now - Date.parse(t)) / 1000;
    if (!Number.isFinite(s)) return '';
    s = Math.max(0, s);
    if (s < 60) return 'now';
    if (s < 3600) return Math.floor(s / 60) + 'm';
    if (s < 86400) return Math.floor(s / 3600) + 'h';
    if (s < 86400 * 30) return Math.floor(s / 86400) + 'd';
    return Math.floor(s / 86400 / 30) + 'mo';
  }
  function sortConvos(list) { return (list || []).slice().sort(function (a, b) { return (Date.parse(b.updatedTime) || 0) - (Date.parse(a.updatedTime) || 0); }); }
  /** Instagram lets you answer freely for 24 hours after the person's last message. */
  function windowOpen(msgs, now) {
    var last = 0;
    (msgs || []).forEach(function (m) { if (m.direction === 'incoming') { var t = Date.parse(m.createdAt); if (t > last) last = t; } });
    return last > 0 && now - last < 24 * H;
  }
  function normalizeTag(s) { return String(s == null ? '' : s).trim().toLowerCase().replace(/\s+/g, '-').replace(/[^\p{L}\p{N}_-]/gu, '').slice(0, 24); }
  function tagsOf(contacts, id) { return (contacts && contacts[id] && contacts[id].tags) || []; }
  /** Tags in use, most used first. */
  function allTags(contacts) {
    var m = {};
    Object.keys(contacts || {}).forEach(function (id) { tagsOf(contacts, id).forEach(function (t) { m[t] = (m[t] || 0) + 1; }); });
    return Object.keys(m).map(function (t) { return { tag: t, n: m[t] }; }).sort(function (a, b) { return b.n - a.n || (a.tag < b.tag ? -1 : 1); });
  }
  function filterConvos(list, contacts, tag, unreadOnly) {
    return (list || []).filter(function (c) {
      if (unreadOnly && !(c.unreadCount > 0)) return false;
      if (tag && tagsOf(contacts, c.participantId).indexOf(tag) < 0) return false;
      return true;
    });
  }
  function messageText(m) {
    if (m.isDeleted) return '(deleted message)';
    if (m.message) return m.message;
    if (m.storyReply) return 'Replied to your story';
    if (m.isStoryMention) return 'Mentioned you in a story';
    var a = (m.attachments || [])[0];
    return a ? '[' + (a.type || 'attachment') + ']' : '(no text)';
  }

  // ------------------------------------------------------------------ the page part (browser only)
  var K = { replies: 'mrdm.replies', contacts: function (acct) { return 'mrdm.contacts.' + acct; } };
  function read(key, fallback) { try { var v = JSON.parse(localStorage.getItem(key) || 'null'); return v == null ? fallback : v; } catch (e) { return fallback; } }
  function write(key, v) { try { localStorage.setItem(key, JSON.stringify(v)); return true; } catch (e) { return false; } }

  /** o = { el, ico, card, call, acct, toast, safeUrl, clip } from the dashboard. Returns { inboxCard, repliesCard, load }. */
  function mount(o) {
    var el = o.el, acct = o.acct, acctId = acct._id || acct.id;
    var st = { convos: null, err: null, loading: false, sel: null, msgs: null, msgErr: null, tag: '', unread: false, sending: false };
    var contacts = read(K.contacts(acctId), {});
    var replies = read(K.replies, []);
    var inboxSec = el('section', { class: 'card', id: 'inbox' });
    var repliesSec = el('section', { class: 'card', id: 'replies' });
    var draft = '';
    var save = function () { if (!write(K.contacts(acctId), contacts)) o.toast('This browser would not save that.'); };
    var now = function () { return Date.now(); };

    function problem(err, again) {
      if (err && (err.status === 402 || err.status === 403)) return el('div', { class: 'empty' }, el('b', null, 'The inbox is not switched on for this Zernio account. '), 'Zernio sells it as an add-on. Once it is on, press Refresh.');
      return el('div', { class: 'empty' }, 'Could not load this: ' + ((err && err.message) || err) + ' ', el('button', { class: 'dashbtn', type: 'button', onclick: again }, 'Try again'));
    }

    async function load() {
      st.loading = true; st.err = null; draw();
      try {
        var r = await o.call('GET', '/inbox/conversations?accountId=' + encodeURIComponent(acctId) + '&platform=instagram&limit=50');
        st.convos = sortConvos((r && r.data) || []);
        if (st.sel) { var keep = st.convos.filter(function (c) { return c.id === st.sel.id; })[0]; if (keep) st.sel = keep; }
      } catch (e) { st.err = e; }
      st.loading = false; draw();
    }
    async function open(c) {
      st.sel = c; st.msgs = null; st.msgErr = null; draft = ''; draw();
      try {
        var r = await o.call('GET', '/inbox/conversations/' + encodeURIComponent(c.id) + '/messages?accountId=' + encodeURIComponent(acctId) + '&sortOrder=desc&limit=50');
        if (st.sel !== c) return;
        st.msgs = ((r && r.messages) || []).slice().reverse();
        if (c.unreadCount > 0) { c.unreadCount = 0; o.call('POST', '/inbox/conversations/' + encodeURIComponent(c.id) + '/read', { accountId: acctId }).catch(function () { /* not worth a message */ }); }
      } catch (e) { st.msgErr = e; }
      draw();
    }
    async function send(text) {
      var c = st.sel; if (!c || !text.trim() || st.sending) return;
      var body = { accountId: acctId, message: text.trim() };
      if (!windowOpen(st.msgs, now())) { body.messagingType = 'MESSAGE_TAG'; body.messageTag = 'HUMAN_AGENT'; }
      st.sending = true; draw();
      try {
        await o.call('POST', '/inbox/conversations/' + encodeURIComponent(c.id) + '/messages', body);
        (st.msgs = st.msgs || []).push({ id: 'local-' + now(), direction: 'outgoing', message: text.trim(), createdAt: new Date().toISOString(), sentVia: 'human' });
        c.lastMessage = text.trim(); c.updatedTime = new Date().toISOString(); st.convos = sortConvos(st.convos); draft = '';
      } catch (e) { o.toast((e && e.message) || 'Could not send that.'); }
      st.sending = false; draw();
    }

    // ---- contacts: tags and a note, kept in this browser
    function contact(id) { return contacts[id] || (contacts[id] = { tags: [], note: '' }); }
    function addTag(id, raw) { var t = normalizeTag(raw); if (!t) return; var c = contact(id); if (c.tags.indexOf(t) < 0) c.tags.push(t); save(); draw(); }
    function dropTag(id, t) { var c = contact(id); c.tags = c.tags.filter(function (x) { return x !== t; }); if (!c.tags.length && !c.note) delete contacts[id]; save(); draw(); }
    function setNote(id, v) { var c = contact(id); c.note = v.slice(0, 500); if (!c.tags.length && !c.note) delete contacts[id]; save(); }

    // ---- drawing
    function who(c) { return c.participantName || 'Instagram user'; }
    function listPane() {
      var tags = allTags(contacts);
      var shown = filterConvos(st.convos, contacts, st.tag, st.unread);
      var chips = el('div', { class: 'ibfilter' },
        el('button', { type: 'button', class: 'dashbtn' + (!st.tag && !st.unread ? ' on' : ''), onclick: function () { st.tag = ''; st.unread = false; draw(); } }, 'All'),
        el('button', { type: 'button', class: 'dashbtn' + (st.unread ? ' on' : ''), onclick: function () { st.unread = !st.unread; draw(); } }, 'Unread'),
        tags.map(function (t) { return el('button', { type: 'button', class: 'dashbtn' + (st.tag === t.tag ? ' on' : ''), onclick: function () { st.tag = st.tag === t.tag ? '' : t.tag; draw(); } }, '#' + t.tag + ' ' + t.n); }));
      var list = !shown.length ? el('div', { class: 'empty' }, st.convos.length ? 'No conversation matches that filter.' : 'No conversations yet. Messages sent to your Instagram account will show here.') :
        el('ul', { class: 'convos' }, shown.map(function (c) {
          return el('li', null, el('button', { type: 'button', class: 'convo' + (st.sel && st.sel.id === c.id ? ' on' : '') + (c.unreadCount > 0 ? ' unread' : ''), onclick: function () { open(c); } },
            el('span', { class: 'who' }, el('b', null, who(c)), el('em', null, ago(c.updatedTime, now()))),
            el('span', { class: 'last' }, o.clip(c.lastMessage || '(no text)', 70)),
            tagsOf(contacts, c.participantId).length ? el('span', { class: 'ibtags' }, tagsOf(contacts, c.participantId).map(function (t) { return el('i', null, '#' + t); })) : null));
        }));
      return el('div', { class: 'ibleft' }, chips, list);
    }
    function threadPane() {
      var c = st.sel;
      if (!c) return el('div', { class: 'ibright' }, el('div', { class: 'empty' }, 'Pick a conversation to read it and reply.'));
      var tagInput = el('input', { class: 'ibtag', type: 'text', maxlength: 24, placeholder: 'Add tag', 'aria-label': 'Add a tag', onkeydown: function (e) { if (e.key === 'Enter') { e.preventDefault(); addTag(c.participantId, e.target.value); } } });
      var head = el('div', { class: 'ibhead' }, el('b', null, who(c)),
        el('div', { class: 'ibtags edit' }, tagsOf(contacts, c.participantId).map(function (t) {
          return el('i', null, '#' + t, el('button', { type: 'button', 'aria-label': 'Remove tag ' + t, onclick: function () { dropTag(c.participantId, t); } }, '×'));
        }), tagInput),
        el('textarea', { class: 'ibnote', rows: 2, maxlength: 500, placeholder: 'Private note about this person (kept in this browser only)', 'aria-label': 'Private note', onblur: function (e) { setNote(c.participantId, e.target.value); }, value: (contacts[c.participantId] || {}).note || '' }));
      var body;
      if (st.msgErr) body = problem(st.msgErr, function () { open(c); });
      else if (!st.msgs) body = el('div', { class: 'skeleton' });
      else body = el('div', { class: 'ibmsgs', role: 'log' }, !st.msgs.length ? el('div', { class: 'empty' }, 'No messages to show.') : st.msgs.map(function (m) {
        var a = (m.attachments || []).filter(function (x) { return o.safeUrl(x.url); })[0];
        return el('div', { class: 'ibmsg ' + (m.direction === 'outgoing' ? 'out' : 'in') },
          el('p', null, messageText(m)), a ? el('a', { href: a.url, target: '_blank', rel: 'noopener' }, 'Open ' + (a.type || 'attachment')) : null,
          el('small', null, new Date(m.createdAt).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) + (m.sentVia && m.sentVia !== 'human' && m.direction === 'outgoing' ? ' · sent by ' + String(m.sentVia).replace(/_/g, ' ') : '')));
      }));
      var open24 = st.msgs ? windowOpen(st.msgs, now()) : true;
      var area = el('textarea', { class: 'ibcompose', rows: 3, maxlength: 1000, placeholder: 'Write a reply', 'aria-label': 'Reply', value: draft, oninput: function (e) { draft = e.target.value; } });
      var pick = replies.length ? el('select', { class: 'select', 'aria-label': 'Insert a saved reply', onchange: function (e) {
        var r = replies.filter(function (x) { return x.id === e.target.value; })[0]; if (r) { draft = (draft ? draft + '\n' : '') + r.text; area.value = draft; } e.target.value = '';
      } }, el('option', { value: '' }, 'Saved replies…'), replies.map(function (r) { return el('option', { value: r.id }, r.name); })) : null;
      var form = el('div', { class: 'ibform' }, open24 ? null : el('p', { class: 'hint' }, 'They last wrote over 24 hours ago. Instagram only lets a person reply after that, using its “human agent” tag (up to 7 days), so your message will be sent that way.'),
        area, el('div', { class: 'ibrow' }, pick, el('button', { class: 'dashbtn primary', type: 'button', disabled: st.sending || !st.msgs, onclick: function () { send(area.value); } }, st.sending ? 'Sending…' : 'Send')));
      return el('div', { class: 'ibright' }, head, body, form);
    }
    function draw() {
      var aside = el('button', { class: 'dashbtn', type: 'button', disabled: st.loading, onclick: load }, st.loading ? 'Loading…' : 'Refresh');
      var body;
      if (!st.convos && !st.err) body = el('div', { class: 'skeleton' });
      else if (st.err) body = problem(st.err, load);
      else body = el('div', { class: 'inbox' }, listPane(), threadPane());
      var keepScroll = inboxSec.querySelector('.ibmsgs'); var top = keepScroll ? keepScroll.scrollTop : 0;
      o.fill(inboxSec, 'mail', 'Inbox', 'Read and answer your Instagram DMs. Tags and notes stay in this browser only.', aside, body);
      var m = inboxSec.querySelector('.ibmsgs'); if (m) m.scrollTop = st.sending || !keepScroll ? m.scrollHeight : top;
    }

    // ---- saved replies
    function drawReplies() {
      var name = el('input', { type: 'text', maxlength: 40, placeholder: 'Name, e.g. Price list', 'aria-label': 'Name' });
      var text = el('textarea', { rows: 3, maxlength: 1000, placeholder: 'The message', 'aria-label': 'Message' });
      var add = el('button', { class: 'dashbtn primary', type: 'button', onclick: function () {
        if (!name.value.trim() || !text.value.trim()) { o.toast('Add a name and a message.'); return; }
        replies.push({ id: 'r' + now().toString(36), name: name.value.trim(), text: text.value.trim() });
        if (!write(K.replies, replies)) o.toast('This browser would not save that.');
        drawReplies(); draw();
      } }, 'Save reply');
      var list = !replies.length ? el('div', { class: 'empty' }, 'No saved replies yet. Save the messages you send again and again, then insert them from the inbox in one click.') :
        el('ul', { class: 'savedlist' }, replies.map(function (r) {
          return el('li', null, el('div', null, el('b', null, r.name), el('p', null, r.text)),
            el('button', { class: 'dashbtn', type: 'button', onclick: function () { replies = replies.filter(function (x) { return x.id !== r.id; }); write(K.replies, replies); drawReplies(); draw(); } }, 'Delete'));
        }));
      o.fill(repliesSec, 'file', 'Saved replies', 'Messages you use again and again. Kept in this browser only.', null, el('div', null, list, el('div', { class: 'savedform' }, name, text, add)));
    }

    drawReplies(); draw();
    return { inboxCard: function () { return inboxSec; }, repliesCard: function () { return repliesSec; }, load: load };
  }

  return { ago: ago, sortConvos: sortConvos, windowOpen: windowOpen, normalizeTag: normalizeTag, allTags: allTags, filterConvos: filterConvos, messageText: messageText, mount: mount };
});
