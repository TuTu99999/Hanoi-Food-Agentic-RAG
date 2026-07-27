import React, { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Utensils, Loader2 } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export const Login = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      await login({ username, password });
      const previousLocation = location.state?.from;
      const destination = previousLocation
        ? `${previousLocation.pathname}${previousLocation.search || ''}${previousLocation.hash || ''}`
        : '/chat';
      navigate(destination, { replace: true });
    } catch (err) {
      setError(err.message || 'Đăng nhập thất bại. Vui lòng thử lại!');
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
          <h2 className="text-2xl font-bold text-slate-800 dark:text-white">Đăng nhập</h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Trợ lý Ẩm thực & Du lịch Hà Nội</p>
        </div>

        {/* Thông báo lỗi nếu có */}
        {error && (
          <div className="mb-4 p-3 bg-red-100 border border-red-300 text-red-700 dark:bg-red-900/30 dark:border-red-800 dark:text-red-400 text-xs rounded-xl text-center">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1">Tên đăng nhập</label>
            <input 
              type="text" required
              value={username} onChange={(e) => setUsername(e.target.value)}
              placeholder="Nhập tên đăng nhập..."
              className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-xl px-4 py-2.5 text-sm text-slate-800 dark:text-white outline-none focus:border-red-500 transition"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-600 dark:text-slate-300 mb-1">Mật khẩu</label>
            <input 
              type="password" required
              value={password} onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-xl px-4 py-2.5 text-sm text-slate-800 dark:text-white outline-none focus:border-red-500 transition"
            />
          </div>
          <button 
            type="submit" 
            disabled={loading}
            className="w-full bg-red-600 hover:bg-red-500 text-white font-medium py-2.5 rounded-xl transition text-sm shadow-md flex items-center justify-center gap-2 disabled:opacity-60"
          >
            {loading ? (
              <>
                <Loader2 size={18} className="animate-spin" />
                Đang xử lý...
              </>
            ) : (
              'Đăng nhập'
            )}
          </button>
        </form>

        <p className="text-xs text-center text-slate-500 dark:text-slate-400 mt-6">
          Chưa có tài khoản? <Link to="/register" className="text-red-500 font-medium hover:underline">Đăng ký ngay</Link>
        </p>
      </div>
    </div>
  );
};
