// Run: node --test tests     (no keys, no network: Zernio is replaced by a fake)
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const MR = createRequire(import.meta.url)('../docs/lib.js');
const account = { _id: 'acc1', profileId: 'prof1', platform: 'instagram', username: 'demo' };
const filled = (over = {}) => ({ ...MR.defaults(account), words: 'guide', linkUrl: 'https://example.com/guide', ...over });

test('a post link is matched to the posts Zernio lists, by its code', () => {
  assert.equal(MR.shortcodeFromUrl('https://www.instagram.com/p/DAbC-_123/?igsh=xyz'), 'DAbC-_123');
  assert.equal(MR.shortcodeFromUrl('https://instagram.com/reel/Xy9/'), 'Xy9');
  assert.equal(MR.shortcodeFromUrl('https://www.instagram.com/someone/p/Q1/'), 'Q1');
  assert.equal(MR.shortcodeFromUrl('https://example.com/p/abc'), null);
  assert.equal(MR.shortcodeFromUrl(''), null);
  const posts = [{ id: '111', permalink: 'https://www.instagram.com/p/AAA/' }, { id: '222', permalink: 'https://www.instagram.com/reel/BBB/' }];
  assert.equal(MR.findPostByUrl(posts, 'https://instagram.com/reel/BBB/?x=1').id, '222');
  assert.equal(MR.findPostByUrl(posts, 'https://instagram.com/p/aaa/'), null, 'codes are case-sensitive');
  assert.equal(MR.findPostByUrl(posts, 'https://instagram.com/p/ZZZ/'), null);
});

test('words are tidied, and bad ones explained', () => {
  assert.deepEqual(MR.normalizeWords(' guide, “Guide”,\nfree , '), ['GUIDE', 'FREE']);
  assert.equal(MR.checkWord('GUIDE'), '');
  assert.equal(MR.checkWord('GUIDE2'), '');
  assert.match(MR.checkWord('MY GUIDE'), /one word/);
  assert.match(MR.checkWord('A'), /2 to 24/);
  assert.match(MR.checkWord('X'.repeat(25)), /2 to 24/);
  assert.equal(MR.checkWord('GUÍA'), '', 'accented letters are fine');
});

test('one post: the request matches what Zernio documents', () => {
  const { errors, body } = MR.buildAutomation(filled({ platformPostId: '17912345678901234', postTitle: 'My new guide' }), account);
  assert.deepEqual(errors, {});
  assert.equal(body.profileId, 'prof1');
  assert.equal(body.accountId, 'acc1');
  assert.deepEqual(body.keywords, ['GUIDE']);
  assert.equal(body.platformPostId, '17912345678901234');
  assert.equal(body.postId, undefined, 'postId is for posts Zernio has not published yet; an existing post uses platformPostId');
  assert.equal(body.matchMode, 'word');
  assert.equal(body.typoTolerance, true);
  assert.equal(body.alsoMatchInDms, true);
  assert.deepEqual(body.buttons, [{ type: 'url', title: 'Open the link', url: 'https://example.com/guide' }]);
  assert.deepEqual(body.audience, { followerStatus: 'follower', whenUnknown: 'verify' });
  assert.ok(body.followGate.message && body.followGate.buttonLabel && body.followGate.profileButtonLabel);
  assert.equal(body.publicReplyPolicy, 'always');
  assert.equal(body.commentReply, '@{{username}} Sent to your DMs 📩');
  assert.equal(body.linkTracking, true);
  assert.equal(body.dmDelaySeconds, undefined, 'no delay: the field is left out');
});

test('any post: whole-comment matching, no post id, no typo tolerance', () => {
  const { errors, body } = MR.buildAutomation(filled({ scope: 'any' }), account);
  assert.deepEqual(errors, {});
  assert.equal(body.platformPostId, undefined);
  assert.equal(body.matchMode, 'exact');
  assert.equal(body.typoTolerance, undefined, 'typo tolerance is only valid with matchMode word');
  assert.match(body.name, /any post/);
  assert.equal(MR.buildAutomation(filled({ scope: 'any', match: 'word' }), account).body.matchMode, 'word', 'the person can override it');
});

