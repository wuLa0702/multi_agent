/**
 * ErrorBoundary — 渲染错误隔离层
 *
 * 任何子组件渲染期抛错 → 显示可读错误卡片（而非整个 React 树卸载白屏），
 * 同时把错误上报到日志（console + .logs/frontend.log）。
 *
 * 用法：
 *   <ErrorBoundary name="ChatPage"><ChatPage /></ErrorBoundary>
 *   <ErrorBoundary name="App" fallback={<自定义UI/>}>...</ErrorBoundary>
 */

import { Component, type ErrorInfo, type ReactNode } from 'react';
import { logError } from '@/utils/logger';

interface ErrorBoundaryProps {
  children: ReactNode;
  /** 错误来源标识（写日志用） */
  name: string;
  /** 自定义 fallback；缺省用内置错误卡片 */
  fallback?: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    logError(this.props.name, error, `componentStack: ${info.componentStack?.slice(0, 500) ?? ''}`);
  }

  private handleReload = (): void => {
    // 清空错误态重试；不行就整页刷新兜底
    this.setState({ error: null });
  };

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    if (this.props.fallback) return this.props.fallback;

    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="max-w-md w-full text-center space-y-4">
          <div className="text-3xl">😿</div>
          <h2 className="text-base font-semibold">页面渲染出错了</h2>
          <p className="text-xs text-muted-foreground break-all leading-relaxed">
            {error.message || String(error)}
          </p>
          <p className="text-[11px] text-muted-foreground/70">
            错误已记录到日志（.logs/frontend.log），刷新可恢复
          </p>
          <div className="flex gap-2 justify-center">
            <button
              onClick={this.handleReload}
              className="px-3 py-1.5 text-xs rounded-md bg-primary text-primary-foreground press"
            >
              重试
            </button>
            <button
              onClick={() => window.location.reload()}
              className="px-3 py-1.5 text-xs rounded-md border border-border press"
            >
              刷新页面
            </button>
          </div>
        </div>
      </div>
    );
  }
}
