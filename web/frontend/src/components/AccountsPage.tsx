import { useState, useEffect, useCallback, useRef } from 'react';
import {
  fetchAccounts, startLogin, loginStatus, mediaUrl,
  accountWhoami, logoutAccount, submitLoginSms,
} from '../lib/api';
import type { AccountItem, AccountWhoami } from '../lib/api';
import { getWhoamiCache, setWhoamiCache, verifyStale } from '../lib/whoami';

type QRState = {
  platform: string;
  name: string;
  state: string;       // starting | qr_ready | success | expired | error | unknown
  message: string;
  qr: string;          // outputs 相对路径
  qrTs?: number;       // 二维码文件 mtime，作 img 缓存键：码刷新一次就变，避免看到过期旧码
};

const STATE_LABEL: Record<string, string> = {
  starting: '启动中…',
  qr_ready: '请扫码',
  scanned: '扫码成功',
  sms_required: '需短信验证',
  verifying: '验证中…',
  success: '登录成功 ✅',
  expired: '二维码已过期',
  error: '登录出错',
  unknown: '等待中…',
};

/** 头像：有 URL 就显示图（加载失败退回首字），否则显示昵称/平台名首字。 */
function Avatar({ url, name }: { url?: string; name: string }) {
  const [broken, setBroken] = useState(false);
  const initial = (name || '?').trim().charAt(0);
  if (url && !broken) {
    return <img className="account-avatar" src={url} alt={name}
      referrerPolicy="no-referrer" onError={() => setBroken(true)} />;
  }
  return <div className="account-avatar account-avatar-fallback">{initial}</div>;
}

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<AccountItem[]>([]);
  const [err, setErr] = useState('');
  const [qr, setQr] = useState<QRState | null>(null);
  const [qrNonce, setQrNonce] = useState(0);   // 每次登录 +1，稳定缓存 key，避免每次轮询 img 闪烁
  const [terminalMsg, setTerminalMsg] = useState('');
  const [busy, setBusy] = useState('');
  const [logoutBusy, setLogoutBusy] = useState('');
  const [smsCode, setSmsCode] = useState('');
  const [smsBusy, setSmsBusy] = useState(false);
  const [smsErr, setSmsErr] = useState('');
  // whoami 结果缓存到 localStorage：打开页面秒显示昵称/头像，不必每次都起浏览器校验
  const [whoami, setWhoami] = useState<Record<string, AccountWhoami | 'loading'>>(() => getWhoamiCache());
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const aliveRef = useRef(true);
  const qrPlatformRef = useRef('');   // 当前登录中的平台，供 submitSms 稳定引用

  useEffect(() => {
    aliveRef.current = true;
    return () => { aliveRef.current = false; };
  }, []);

  // 真校验某平台登录态 + 拉昵称/头像（后端起浏览器，数秒）；手动「校验账号」或登录成功后调
  const runWhoami = useCallback((platform: string) => {
    setWhoami((w) => ({ ...w, [platform]: 'loading' }));
    accountWhoami(platform)
      .then((r) => { if (aliveRef.current) { setWhoami((w) => ({ ...w, [platform]: r })); setWhoamiCache(platform, r); } })
      .catch(() => {
        if (aliveRef.current) setWhoami((w) => { const n = { ...w }; delete n[platform]; return n; });
      });
  }, []);

  // 打开页面：拉「快」状态（读 status.json，不起浏览器），随后后台自愈——对缓存缺失/过期的
  // 浏览器平台逐个真校验（whoami），结果到了刷新 UI，并令陈旧的假阴性缓存被真值覆盖。
  const load = useCallback(() => {
    setErr('');
    fetchAccounts()
      .then((list) => {
        if (!aliveRef.current) return;
        setAccounts(list);
        const targets = list
          .filter((a) => a.supported && a.backend !== 'biliup')
          .map((a) => a.platform);
        verifyStale(targets, {
          alive: () => aliveRef.current,
          onUpdate: (platform, r) => setWhoami((w) => ({ ...w, [platform]: r })),
        });
      })
      .catch(() => setErr('加载账号状态失败'));
  }, []);

  useEffect(() => { load(); }, [load]);

  const stopPoll = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }, []);

  useEffect(() => () => stopPoll(), [stopPoll]);

  const closeQr = useCallback(() => {
    stopPoll();
    setQr(null);
    setSmsCode(''); setSmsErr(''); setSmsBusy(false);
    load();
  }, [stopPoll, load]);

  const submitSms = useCallback(async () => {
    const code = smsCode.replace(/\D/g, '');
    if (code.length < 4) { setSmsErr('请输入手机收到的验证码'); return; }
    setSmsBusy(true); setSmsErr('');
    try {
      await submitLoginSms(qrPlatformRef.current, code);
      setSmsCode('');
      // 乐观切到「验证中」转圈：后端读走码→verifying；成功→success，失败→退回 sms_required 带错误
      setQr((prev) => prev && ({ ...prev, state: 'verifying', message: '正在验证验证码…' }));
      // 不停轮询：runner 读走验证码填码提交后，state 会转 success / 或退回 sms_required 重试
    } catch (e) {
      setSmsErr(e instanceof Error ? e.message : '提交验证码失败');
    } finally {
      setSmsBusy(false);
    }
  }, [smsCode]);

  const handleLogin = useCallback(async (a: AccountItem) => {
    if (!a.supported) return;
    setTerminalMsg('');
    setBusy(a.platform);
    setSmsCode(''); setSmsErr('');
    qrPlatformRef.current = a.platform;
    setQrNonce((n) => n + 1);
    try {
      const res = await startLogin(a.platform);
      if (res.mode === 'terminal') {
        setTerminalMsg(res.message || '请在终端登录');
        return;
      }
      setQr({ platform: a.platform, name: a.name, state: res.state || 'starting',
              message: res.message || '', qr: res.qr || '' });   // qrTs 由随后的轮询填入
      stopPoll();
      pollRef.current = setInterval(async () => {
        try {
          const s = await loginStatus(a.platform);
          setQr((prev) => prev && ({ ...prev, state: s.state, message: s.message, qr: s.qr, qrTs: s.qrTs }));
          if (['success', 'expired', 'error'].includes(s.state)) {
            stopPoll();
            if (s.state === 'success') runWhoami(a.platform);   // 登录成功即拉账号信息
          }
        } catch { /* 忽略单次轮询失败 */ }
      }, 2000);
    } catch (e) {
      setErr(e instanceof Error ? e.message : '启动登录失败');
    } finally {
      setBusy('');
    }
  }, [stopPoll, runWhoami]);

  const handleLogout = useCallback(async (a: AccountItem) => {
    if (!window.confirm(`确定退出「${a.name}」的登录？登录态将被清除，下次发布需重新扫码。`)) return;
    setLogoutBusy(a.platform);
    try {
      await logoutAccount(a.platform);
      setWhoami((w) => { const n = { ...w }; delete n[a.platform]; return n; });
      setWhoamiCache(a.platform, null);
      load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : '退出登录失败');
    } finally {
      setLogoutBusy('');
    }
  }, [load]);

  // 卡片真实登录态：whoami 权威（已返回则以它为准，自愈假阳性），否则用后端 last-known
  const effLoggedIn = (a: AccountItem): boolean => {
    const w = whoami[a.platform];
    if (w && w !== 'loading') return w.loggedIn;
    return a.loggedIn;
  };

  const badge = (a: AccountItem) => {
    if (!a.supported) return <span className="badge">待重写</span>;
    if (whoami[a.platform] === 'loading') return <span className="badge">校验中…</span>;
    if (effLoggedIn(a)) return <span className="badge badge-ok">✓ 已登录</span>;
    return <span className="badge">未登录</span>;
  };

  return (
    <div className="accounts-page">
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
        <div>
          <h1 className="page-title">账号登录 Accounts</h1>
          <p className="page-subtitle">
            用手机 App 扫码登录，登录态本地持久化，之后发布免登。<br />
            ⚠️ 平台可能对机房/代理 IP 判风险导致二维码弹不出，需干净/家宽 IP，或在正常网络登录后拷贝登录态目录。
          </p>
        </div>
        <button className="btn btn-sm" onClick={load}>⟳ 刷新</button>
      </div>

      {err && <div style={{ color: 'var(--red)', fontSize: 13, marginTop: 12 }}>{err}</div>}
      {terminalMsg && (
        <div className="card" style={{ padding: 13, fontSize: 13, marginTop: 14 }}>{terminalMsg}</div>
      )}

      <div className="accounts-grid">
        {accounts.map((a) => {
          const w = whoami[a.platform];
          const info = w && w !== 'loading' ? w : null;
          const logged = effLoggedIn(a);
          return (
            <div key={a.platform} className="card account-card" style={{ opacity: a.supported ? 1 : 0.6 }}>
              <div className="account-card-head">
                <span className="account-card-name">{a.name}</span>
                {badge(a)}
              </div>

              {logged && info && (
                <div className="account-identity">
                  <Avatar url={info.avatar} name={info.name || a.name} />
                  <span className="account-nick">{info.name || '（已登录）'}</span>
                </div>
              )}
              {!logged && (
                <div className="account-card-note">{a.note ? a.note : `后端：${a.backend}`}</div>
              )}

              <div style={{ display: 'flex', gap: 8, marginTop: 'auto' }}>
                {logged ? (
                  <>
                    <button className="btn btn-sm" style={{ flex: 1 }}
                      disabled={busy === a.platform || w === 'loading'}
                      onClick={() => runWhoami(a.platform)}>
                      {w === 'loading' ? '校验中…' : '校验账号'}
                    </button>
                    <button className="btn btn-sm btn-ghost" style={{ flex: 1 }}
                      disabled={logoutBusy === a.platform}
                      onClick={() => handleLogout(a)}>
                      {logoutBusy === a.platform ? '退出中…' : '退出登录'}
                    </button>
                  </>
                ) : (
                  <button
                    className={`btn btn-block ${a.supported ? 'btn-primary' : ''}`}
                    disabled={!a.supported || busy === a.platform}
                    onClick={() => handleLogin(a)}>
                    {busy === a.platform ? '启动中…' : '登录'}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {qr && (
        <div className="overlay" onClick={closeQr}>
          <div className="modal" style={{ width: 360, maxWidth: '100%', textAlign: 'center' }}
            onClick={(e) => e.stopPropagation()}>
            <h3 style={{ margin: '0 0 4px' }}>登录 {qr.name}</h3>
            <div style={{ fontSize: 13, marginBottom: 14,
              color: qr.state === 'success' ? 'var(--green)'
                : ['error', 'expired'].includes(qr.state) ? 'var(--red)' : 'var(--text-secondary)' }}>
              {STATE_LABEL[qr.state] || qr.state}{qr.message ? ` — ${qr.message}` : ''}
            </div>
            {qr.state === 'sms_required' ? (
              <div style={{ padding: '6px 4px 2px' }}>
                <div style={{ fontSize: 13, marginBottom: 10,
                  color: /错误|过期|失败|重新|未找到|未完成|不正确|失效/.test(qr.message || '')
                    ? 'var(--red)' : 'var(--text-secondary)' }}>
                  {qr.message || '平台风控要求短信验证，验证码已发到你手机，请输入：'}
                </div>
                <input
                  value={smsCode}
                  onChange={(e) => setSmsCode(e.target.value.replace(/\D/g, '').slice(0, 8))}
                  onKeyDown={(e) => { if (e.key === 'Enter') submitSms(); }}
                  placeholder="短信验证码" inputMode="numeric" autoFocus
                  style={{ width: '100%', boxSizing: 'border-box', textAlign: 'center',
                    letterSpacing: 6, fontSize: 20, padding: '10px 12px',
                    border: '1px solid var(--border)', borderRadius: 8 }} />
                {smsErr && <div style={{ color: 'var(--red)', fontSize: 12, marginTop: 6 }}>{smsErr}</div>}
                <button className="btn btn-primary btn-block" style={{ marginTop: 12 }}
                  disabled={smsBusy} onClick={submitSms}>
                  {smsBusy ? '提交中…' : '提交验证码'}
                </button>
              </div>
            ) : qr.state === 'qr_ready' && qr.qr ? (
              <img className="qr-img" src={`${mediaUrl(qr.qr)}?v=${qr.qrTs || qrNonce}`} alt="登录二维码" />
            ) : qr.state === 'scanned' ? (
              <div className="loading" style={{ padding: 40 }}><div className="spinner" />扫码成功，正在跳转验证…（首次可能等十几秒）</div>
            ) : qr.state === 'verifying' ? (
              <div className="loading" style={{ padding: 40 }}><div className="spinner" />正在验证验证码，登录中…</div>
            ) : qr.state === 'success' ? (
              <div style={{ fontSize: 48, padding: 40 }}>✅</div>
            ) : ['error', 'expired'].includes(qr.state) ? (
              <div style={{ fontSize: 13, color: 'var(--red)', padding: 30 }}>
                {qr.message || '登录失败'}<br />可关闭后重试（或换干净 IP）。
              </div>
            ) : (
              <div className="loading" style={{ padding: 40 }}><div className="spinner" />准备二维码…</div>
            )}
            <div style={{ marginTop: 16 }}>
              <button className="btn" onClick={closeQr}>{qr.state === 'success' ? '完成' : '关闭'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
