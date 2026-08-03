import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ErrorBoundary from '../ErrorBoundary';

/** 渲染时抛错的子组件（模拟真实渲染崩溃） */
function Boom(): never {
  throw new Error('boom-render-error');
}

function Ok(): JSX.Element {
  return <div>正常内容</div>;
}

describe('ErrorBoundary', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('子组件正常时不干扰渲染', () => {
    render(
      <ErrorBoundary name="Test">
        <Ok />
      </ErrorBoundary>,
    );
    expect(screen.getByText('正常内容')).toBeInTheDocument();
  });

  it('子组件渲染崩溃时显示错误卡片而非白屏', () => {
    // 抑制 React 上报到 console 的错误（预期行为）
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <ErrorBoundary name="Test">
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/页面渲染出错了/)).toBeInTheDocument();
    expect(screen.getByText('boom-render-error')).toBeInTheDocument();
    expect(errSpy).toHaveBeenCalled();
  });

  it('点击「重试」后重新渲染子树', () => {
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <ErrorBoundary name="Test">
        <Boom />
      </ErrorBoundary>,
    );
    fireEvent.click(screen.getByText('重试'));
    // 重试后仍抛错 → 回到错误卡片（不白屏）
    expect(screen.getByText(/页面渲染出错了/)).toBeInTheDocument();
    expect(errSpy).toHaveBeenCalled();
  });
});
