import { useState, useEffect, useCallback, useRef } from 'react';
import Sidebar from './components/Sidebar';
import type { Page } from './components/Sidebar';
import ChatPage from './components/ChatPage';
import SkillPage from './components/SkillPage';
import OutputsPage from './components/OutputsPage';
import AccountsPage from './components/AccountsPage';
import ProfilePage from './components/ProfilePage';
import DashboardPage from './components/DashboardPage';
import TrendsPage from './components/TrendsPage';
import CalendarPage from './components/CalendarPage';
import IdeasPage from './components/IdeasPage';
import PublishPage from './components/PublishPage';
import BreakdownPage from './components/BreakdownPage';
import SubNav from './components/SubNav';
import OnboardingWizard from './components/OnboardingWizard';
import { fetchStatus, fetchPersonas, streamChat, fetchLastTurn, stopChat } from './lib/api';
import type { PersonaItem, UploadedFile } from './lib/api';
import { deleteSession as deleteRemoteSession } from './lib/api';
import {
  loadSessions,
  saveSessions,
  createSession,
  updateSessionTitle,
  loadActiveId,
  saveActiveId,
} from './lib/store';
import type { ChatSession, ChatMessage, StreamState } from './lib/store';

const ONBOARDING_SEEN_KEY = 'easel_onboarding_seen';

function onboardingSeen(): boolean {
  const current = localStorage.getItem(ONBOARDING_SEEN_KEY);
  if (current) return true;
  const previousKey = `${['post', 'craft'].join('')}_onboarding_seen`;
  const previous = localStorage.getItem(previousKey);
  if (previous) {
    localStorage.setItem(ONBOARDING_SEEN_KEY, previous);
    localStorage.removeItem(previousKey);
    return true;
  }
  return false;
}

