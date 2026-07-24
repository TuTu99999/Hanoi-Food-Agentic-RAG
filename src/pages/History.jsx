import React, { useEffect, useState } from 'react';
import { MessageSquare, Calendar, Trash2, Loader2, MessageCircle } from 'lucide-react';

export const History = () => {
  const [sessions, setSessions] = useState([]);
  const [selectedSessionId, setSelectedSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [error, setError] = useState(null);

  const token = localStorage.getItem('token'); // Lấy JWT token lưu từ lúc Login

  // 1. Lấy danh sách các phiên trò chuyện (Sessions)
  const fetchSessions = async () => {
    try {
      const response = await fetch('http://127.0.0.1:8000/api/history', {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });

      if (!response.ok) {
        throw new Error('Không thể tải lịch sử trò chuyện.');
      }

      const data = await response.json();
      setSessions(data);
    } catch (err) {
      console.error(err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSessions();
  }, []);

  // 2. Lấy danh sách tin nhắn của 1 Session cụ thể
  const handleSelectSession = async (sessionId) => {
    setSelectedSessionId(sessionId);
    setLoadingMessages(true);
    try {
      const response = await fetch(`http://127.0.0.1:8000/api/history/${sessionId}`, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });

      if (!response.ok) throw new Error('Không thể tải tin nhắn.');

      const data = await response.json();
      setMessages(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingMessages(false);
    }
  };

  // 3. Xóa 1 phiên trò chuyện
  const handleDeleteSession = async (e, sessionId) => {
    e.stopPropagation(); // Tránh bị trigger sự kiện click chọn session

    if (!window.confirm('Bạn có chắc chắn muốn xóa phiên hội thoại này?')) return;

    try {
      const response = await fetch(`http://127.0.0.1:8000/api/history/${sessionId}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });

      if (response.ok) {
        setSessions(prev => prev.filter(s => s.id !== sessionId));
        if (selectedSessionId === sessionId) {
          setSelectedSessionId(null);
          setMessages([]);
        }
      }
    } catch (err) {
      console.error('Lỗi khi xóa:', err);
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
      
      {/* CỘT TRÁI: Danh sách các phiên trò chuyện */}
      <div className="md:col-span-1 border-r border-slate-200 dark:border-slate-700 pr-0 md:pr-4">
        <h1 className="text-lg font-bold text-slate-800 dark:text-white mb-4">Lịch sử trò chuyện</h1>
        
        {error && <p className="text-xs text-red-500 mb-4">{error}</p>}

        {sessions.length === 0 ? (
          <p className="text-sm text-slate-500">Chưa có lịch sử nào.</p>
        ) : (
          <div className="space-y-2">
            {sessions.map((s) => (
              <div 
                key={s.id} 
                onClick={() => handleSelectSession(s.id)}
                className={`p-3 rounded-xl border transition cursor-pointer flex items-center justify-between group ${
                  selectedSessionId === s.id 
                    ? 'border-red-500 bg-red-50 dark:bg-slate-800' 
                    : 'border-slate-200 dark:border-slate-700 hover:border-red-300 bg-white dark:bg-slate-800'
                }`}
              >
                <div className="flex items-center gap-2.5 overflow-hidden">
                  <MessageSquare size={16} className="text-red-600 shrink-0" />
                  <div className="truncate">
                    <p className="text-xs font-semibold text-slate-800 dark:text-slate-200 truncate">
                      {s.title || `Phiên #${s.id}`}
                    </p>
                    <span className="text-[10px] text-slate-400 flex items-center gap-1 mt-0.5">
                      <Calendar size={10} /> {new Date(s.created_at).toLocaleDateString('vi-VN')}
                    </span>
                  </div>
                </div>

                <button 
                  onClick={(e) => handleDeleteSession(e, s.id)}
                  className="p-1.5 text-slate-400 hover:text-red-600 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 opacity-0 group-hover:opacity-100 transition"
                  title="Xóa phiên này"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* CỘT PHẢI: Nội dung chi tiết các tin nhắn trong phiên được chọn */}
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
        ) : (
          <div className="space-y-4 max-h-[500px] overflow-y-auto pr-2">
            {messages.map((msg) => (
              <div 
                key={msg.id} 
                className={`p-3 rounded-xl text-sm ${
                  msg.sender === 'user' || msg.is_user
                    ? 'bg-red-600 text-white ml-auto max-w-[80%]' 
                    : 'bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-100 max-w-[85%]'
                }`}
              >
                <p className="whitespace-pre-wrap">{msg.content || msg.message}</p>
              </div>
            ))}
          </div>
        )}
      </div>

    </div>
  );
};