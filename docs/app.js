/* ManyReply DM: the page. Everything is built with textContent-safe DOM calls, because post captions and names come from Instagram. */
(function () {
  'use strict';
  const MR = window.MR;
  const CFG = window.MANYREPLY_CONFIG || {};
  const SIGNUP = CFG.zernioSignupUrl || 'https://zernio.com';
  const IS_REFERRAL = !!CFG.zernioSignupUrl;
  const root = document.getElementById('app');
  const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const S = { client: null, accounts: [], account: null, automations: null, posts: null, postsError: '' };
  let renderId = 0;

  // ---------------------------------------------------------------- small helpers

  function el(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    let value;
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') n.className = v;
      else if (k === 'style') n.style.cssText = v; // CSSOM, so the strict CSP (no inline style attributes) still holds
      else if (k === 'value') value = v;
      else if (['checked', 'disabled', 'hidden', 'selected', 'open'].includes(k)) n[k] = !!v;
      else if (k.startsWith('on') && typeof v === 'function') n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat(Infinity)) { if (kid == null || kid === false) continue; n.append(kid instanceof Node ? kid : String(kid)); }
    if (value !== undefined) n.value = value;
    return n;
  }
  let uidn = 0;
  const uid = (p) => `${p}-${++uidn}`;
  const go = (hash) => { if (location.hash === hash) render(); else location.hash = hash; };

  function toast(text) {
    const t = el('div', { class: 'toast', role: 'status' }, text);
    document.body.append(t);
    setTimeout(() => t.remove(), 3200);
  }
  const safeImg = (u) => (/^https:\/\//i.test(u || '') ? u : '');
  const when = (iso) => { const d = new Date(iso); return isNaN(d) ? '' : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }); };

  // The key lives in this browser only: this tab by default, or this device if the person asks.
  const keep = {
    load() { try { return sessionStorage.getItem('mrdm.key') || localStorage.getItem('mrdm.key') || ''; } catch (e) { return ''; } },
    save(key, remember) {
      try {
        sessionStorage.removeItem('mrdm.key'); localStorage.removeItem('mrdm.key');
        (remember ? localStorage : sessionStorage).setItem('mrdm.key', key);
      } catch (e) { /* storage blocked: the key stays in memory for this visit */ }
    },
    clear() { try { sessionStorage.removeItem('mrdm.key'); localStorage.removeItem('mrdm.key'); } catch (e) { /* nothing to clear */ } },
    account(id) { try { if (id) localStorage.setItem('mrdm.account', id); else return localStorage.getItem('mrdm.account') || ''; } catch (e) { return ''; } return ''; },
  };

  // ---------------------------------------------------------------- frame

  function logo() {
    const n = document.createElement('span');
    n.innerHTML = '<svg viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="9" fill="#1A6BFF"/><rect x="6" y="7" width="14" height="9" rx="4.5" fill="#FFE14D"/><rect x="12" y="17" width="14" height="8" rx="4" fill="#fff"/></svg>';
    return n.firstChild;
  }
  function shell(content, signedIn) {
    const top = el('header', { class: 'topbar' },
      el('a', { class: 'brand', href: '#/' }, logo(), 'ManyReply', el('small', null, 'DM')),
      signedIn && S.account && el('div', { class: 'who' }, el('span', null, 'Connected as ', el('strong', null, '@' + S.account.username)),
        el('button', { class: 'btn quiet small', type: 'button', onclick: signOut }, 'Disconnect')));
    const foot = el('footer', { class: 'foot' },
      el('span', null, 'Your key stays in this browser and is sent only to zernio.com.'),
      el('a', { href: CFG.repoUrl || '#', target: '_blank', rel: 'noopener' }, 'Free and open source'),
      el('span', null, 'Built on Zernio. Not affiliated with Instagram, Meta or Zernio.'));
    root.replaceChildren(top, el('main', { class: 'page' }, content), foot);
  }
  function signOut() {
    keep.clear();
    Object.assign(S, { client: null, accounts: [], account: null, automations: null, posts: null, postsError: '' });
    go('#/');
  }

  // ---------------------------------------------------------------- the phone

  /** What people receive. `view` is 'follower' or 'new' (not following yet). In demo mode each part arrives in turn. */
  function phoneNode(m, view, demo) {
    const step = (node) => { if (demo) node.classList.add('demo-step'); return node; };
    const initial = (s) => (s || '?').replace(/[^A-Za-z0-9]/g, '').slice(0, 1) || '?';
    const dmBlock = (text, buttons) => [
      step(el('div', { class: 'bubble' }, text)),
      step(el('div', { class: 'pbtns' }, buttons.map((b) => el('div', { class: 'pbtn' }, b)))),
    ];
    const body = [
      step(el('div', { class: 'cmt' }, el('span', { class: 'avatar alt' }, initial(m.commenter)),
        el('div', null, el('p', null, el('b', null, m.commenter + ' '), m.word)))),
      m.reply && step(el('div', { class: 'cmt', style: 'margin-left:2rem' }, el('span', { class: 'avatar' }, initial(m.handle)),
        el('div', null, el('p', null, el('b', null, m.handle + ' '), m.reply)))),
      step(el('div', { class: 'rule' }, 'Direct message')),
    ];
    if (m.gate && view === 'new') {
      body.push(...dmBlock(m.gate.text, m.gate.buttons));
      body.push(step(el('div', { class: 'rule' }, 'After they follow and tap the second button')));
    }
    body.push(...dmBlock(m.dm.text, m.dm.buttons));
    return el('div', { class: 'phone', role: 'img', 'aria-label': 'Preview of the comment, the reply and the direct message' },
      el('div', { class: 'phone-bar' }, el('span', { class: 'avatar' }, initial(m.handle)), m.handle),
      el('div', { class: 'phone-body' }, body));
  }
  function playDemo(node) {
    const parts = [...node.querySelectorAll('.demo-step')];
    if (reduceMotion) { parts.forEach((p) => p.classList.add('in')); return; }
    parts.forEach((p, i) => setTimeout(() => p.classList.add('in'), 500 + i * 650));
  }
  function previewPanel(getForm) {
    let view = 'follower';
    const holder = el('div');
    const tabs = el('div', { class: 'tabs', role: 'tablist', 'aria-label': 'Who is receiving it' });
    function draw() {
      const f = getForm();
      const m = MR.previewModel(f, S.account);
      if (!m.gate) view = 'follower';
      tabs.hidden = !m.gate;
      tabs.replaceChildren(...[['follower', 'A follower'], ['new', 'Not following yet']].map(([id, label]) =>
        el('button', { class: 'tab', type: 'button', role: 'tab', 'aria-selected': String(view === id), onclick: () => { view = id; draw(); } }, label)));
      holder.replaceChildren(phoneNode(m, view, false));
    }
    draw();
    return { node: el('div', null, tabs, holder), update: draw };
  }

  // ---------------------------------------------------------------- connect

  function connectView(error) {
    const demoModel = MR.previewModel({ ...MR.defaults({ username: 'yourhandle' }), words: 'guide', linkUrl: 'https://example.com/guide', gate: false }, { username: 'yourhandle' });
    const demo = phoneNode(demoModel, 'follower', true);
    const keyId = uid('key');
    const keyInput = el('input', { class: 'input', id: keyId, type: 'password', autocomplete: 'off', spellcheck: 'false', placeholder: 'Paste your Zernio API key', required: true });
    const remember = el('input', { type: 'checkbox' });
    const status = el('div', { 'aria-live': 'polite' }, error && el('div', { class: 'notice error' }, error));
    const submit = el('button', { class: 'btn primary', type: 'submit' }, 'Connect');
    const form = el('form', { onsubmit: async (e) => {
      e.preventDefault();
      const key = keyInput.value.trim();
      if (!key) return;
      submit.disabled = true; submit.textContent = 'Connecting…';
      status.replaceChildren();
      try {
        await connect(key, remember.checked);
      } catch (err) {
        submit.disabled = false; submit.textContent = 'Connect';
        status.replaceChildren(el('div', { class: 'notice error' }, err.message || String(err)));
      }
    } },
      el('div', { class: 'field' }, el('label', { for: keyId }, 'Zernio API key'), keyInput,
        el('p', { class: 'hint' }, 'In Zernio, open API keys and create one.')),
      el('label', { class: 'check' }, remember, el('span', null, 'Keep me connected on this device', el('small', null, 'Otherwise you are disconnected when you close this tab.'))),
      el('div', { style: 'margin-top:1.2rem' }, submit), status,
      el('p', { class: 'privacy' }, 'This page has no server. Your key is stored only in this browser and sent only to zernio.com.'));
    const referral = el('div', { class: 'referral' },
      el('p', null, el('strong', null, 'New to Zernio?'), ' Zernio connects your Instagram account. Its first two connected accounts are free (see their pricing).'),
      el('a', { class: 'btn', href: SIGNUP, target: '_blank', rel: 'noopener sponsored' }, 'Create a free Zernio account'),
      IS_REFERRAL && el('p', { class: 'small' }, 'This is a referral link. If you sign up through it, the maker of this tool earns a commission from Zernio, and your price stays the same. Sign up in this browser so the referral is counted.'),
      el('ol', { class: 'steps-help' }, el('li', null, 'Connect your Instagram account in Zernio.'), el('li', null, 'Create an API key.'), el('li', null, 'Paste it above.')));
    shell(el('div', { class: 'connect' },
      el('div', { class: 'connect-hero' },
        el('h1', null, 'Turn a comment into a DM'),
        el('p', { class: 'lead' }, 'Pick a word. When someone comments it on your Instagram post, they get your link by DM. People who don’t follow you yet are asked to follow first.'),
        el('div', { class: 'demo' }, demo)),
      el('div', { class: 'panel connect-form' }, el('h2', null, 'Connect Zernio'), form, referral)), false);
    playDemo(demo);
    keyInput.focus({ preventScroll: true });
  }

  async function connect(key, remember) {
    const client = MR.createClient(key);
    const accounts = await client.accounts();
    if (!accounts.length) {
      const e = new Error('This key works, but no Instagram account is connected in Zernio yet. Connect Instagram in Zernio, then try again.');
      throw e;
    }
    keep.save(key, remember);
    S.client = client; S.accounts = accounts;
    const saved = keep.account();
    S.account = accounts.find((a) => a._id === saved) || accounts[0];
    S.automations = null; S.posts = null;
    go('#/');
  }

  // ---------------------------------------------------------------- the words

  async function loadAutomations(force) {
    if (!S.automations || force) {
      const all = await S.client.automations(S.account.profileId);
      S.automations = all.filter((a) => a.platform === 'instagram' && (!a.accountId || a.accountId === S.account._id));
    }
    return S.automations;
  }
  async function loadPosts() {
    if (S.posts) return S.posts;
    try { S.posts = await S.client.posts(S.account._id); S.postsError = ''; }
    catch (e) { S.postsError = e.message; S.posts = []; }
    return S.posts;
  }

  async function homeView(id) {
    const list = el('div', { class: 'words', 'aria-busy': 'true' }, el('div', { class: 'skeleton' }), el('div', { class: 'skeleton' }));
    const picker = S.accounts.length > 1 && el('select', { class: 'select', 'aria-label': 'Instagram account', style: 'width:auto', onchange: (e) => {
      S.account = S.accounts.find((a) => a._id === e.target.value); keep.account(S.account._id); S.automations = null; S.posts = null; go('#/');
    } }, S.accounts.map((a) => el('option', { value: a._id, selected: a._id === S.account._id }, '@' + a.username)));
    shell(el('div', null,
      el('div', { class: 'head' }, el('h2', null, 'Your words'),
        el('div', { class: 'tools' }, picker,
          el('button', { class: 'btn quiet small', type: 'button', onclick: async () => { S.automations = null; await homeView(); } }, 'Refresh numbers'),
          el('a', { class: 'btn primary', href: '#/new' }, 'New word'))),
      list), true);
    let autos, posts;
    try { [autos, posts] = await Promise.all([loadAutomations(true), loadPosts()]); }
    catch (e) {
      if (id !== renderId) return;
      list.removeAttribute('aria-busy');
      list.replaceChildren(el('div', { class: 'empty' }, el('h3', null, 'Could not load your words'), el('p', null, e.message),
        el('button', { class: 'btn', type: 'button', onclick: () => homeView() }, 'Try again')));
      return;
    }
    if (id !== renderId) return;
    list.removeAttribute('aria-busy');
    if (!autos.length) {
      list.replaceChildren(el('div', { class: 'empty' }, el('h3', null, 'No words yet'),
        el('p', null, 'Create a word, then end your next post with “Comment GUIDE for the link”. Everyone who comments it gets your link by DM.'),
        el('a', { class: 'btn primary', href: '#/new' }, 'Create your first word')));
      return;
    }
    const byId = new Map((posts || []).map((p) => [p.id, p]));
    list.replaceChildren(...autos.map((a) => wordRow(a, byId.get(a.platformPostId))));
  }

  function wordRow(a, post) {
    const st = MR.statsOf(a);
    const thumb = post && safeImg(post.picture)
      ? el('img', { class: 'thumb', src: safeImg(post.picture), alt: '', loading: 'lazy', referrerpolicy: 'no-referrer' })
      : el('span', { class: 'thumb any' }, a.platformPostId ? 'POST' : 'ANY');
    const label = (post && post.message) || a.postTitle || (a.platformPostId ? 'One post' : 'Works on any of your posts');
    const row = el('div', { class: 'word-row' });
    const live = a.isActive !== false;
    const toggle = el('input', { type: 'checkbox', checked: live, onchange: async (e) => {
      const want = e.target.checked;
      e.target.disabled = true;
      try { await S.client.update(a.id, { isActive: want }); a.isActive = want; text.textContent = want ? 'Live' : 'Paused'; }
      catch (err) { e.target.checked = !want; toast(err.message); }
      e.target.disabled = false;
    } });
    const text = el('span', null, live ? 'Live' : 'Paused');
    const actions = el('div', { class: 'actions' });
    const drawActions = (confirming) => {
      actions.replaceChildren(
        el('label', { class: 'switch' }, toggle, el('i'), text),
        MR.isEditable(a) ? el('a', { class: 'btn quiet small', href: '#/edit/' + encodeURIComponent(a.id) }, 'Edit') : el('span', { class: 'hint', title: 'This word was made outside this dashboard, so it can only be paused or deleted here.' }, 'Made elsewhere'),
        confirming
          ? [el('button', { class: 'btn quiet small danger', type: 'button', onclick: async (e) => {
                e.target.disabled = true;
                try { await S.client.remove(a.id); S.automations = S.automations.filter((x) => x.id !== a.id); row.remove(); toast('Deleted'); if (!S.automations.length) homeView(); }
                catch (err) { toast(err.message); e.target.disabled = false; }
              } }, 'Yes, delete'),
             el('button', { class: 'btn quiet small', type: 'button', onclick: () => drawActions(false) }, 'Keep')]
          : el('button', { class: 'btn quiet small danger', type: 'button', onclick: () => drawActions(true) }, 'Delete'));
    };
    drawActions(false);
    row.append(
      el('div', { class: 'chips' }, (a.keywords && a.keywords.length ? a.keywords : ['(any comment)']).map((k) => el('span', { class: 'chip' }, k))),
      el('div', { class: 'post-cell' }, thumb, el('div', { style: 'min-width:0' }, el('p', null, MR.clip(label, 90)), el('small', null, a.platformPostId ? 'One post' : 'Any post'))),
      el('dl', { class: 'stats' }, [['comments', st.comments], ['DMs sent', st.dms], ['link clicks', st.clicks], ['followed', st.followed]]
        .map(([t, n]) => el('div', { class: 'stat' }, el('dd', null, String(n)), el('dt', null, t)))),
      actions);
    return row;
  }

  // ---------------------------------------------------------------- the editor

  async function editorView(editId, id) {
    let existing = null;
    shell(el('p', { class: 'boot' }, 'Loading…'), true);
    try {
      const autos = await loadAutomations();
      if (editId) existing = autos.find((a) => a.id === editId) || null;
    } catch (e) { return connectErrorToHome(e); }
    if (id !== renderId) return;
    if (editId && (!existing || !MR.isEditable(existing))) { toast('That word can’t be edited here.'); return go('#/'); }

    const form = existing ? MR.fromAutomation(existing, S.account) : MR.defaults(S.account);
    let current = MR.buildAutomation(form, S.account);
    let showErrors = false;
    const errs = {};
    const fieldEls = {};

    // -- builders that keep a form field and its control in step
    const bindText = (node, name) => { node.value = form[name] == null ? '' : form[name]; node.dataset.field = name; fieldEls[name] = node;
      node.addEventListener('input', () => { form[name] = node.value; update(); }); return node; };
    const bindCheck = (node, name) => { node.checked = !!form[name]; node.addEventListener('change', () => { form[name] = node.checked; update(); }); return node; };
    const errFor = (name) => { const s = el('div', { class: 'err', id: 'err-' + name, hidden: true }); errs[name] = s; return s; };
    const fieldBox = (label, control, name, extra) => {
      const cid = uid('f'); control.id = cid;
      return el('div', { class: 'field' }, el('label', { for: cid }, label), control, extra, errFor(name));
    };
    const counters = [];
    const counter = (name, max) => { const c = el('span', { class: 'counter' }); counters.push([c, name, max]); return c; };

    const preview = previewPanel(() => form);
    const flow = el('div', { class: 'flow', 'aria-label': 'What happens, in order' });
    const reqPre = el('pre');
    const banner = el('div', { 'aria-live': 'polite' });

    // -- 1. which post
    const scopeLocked = !!existing;
    const postGrid = el('div', { class: 'picker', role: 'group', 'aria-label': 'Your recent posts' });
    const postNote = el('p', { class: 'hint', 'aria-live': 'polite' });
    const urlInput = el('input', { class: 'input', type: 'url', placeholder: 'https://www.instagram.com/p/…', spellcheck: 'false', autocomplete: 'off' });
    const postBox = el('div', null,
      fieldBox('Paste a post link, or pick one below', urlInput, 'post', postNote), postGrid);
    function selectPost(p) {
      form.platformPostId = p.id;
      form.postTitle = MR.clip(p.message || `Post from ${when(p.createdTime)}`, 80);
      for (const b of postGrid.children) b.setAttribute('aria-pressed', String(b.dataset.id === p.id));
      update();
    }
    function drawPosts(posts) {
      const taken = new Map((S.automations || []).filter((a) => a.platformPostId && a.isActive !== false && (!existing || a.id !== existing.id))
        .map((a) => [a.platformPostId, (a.keywords || [])[0] || 'word']));
      postGrid.replaceChildren(...posts.map((p) => {
        const word = taken.get(p.id);
        return el('button', { class: 'pick', type: 'button', 'data-id': p.id, disabled: !!word, 'aria-pressed': String(form.platformPostId === p.id),
          title: word ? `This post already has the word ${word}` : (p.message || ''), onclick: () => selectPost(p) },
          safeImg(p.picture) ? el('img', { src: safeImg(p.picture), alt: '', loading: 'lazy', referrerpolicy: 'no-referrer' }) : el('div', { style: 'aspect-ratio:1;background:var(--line)' }),
          word && el('span', { class: 'chip' }, word),
          el('small', null, MR.clip(p.message || 'No caption', 48) + (p.createdTime ? ` · ${when(p.createdTime)}` : '')));
      }));
      if (S.postsError) postNote.textContent = `Could not load your posts. ${S.postsError} You can still choose “Any post”.`;
      else if (!posts.length) postNote.textContent = 'No posts found on this account yet. Choose “Any post” to work on every post.';
      else postNote.textContent = 'Showing your 25 most recent posts. For an older post, choose “Any post”.';
    }
    urlInput.addEventListener('input', () => {
      const v = urlInput.value.trim();
      if (!v) { postNote.textContent = 'Showing your 25 most recent posts. For an older post, choose “Any post”.'; return; }
      if (!MR.shortcodeFromUrl(v)) { postNote.textContent = 'That doesn’t look like an Instagram post link.'; return; }
      const hit = MR.findPostByUrl(S.posts || [], v);
      if (!hit) { postNote.textContent = 'That post isn’t in your 25 most recent. Pick one from the list, or choose “Any post”.'; return; }
      if ([...postGrid.children].find((b) => b.dataset.id === hit.id && b.disabled)) { postNote.textContent = 'That post already has a word. Edit or delete it first.'; return; }
      selectPost(hit);
      postNote.textContent = 'Found it. Selected below.';
      const b = [...postGrid.children].find((x) => x.dataset.id === hit.id); if (b) b.scrollIntoView({ block: 'nearest' });
    });
    const scope = el('div', { class: 'seg', role: 'radiogroup', 'aria-label': 'Which post' },
      [['post', 'One of my posts'], ['any', 'Any post']].map(([val, label]) => el('label', null,
        el('input', { type: 'radio', name: 'scope', value: val, checked: form.scope === val, disabled: scopeLocked,
          onchange: () => { form.scope = val; update(); } }), el('span', null, label))));
    const sec1 = el('fieldset', { class: 'panel section' }, el('legend', null, el('h3', null, 'Which post')),
      scopeLocked
        ? el('p', { class: 'hint', style: 'margin-top:0.5rem' }, form.scope === 'post' ? 'This word stays on its post. To move it, create a new word and delete this one.' : 'This word works on any of your posts.')
        : [scope, el('p', { class: 'hint', style: 'margin-top:0.6rem', id: 'scope-hint' })],
      !scopeLocked && postBox);

    // -- 2. the word
    const wordInput = bindText(el('input', { class: 'input keyword-input', placeholder: 'GUIDE', spellcheck: 'false', autocomplete: 'off', autocapitalize: 'characters' }), 'words');
    const matchSel = bindText(el('select', { class: 'select' }, [['', 'Recommended for this choice'], ['word', 'The word anywhere in a comment'], ['exact', 'Only when the comment is just the word']]
      .map(([v, t]) => el('option', { value: v }, t))), 'match');
    const sec2 = el('fieldset', { class: 'panel section' }, el('legend', null, el('h3', null, 'The word')),
      fieldBox('What people comment', wordInput, 'words', el('p', { class: 'hint' }, 'One word. Add alternatives with commas, like GUIDE, GUIA. Spelling slips are forgiven when the word can sit inside a comment.')),
      fieldBox('When it counts', matchSel, 'match', el('p', { class: 'hint', id: 'match-hint' })),
      el('label', { class: 'check' }, bindCheck(el('input', { type: 'checkbox' }), 'alsoDms'), el('span', null, 'Also send the link when someone DMs me the word')));

    // -- 3. the message
    const dmArea = bindText(el('textarea', { class: 'textarea', rows: 4 }), 'dmMessage');
    const linkUrl = bindText(el('input', { class: 'input', type: 'url', placeholder: 'https://', spellcheck: 'false', autocomplete: 'off' }), 'linkUrl');
    const linkLabel = bindText(el('input', { class: 'input', maxlength: 40 }), 'linkLabel');
    const link2Url = bindText(el('input', { class: 'input', type: 'url', placeholder: 'https://', spellcheck: 'false' }), 'link2Url');
    const link2Label = bindText(el('input', { class: 'input', maxlength: 40 }), 'link2Label');
    const delaySel = el('select', { class: 'select', onchange: (e) => { form.delay = Number(e.target.value); update(); } },
      MR.DELAYS.map(([v, t]) => el('option', { value: String(v), selected: Number(form.delay) === v }, t)));
    const sec3 = el('fieldset', { class: 'panel section' }, el('legend', null, el('h3', null, 'The message')),
      fieldBox('Message', dmArea, 'dmMessage', el('div', { class: 'counter-row' }, el('p', { class: 'hint' }, 'Use {{first_name}} to greet people by name.'), counter('dmMessage', MR.LIMITS.dm))),
      el('div', { class: 'row2' },
        fieldBox('Link people get', linkUrl, 'linkUrl'),
        fieldBox('Button name', linkLabel, 'linkLabel', counter('linkLabel', MR.LIMITS.button))),
      el('details', { class: 'advanced', open: !!(form.link2Url || form.link2Label) }, el('summary', null, 'Add a second button'),
        el('div', { class: 'row2' }, fieldBox('Second link', link2Url, 'link2Url'), fieldBox('Button name', link2Label, 'link2Label', counter('link2Label', MR.LIMITS.button)))),
      fieldBox('When to send it', delaySel, 'delay'));

    // -- 4. followers only
    const gateMsg = bindText(el('textarea', { class: 'textarea', rows: 5 }), 'gateMessage');
    const gateProfile = bindText(el('input', { class: 'input' }), 'gateProfileButton');
    const gateBtn = bindText(el('input', { class: 'input' }), 'gateButton');
    const gateRetry = bindText(el('textarea', { class: 'textarea', rows: 4 }), 'notFollowingMessage');
    const gateBox = el('div', null,
      fieldBox('Follow request', gateMsg, 'gateMessage', counter('gateMessage', MR.LIMITS.gate)),
      el('div', { class: 'row2 even' }, fieldBox('Button that opens your profile', gateProfile, 'gateProfileButton', counter('gateProfileButton', MR.LIMITS.gateButton)),
        fieldBox('Button they tap once following', gateBtn, 'gateButton', counter('gateButton', MR.LIMITS.gateButton))),
      el('details', { class: 'advanced' }, el('summary', null, 'What to say if they tap before following'), fieldBox('Message', gateRetry, 'notFollowingMessage')));
    const sec4 = el('fieldset', { class: 'panel section' }, el('legend', null, el('h3', null, 'Followers only')),
      el('label', { class: 'check' }, bindCheck(el('input', { type: 'checkbox' }), 'gate'),
        el('span', null, 'Ask people to follow before they get the link', el('small', null, 'Followers get the link straight away. Everyone else is asked to follow first, then taps a button to receive it.'))),
      gateBox);

    // -- 5. public reply
    const replyText = bindText(el('input', { class: 'input' }), 'replyText');
    const replyVar = bindText(el('textarea', { class: 'textarea', rows: 3 }), 'replyVariations');
    const replyBox = el('div', null,
      fieldBox('Reply', replyText, 'replyText', el('p', { class: 'hint' }, 'Use {{username}} to mention them.')),
      fieldBox('Other replies to rotate through', replyVar, 'replyVariations', el('p', { class: 'hint' }, 'One per line, up to four. Repeating the same reply can look like spam.')));
    const sec5 = el('fieldset', { class: 'panel section' }, el('legend', null, el('h3', null, 'Public reply')),
      el('label', { class: 'check' }, bindCheck(el('input', { type: 'checkbox' }), 'reply'), el('span', null, 'Reply under the comment', el('small', null, 'Tells people to check their DMs.'))),
      replyBox);

    const sec6 = el('details', { class: 'panel section reqview' }, el('summary', { style: 'cursor:pointer;font-weight:600' }, 'See exactly what will be sent to Zernio'), reqPre);

    const submitBtn = el('button', { class: 'btn primary', type: 'button', onclick: submit }, existing ? 'Save changes' : 'Create word');

    function update() {
      current = MR.buildAutomation(form, S.account);
      flow.replaceChildren(...MR.flowSteps(form).map((s) => el('div', { class: 'step' + (s.on ? '' : ' off') }, el('b', null, s.title), el('span', null, s.note))));
      preview.update();
      postBox.hidden = form.scope !== 'post';
      const hint = document.getElementById('scope-hint');
      if (hint) hint.textContent = form.scope === 'post' ? 'Only comments on this post count. One word per post.' : 'The word works on every post you make, now and later. Use it for a word you repeat.';
      const mh = document.getElementById('match-hint');
      if (mh) mh.textContent = `Right now: ${MR.matchModeFor(form) === 'exact' ? 'the comment must be only the word' : 'the word can sit inside a longer comment'}.`;
      gateBox.hidden = !form.gate; replyBox.hidden = !form.reply;
      for (const [c, name, max] of counters) { const n = String(form[name] || '').trim().length; c.textContent = `${n}/${max}`; c.classList.toggle('over', n > max); }
      for (const [name, node] of Object.entries(errs)) {
        const msg = current.errors[name];
        const live = name === 'words' && String(form.words).trim() && msg;
        const show = !!msg && (showErrors || live);
        node.textContent = show ? msg : ''; node.hidden = !show;
        const ctl = fieldEls[name]; if (ctl) { ctl.setAttribute('aria-invalid', String(show)); if (show) ctl.setAttribute('aria-describedby', 'err-' + name); else ctl.removeAttribute('aria-describedby'); }
      }
      reqPre.textContent = JSON.stringify(existing ? MR.toPatch(current.body) : current.body, null, 2);
    }

    async function submit() {
      showErrors = true; update(); banner.replaceChildren();
      if (Object.keys(current.errors).length) {
        banner.replaceChildren(el('div', { class: 'notice error' }, 'Fix the highlighted fields, then try again.'));
        const first = document.querySelector('[aria-invalid="true"]') || document.querySelector('.err:not([hidden])');
        if (first) first.scrollIntoView({ block: 'center', behavior: reduceMotion ? 'auto' : 'smooth' });
        if (first && first.focus) first.focus({ preventScroll: true });
        return;
      }
      submitBtn.disabled = true; submitBtn.textContent = existing ? 'Saving…' : 'Creating…';
      try {
        if (existing) {
          await S.client.update(existing.id, MR.toPatch(current.body));
          S.automations = null; toast('Saved'); go('#/');
        } else {
          await S.client.create(current.body);
          S.automations = null;
          showDone(current.body);
        }
      } catch (e) {
        submitBtn.disabled = false; submitBtn.textContent = existing ? 'Save changes' : 'Create word';
        banner.replaceChildren(el('div', { class: 'notice error' }, e.message || String(e)));
        banner.scrollIntoView({ block: 'center' });
      }
    }

    function showDone(body) {
      const word = body.keywords[0];
      const line = `Comment ${word} and I'll send you the link.`;
      shell(el('div', { class: 'panel done', style: 'max-width:42rem' },
        el('h2', null, `“${word}” is live`),
        el('p', { style: 'color:var(--muted)' }, 'Add this line to your post, then test it: comment the word from another account.'),
        el('div', { class: 'copyline' }, el('code', null, line),
          el('button', { class: 'btn', type: 'button', onclick: async () => {
            try { await navigator.clipboard.writeText(line); toast('Copied'); } catch (e) { toast('Select the line and copy it'); }
          } }, 'Copy line')),
        body.followGate && el('p', { class: 'hint', style: 'margin-top:1rem' }, 'People who don’t follow you yet are asked to follow first.'),
        el('div', { class: 'actions', style: 'margin-top:1.4rem' },
          el('a', { class: 'btn primary', href: '#/' }, 'Back to your words'), el('a', { class: 'btn', href: '#/new', onclick: () => setTimeout(render, 0) }, 'Add another word'))), true);
    }

    shell(el('div', null,
      el('div', { class: 'crumbs' }, el('a', { class: 'btn quiet small', href: '#/' }, '← Your words')),
      el('h2', null, existing ? `Edit ${(existing.keywords || [])[0] || 'word'}` : 'New word'),
      flow,
      el('div', { class: 'editor' },
        el('form', { class: 'editor-main', onsubmit: (e) => e.preventDefault(), novalidate: true }, sec1, sec2, sec3, sec4, sec5, sec6,
          el('div', { class: 'bar' }, submitBtn, el('a', { class: 'btn quiet', href: '#/' }, 'Cancel')), banner),
        el('aside', { class: 'editor-side' }, el('h3', { style: 'margin-bottom:0.7rem' }, 'What people see'), preview.node,
          el('p', { class: 'hint', style: 'margin-top:0.8rem;text-align:center' }, 'A sample commenter, Alex. Each person sees their own name.')))), true);
    update();
    if (!scopeLocked) loadPosts().then((posts) => { if (id === renderId) { drawPosts(posts); update(); } });
    else if (form.scope === 'post') loadPosts();
    wordInput.focus({ preventScroll: true });
  }

  function connectErrorToHome(e) {
    root.querySelector('.page') && root.querySelector('.page').replaceChildren(el('div', { class: 'empty' }, el('h3', null, 'Could not load your words'), el('p', null, e.message),
      el('a', { class: 'btn', href: '#/' }, 'Back')));
  }

  // ---------------------------------------------------------------- routing

  function render() {
    const id = ++renderId;
    const h = location.hash || '#/';
    if (!S.client) return connectView();
    if (h === '#/new') return editorView(null, id);
    const m = h.match(/^#\/edit\/(.+)$/);
    if (m) return editorView(decodeURIComponent(m[1]), id);
    return homeView(id);
  }
  window.addEventListener('hashchange', render);

  async function boot() {
    const key = keep.load();
    if (!key) return render();
    root.replaceChildren(el('p', { class: 'boot' }, 'Connecting to Zernio…'));
    try {
      const client = MR.createClient(key);
      const accounts = await client.accounts();
      if (!accounts.length) throw new Error('This key works, but no Instagram account is connected in Zernio yet.');
      S.client = client; S.accounts = accounts;
      S.account = accounts.find((a) => a._id === keep.account()) || accounts[0];
      render();
    } catch (e) {
      if (e.status === 401) keep.clear();
      connectView(e.message);
    }
  }
  boot();
})();