export default function App() {
  const [currentPage, setCurrentPage] = useState<Page>('dashboard');
  const [personas, setPersonas] = useState<PersonaItem[]>([]);
  const [selectedPersona, setSelectedPersona] = useState('');
  const [sessions, setSessions] = useState<ChatSession[]>(() => loadSessions());
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [gatewayStatus, setGatewayStatus] = useState('connecting');
  const [showRecommend, setShowRecommend] = useState(false);
  const [showWizard, setShowWizard] = useState(false);

  // 挂载时决定进哪个会话。规则：
  //  - 同一标签刷新（sessionStorage 记着本标签的会话）→ 直接续上（同标签不算冲突）。
  //  - 新开标签/窗口 → 若「上次活跃会话」正被另一个存活标签占用（跨标签 BroadcastChannel 探测），
  //    则开一个新会话，避免两个窗口撞同一会话 → openclaw 并发 takeover 崩溃（后端还有 flock 兜底）。
  //  - 否则续上上次会话（保留「关页重开续接」的体验）。
  const TAB_SESSION_KEY = 'easel_tab_session';
  useEffect(() => {
    const existing = loadSessions();
    let ch: BroadcastChannel | null = null;
    try { ch = new BroadcastChannel('easel-session'); } catch { ch = null; }

    const settle = (id: string, sess: ChatSession[]) => {
      setSessions(sess);
      setActiveSessionId(id);
      const s = sess.find((x) => x.id === id);
      if (s) setSelectedPersona(s.persona || '');
      try { sessionStorage.setItem(TAB_SESSION_KEY, id); } catch { /* ignore */ }
      ch?.postMessage({ type: 'claim', sessionId: id });
    };
    const openNew = (sess: ChatSession[]) => {
      const ns = createSession();
      const updated = [ns, ...sess];
      saveSessions(updated);
      settle(ns.id, updated);
    };

    // 持久监听：别的标签问「谁在用会话 X」时，若正是本标签当前会话就应答 owned
    const onMsg = (e: MessageEvent) => {
      const d = e.data as { type?: string; sessionId?: string } | null;
      if (d?.type === 'query' && d.sessionId && d.sessionId === activeIdRef.current) {
        ch?.postMessage({ type: 'owned', sessionId: d.sessionId });
      }
    };
    ch?.addEventListener('message', onMsg);

    // 1) 本标签刷新：续本标签原会话
    let tabOwn: string | null = null;
    try { tabOwn = sessionStorage.getItem(TAB_SESSION_KEY); } catch { tabOwn = null; }
    if (tabOwn && existing.find((s) => s.id === tabOwn)) {
      settle(tabOwn, existing);
      return () => { ch?.removeEventListener('message', onMsg); ch?.close(); };
    }

    // 2) 新标签：候选=上次活跃会话；先跨标签问有没有别的活标签占着它
    const lastId = loadActiveId();
    const candidate = lastId && existing.find((s) => s.id === lastId) ? lastId : null;
    if (candidate && ch) {
      let taken = false;
      const probe = (e: MessageEvent) => {
        const d = e.data as { type?: string; sessionId?: string } | null;
        if (d?.type === 'owned' && d.sessionId === candidate) taken = true;
      };
      ch.addEventListener('message', probe);
      ch.postMessage({ type: 'query', sessionId: candidate });
      const t = setTimeout(() => {
        ch?.removeEventListener('message', probe);
        if (taken) openNew(existing);      // 另一个窗口在用 → 开新会话
        else settle(candidate, existing);  // 没人占 → 续上
      }, 250);
      return () => { clearTimeout(t); ch?.removeEventListener('message', probe); ch?.removeEventListener('message', onMsg); ch?.close(); };
    }

    // 3) 无候选 / 不支持 BroadcastChannel：退化为原逻辑（复用空会话或新建；后端 flock 兜底防崩）
    if (candidate) {
      settle(candidate, existing);
    } else {
      const empty = existing.find((s) => s.messages.length === 0);
      if (empty) settle(empty.id, existing);
      else openNew(existing);
    }
    return () => { ch?.removeEventListener('message', onMsg); ch?.close(); };
  }, []);

  // 持久化当前活跃会话 id，重开网页据此续接上次对话（修复"今天再问就忘了"）。
  // 仅在非空时写：避免挂载首刷 activeSessionId 尚为 null 时误清掉已存的 id。
  // 同时更新本标签的 sessionStorage 标记：手动切会话/新建后刷新本标签仍续在正确会话上。
  useEffect(() => {
    if (activeSessionId) {
      saveActiveId(activeSessionId);
      try { sessionStorage.setItem(TAB_SESSION_KEY, activeSessionId); } catch { /* ignore */ }
    }
  }, [activeSessionId]);

  // Fetch status on mount — 真实反映 gateway 状态 + 首次引导检测
  useEffect(() => {
    fetchStatus()
      .then((data) => {
        setPersonas(data.personas || []);
        setGatewayStatus(data.gateway ? 'connected' : 'disconnected');
        // 首次使用：没有任何个性化画像 且 未看过引导 → 推荐配置
        if ((data.personas || []).length === 0 && !onboardingSeen()) {
          setShowRecommend(true);
        }
      })
      .catch(() => {
        setGatewayStatus('disconnected');
      });
  }, []);

  const activeSession = sessions.find((s) => s.id === activeSessionId) || null;

  // 最新 sessions 的 ref，供回调里读取而不必进依赖数组（避免闭包过期/频繁重建）
  const sessionsRef = useRef(sessions);
  useEffect(() => { sessionsRef.current = sessions; }, [sessions]);

  // 当前活跃会话 id 的 ref：供跨标签「谁在用会话 X」查询时即时应答（见挂载 effect）
  const activeIdRef = useRef<string | null>(activeSessionId);
  useEffect(() => { activeIdRef.current = activeSessionId; }, [activeSessionId]);

  // ---- 流式对话：状态与生命周期都放在 App（永不卸载），切页/切 ChatPage 都不中断/丢失 ----
  const [streams, setStreams] = useState<Record<string, StreamState>>({});
  const streamCtl = useRef<Record<string, AbortController>>({});
  const streamAcc = useRef<Record<string, { content: string; thinking: string; steps: string[] }>>({});

  const appendAssistant = useCallback((sessionId: string, msg: ChatMessage, sessionKey?: string) => {
    setSessions((prev) => {
      const next = prev.map((s) =>
        s.id === sessionId
          ? { ...s, messages: [...s.messages, msg], sessionKey: sessionKey || s.sessionKey, pendingTurnId: undefined }
          : s);
      saveSessions(next);
      return next;
    });
  }, []);

  const clearStream = useCallback((sessionId: string) => {
    delete streamCtl.current[sessionId];
    delete streamAcc.current[sessionId];
    setStreams((prev) => {
      const next = { ...prev };
      delete next[sessionId];
      return next;
    });
  }, []);

  // 启动一次流式（fetch + 累积 + 回调）——只管流，不动消息列表
  const startStream = useCallback((
    sessionId: string,
    text: string,
    persona: string | undefined,
    attachments: UploadedFile[] = [],
  ) => {
    const turnId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    try { sessionStorage.setItem(`easel_pending_turn:${sessionId}`, turnId); } catch { /* ignore */ }
    setSessions((prev) => {
      const next = prev.map((s) => (s.id === sessionId ? { ...s, pendingTurnId: turnId } : s));
      saveSessions(next); return next;
    });
    streamAcc.current[sessionId] = { content: '', thinking: '', steps: [] };
    setStreams((prev) => ({ ...prev, [sessionId]: { content: '', thinking: '', activity: '' } }));
    streamCtl.current[sessionId] = streamChat(
      text, persona, sessionId,
      (chunk) => {
        const a = streamAcc.current[sessionId]; if (!a) return; a.content += chunk;
        setStreams((p) => (p[sessionId] ? { ...p, [sessionId]: { ...p[sessionId], content: a.content } } : p));
      },
      (sessionKey) => {
        const a = streamAcc.current[sessionId];
        appendAssistant(sessionId, {
          role: 'assistant', content: a?.content || '',
          thinking: a?.thinking || undefined, activity: a?.steps.join('\n') || undefined,
        }, sessionKey);
        clearStream(sessionId);
        try { sessionStorage.removeItem(`easel_pending_turn:${sessionId}`); } catch { /* ignore */ }
      },
      (err) => {
        const a = streamAcc.current[sessionId];
        appendAssistant(sessionId, {
          role: 'assistant',
          content: (a?.content ? a.content + '\n\n' : '') + `Error: ${err.message}`,
          thinking: a?.thinking || undefined, activity: a?.steps.join('\n') || undefined,
        });
        clearStream(sessionId);
        try { sessionStorage.removeItem(`easel_pending_turn:${sessionId}`); } catch { /* ignore */ }
      },
      (thinkChunk) => {
        const a = streamAcc.current[sessionId]; if (!a) return;
        a.thinking = (a.thinking + thinkChunk).slice(-4000);
        setStreams((p) => (p[sessionId] ? { ...p, [sessionId]: { ...p[sessionId], thinking: a.thinking } } : p));
      },
      (status) => {
        const a = streamAcc.current[sessionId]; if (!a) return;
        if (a.steps[a.steps.length - 1] !== status) a.steps.push(status);
        setStreams((p) => (p[sessionId] ? { ...p, [sessionId]: { ...p[sessionId], activity: status } } : p));
      },
      // onInterrupted：SSE 被中断（长任务时代理掐断），但后端仍在跑并会落盘完整结果。
      // streamChat 会按 eventId 自动重连并补发遗漏事件；这里只更新用户可见状态。
      () => {
        setStreams((p) => (p[sessionId]
          ? { ...p, [sessionId]: { ...p[sessionId], activity: '⏳ 连接中断，正在自动续接…' } } : p));
      },
      turnId,
      false,
      undefined,
      attachments,
    );
  }, [appendAssistant, clearStream]);

  // 刷新/重开页面后按 eventId=0 重放当前 job，再继续实时 tail；旧任务无事件日志时退回最终快照。
  const resumePendingTurn = useCallback((sessionId: string) => {
    if (streamCtl.current[sessionId] || streamAcc.current[sessionId]) return;  // 本标签正在跑，不插手
    const s = sessionsRef.current.find((x) => x.id === sessionId);
    const last = s?.messages[s.messages.length - 1];
    if (!last || last.role !== 'user') return;   // 没有悬空的用户消息 = 无需恢复
    let turnId = s.pendingTurnId;
    try { turnId = sessionStorage.getItem(`easel_pending_turn:${sessionId}`) || turnId; } catch { /* use persisted id */ }
    streamAcc.current[sessionId] = { content: '', thinking: '', steps: [] };
    setStreams((p) => ({ ...p, [sessionId]: { content: '', thinking: '', activity: '⏳ 正在接回上一轮结果…' } }));
    if (!turnId) {
      void fetchLastTurn(sessionId).then((r) => {
        if (r.status === 'done') appendAssistant(sessionId, { role: 'assistant', content: r.text || '（无输出）' });
        clearStream(sessionId);
      }).catch(() => clearStream(sessionId));
      return;
    }
    streamCtl.current[sessionId] = streamChat(
      '', undefined, sessionId,
      (chunk) => {
        const a = streamAcc.current[sessionId]; if (!a) return; a.content += chunk;
        setStreams((p) => (p[sessionId] ? { ...p, [sessionId]: { ...p[sessionId], content: a.content } } : p));
      },
      (sessionKey) => {
        const a = streamAcc.current[sessionId];
        appendAssistant(sessionId, {
          role: 'assistant', content: a?.content || '（无输出）',
          thinking: a?.thinking || undefined, activity: a?.steps.join('\n') || undefined,
        }, sessionKey);
        clearStream(sessionId);
        try { sessionStorage.removeItem(`easel_pending_turn:${sessionId}`); } catch { /* ignore */ }
      },
      (err) => {
        const a = streamAcc.current[sessionId];
        appendAssistant(sessionId, { role: 'assistant', content: (a?.content || '') + `\n\nError: ${err.message}` });
        clearStream(sessionId);
      },
      (chunk) => { const a = streamAcc.current[sessionId]; if (a) a.thinking = (a.thinking + chunk).slice(-4000); },
      (status) => {
        const a = streamAcc.current[sessionId]; if (!a) return;
        if (a.steps[a.steps.length - 1] !== status) a.steps.push(status);
        setStreams((p) => (p[sessionId] ? { ...p, [sessionId]: { ...p[sessionId], activity: status } } : p));
      },
      () => setStreams((p) => (p[sessionId]
        ? { ...p, [sessionId]: { ...p[sessionId], activity: '⏳ 正在自动续接…' } } : p)),
      turnId,
      true,
      () => {
        // The event log may disappear after a backend restart. Prefer the
        // completed per-session snapshot; otherwise terminate stale recovery.
        void fetchLastTurn(sessionId, turnId).then((r) => {
          if (r.status === 'done') {
            appendAssistant(sessionId, { role: 'assistant', content: r.text || '（无输出）' });
          } else {
            appendAssistant(sessionId, {
              role: 'assistant',
              content: '上一轮任务记录已失效，无法继续恢复。请重新发送上一条消息。',
            });
          }
          clearStream(sessionId);
          try { sessionStorage.removeItem(`easel_pending_turn:${sessionId}`); } catch { /* ignore */ }
        }).catch(() => {
          appendAssistant(sessionId, {
            role: 'assistant', content: '上一轮任务记录已失效，请重新发送上一条消息。',
          });
          clearStream(sessionId);
        });
      },
    );
  }, [appendAssistant, clearStream]);

  // 活跃会话确定后（含挂载首刷）尝试恢复它悬空的一轮
  useEffect(() => {
    if (activeSessionId) resumePendingTurn(activeSessionId);
  }, [activeSessionId, resumePendingTurn]);

  // 落用户消息（可选先把 messages 截断到 truncateAt）→ 启动流。retry/edit 都走这里。
  const sendUserAndStream = useCallback((
    sessionId: string,
    displayText: string,
    attachments: UploadedFile[] = [],
    legacyAgentText?: string,
    truncateAt?: number,
  ) => {
    const visible = displayText.trim();
    const agentMessage = (legacyAgentText || displayText).trim();
    if ((!agentMessage && attachments.length === 0) || streamCtl.current[sessionId]) return;
    const cur = sessionsRef.current.find((s) => s.id === sessionId);
    const persona = cur?.persona || selectedPersona || undefined;
    setSessions((prev) => {
      const next = prev.map((s) => {
        if (s.id !== sessionId) return s;
        const base = truncateAt != null ? s.messages.slice(0, truncateAt) : s.messages;
        const updated = {
          ...s,
          messages: [...base, {
            role: 'user',
            content: visible,
            ...(attachments.length ? { attachments } : {}),
            ...(legacyAgentText && legacyAgentText !== visible ? { agentContent: legacyAgentText } : {}),
          } as ChatMessage],
        };
        updateSessionTitle(updated);
        return updated;
      });
      saveSessions(next);
      return next;
    });
    startStream(sessionId, agentMessage, persona, attachments);
  }, [selectedPersona, startStream]);

  const handleSendMessage = useCallback((sessionId: string, displayText: string, attachments?: UploadedFile[]) => {
    sendUserAndStream(sessionId, displayText, attachments);
  }, [sendUserAndStream]);

  // 重试/编辑重发：从该用户消息处截断（丢弃它及其之后），用 text 重新发起。
  const handleResend = useCallback((
    sessionId: string,
    userIndex: number,
    displayText: string,
    attachments?: UploadedFile[],
    legacyAgentText?: string,
  ) => {
    sendUserAndStream(sessionId, displayText, attachments, legacyAgentText, userIndex);
  }, [sendUserAndStream]);

  // 热点「一键做成内容」：新开会话，把选题作为指令发出去，跳到对话页。
  const handleUseTopic = useCallback((title: string) => {
    const prompt = `围绕当前热点「${title}」：先判断它适不适合我的账号赛道；若合适，给 2-3 个差异化的二创角度，并把你最推荐的那条写成可直接发布的文案初稿。`;
    const ns = createSession(selectedPersona || undefined);
    setSessions((prev) => { const u = [ns, ...prev]; saveSessions(u); return u; });
    setActiveSessionId(ns.id);
    setCurrentPage('chat');
    sendUserAndStream(ns.id, prompt);
  }, [selectedPersona, sendUserAndStream]);

  const handleStopStream = useCallback((sessionId: string) => {
    streamCtl.current[sessionId]?.abort();
    // 告诉后端**真正终止**这一轮 agent 并释放会话锁——否则后端进程还在跑、占着锁，下一句会被拦
    void stopChat(sessionId).catch(() => { /* 后端可能已结束，忽略 */ });
    const a = streamAcc.current[sessionId];
    if (a && (a.content || a.thinking || a.steps.length)) {
      appendAssistant(sessionId, {
        role: 'assistant',
        content: (a.content || '') + '\n\n_（已停止）_',
        thinking: a.thinking || undefined,
        activity: a.steps.join('\n') || undefined,
      });
    }
    clearStream(sessionId);
    // 关键：清掉「本轮进行中」标记，否则下一句被判为「上一条还没跑完」拦下
    setSessions((prev) => {
      const next = prev.map((s) => (s.id === sessionId ? { ...s, pendingTurnId: undefined } : s));
      saveSessions(next);
      return next;
    });
    try { sessionStorage.removeItem(`easel_pending_turn:${sessionId}`); } catch { /* ignore */ }
  }, [appendAssistant, clearStream]);

  const handleSessionRename = useCallback((id: string, title: string) => {
    const t = title.trim();
    if (!t) return;
    setSessions((prev) => {
      const next = prev.map((s) => (s.id === id ? { ...s, title: t } : s));
      saveSessions(next);
      return next;
    });
  }, []);

  const handleSessionArchive = useCallback((id: string, archived: boolean) => {
    setSessions((prev) => {
      const next = prev.map((s) => (s.id === id ? { ...s, archived } : s));
      saveSessions(next);
      return next;
    });
    // 归档当前激活会话 → 切到另一个未归档会话或新建
    if (archived && id === activeSessionId) {
      const rest = sessionsRef.current.filter((s) => s.id !== id && !s.archived);
      if (rest.length) {
        setActiveSessionId(rest[0].id);
      } else {
        const ns = createSession(selectedPersona || undefined);
        setSessions((prev) => { const u = [ns, ...prev]; saveSessions(u); return u; });
        setActiveSessionId(ns.id);
      }
      setCurrentPage('chat');
    }
  }, [activeSessionId, selectedPersona]);

  const handleNewChat = useCallback(() => {
    const newSession = createSession(selectedPersona || undefined);
    setSessions((prev) => {
      const updated = [newSession, ...prev];
      saveSessions(updated);
      return updated;
    });
    setActiveSessionId(newSession.id);
    setCurrentPage('chat');
  }, [selectedPersona]);

  const handleSessionSelect = useCallback((id: string) => {
    setActiveSessionId(id);
    const target = sessions.find(s => s.id === id);
    if (target) {
      setSelectedPersona(target.persona || '');
    }
    setCurrentPage('chat');
  }, [sessions]);

  const handleSessionDelete = useCallback((id: string) => {
    if (!window.confirm('确定删除这条对话？')) return;

    const target = sessionsRef.current.find((s) => s.id === id);
    const wasRunning = Boolean(streamCtl.current[id]);
    const stopped = wasRunning
      ? stopChat(id).catch(() => ({ stopped: false }))
      : Promise.resolve({ stopped: false });
    streamCtl.current[id]?.abort();   // 删除正在流式的会话时中止其流
    clearStream(id);
    try { sessionStorage.removeItem(`easel_pending_turn:${id}`); } catch { /* ignore */ }

    if (target?.sessionKey) {
      // Do not delete OpenClaw's session record while its agent is still
      // writing to it; the stop endpoint waits for backend cleanup first.
      void stopped.then(() => deleteRemoteSession(target.sessionKey as string)).catch(() => {});
    }

    setSessions((prev) => {
      const updated = prev.filter((s) => s.id !== id);
      saveSessions(updated);

      if (id === activeSessionId) {
        if (updated.length > 0) {
          setActiveSessionId(updated[0].id);
        } else {
          const newSession = createSession();
          updated.unshift(newSession);
          saveSessions(updated);
          setActiveSessionId(newSession.id);
        }
      }
      return updated;
    });
  }, [activeSessionId, clearStream]);

  // 首次引导：跳过（用通用模式）
  const dismissRecommend = useCallback(() => {
    localStorage.setItem(ONBOARDING_SEEN_KEY, '1');
    setShowRecommend(false);
  }, []);

  // 打开引导向导
  const openWizard = useCallback(() => {
    setShowRecommend(false);
    setShowWizard(true);
  }, []);

  // 画像创建完成
  const handleProfileCreated = useCallback((name: string) => {
    localStorage.setItem(ONBOARDING_SEEN_KEY, '1');
    setShowWizard(false);
    fetchPersonas().then((list) => {
      setPersonas(list);
      setSelectedPersona(name);
      // 用新画像开一个新会话
      const newSession = createSession(name);
      setSessions((prev) => {
        const updated = [newSession, ...prev];
        saveSessions(updated);
        return updated;
      });
      setActiveSessionId(newSession.id);
      setCurrentPage('profile');
    }).catch(() => {});
  }, []);

  // 画像删除完成：刷新列表 + 若删的是当前选中的则清空选择
  const handleProfileDeleted = useCallback((name: string) => {
    fetchPersonas().then((list) => {
      setPersonas(list);
      setSelectedPersona((cur) => (cur === name ? '' : cur));
    }).catch(() => {});
  }, []);

  // 流式生命周期在 App，页面切换随意——ChatPage 可自由卸载/重挂，回来从 props 读流式态即可。
  const renderPage = () => {
    switch (currentPage) {
      case 'dashboard':
        return (
          <DashboardPage
            persona={selectedPersona}
            gatewayStatus={gatewayStatus}
            onNavigate={setCurrentPage}
            onUseTopic={handleUseTopic}
          />
        );
      case 'chat':
        return activeSession ? (
          <ChatPage
            key={activeSession.id}
            session={activeSession}
            stream={streams[activeSession.id]}
            onSend={(displayText, attachments) => handleSendMessage(activeSession.id, displayText, attachments)}
            onStop={() => handleStopStream(activeSession.id)}
            onResend={(userIndex, displayText, attachments, legacyAgentText) => handleResend(
              activeSession.id, userIndex, displayText, attachments, legacyAgentText,
            )}
          />
        ) : null;
      case 'trends':
        return <TrendsPage onUseTopic={handleUseTopic} />;
      case 'ideas':
        return <IdeasPage onUseTopic={handleUseTopic} />;
      case 'calendar':
        return <CalendarPage />;
      case 'publish':
        return <PublishPage persona={selectedPersona} />;
      case 'breakdown':
        return <BreakdownPage persona={selectedPersona} />;
      case 'skills':
        return <SkillPage persona={selectedPersona} />;
      case 'outputs':
        return <OutputsPage />;
      case 'accounts':
        return <AccountsPage />;
      case 'profile':
        return <ProfilePage persona={selectedPersona} onNewProfile={() => setShowWizard(true)} onDeleted={handleProfileDeleted} />;
      default:
        return null;
    }
  };

  const handlePersonaChange = useCallback((persona: string) => {
    setSelectedPersona(persona);
    setCurrentPage('chat');
    // 修复：选/切画像不再新建空会话丢上下文。就地把当前会话的画像设为新选的、
    // 保留会话 id 与历史（画像只是每轮的系统前缀，中途换安全）。想开新线程用「New Chat」。
    const cur = sessionsRef.current.find((s) => s.id === activeSessionId);
    if (cur) {
      setSessions((prev) => {
        const updated = prev.map((s) =>
          s.id === activeSessionId ? { ...s, persona: persona || undefined } : s);
        saveSessions(updated);
        return updated;
      });
    } else {
      // 无活跃会话（极少）才新建
      const ns = createSession(persona || undefined);
      setSessions((prev) => { const u = [ns, ...prev]; saveSessions(u); return u; });
      setActiveSessionId(ns.id);
    }
  }, [activeSessionId]);

  return (
    <div className="app-layout">
      <Sidebar
        currentPage={currentPage}
        onPageChange={setCurrentPage}
        personas={personas}
        selectedPersona={selectedPersona}
        onPersonaChange={handlePersonaChange}
        onNewProfile={() => setShowWizard(true)}
        sessions={sessions}
        activeSessionId={activeSessionId}
        activeSessionHasMessages={activeSession ? activeSession.messages.length > 0 : false}
        onSessionSelect={handleSessionSelect}
        onSessionDelete={handleSessionDelete}
        onSessionRename={handleSessionRename}
        onSessionArchive={handleSessionArchive}
        onNewChat={handleNewChat}
        gatewayStatus={gatewayStatus}
      />
      <main className="main-content">
        {(['trends', 'ideas', 'calendar', 'publish', 'breakdown'] as Page[]).includes(currentPage) && (
          <SubNav current={currentPage} onNavigate={setCurrentPage} />
        )}
        <div className="page-host">
          {renderPage()}
        </div>
      </main>

      {/* 首次使用：推荐配置画像 */}
      {showRecommend && (
        <div className="overlay">
          <div className="modal" style={{ width: 420, maxWidth: '100%', textAlign: 'center' }}>
            <div style={{ fontSize: 40 }}>👋</div>
            <h2 style={{ margin: '12px 0 8px', fontSize: 20 }}>欢迎使用 Easel</h2>
            <p style={{ color: 'var(--text-secondary)', fontSize: 14, lineHeight: 1.6 }}>
              配置你的账号画像，生成的内容会更贴合你的风格、受众和平台调性。<br />
              大约 2 分钟，也可以随时在侧栏「+ 新建画像」补配。
            </p>
            <div style={{ display: 'flex', gap: 10, marginTop: 20, justifyContent: 'center' }}>
              <button className="btn" onClick={dismissRecommend}>先用通用模式</button>
              <button className="btn btn-primary" onClick={openWizard}>开始配置</button>
            </div>
          </div>
        </div>
      )}

      {/* 画像配置向导 */}
      {showWizard && (
        <OnboardingWizard onClose={() => setShowWizard(false)} onCreated={handleProfileCreated} />
      )}
    </div>
  );
}
