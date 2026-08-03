import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import App from './App';
import ErrorBoundary from '@/components/shared/ErrorBoundary';
import { setupGlobalErrorHandlers } from '@/utils/logger';

// 全局错误捕获：window.onerror / unhandledrejection → 日志上报（不崩页面）
setupGlobalErrorHandlers();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary name="App">
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
