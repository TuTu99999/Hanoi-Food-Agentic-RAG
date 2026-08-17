import React, { useEffect, useRef, useState } from 'react';
import { MessageSquare, Calendar, Trash2, Loader2, MessageCircle } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useChat } from '../context/ChatContext';
import { ApiError, apiJson } from '../lib/api';
import { AssistantMarkdown } from '../components/ChatMessage';

const SESSION_PAGE_SIZE = 20;
const MESSAGE_PAGE_SIZE = 100;

const getSessions = (payload) => (
  Array.isArray(payload) ? payload : payload?.sessions || []
);

const normalizeMessages = (payload) => {
  const records = Array.isArray(payload) ? payload : payload?.messages || [];

  return records.flatMap((record) => {
    if (record?.role && record.content !== undefined && record.content !== null) {
      return [record];
    }

    // Tương thích dữ liệu cũ trong lúc database/backend được nâng cấp.
    const legacyMessages = [];
    if (record?.question !== undefined && record.question !== null) {
      legacyMessages.push({
        ...record,
        id: `${record.id}-user`,
        role: 'user',
        content: record.question,
      });
    }
    if (record?.answer !== undefined && record.answer !== null) {
      legacyMessages.push({
        ...record,
        id: `${record.id}-assistant`,
        role: 'assistant',
        content: record.answer,
      });
    }
    return legacyMessages;
  });
};