test('the limits Zernio documents are enforced before anything is sent', () => {
  const bad = (over) => MR.buildAutomation(filled({ platformPostId: '1', ...over }), account).errors;
  assert.ok(bad({ scope: 'post', platformPostId: '' }).post);
  assert.ok(bad({ words: '' }).words);
  assert.ok(bad({ words: 'two words' }).words);
  assert.ok(bad({ dmMessage: '' }).dmMessage);
  assert.match(bad({ dmMessage: 'x'.repeat(641) }).dmMessage, /640/);
  assert.equal(bad({ dmMessage: 'x'.repeat(640) }).dmMessage, undefined);
  assert.ok(bad({ linkUrl: 'http://example.com' }).linkUrl, 'links must be https');
  assert.ok(bad({ linkUrl: 'not a link' }).linkUrl);
  assert.ok(bad({ linkLabel: 'x'.repeat(21) }).linkLabel, 'button names are 20 characters at most');
  assert.equal(bad({ linkLabel: 'x'.repeat(20) }).linkLabel, undefined);
  assert.ok(bad({ link2Url: 'https://b.com' }).link2Label, 'a second button needs a name');
  assert.ok(bad({ link2Label: 'More' }).link2Url, 'and a link');
  assert.ok(bad({ gateButton: 'x'.repeat(21) }).gateButton);
  assert.ok(bad({ gateProfileButton: '' }).gateProfileButton);
  assert.ok(bad({ gateMessage: 'x'.repeat(641) }).gateMessage);
  assert.ok(bad({ notFollowingMessage: 'x'.repeat(1001) }).notFollowingMessage);
  assert.ok(bad({ replyText: '  ' }).replyText);
  assert.ok(bad({ replyVariations: 'a\nb\nc\nd\ne' }).replyVariations, 'up to 5 replies in all');
  assert.ok(bad({ delay: 99999 }).delay);
  assert.equal(MR.buildAutomation(filled({ platformPostId: '1' }), null).errors.account.length > 0, true);
});

test('options switch parts of the flow off', () => {
  const { body } = MR.buildAutomation(filled({ platformPostId: '1', gate: false, reply: false, delay: 60, alsoDms: false, link2Url: 'https://b.com', link2Label: 'More' }), account);
  assert.deepEqual(body.audience, { followerStatus: 'any' });
  assert.equal(body.followGate, undefined);
  assert.equal(body.commentReply, undefined);
  assert.equal(body.publicReplyPolicy, undefined);
  assert.equal(body.dmDelaySeconds, 60);
  assert.equal(body.alsoMatchInDms, false);
  assert.equal(body.buttons.length, 2);
});

test('an edit never moves a word to another post', () => {
  const { body } = MR.buildAutomation(filled({ platformPostId: '9', postTitle: 't' }), account);
  const patch = MR.toPatch(body);
  for (const k of ['profileId', 'accountId', 'platformPostId', 'postTitle']) assert.equal(patch[k], undefined);
  assert.deepEqual(patch.keywords, ['GUIDE']);
});

test('a word made here loads back into the form unchanged', () => {
  const form = filled({ platformPostId: '17', postTitle: 'Title', link2Url: 'https://b.com', link2Label: 'More', delay: 30, gate: true });
  const { body } = MR.buildAutomation(form, account);
  const back = MR.fromAutomation({ ...body, id: 'a1', isActive: true }, account);
  assert.deepEqual(MR.buildAutomation(back, account).body, body);
  assert.equal(MR.isEditable({ ...body }), true);
  assert.equal(MR.isEditable({ ...body, trigger: 'story_reply' }), false, 'story automations are left alone');
  assert.equal(MR.isEditable({ ...body, template: { x: 1 } }), false);
  assert.equal(MR.isEditable({ ...body, buttons: [{ type: 'postback', title: 't', payload: 'p' }] }), false);
});

test('what people see: names filled in, unknown fields blanked', () => {
  assert.equal(MR.personalize('Hi {{first_name}} / @{{username}} / {{name}} / {{nope}}!'), 'Hi Alex / @alex.rivera / Alex Rivera / !');
  const m = MR.previewModel(filled({ platformPostId: '1' }), account);
  assert.equal(m.word, 'GUIDE');
  assert.equal(m.reply, '@alex.rivera Sent to your DMs 📩');
  assert.match(m.dm.text, /Here you go Alex/);
  assert.deepEqual(m.gate.buttons, ['Follow me 👉', "I'm following ✅"]);
  assert.equal(MR.previewModel(filled({ gate: false }), account).gate, null);
  assert.equal(MR.previewModel(filled({ reply: false }), account).reply, '');
});

