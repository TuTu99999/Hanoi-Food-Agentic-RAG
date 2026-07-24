import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Send, Loader2 } from 'lucide-react';
import { ChatMessage } from '../components/ChatMessage';

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
  "Phúc Thọ", "Thanh Oai", "Thường Tín", "Ứng Hòa"
];

export const Chat = () => {
  const [messages, setMessages] = useState([
    { id: 1, role: 'assistant', content: 'Xin chào! Tớ là trợ lý tư vấn địa điểm du lịch & ẩm thực Hà Nội. Bạn đang tìm quán ăn hay địa điểm ở khu vực nào?' }
  ]);
  const [input, setInput] = useState('');
  const [district, setDistrict] = useState('Tất cả');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef(null);
  const navigate = useNavigate();

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSend = async (e) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userText = input;
    setInput('');
    
    const userMsg = { id: Date.now(), role: 'user', content: userText };
    setMessages(prev => [...prev, userMsg]);
    setIsLoading(true);

    const botMsgId = Date.now() + 1;
    setMessages(prev => [...prev, { id: botMsgId, role: 'assistant', content: '' }]);

    try {
      const response = await fetch('http://127.0.0.1:8000/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include', // Đính kèm HttpOnly Cookie chứa access_token
        body: JSON.stringify({ 
          question: userText, 
          district: district === 'Tất cả' ? null : district 
        })
      });

      // Xử lý khi hết hạn phiên đăng nhập / chưa Auth
      if (response.status === 401) {
        localStorage.removeItem('isAuthenticated');
        navigate('/login');
        return;
      }

      if (!response.ok) {
        throw new Error(`Lỗi kết nối Server (${response.status})`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        let chunk = decoder.decode(value, { stream: true });
        
        // Bóc tách nếu BE gửi dạng Server-Sent Events (SSE)
        if (chunk.startsWith('data: ')) {
          chunk = chunk.replace(/^data:\s*/gm, '');
        }

        setMessages(prev => prev.map(msg => {
          if (msg.id === botMsgId) {
            return { ...msg, content: msg.content + chunk };
          }
          return msg;
        }));
      }
    } catch (error) {
      console.error('Lỗi Stream Chat:', error);
      setMessages(prev => prev.map(msg => 
        msg.id === botMsgId 
          ? { ...msg, content: '⚠️ Có lỗi xảy ra khi kết nối máy chủ! Vui lòng thử lại sau.' } 
          : msg
      ));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-[calc(100vh-61px)] bg-slate-50 dark:bg-slate-900">
      {/* Thanh lọc khu vực */}
      <div className="bg-white dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 px-4 py-2 flex items-center justify-between text-xs shadow-sm">
        <span className="text-slate-500 dark:text-slate-400 font-medium">Lọc khu vực:</span>
        <select 
          value={district} 
          onChange={(e) => setDistrict(e.target.value)}
          className="bg-slate-100 dark:bg-slate-700 text-slate-800 dark:text-slate-200 rounded-lg px-3 py-1.5 outline-none border border-slate-200 dark:border-slate-600 focus:border-red-500 transition cursor-pointer font-medium"
        >
          {HANOI_DISTRICTS.map((item) => (
            <option key={item} value={item}>
              {item === "Tất cả" ? "Tất cả quận/huyện" : item}
            </option>
          ))}
        </select>
      </div>

      {/* Khung tin nhắn */}
      <div className="flex-1 overflow-y-auto p-4 max-w-4xl mx-auto w-full">
        {messages.map((msg) => (
          <ChatMessage key={msg.id} message={msg} />
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
            placeholder="Hỏi về địa điểm, món ăn Hà Nội..."
            className="flex-1 bg-slate-100 dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-xl px-4 py-3 text-sm text-slate-800 dark:text-slate-100 placeholder-slate-400 outline-none focus:border-red-500 transition"
          />
          <button 
            type="submit" 
            disabled={isLoading || !input.trim()}
            className="bg-red-600 hover:bg-red-500 text-white px-5 py-3 rounded-xl transition disabled:opacity-50 flex items-center gap-2 shadow-md"
          >
            {isLoading ? <Loader2 className="animate-spin" size={18} /> : <Send size={18} />}
          </button>
        </form>
      </div>
    </div>
  );
};