import React, { useState } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { Sun, Moon, Utensils, LogOut, History, MessageSquare, Loader2 } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { useAuth } from '../context/AuthContext';

export const Navbar = () => {
  const { isDark, toggleTheme } = useTheme();
  const { user, logout } = useAuth();
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState('');
  const navigate = useNavigate();
  const location = useLocation();

  const isActive = (path) => location.pathname === path;

  const handleLogout = async () => {
    if (isLoggingOut) return;

    setIsLoggingOut(true);
    setLogoutError('');
    try {
      await logout();
      navigate('/login', { replace: true });
    } catch (error) {
      setLogoutError(error.message || 'Không thể đăng xuất. Vui lòng thử lại.');
    } finally {
      setIsLoggingOut(false);
    }
  };

  return (
    <nav className="bg-white dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 px-4 py-3 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto flex items-center justify-between">
        <Link to="/chat" className="flex items-center gap-2 font-bold text-lg text-slate-800 dark:text-white">
          <div className="bg-red-600 text-white p-2 rounded-xl">
            <Utensils size={18} />
          </div>
          <span>Hà Nội Food </span>
        </Link>

        <div className="flex items-center gap-1 sm:gap-3">
          <Link 
            to="/chat" 
            className={`p-2 rounded-xl flex items-center gap-1.5 text-sm font-medium transition ${
              isActive('/chat') 
                ? 'bg-red-50 dark:bg-slate-700 text-red-600 dark:text-red-400' 
                : 'text-slate-600 dark:text-slate-300 hover:text-red-600 dark:hover:text-red-400'
            }`}
          >
            <MessageSquare size={18} /> <span className="hidden md:inline">Chat</span>
          </Link>

          <Link 
            to="/history" 
            className={`p-2 rounded-xl flex items-center gap-1.5 text-sm font-medium transition ${
              isActive('/history') 
                ? 'bg-red-50 dark:bg-slate-700 text-red-600 dark:text-red-400' 
                : 'text-slate-600 dark:text-slate-300 hover:text-red-600 dark:hover:text-red-400'
            }`}
          >
            <History size={18} /> <span className="hidden md:inline">Lịch sử</span>
          </Link>

          <button 
            onClick={toggleTheme} 
            className="p-2 rounded-xl text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition ml-1"
            aria-label={isDark ? 'Chuyển sang giao diện sáng' : 'Chuyển sang giao diện tối'}
          >
            {isDark ? <Sun size={18} className="text-amber-400" /> : <Moon size={18} />}
          </button>

          <button 
            type="button"
            onClick={handleLogout}
            disabled={isLoggingOut}
            className="p-2 rounded-xl text-red-600 hover:bg-red-50 dark:hover:bg-slate-700 transition flex items-center gap-1 text-sm font-medium disabled:opacity-60"
            aria-label={`Đăng xuất tài khoản ${user?.username || ''}`}
            title={logoutError || `Đăng xuất ${user?.username || ''}`}
          >
            {isLoggingOut ? <Loader2 size={18} className="animate-spin" /> : <LogOut size={18} />}
            <span className="hidden md:inline">{isLoggingOut ? 'Đang thoát...' : 'Thoát'}</span>
          </button>
        </div>
      </div>
    </nav>
  );
};
