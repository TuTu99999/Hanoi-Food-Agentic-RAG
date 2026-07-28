const CHAT_SESSION_STORAGE_KEY = 'hanoi-rag:active-chat:v1';

export const normalizeSessionId = (value) => {
  if (
    typeof value !== 'number'
    && !(typeof value === 'string' && /^\d+$/.test(value.trim()))
  ) {
    return null;
  }

  const sessionId = Number(value);
  return Number.isSafeInteger(sessionId) && sessionId > 0 ? sessionId : null;
};

const getOwnerId = (user) => {
  const username = typeof user?.username === 'string'
    ? user.username.trim()
    : '';

  if (username) return `username:${username}`;

  if (Number.isSafeInteger(Number(user?.id)) && Number(user.id) > 0) {
    return `id:${Number(user.id)}`;
  }

  return null;
};

const getStorage = () => {
  try {
    return typeof window !== 'undefined' ? window.sessionStorage : null;
  } catch {
    return null;
  }
};

export const readStoredChatSession = (user) => {
  const storage = getStorage();
  const owner = getOwnerId(user);
  if (!storage || !owner) return null;

  try {
    const stored = JSON.parse(storage.getItem(CHAT_SESSION_STORAGE_KEY));
    const sessionId = normalizeSessionId(stored?.sessionId);

    if (stored?.owner !== owner || !sessionId) {
      storage.removeItem(CHAT_SESSION_STORAGE_KEY);
      return null;
    }

    return sessionId;
  } catch {
    clearStoredChatSession();
    return null;
  }
};

export const storeChatSession = (user, value) => {
  const storage = getStorage();
  const owner = getOwnerId(user);
  const sessionId = normalizeSessionId(value);

  if (!storage || !owner || !sessionId) return null;

  try {
    storage.setItem(
      CHAT_SESSION_STORAGE_KEY,
      JSON.stringify({ owner, sessionId }),
    );
  } catch {
    // Continue with in-memory state when browser storage is unavailable.
  }

  return sessionId;
};

export const clearStoredChatSession = () => {
  const storage = getStorage();
  if (!storage) return;

  try {
    storage.removeItem(CHAT_SESSION_STORAGE_KEY);
  } catch {
    // Storage cleanup is best-effort.
  }
};