test('the flow strip shows what is on', () => {
  const steps = MR.flowSteps(filled({ gate: false, delay: 300 }));
  assert.deepEqual(steps.map((s) => [s.id, s.on]), [['comment', true], ['reply', true], ['check', false], ['dm', true]]);
  assert.equal(steps[0].title, 'Comment GUIDE');
  assert.equal(steps[3].note, 'After 5 minutes');
});

test('stats are read safely', () => {
  assert.deepEqual(MR.statsOf({}), { comments: 0, dms: 0, clicks: 0, followed: 0 });
  assert.deepEqual(MR.statsOf({ stats: { triggered: 5, dmsSent: 4, linkClicks: 3, followGatePassed: 2 } }), { comments: 5, dms: 4, clicks: 3, followed: 2 });
});

// ---- the client: what is sent, and how failures are explained
function fakeFetch(handler) {
  const calls = [];
  const fn = async (url, init) => {
    calls.push({ url, init });
    const { status = 200, json } = handler(url, init) || {};
    const text = json === undefined ? '' : JSON.stringify(json);
    return { ok: status >= 200 && status < 300, status, text: async () => text };
  };
  fn.calls = calls;
  return fn;
}

test('the key goes only in the Authorization header, to zernio.com, and no cookies are sent', async () => {
  const f = fakeFetch(() => ({ json: { accounts: [{ _id: '1', platform: 'instagram' }, { _id: '2', platform: 'tiktok' }] } }));
  const accounts = await MR.createClient('KEY-123', f).accounts();
  assert.deepEqual(accounts.map((a) => a._id), ['1'], 'only Instagram accounts');
  const { url, init } = f.calls[0];
  assert.equal(url, 'https://zernio.com/api/v1/accounts');
  assert.equal(init.headers.Authorization, 'Bearer KEY-123');
  assert.ok(!url.includes('KEY-123'));
  assert.equal(init.credentials, 'omit');
  assert.equal(init.headers['Content-Type'], undefined, 'a plain GET stays a simple request');
});

test('each call goes where Zernio documents it', async () => {
  const f = fakeFetch((url, init) => ({ json: { automation: { id: 'a1' }, automations: [], posts: [] } }));
  const c = MR.createClient('K', f);
  await c.posts('acc/1');
  await c.automations('prof1');
  await c.create({ name: 'n' });
  await c.update('a1', { isActive: false });
  await c.remove('a1');
  assert.deepEqual(f.calls.map((x) => [x.init.method, x.url.replace('https://zernio.com/api/v1', '')]), [
    ['GET', '/accounts/acc%2F1/posts'], ['GET', '/comment-automations?profileId=prof1'], ['POST', '/comment-automations'],
    ['PATCH', '/comment-automations/a1'], ['DELETE', '/comment-automations/a1']]);
  assert.equal(f.calls[2].init.body, '{"name":"n"}');
});

test('failures say what happened and what to do, with Zernio\'s own words kept', async () => {
  const fail = async (status, json) => MR.createClient('K', fakeFetch(() => ({ status, json }))).create({}).catch((e) => e);
  const e401 = await fail(401, { error: 'bad key', code: 'invalid_credentials' });
  assert.equal(e401.status, 401);
  assert.match(e401.message, /did not accept this API key/);
  assert.match(e401.message, /bad key/);
  assert.match((await fail(409, { error: 'exists' })).message, /already has a word/);
  assert.match((await fail(400, { error: 'dmMessage too long' })).message, /dmMessage too long/);
  assert.match((await fail(401, { code: 'TOKEN_EXPIRED' })).message, /reconnected/);
  assert.match((await fail(503, {})).message, /temporarily unavailable/);
  assert.match((await fail(429, {})).message, /limiting/);
  const down = await MR.createClient('K', async () => { throw new TypeError('Failed to fetch'); }).accounts().catch((e) => e);
  assert.equal(down.code, 'network');
  assert.match(down.message, /Could not reach Zernio/);
});
