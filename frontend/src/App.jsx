import React from 'react';
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { ThemeProvider } from './context/ThemeContext';
import { AuthProvider, useAuth } from './context/AuthContext';
import { Navbar } from './components/Navbar';
import { Login } from './pages/Login';
import { Register } from './pages/Register';
import { Chat } from './pages/Chat';
import { History } from './pages/History';

const ProtectedLayout = () => {
  const { user, isCheckingAuth, authError, refreshAuth } = useAuth();
  const location = useLocation();

  if (isCheckingAuth) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="animate-spin text-red-600" size={28} />
      </div>
    );
  }

  if (authError) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-3 px-4 text-center">
        <p className="text-sm text-red-600 dark:text-red-400">
          Không thể kiểm tra phiên đăng nhập. Vui lòng kiểm tra máy chủ và thử lại.
        </p>
        <button
          type="button"
          onClick={() => refreshAuth()}
          className="bg-red-600 hover:bg-red-500 text-white px-4 py-2 rounded-xl text-sm transition"
        >
          Thử lại
        </button>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return (
    <>
      <Navbar />
      <Outlet />
    </>
  );
};

function App() {
  return (
    <ThemeProvider>
      <BrowserRouter
        future={{
          v7_startTransition: true,
          v7_relativeSplatPath: true,
        }}
      >
        <AuthProvider>
          <div className="min-h-screen bg-slate-50 dark:bg-slate-900 transition-colors">
            <Routes>
              <Route path="/login" element={<Login />} />
              <Route path="/register" element={<Register />} />

              <Route element={<ProtectedLayout />}>
                <Route path="/chat" element={<Chat />} />
                <Route path="/history" element={<History />} />
                <Route path="*" element={<Navigate to="/chat" replace />} />
              </Route>
            </Routes>
          </div>
        </AuthProvider>
      </BrowserRouter>
    </ThemeProvider>
  );
}

export default App;
