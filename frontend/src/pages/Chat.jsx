import React, { useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Send, Loader2, Plus } from 'lucide-react';
import { ChatMessage } from '../components/ChatMessage';
import { useAuth } from '../context/AuthContext';
import { DEFAULT_DISTRICT, useChat } from '../context/ChatContext';
import { apiFetch, toApiError } from '../lib/api';

const STREAM_IDLE_TIMEOUT_MS = 40000;

// Danh sách 30 quận/huyện/thị xã Hà Nội (Đã lọc trùng)
export const HANOI_DISTRICTS = [
  "Tất cả",
  // 12 Quận Nội thành
  "Hoàn Kiếm", "Ba Đình", "Tây Hồ", "Cầu Giấy", "Hai Bà Trưng", "Đống Đa", 
  "Thanh Xuân", "Hoàng Mai", "Long Biên", "Nam Từ Liêm", "Bắc Từ Liêm", "Hà Đông",
  // 1 Thị xã
  "Sơn Tây",
  // 17 Huyện Ngoại thành
  "Thanh Trì", "Gia Lâm", "Đông Anh", "Sóc Sơn", "Thạch Thất", "Quốc Oai", 
  "Chương Mỹ", "Đan Phượng", "Hoài Đức", "Mê Linh", "Mỹ Đức", "Phú Xuyên", 
  "Phúc Thọ", "Thanh Oai", "Thường Tín", "Ứng Hòa", "Ba Vì"
];

const splitSseFrames = (buffer) => {
  const frames = [];
  let rest = buffer;

  while (true) {
    const boundary = /\r?\n\r?\n/.exec(rest);
    if (!boundary) break;

    frames.push(rest.slice(0, boundary.index));
    rest = rest.slice(boundary.index + boundary[0].length);
  }

  return { frames, rest };
};

const parseSseFrame = (frame) => {
  let eventName = 'message';
  const dataLines = [];

  frame.split(/\r?\n/).forEach((line) => {
    if (!line || line.startsWith(':')) return;

    const separatorIndex = line.indexOf(':');
    const field = separatorIndex === -1 ? line : line.slice(0, separatorIndex);
    let value = separatorIndex === -1 ? '' : line.slice(separatorIndex + 1);
    if (value.startsWith(' ')) value = value.slice(1);

    if (field === 'event') eventName = value || 'message';
    if (field === 'data') dataLines.push(value);
  });

  const rawData = dataLines.join('\n');
  if (rawData === '[DONE]') return { eventName: 'done', payload: {} };

  if (!rawData) return { eventName, payload: {} };

  try {
    return { eventName, payload: JSON.parse(rawData) };
  } catch {
    return { eventName, payload: { content: rawData } };
  }
};

