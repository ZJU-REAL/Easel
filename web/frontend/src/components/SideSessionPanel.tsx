import { useState, useRef, useEffect, useMemo } from 'react';
import type { ChatSession, StreamState } from '../lib/store';
import { parseSeedMessage } from '../lib/side-session';

interface SideSessionPanelProps {
  mainSession: ChatSession;                     // 面板锚定的主会话
  sideSessions: ChatSession[];                  // 该主会话的全部旁路会话
  openSideId: string | null;                    // chat 模式打开的旁路会话；null = list 模式
  stream?: StreamState;                         // 打开中的旁路会话的流式态
  onClose: () => void;                          // 关闭整个面板
  onSelectSide: (id: string | null) => void;    // 切换 chat/list 模式
  onDerive: (turns: number | 'all') => void;    // 新建旁路会话（携带主会话最近 N 轮）
  onSend: (sideId: string, text: string) => void;
  onStop: (sideId: string) => void;
  onBringBack: (sideId: string, summary: string) => void;
  onDeleteSide: (sideId: string) => void;
}

const GRAN_OPTIONS = [5, 10, 20, 'all'] as const;

/** 带回摘要草稿：逐轮 `用户：…` / `助手：…`（纯前端确定性生成，无模型摘要）。 */
function buildBringBackDraft(side: ChatSession): string {
  // seed（首条交接消息）不进摘要；其后才是旁路会话的真实往返
  const turns = side.messages.slice(1);
  if (!turns.length) return '';
  return turns
    .map((m) => `${m.role === 'user' ? '用户' : '助手'}：${m.content.trim()}`)
    .join('\n\n');
}

