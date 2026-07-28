import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { ApiError, apiJson } from '../lib/api';
import { clearStoredChatSession } from '../lib/chatSession';

const AuthContext = createContext(null);

const normalizeUser = (payload) => {
  const candidate = payload?.user ?? payload;
  if (!candidate || typeof candidate !== 'object' || !candidate.username) return null;

  return {
    ...candidate,
    username: candidate.username,
  };
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [isCheckingAuth, setIsCheckingAuth] = useState(true);
  const [authError, setAuthError] = useState(null);
  const authRequestIdRef = useRef(0);

  const refreshAuth = useCallback(async ({ signal } = {}) => {
    const requestId = ++authRequestIdRef.current;
    setIsCheckingAuth(true);
    setAuthError(null);

    try {
      const payload = await apiJson('/api/auth/me', { signal });
      const currentUser = normalizeUser(payload);

      if (!currentUser) {
        throw new Error('Máy chủ trả về thông tin tài khoản không hợp lệ.');
      }

      if (requestId !== authRequestIdRef.current) return null;
      setUser(currentUser);
      return currentUser;
    } catch (error) {
      if (error.name === 'AbortError') throw error;
      if (requestId !== authRequestIdRef.current) return null;

      setUser(null);
      if (error instanceof ApiError && error.status === 401) {
        clearStoredChatSession();
      } else {
        setAuthError(error);
      }
      return null;
    } finally {
      if (!signal?.aborted && requestId === authRequestIdRef.current) {
        setIsCheckingAuth(false);
      }
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    refreshAuth({ signal: controller.signal }).catch(() => {});

    return () => controller.abort();
  }, [refreshAuth]);

  const login = useCallback(async ({ username, password }) => {
    const requestId = ++authRequestIdRef.current;
    try {
      const payload = await apiJson('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      });

      let loggedInUser = normalizeUser(payload);
      if (!loggedInUser) {
        const mePayload = await apiJson('/api/auth/me');
        loggedInUser = normalizeUser(mePayload);
      }

      if (!loggedInUser) {
        throw new Error('Không thể xác nhận tài khoản sau khi đăng nhập.');
      }

      if (requestId !== authRequestIdRef.current) return loggedInUser;
      setAuthError(null);
      setUser(loggedInUser);
      setIsCheckingAuth(false);
      return loggedInUser;
    } catch (error) {
      if (requestId === authRequestIdRef.current) {
        setUser(null);
        setIsCheckingAuth(false);
      }
      throw error;
    }
  }, []);

  const logout = useCallback(async () => {
    const requestId = ++authRequestIdRef.current;
    try {
      await apiJson('/api/auth/logout', { method: 'POST' });
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 401) throw error;
    }

    if (requestId !== authRequestIdRef.current) return;
    clearStoredChatSession();
    setUser(null);
    setAuthError(null);
    setIsCheckingAuth(false);
  }, []);

  const markUnauthenticated = useCallback(() => {
    authRequestIdRef.current += 1;
    clearStoredChatSession();
    setUser(null);
    setAuthError(null);
    setIsCheckingAuth(false);
  }, []);

  const value = useMemo(() => ({
    user,
    isCheckingAuth,
    authError,
    refreshAuth,
    login,
    logout,
    markUnauthenticated,
  }), [
    user,
    isCheckingAuth,
    authError,
    refreshAuth,
    login,
    logout,
    markUnauthenticated,
  ]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth phải được dùng bên trong AuthProvider.');
  }
  return context;
};