export const Chat = () => {
  const {
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
    activeRequestRef,
  } = useChat();
  const messagesEndRef = useRef(null);
  const { markUnauthenticated } = useAuth();
  const navigate = useNavigate();

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    if (isLoading) return undefined;

    const controller = new AbortController();
    restoreSession({ signal: controller.signal });
    return () => controller.abort();
  }, [isLoading, restoreSession]);

  const handleSend = async (e) => {
    e.preventDefault();
    if (
      !input.trim()
      || isLoading
      || isRestoring
      || restoreError
      || activeRequestRef.current
    ) {
      return;
    }

    const userText = input.trim();
    setInput('');

    const requestMarker = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const userClientId = `user-${requestMarker}`;
    const botClientId = `assistant-${requestMarker}`;
    const userMsg = { clientId: userClientId, role: 'user', content: userText };
    setMessages(prev => [...prev, userMsg]);
    setIsLoading(true);
    setMessages(prev => [...prev, { clientId: botClientId, role: 'assistant', content: '' }]);

    const controller = new AbortController();
    activeRequestRef.current = controller;
    let streamTimedOut = false;
    let streamTimeoutId;

    const resetStreamTimeout = () => {
      clearTimeout(streamTimeoutId);
      streamTimeoutId = setTimeout(() => {
        streamTimedOut = true;
        controller.abort();
      }, STREAM_IDLE_TIMEOUT_MS);
    };

    try {
      resetStreamTimeout();
      const response = await apiFetch('/api/chat/stream', {
        method: 'POST',
        signal: controller.signal,
        body: JSON.stringify({ 
          session_id: sessionId,
          question: userText,
          district: district === DEFAULT_DISTRICT ? null : district,
        }),
      });

      if (response.status === 401) {
        markUnauthenticated();
        navigate('/login', {
          replace: true,
          state: { from: { pathname: '/chat' } },
        });
        return;
      }

      if (!response.ok) {
        throw await toApiError(response, 'Không thể gửi câu hỏi.');
      }

      if (!response.body) {
        throw new Error('Trình duyệt không nhận được luồng phản hồi từ máy chủ.');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';
      let shouldStop = false;
      let receivedTerminalEvent = false;

      const mergeServerMessage = (clientId, serverMessage) => {
        if (!serverMessage || typeof serverMessage !== 'object') return;

        setMessages(prev => prev.map(message => (
          message.clientId === clientId
            ? { ...message, ...serverMessage, clientId }
            : message
        )));
      };

      const appendAssistantContent = (content) => {
        if (content === undefined || content === null || content === '') return;

        setMessages(prev => prev.map(message => (
          message.clientId === botClientId
            ? { ...message, content: `${message.content || ''}${String(content)}` }
            : message
        )));
      };

      const processFrame = (frame) => {
        const { eventName, payload } = parseSseFrame(frame);
        const explicitType = eventName !== 'message'
          ? eventName
          : payload?.type || payload?.event;
        const eventType = String(
          explicitType
            || (payload?.done ? 'done' : null)
            || (payload?.error ? 'error' : null)
            || (payload?.user_message ? 'session' : 'token')
        ).toLowerCase();

        if (payload?.session_id !== undefined && payload?.session_id !== null) {
          if (!setSessionId(payload.session_id)) {
            throw new Error('Máy chủ trả về session ID không hợp lệ.');
          }
        }

        if (eventType === 'session') {
          mergeServerMessage(userClientId, payload.user_message);
          mergeServerMessage(botClientId, payload.assistant_message);
          return false;
        }

        if (eventType === 'done') {
          mergeServerMessage(botClientId, payload.assistant_message);
          receivedTerminalEvent = true;
          return true;
        }

        if (eventType === 'error') {
          const fallbackContent = `⚠️ ${
            payload.message
            || payload.detail
            || 'Có lỗi xảy ra khi xử lý câu hỏi.'
          }`;
          const serverErrorMessage = {
            role: 'assistant',
            ...(payload.assistant_message || {}),
            status: 'error',
            content: payload.assistant_message?.content || fallbackContent,
          };
          mergeServerMessage(botClientId, serverErrorMessage);
          receivedTerminalEvent = true;
          return true;
        }

        appendAssistantContent(payload?.content ?? payload?.token ?? payload?.text);
        return false;
      };

      while (!shouldStop) {
        const { done, value } = await reader.read();
        if (done) {
          buffer += decoder.decode();
          if (buffer.trim()) shouldStop = processFrame(buffer.trim());
          break;
        }

        resetStreamTimeout();
        buffer += decoder.decode(value, { stream: true });
        const parsedBuffer = splitSseFrames(buffer);
        buffer = parsedBuffer.rest;

        for (const frame of parsedBuffer.frames) {
          if (frame.trim() && processFrame(frame)) {
            shouldStop = true;
            break;
          }
        }
      }

      if (shouldStop) {
        await reader.cancel().catch(() => {});
      }

      if (!receivedTerminalEvent) {
        setMessages(prev => prev.map(message => (
          message.clientId === botClientId
            ? {
                ...message,
                status: 'error',
                content: message.content
                  ? `${message.content}\n\n⚠️ Luồng phản hồi bị gián đoạn.`
                  : '⚠️ Máy chủ không trả về nội dung.',
              }
            : message
        )));
      }
    } catch (error) {
      if (error.name === 'AbortError' && !streamTimedOut) return;

      console.error('Lỗi Stream Chat:', error);
      const errorMessage = streamTimedOut
        ? 'Hệ thống phản hồi quá thời gian. Vui lòng thử lại.'
        : error.message || 'Có lỗi xảy ra khi kết nối máy chủ. Vui lòng thử lại sau.';
      setMessages(prev => prev.map(message =>
        message.clientId === botClientId
          ? {
              ...message,
              status: 'error',
              content: message.content
                ? `${message.content}\n\n⚠️ ${errorMessage}`
                : `⚠️ ${errorMessage}`,
            }
          : message
      ));
    } finally {
      clearTimeout(streamTimeoutId);
      if (activeRequestRef.current === controller) {
        activeRequestRef.current = null;
        setIsLoading(false);
      }
    }
  };

  return (
    <div className="flex flex-col h-[calc(100vh-61px)] bg-slate-50 dark:bg-slate-900">
      {/* Thanh lọc khu vực */}
      <div className="bg-white dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 px-4 py-2 flex items-center justify-between text-xs shadow-sm">
        <span className="text-slate-500 dark:text-slate-400 font-medium">Lọc khu vực:</span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => clearChat()}
            disabled={isLoading}
            aria-label="Bắt đầu cuộc trò chuyện mới"
            className="flex items-center gap-1 rounded-lg px-2.5 py-1.5 font-medium text-red-600 hover:bg-red-50 dark:hover:bg-slate-700 disabled:opacity-50 transition"
          >
            <Plus size={14} />
            <span className="hidden sm:inline">Cuộc trò chuyện mới</span>
          </button>
          <select
            value={district}
            onChange={(e) => setDistrict(e.target.value)}
            className="bg-slate-100 dark:bg-slate-700 text-slate-800 dark:text-slate-200 rounded-lg px-3 py-1.5 outline-none border border-slate-200 dark:border-slate-600 focus:border-red-500 transition cursor-pointer font-medium"
          >
            {HANOI_DISTRICTS.map((item) => (
              <option key={item} value={item}>
                {item === DEFAULT_DISTRICT ? 'Tất cả quận/huyện' : item}
              </option>
            ))}
          </select>
        </div>
      </div>

      {restoreError && (
        <div
          role="alert"
          className="mx-auto mt-3 flex w-[calc(100%-2rem)] max-w-4xl items-center justify-between gap-3 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300"
        >
          <span>{restoreError}</span>
          <button
            type="button"
            onClick={() => restoreSession()}
            disabled={isRestoring}
            className="shrink-0 font-semibold underline disabled:opacity-50"
          >
            Thử lại
          </button>
        </div>
      )}

      {/* Khung tin nhắn */}
      <div className="flex-1 overflow-y-auto p-4 max-w-4xl mx-auto w-full">
        {isRestoring && (
          <div className="flex items-center justify-center gap-2 py-3 text-xs text-slate-500 dark:text-slate-400">
            <Loader2 className="animate-spin" size={15} />
            Đang khôi phục cuộc trò chuyện...
          </div>
        )}
        {messages.map((msg) => (
          <ChatMessage key={msg.clientId || msg.id} message={msg} />
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Ô nhập câu hỏi */}
      <div className="p-4 bg-white dark:bg-slate-800 border-t border-slate-200 dark:border-slate-700">
        <form onSubmit={handleSend} className="max-w-4xl mx-auto flex gap-2">
          <input 
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={isRestoring || Boolean(restoreError)}
            placeholder="Hỏi về địa điểm, món ăn Hà Nội..."
            className="flex-1 bg-slate-100 dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-xl px-4 py-3 text-sm text-slate-800 dark:text-slate-100 placeholder-slate-400 outline-none focus:border-red-500 transition"
          />
          <button 
            type="submit" 
            disabled={isLoading || isRestoring || Boolean(restoreError) || !input.trim()}
            className="bg-red-600 hover:bg-red-500 text-white px-5 py-3 rounded-xl transition disabled:opacity-50 flex items-center gap-2 shadow-md"
          >
            {isLoading || isRestoring
              ? <Loader2 className="animate-spin" size={18} />
              : <Send size={18} />}
          </button>
        </form>
      </div>
    </div>
  );
};