export default function SideSessionPanel({
  mainSession, sideSessions, openSideId, stream,
  onClose, onSelectSide, onDerive, onSend, onStop, onBringBack, onDeleteSide,
}: SideSessionPanelProps) {
  const [granOpen, setGranOpen] = useState(false);
  const [input, setInput] = useState('');
  const [bringOpen, setBringOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const [brought, setBrought] = useState<string | null>(null);  // 已带回过的旁路会话 id（提示用）
  const isComposingRef = useRef(false);
  const msgsEndRef = useRef<HTMLDivElement>(null);
  const draftRef = useRef<HTMLTextAreaElement>(null);

  const side = openSideId ? sideSessions.find((s) => s.id === openSideId) || null : null;
  const isStreaming = !!stream;

  // 进入 chat 模式时重置面板内局部状态
  useEffect(() => {
    setInput(''); setBringOpen(false); setGranOpen(false);
    setBrought((prev) => (prev === openSideId ? prev : null));
  }, [openSideId]);

  // 打开带回表单：预填确定性草稿
  const openBringForm = () => {
    if (!side) return;
    setDraft(buildBringBackDraft(side));
    setBringOpen(true);
    requestAnimationFrame(() => draftRef.current?.focus());
  };

  const confirmBringBack = () => {
    if (!side) return;
    const text = draft.trim();
    if (!text) return;
    onBringBack(side.id, text);
    setBringOpen(false);
    setBrought(side.id);
  };

  // 消息区自动滚底（流式增量也跟随）
  useEffect(() => {
    if (side) msgsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [side?.messages.length, stream?.content, side?.id]);

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed || isStreaming || !side) return;
    onSend(side.id, trimmed);
    setInput('');
  };

  // seed 首条消息解析（紧凑卡片用）；解析失败按普通消息渲染
  const seed = useMemo(
    () => (side && side.messages.length > 0 ? parseSeedMessage(side.messages[0].content) : null),
    [side],
  );

  if (!side) {
    // ---- list 模式 ----
    return (
      <aside className="ssp" onClick={(e) => e.stopPropagation()}>
        <header className="ssp-head">
          <span className="ssp-title">⤷ 旁路会话</span>
          <button className="ssp-x" onClick={onClose} title="关闭">×</button>
        </header>
        <div className="ssp-sub">{sideSessions.length ? `${sideSessions.length} 条 · 与主对话互不污染` : '与主对话互不污染的试错 / 探索对话'}</div>
        <div className="ssp-list">
          {sideSessions.map((sd) => (
            <div key={sd.id} className="ssp-item">
              <button className="ssp-item-main" onClick={() => onSelectSide(sd.id)} title={sd.title}>
                <span className="ssp-item-title">{sd.title}</span>
                <span className="ssp-item-meta">{sd.messages.length > 1 ? `${Math.ceil((sd.messages.length - 1) / 2)} 轮` : '尚未开局'}</span>
              </button>
              <button className="ssp-item-x" onClick={() => onDeleteSide(sd.id)} title="删除">×</button>
            </div>
          ))}
          {!sideSessions.length && <div className="ssp-empty">还没有旁路会话。新建一个，携带主会话最近的上下文开局。</div>}
        </div>
        {!granOpen ? (
          <button className="ssp-new" onClick={() => setGranOpen(true)}>＋ 新建旁路会话</button>
        ) : (
          <div className="ssp-gran">
            <div className="ssp-gran-label">携带「{mainSession.title}」最近：</div>
            <div className="ssp-gran-opts">
              {GRAN_OPTIONS.map((n) => (
                <button key={String(n)} className="ssp-gran-opt"
                  onClick={() => { setGranOpen(false); onDerive(n); }}>
                  {n === 'all' ? '全部轮次' : `${n} 轮`}
                </button>
              ))}
            </div>
            <button className="ssp-gran-cancel" onClick={() => setGranOpen(false)}>取消</button>
          </div>
        )}
      </aside>
    );
  }

  // ---- chat 模式 ----
  const displayMessages = [...side.messages];
  if (isStreaming) displayMessages.push({ role: 'assistant', content: stream!.content || '' });

  return (
    <aside className="ssp" onClick={(e) => e.stopPropagation()}>
      <header className="ssp-head">
        <button className="ssp-back" onClick={() => onSelectSide(null)} title="返回旁路会话列表">←</button>
        <span className="ssp-title ssp-title-ellipsis" title={side.title}>{side.title}</span>
        <button className="ssp-bring-btn" onClick={openBringForm} disabled={side.messages.length <= 1}
          title="把这段旁路对话的结论整理后带回主会话">带回主会话</button>
        <button className="ssp-x" onClick={onClose} title="关闭">×</button>
      </header>

      {bringOpen && (
        <div className="ssp-bring">
          <div className="ssp-bring-label">带回内容（可编辑，将以一条消息写入主会话）：</div>
          <textarea ref={draftRef} className="ssp-bring-text" value={draft}
            onChange={(e) => setDraft(e.target.value)} rows={6} />
          <div className="ssp-bring-bar">
            <button className="ssp-bring-cancel" onClick={() => setBringOpen(false)}>不带回</button>
            <button className="ssp-bring-ok" onClick={confirmBringBack} disabled={!draft.trim()}>带回主会话</button>
          </div>
        </div>
      )}
      {!bringOpen && brought === side.id && (
        <div className="ssp-brought-note">已作为一条消息带回主会话 ✓</div>
      )}

      <div className="ssp-msgs">
        {displayMessages.map((msg, i) => {
          // 首条 seed 用紧凑卡片渲染（不展开全部快照内容）
          if (i === 0 && seed) {
            return (
              <div key="seed" className="ssp-seed" title={side.messages[0].content}>
                <span className="ssp-seed-tag">交接上下文</span>
                来自「{seed.mainTitle}」最近 {seed.turnsLabel} 轮 · {seed.items.length} 条
              </div>
            );
          }
          const live = isStreaming && i === displayMessages.length - 1 && msg.role === 'assistant';
          return (
            <div key={i} className={`ssp-msg ssp-msg-${msg.role}`}>
              <div className={`ssp-bubble ${msg.role === 'user' ? 'ssp-bubble-user' : 'ssp-bubble-assistant'}`}>
                {msg.content}
                {live && <span className="ssp-cursor" />}
              </div>
              {live && stream!.thinking && <div className="ssp-thinking">{stream!.thinking}</div>}
            </div>
          );
        })}
        <div ref={msgsEndRef} />
      </div>

      <div className="ssp-input">
        <textarea
          className="ssp-text"
          placeholder={isStreaming ? '生成中…' : '在旁路会话里继续对话…'}
          value={input}
          rows={2}
          onChange={(e) => setInput(e.target.value)}
          onCompositionStart={() => { isComposingRef.current = true; }}
          onCompositionEnd={() => { isComposingRef.current = false; }}
          onKeyDown={(e) => {
            if (isComposingRef.current || e.nativeEvent.isComposing || e.nativeEvent.keyCode === 229) return;
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
          }}
        />
        <div className="ssp-input-bar">
          <span className="ssp-hint">{isStreaming ? '生成中…' : 'Enter 发送'}</span>
          {isStreaming ? (
            <button className="ssp-send" onClick={() => onStop(side.id)} title="停止生成">■</button>
          ) : (
            <button className="ssp-send" onClick={handleSend} disabled={!input.trim()} title="发送">↑</button>
          )}
        </div>
      </div>
    </aside>
  );
}
