import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';

interface Props { children: ReactNode }
interface State { hasError: boolean; message: string }

/** 全局错误边界：任一渲染期异常不再白屏整个应用。 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: '' };

  static getDerivedStateFromError(err: Error): State {
    return { hasError: true, message: err.message };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Easel UI error:', error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
          height: '100vh', gap: 12, color: 'var(--text)', background: 'var(--bg)', padding: 24, textAlign: 'center',
        }}>
          <div style={{ fontSize: 40 }}>😵</div>
          <h2 style={{ margin: 0 }}>页面出错了</h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: 14, maxWidth: 420 }}>{this.state.message}</p>
          <button onClick={() => window.location.reload()}
            style={{ padding: '9px 18px', borderRadius: 8, border: 'none', background: 'var(--text, #17191c)', color: '#fff', cursor: 'pointer' }}>
            刷新页面
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
