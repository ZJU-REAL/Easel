import { useEffect, useRef, useState } from 'react';
import { cancelCodexLogin, fetchCodexLogin, logoutCodex, startCodexLogin } from '../lib/api';
import type { CodexLoginState } from '../lib/api';

export default function CodexLogin({ disabled, authenticated, onConnected }: {
  disabled: boolean; authenticated: boolean; onConnected: () => void;
}) {
  const [login, setLogin] = useState<CodexLoginState>({ state: 'idle' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [pollError, setPollError] = useState('');
  const [loggedIn, setLoggedIn] = useState(authenticated);
  const [refresh, setRefresh] = useState(0);
  const completed = useRef('');
  const generation = useRef(0);
  const onConnectedRef = useRef(onConnected);
  onConnectedRef.current = onConnected;
  const pending = login.state === 'starting' || login.state === 'pending';

  useEffect(() => { setLoggedIn(authenticated); }, [authenticated]);

  useEffect(() => {
    if (disabled) return;
    const current = ++generation.current;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const value = await fetchCodexLogin();
        if (!alive || current !== generation.current) return;
        setPollError('');
        setLogin(value);
        if (value.state === 'success' && value.id && completed.current !== value.id) {
          completed.current = value.id;
          onConnectedRef.current();
        }
        if (value.state === 'starting' || value.state === 'pending') timer = setTimeout(() => void poll(), 1500);
      } catch {
        if (alive && current === generation.current) {
          setPollError('暂时无法读取登录进度，正在重试…');
          timer = setTimeout(() => void poll(), 3000);
        }
      }
    };
    void poll();
    return () => { alive = false; clearTimeout(timer); };
  }, [disabled, refresh]);

  const start = async (method: 'browser' | 'device') => {
    generation.current += 1;
    // Open synchronously with the click, before awaiting HTTP, to avoid popup blocking.
    const popup = window.open('about:blank', '_blank');
    if (popup) popup.opener = null;
    setBusy(true);
    setError('');
    try {
      const value = await startCodexLogin(method);
      setLogin(value);
      if (value.state === 'success') setLoggedIn(true);
      if (value.authUrl && popup) popup.location.replace(value.authUrl);
      else popup?.close();
    } catch (reason) {
      popup?.close();
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
      setRefresh(previous => previous + 1);
    }
  };
  const cancel = async () => {
    if (!login.id) return;
    generation.current += 1;
    setBusy(true);
    setError('');
    try {
      setLogin(await cancelCodexLogin(login.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
      setRefresh(previous => previous + 1);
    }
  };
  const logout = async () => {
    if (!window.confirm('退出 Codex 后，Easel 将无法继续使用 Codex，直到你再次登录。已有对话和作品会保留。确定退出吗？')) return;
    setBusy(true);
    setError('');
    generation.current += 1;
    try {
      setLogin(await logoutCodex());
      setLoggedIn(false);
      onConnectedRef.current();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
      setRefresh(previous => previous + 1);
    }
  };

  return <div aria-label="Codex 登录">
    <div className="settings-native-models">
      <button className="btn btn-sm" disabled={disabled || busy || pending}
        onClick={() => void start('browser')}>{busy && !pending ? '准备登录…' : loggedIn ? '重新登录 Codex' : '登录 Codex'}</button>
      <button className="btn btn-sm" disabled={disabled || busy || pending}
        onClick={() => void start('device')}>使用验证码登录</button>
      {loggedIn && <button className="btn btn-sm" disabled={disabled || busy || pending}
        onClick={() => void logout()}>退出登录</button>}
      {pending && <button className="btn btn-sm" disabled={busy} onClick={() => void cancel()}>取消登录</button>}
    </div>
    {login.userCode && <p className="desc">请在官方页面输入验证码：<strong>{login.userCode}</strong></p>}
    {login.authUrl && <p className="desc">
      <a href={login.authUrl} target="_blank" rel="noopener noreferrer">打开官方登录页</a>
      {' '}· 如果新窗口未打开，可点击此链接。
    </p>}
    {login.message && <p className="desc" role="status">{login.message}</p>}
    {error && <p className="desc" role="status">{error}</p>}
    {pollError && <p className="desc" role="status">{pollError}</p>}
    <p className="desc">使用 ChatGPT 账号在官方页面授权，完成后自动更新状态。
      无法跳转或无法返回时，可使用验证码登录。
      {authenticated ? '重新登录会更新本机 Codex 使用的账号。' : ''}</p>
  </div>;
}
