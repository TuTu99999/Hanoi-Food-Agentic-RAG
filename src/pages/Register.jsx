// Register.jsx
import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Utensils, Loader2 } from 'lucide-react';

export const Register = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState(''); // 👈 Thêm state xác nhận mật khẩu
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    // 1. Kiểm tra mật khẩu nhập lại ở Frontend
    if (password !== confirmPassword) {
      setError('Mật khẩu xác nhận không khớp!');
      return;
    }

    if (password.length < 6) {
      setError('Mật khẩu phải có ít nhất 6 ký tự!');
      return;
    }

    setLoading(true);

    try {
      // 2. Gọi API Đăng ký
      const response = await fetch('http://127.0.0.1:8000/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }), // Chỉ gửi username & password xuống BE
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || 'Đăng ký thất bại!');
      }

      // 3. Đăng ký THÀNH CÔNG -> KO lưu Cookie/localStorage gì cả, đẩy thẳng về /login
      alert('Tạo tài khoản thành công! Vui lòng đăng nhập.');
      navigate('/login');

    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-100 dark:bg-slate-900 px-4">
      <div className="max-w-md w-full bg-white dark:bg-slate-800 rounded-2xl p-8 shadow-lg border border-slate-200 dark:border-slate-700">
        <div className="flex flex-col items-center mb-6">
          <div className="bg-red-600 text-white p-3 rounded-2xl mb-2 shadow-md">
            <Utensils size={28} />
          </div>
          <h2 className="text-2xl font-bold text-slate-800 dark:text-white">Đăng ký tài khoản</h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Trợ lý Ẩm thực & Du lịch Hà Nội</p>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-100 border border-red-300 text-red-700 dark:bg-red-900/30 dark:border-red-800 dark:text-red-400 text-xs rounded-xl text-center">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1">Tên đăng nhập</label>
            <input 
              type="text" required value={username} onChange={(e) => setUsername(e.target.value)}
              placeholder="Nhập tên đăng nhập..."
              className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-xl px-4 py-2.5 text-sm text-slate-800 dark:text-white outline-none focus:border-red-500 transition"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1">Mật khẩu</label>
            <input 
              type="password" required value={password} onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-xl px-4 py-2.5 text-sm text-slate-800 dark:text-white outline-none focus:border-red-500 transition"
            />
          </div>

          {/* Ô nhập lại mật khẩu */}
          <div>
            <label className="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1">Xác nhận mật khẩu</label>
            <input 
              type="password" required value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="••••••••"
              className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-xl px-4 py-2.5 text-sm text-slate-800 dark:text-white outline-none focus:border-red-500 transition"
            />
          </div>

          <button 
            type="submit" disabled={loading}
            className="w-full bg-red-600 hover:bg-red-500 text-white font-medium py-2.5 rounded-xl transition text-sm flex items-center justify-center gap-2 disabled:opacity-60 shadow-md"
          >
            {loading ? <Loader2 size={18} className="animate-spin" /> : 'Đăng ký'}
          </button>
        </form>

        <p className="text-xs text-center text-slate-500 dark:text-slate-400 mt-6">
          Đã có tài khoản? <Link to="/login" className="text-red-500 font-medium hover:underline">Đăng nhập ngay</Link>
        </p>
      </div>
    </div>
  );
};