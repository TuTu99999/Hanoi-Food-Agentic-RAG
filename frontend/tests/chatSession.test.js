import assert from 'node:assert/strict';
import test from 'node:test';

import {
  clearStoredChatSession,
  normalizeSessionId,
  readStoredChatSession,
  storeChatSession,
} from '../src/lib/chatSession.js';


const createSessionStorage = () => {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  };
};


test.beforeEach(() => {
  globalThis.window = {
    sessionStorage: createSessionStorage(),
  };
});


test.afterEach(() => {
  delete globalThis.window;
});


test('normalizeSessionId accepts only positive safe integers', () => {
  assert.equal(normalizeSessionId(12), 12);
  assert.equal(normalizeSessionId(' 12 '), 12);
  assert.equal(normalizeSessionId(0), null);
  assert.equal(normalizeSessionId('-1'), null);
  assert.equal(normalizeSessionId('12.5'), null);
  assert.equal(normalizeSessionId('not-an-id'), null);
});


test('stored chat session is isolated by user', () => {
  const alice = { id: 1, username: 'alice' };
  const bob = { id: 2, username: 'bob' };

  assert.equal(storeChatSession(alice, 42), 42);
  assert.equal(readStoredChatSession(alice), 42);
  assert.equal(readStoredChatSession(bob), null);
  assert.equal(readStoredChatSession(alice), null);
});


test('clearStoredChatSession removes the current value', () => {
  const user = { id: 1, username: 'alice' };

  storeChatSession(user, 99);
  clearStoredChatSession();

  assert.equal(readStoredChatSession(user), null);
});