export const History = () => {
  const [sessions, setSessions] = useState([]);
  const [selectedSessionId, setSelectedSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [loadingMoreSessions, setLoadingMoreSessions] = useState(false);
  const [loadingOlderMessages, setLoadingOlderMessages] = useState(false);
  const [hasMoreSessions, setHasMoreSessions] = useState(false);
  const [hasMoreMessages, setHasMoreMessages] = useState(false);
  const [deletingSessionId, setDeletingSessionId] = useState(null);
  const [error, setError] = useState('');
  const [detailError, setDetailError] = useState('');
  const [olderMessagesError, setOlderMessagesError] = useState('');
  const detailAbortRef = useRef(null);
  const { markUnauthenticated } = useAuth();
  const { clearSessionIfActive } = useChat();

  const handleRequestError = (requestError, setErrorMessage) => {
    if (requestError instanceof ApiError && requestError.status === 401) {
      markUnauthenticated();
      return;
    }

    setErrorMessage(requestError.message || 'Không thể kết nối máy chủ.');
  };

  useEffect(() => {
    const controller = new AbortController();

    const fetchSessions = async () => {
      setLoading(true);
      setError('');

      try {
        const payload = await apiJson(
          `/api/history?limit=${SESSION_PAGE_SIZE}`,
          { signal: controller.signal },
        );
        const records = getSessions(payload);
        setSessions(records);
        setHasMoreSessions(records.length === SESSION_PAGE_SIZE);
      } catch (requestError) {
        if (requestError.name !== 'AbortError') {
          handleRequestError(requestError, setError);
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };

    fetchSessions();
    return () => controller.abort();
  }, [markUnauthenticated]);

  useEffect(() => () => {
    detailAbortRef.current?.abort();
  }, []);

  const handleLoadMoreSessions = async () => {
    const cursor = sessions.at(-1)?.id;
    if (!cursor || loadingMoreSessions) return;

    setLoadingMoreSessions(true);
    setError('');

    try {
      const payload = await apiJson(
        `/api/history?limit=${SESSION_PAGE_SIZE}&cursor=${cursor}`,
      );
      const records = getSessions(payload);
      setSessions(previous => {
        const existingIds = new Set(previous.map(session => session.id));
        return [
          ...previous,
          ...records.filter(session => !existingIds.has(session.id)),
        ];
      });
      setHasMoreSessions(records.length === SESSION_PAGE_SIZE);
    } catch (requestError) {
      handleRequestError(requestError, setError);
    } finally {
      setLoadingMoreSessions(false);
    }
  };

  const handleSelectSession = async (sessionId) => {
    detailAbortRef.current?.abort();
    const controller = new AbortController();
    detailAbortRef.current = controller;

    setSelectedSessionId(sessionId);
    setMessages([]);
    setHasMoreMessages(false);
    setDetailError('');
    setOlderMessagesError('');
    setLoadingMessages(true);
    setLoadingOlderMessages(false);

    try {
      const payload = await apiJson(
        `/api/history/${sessionId}?limit=${MESSAGE_PAGE_SIZE}`,
        {
        signal: controller.signal,
        },
      );

      if (detailAbortRef.current === controller) {
        const records = normalizeMessages(payload);
        setMessages(records);
        setHasMoreMessages(records.length === MESSAGE_PAGE_SIZE);
      }
    } catch (requestError) {
      if (requestError.name !== 'AbortError' && detailAbortRef.current === controller) {
        handleRequestError(requestError, setDetailError);
      }
    } finally {
      if (detailAbortRef.current === controller) {
        detailAbortRef.current = null;
        setLoadingMessages(false);
      }
    }
  };

  const handleLoadOlderMessages = async () => {
    const cursor = messages[0]?.position;
    if (
      !selectedSessionId
      || cursor === undefined
      || cursor === null
      || loadingOlderMessages
    ) {
      return;
    }

    const sessionId = selectedSessionId;
    const controller = new AbortController();
    detailAbortRef.current = controller;
    setLoadingOlderMessages(true);
    setOlderMessagesError('');

    try {
      const payload = await apiJson(
        `/api/history/${sessionId}?limit=${MESSAGE_PAGE_SIZE}&cursor=${cursor}`,
        { signal: controller.signal },
      );
      const records = normalizeMessages(payload);
      if (detailAbortRef.current === controller) {
        setMessages(previous => [...records, ...previous]);
        setHasMoreMessages(records.length === MESSAGE_PAGE_SIZE);
      }
    } catch (requestError) {
      if (
        requestError.name !== 'AbortError'
        && detailAbortRef.current === controller
      ) {
        handleRequestError(requestError, setOlderMessagesError);
      }
    } finally {
      if (detailAbortRef.current === controller) {
        detailAbortRef.current = null;
        setLoadingOlderMessages(false);
      }
    }
  };

  const handleDeleteSession = async (event, sessionId) => {
    event.stopPropagation();
    if (!window.confirm('Bạn có chắc chắn muốn xóa phiên hội thoại này?')) return;

    setDeletingSessionId(sessionId);
    setError('');

    try {
      await apiJson(`/api/history/${sessionId}`, { method: 'DELETE' });
      setSessions(previous => previous.filter(session => session.id !== sessionId));
      clearSessionIfActive(sessionId);

      if (selectedSessionId === sessionId) {
        detailAbortRef.current?.abort();
        detailAbortRef.current = null;
        setSelectedSessionId(null);
        setMessages([]);
        setHasMoreMessages(false);
        setDetailError('');
        setOlderMessagesError('');
        setLoadingMessages(false);
      }
    } catch (requestError) {
      handleRequestError(requestError, setError);
    } finally {
      setDeletingSessionId(null);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[300px]">
        <Loader2 className="animate-spin text-red-600" size={28} />
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto p-6 grid grid-cols-1 md:grid-cols-3 gap-6">
      <div className="md:col-span-1 border-r border-slate-200 dark:border-slate-700 pr-0 md:pr-4">
        <h1 className="text-lg font-bold text-slate-800 dark:text-white mb-4">Lịch sử trò chuyện</h1>

        {error && <p className="text-xs text-red-500 mb-4">{error}</p>}

        {sessions.length === 0 ? (
          <p className="text-sm text-slate-500">Chưa có lịch sử nào.</p>
        ) : (
          <div className="space-y-2">
            {sessions.map((session) => (
              <div
                key={session.id}
                onClick={() => handleSelectSession(session.id)}
                className={`p-3 rounded-xl border transition cursor-pointer flex items-center justify-between group ${
                  selectedSessionId === session.id
                    ? 'border-red-500 bg-red-50 dark:bg-slate-800'
                    : 'border-slate-200 dark:border-slate-700 hover:border-red-300 bg-white dark:bg-slate-800'
                }`}
              >
                <div className="flex items-center gap-2.5 overflow-hidden">
                  <MessageSquare size={16} className="text-red-600 shrink-0" />
                  <div className="truncate">
                    <p className="text-xs font-semibold text-slate-800 dark:text-slate-200 truncate">
                      {session.title || `Phiên #${session.id}`}
                    </p>
                    <span className="text-[10px] text-slate-400 flex items-center gap-1 mt-0.5">
                      <Calendar size={10} />
                      {new Date(session.created_at).toLocaleDateString('vi-VN')}
                    </span>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={(event) => handleDeleteSession(event, session.id)}
                  disabled={deletingSessionId === session.id}
                  className="p-1.5 text-slate-400 hover:text-red-600 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 opacity-0 group-hover:opacity-100 transition disabled:opacity-60"
                  title="Xóa phiên này"
                  aria-label={`Xóa ${session.title || `phiên ${session.id}`}`}
                >
                  {deletingSessionId === session.id
                    ? <Loader2 size={14} className="animate-spin" />
                    : <Trash2 size={14} />}
                </button>
              </div>
            ))}
            {hasMoreSessions && (
              <button
                type="button"
                onClick={handleLoadMoreSessions}
                disabled={loadingMoreSessions}
                className="w-full rounded-lg border border-slate-200 dark:border-slate-700 px-3 py-2 text-xs font-medium text-slate-600 dark:text-slate-300 hover:border-red-300 disabled:opacity-60"
              >
                {loadingMoreSessions ? 'Đang tải...' : 'Tải thêm'}
              </button>
            )}
          </div>
        )}
      </div>

      <div className="md:col-span-2">
        <h2 className="text-lg font-bold text-slate-800 dark:text-white mb-4">Chi tiết tin nhắn</h2>

        {!selectedSessionId ? (
          <div className="flex flex-col items-center justify-center min-h-[250px] text-slate-400">
            <MessageCircle size={40} className="mb-2 stroke-1" />
            <p className="text-sm">Chọn một phiên hội thoại bên trái để xem chi tiết</p>
          </div>
        ) : loadingMessages ? (
          <div className="flex justify-center py-10">
            <Loader2 className="animate-spin text-red-600" size={24} />
          </div>
        ) : detailError ? (
          <p className="text-sm text-red-500">{detailError}</p>
        ) : messages.length === 0 ? (
          <p className="text-sm text-slate-500">Phiên này chưa có tin nhắn.</p>
        ) : (
          <div className="space-y-4 max-h-[500px] overflow-y-auto pr-2">
            {olderMessagesError && (
              <p className="text-xs text-red-500">{olderMessagesError}</p>
            )}
            {hasMoreMessages && (
              <button
                type="button"
                onClick={handleLoadOlderMessages}
                disabled={loadingOlderMessages}
                className="w-full rounded-lg border border-slate-200 dark:border-slate-700 px-3 py-2 text-xs font-medium text-slate-600 dark:text-slate-300 hover:border-red-300 disabled:opacity-60"
              >
                {loadingOlderMessages ? 'Đang tải...' : 'Tải tin nhắn cũ hơn'}
              </button>
            )}
            {messages.map((message, index) => {
              const isUser = message.role === 'user';
              return (
                <div
                  key={`${message.id ?? 'message'}-${message.position ?? index}-${message.role}`}
                  className={`p-3 rounded-xl text-sm ${
                    isUser
                      ? 'bg-red-600 text-white ml-auto max-w-[80%]'
                      : `bg-white dark:bg-slate-800 border text-slate-800 dark:text-slate-100 max-w-[85%] ${
                          message.status === 'error'
                            ? 'border-red-300 dark:border-red-800'
                            : 'border-slate-200 dark:border-slate-700'
                        }`
                  }`}
                >
                  {isUser ? (
                    <p className="whitespace-pre-wrap">{message.content}</p>
                  ) : (
                    <div className="prose dark:prose-invert max-w-none text-sm">
                      <AssistantMarkdown content={message.content} />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
