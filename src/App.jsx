import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider } from './context/ThemeContext';
import { Navbar } from './components/Navbar';
import { Login } from './pages/Login';
import { Register } from './pages/Register';
import { Chat } from './pages/Chat';
import { History } from './pages/History';

function App() {
  return (
    <ThemeProvider>
      <BrowserRouter
      future={{
        v7_startTransition: true,   
        v7_relativeSplatPath: true, 
      }}>
        <div className="min-h-screen bg-slate-50 dark:bg-slate-900 transition-colors">
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            
            {/* Layout có Navbar */}
            <Route path="*" element={
              <>
                <Navbar />
                <Routes>
                  <Route path="/chat" element={<Chat />} />
                  <Route path="/history" element={<History />} />
                  <Route path="*" element={<Navigate to="/chat" replace />} />
                </Routes>
              </>
            } />
          </Routes>
        </div>
      </BrowserRouter>
    </ThemeProvider>
  );
}

export default App;