// Run: node --test tests/inbox.test.mjs   (the pure helpers behind the inbox)
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const I = createRequire(import.meta.url)('../docs/inbox.js');

const H = 3600000, now = Date.parse('2026-11-17T12:00:00Z');

test('ago', () => {
  assert.equal(I.ago(new Date(now - 20000).toISOString(), now), 'now');
  assert.equal(I.ago(new Date(now - 5 * 60000).toISOString(), now), '5m');
  assert.equal(I.ago(new Date(now - 3 * H).toISOString(), now), '3h');
  assert.equal(I.ago(new Date(now - 49 * H).toISOString(), now), '2d');
  assert.equal(I.ago('nonsense', now), '');
});

test('conversations sort newest first', () => {
  const l = I.sortConvos([{ id: 'a', updatedTime: '2026-11-01T00:00:00Z' }, { id: 'b', updatedTime: '2026-11-10T00:00:00Z' }, { id: 'c' }]);
  assert.deepEqual(l.map((c) => c.id), ['b', 'a', 'c']);
});

test('the 24 hour window follows their last message', () => {
  const m = (dir, h) => ({ direction: dir, createdAt: new Date(now - h * H).toISOString() });
  assert.equal(I.windowOpen([m('incoming', 30), m('incoming', 2), m('outgoing', 1)], now), true);
  assert.equal(I.windowOpen([m('incoming', 25), m('outgoing', 1)], now), false);
  assert.equal(I.windowOpen([m('outgoing', 1)], now), false);
  assert.equal(I.windowOpen([], now), false);
});

test('tags are tidied, counted and used to filter', () => {
  assert.equal(I.normalizeTag('  Hot Lead! '), 'hot-lead');
  assert.equal(I.normalizeTag(''), '');
  const contacts = { u1: { tags: ['lead', 'vip'] }, u2: { tags: ['lead'] }, u3: { tags: [] } };
  assert.deepEqual(I.allTags(contacts), [{ tag: 'lead', n: 2 }, { tag: 'vip', n: 1 }]);
  const list = [{ participantId: 'u1', unreadCount: 0 }, { participantId: 'u2', unreadCount: 2 }, { participantId: 'u3', unreadCount: 1 }];
  assert.equal(I.filterConvos(list, contacts, 'lead', false).length, 2);
  assert.equal(I.filterConvos(list, contacts, 'lead', true).length, 1);
  assert.equal(I.filterConvos(list, contacts, '', true).length, 2);
  assert.equal(I.filterConvos(list, contacts, '', false).length, 3);
});

test('message text falls back to what the message was', () => {
  assert.equal(I.messageText({ message: 'hi' }), 'hi');
  assert.equal(I.messageText({ storyReply: { storyId: '1' } }), 'Replied to your story');
  assert.equal(I.messageText({ isStoryMention: true }), 'Mentioned you in a story');
  assert.equal(I.messageText({ attachments: [{ type: 'image' }] }), '[image]');
  assert.equal(I.messageText({ isDeleted: true, message: 'x' }), '(deleted message)');
  assert.equal(I.messageText({}), '(no text)');
});
