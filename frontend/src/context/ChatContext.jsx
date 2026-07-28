import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useAuth } from './AuthContext';
import { ApiError, apiJson } from '../lib/api';
import {
  clearStoredChatSession,
  normalizeSessionId,
  readStoredChatSession,
  storeChatSession,
} from '../lib/chatSession';

const ChatContext = createContext(null);

export const DEFAULT_DISTRICT = 'Tất cả';

const createWelcomeMessages = () => ([
  {
    clientId: 'welcome',
    role: 'assistant',
    content: 'Xin chào! Tớ là trợ lý ẩm thực Hà Nội. Bạn đang tìm món ăn hoặc quán ở khu vực nào?',
  },
]);

const normalizeHistoryMessages = (payload) => {
  const records = Array.isArray(payload) ? payload : payload?.messages || [];

  return records.flatMap((record) => {
    if (
      (record?.role === 'user' || record?.role === 'assistant')
      && typeof record.content === 'string'
    ) {
      return [{
        id: record.id,
        turn_id: record.turn_id,
        position: record.position,
        role: record.role,
        content: record.content,
        status: ['pending', 'completed', 'error'].includes(record.status)
          ? record.status
          : 'completed',
        district_filter: record.district_filter ?? null,
        created_at: record.created_at,
      }];
    }

    const legacyMessages = [];
    if (typeof record?.question === 'string') {
      legacyMessages.push({
        id: `${record.id}-user`,
        role: 'user',
        content: record.question,
        status: 'completed',
      });
    }
    if (typeof record?.answer === 'string') {
      legacyMessages.push({
        id: `${record.id}-assistant`,
        role: 'assistant',
        content: record.answer,
        status: 'completed',
      });
    }
    return legacyMessages;
  });
};

export const ChatProvider = ({ children }) => {
  const { user, markUnauthenticated } = useAuth();
  const initialSessionId = useMemo(
    () => readStoredChatSession(user),
    [user],
  );

  const [messages, setMessages] = useState(createWelcomeMessages);
  const [input, setInput] = useState('');
  const [district, setDistrict] = useState(DEFAULT_DISTRICT);
  const [sessionId, setSessionIdState] = useState(initialSessionId);
  const [isLoading, setIsLoading] = useState(false);
  const [isRestoring, setIsRestoring] = useState(false);
  const [restoreError, setRestoreError] = useState('');

  const activeRequestRef = useRef(null);
  const sessionIdRef = useRef(initialSessionId);
  const restoreRequestIdRef = useRef(0);

  useEffect(() => () => {
    restoreRequestIdRef.current += 1;
    activeRequestRef.current?.abort();
  }, []);

  const setSessionId = useCallback((value) => {
    const normalized = normalizeSessionId(value);
    sessionIdRef.current = normalized;
    setSessionIdState(normalized);

    if (normalized) {
      storeChatSession(user, normalized);
    } else {
      clearStoredChatSession();
    }

    return normalized;
  }, [user]);

  const clearChat = useCallback(({ abortRequest = true } = {}) => {
    restoreRequestIdRef.current += 1;
    if (abortRequest) activeRequestRef.current?.abort();
    activeRequestRef.current = null;
    sessionIdRef.current = null;
    clearStoredChatSession();

    setSessionIdState(null);
    setMessages(createWelcomeMessages());
    setInput('');
    setDistrict(DEFAULT_DISTRICT);
    setIsLoading(false);
    setIsRestoring(false);
    setRestoreError('');
  }, []);

  const clearSessionIfActive = useCallback((value) => {
    const normalized = normalizeSessionId(value);
    if (normalized && normalized === sessionIdRef.current) {
      clearChat();
      return true;
    }
    return false;
  }, [clearChat]);

  const restoreSession = useCallback(async ({ signal } = {}) => {
    const targetSessionId = sessionIdRef.current;
    if (!targetSessionId) {
      setRestoreError('');
      return false;
    }

    const requestId = ++restoreRequestIdRef.current;
    setIsRestoring(true);
    setRestoreError('');

    try {
      const payload = await apiJson(`/api/history/${targetSessionId}`, { signal });
      if (
        requestId !== restoreRequestIdRef.current
        || targetSessionId !== sessionIdRef.current
      ) {
        return false;
      }

      const restoredMessages = normalizeHistoryMessages(payload);
      setMessages(
        restoredMessages.length > 0
          ? restoredMessages
          : createWelcomeMessages(),
      );
      return true;
    } catch (error) {
      if (error.name === 'AbortError' || requestId !== restoreRequestIdRef.current) {
        return false;
      }

      if (error instanceof ApiError && error.status === 401) {
        clearChat();
        markUnauthenticated();
        return false;
      }

      if (error instanceof ApiError && error.status === 404) {
        clearChat();
        return false;
      }

      setRestoreError(
        error instanceof ApiError
          ? error.message
          : 'Không thể khôi phục cuộc trò chuyện. Vui lòng thử lại.',
      );
      return false;
    } finally {
      if (requestId === restoreRequestIdRef.current) {
        setIsRestoring(false);
      }
    }
  }, [clearChat, markUnauthenticated]);

  const value = useMemo(() => ({
    messages,
    setMessages,
    input,
    setInput,
    district,
    setDistrict,
    sessionId,
    setSessionId,
    isLoading,
    setIsLoading,
    isRestoring,
    restoreError,
    restoreSession,
    clearChat,
    clearSessionIfActive,
    activeRequestRef,
  }), [
    messages,
    input,
    district,
    sessionId,
    setSessionId,
    isLoading,
    isRestoring,
    restoreError,
    restoreSession,
    clearChat,
    clearSessionIfActive,
  ]);

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
};

export const useChat = () => {
  const context = useContext(ChatContext);
  if (!context) {
    throw new Error('useChat phải được dùng bên trong ChatProvider.');
  }
  return context;
};
