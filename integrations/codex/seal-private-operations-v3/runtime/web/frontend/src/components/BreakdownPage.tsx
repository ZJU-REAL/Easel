import { useState } from 'react';
import { runAgent, createIdea } from '../lib/api';
import { renderMarkdown } from '../lib/sanitize';
import { IconFire, IconIdea, IconSkills } from './icons';

interface BreakdownPageProps {
  persona: string;
}

export default function BreakdownPage({ persona }: BreakdownPageProps) {
  const [input, setInput] = useState('');
  const [result, setResult] = useState('');
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState('');

  const run = async () => {
    if (!input.trim()) return;
    setLoading(true); setResult('');
    const prompt =
      `你是爆款内容拆解专家。拆解下面这条内容，用中文分点输出：\n` +
      `1. **一句话概括**\n` +
      `2. **钩子拆解**：开头为什么抓人\n` +
      `3. **结构套路**：分段/节奏/信息编排\n` +
      `4. **为什么会火**：情绪/共鸣/实用/争议点\n` +
      `5. **可复制模板**：把套路抽象成我能直接套用的结构框架\n` +
      `6. **借这个套路${persona ? `、结合我的画像「${persona}」` : ''}可做的 3 个选题**\n\n` +
      `待拆解内容：\n${input}`;
    try {
      const res = await runAgent(prompt, persona);
      setResult(res.response);
    } catch (e) {
      setResult(e instanceof Error ? e.message : '拆解失败，请重试');
    } finally { setLoading(false); }
  };

  const saveToIdeas = async () => {
    if (!result) return;
    const firstLine = input.trim().split('\n')[0].slice(0, 24);
    await createIdea({ title: `拆解模板：${firstLine}`, note: result, source: '爆款拆解', status: 'pending' });
    setToast('已存入选题库');
    setTimeout(() => setToast(''), 2200);
  };

  return (
    <div className="page-scroll breakdown-page">
      <div className="page-head">
        <div>
          <h1 className="page-title"><IconFire size={21} /> 爆款拆解</h1>
          <p className="page-subtitle">贴一条对标/爆款内容，AI 拆出钩子、结构、火的原因，并给你可复制的模板与选题。</p>
        </div>
      </div>

      <div className="breakdown-body">
        <textarea className="field" style={{ minHeight: 160 }} value={input}
          placeholder="把对标账号的爆款文案 / 你收藏的内容粘贴进来…"
          onChange={(e) => setInput(e.target.value)} />
        <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
          <button className="btn btn-primary" disabled={loading || !input.trim()} onClick={run}>
            <IconSkills size={15} /> {loading ? '拆解中…' : '开始拆解'}
          </button>
          {result && <button className="btn" onClick={saveToIdeas}><IconIdea size={14} /> 存入选题库</button>}
          {result && <button className="btn btn-ghost" onClick={() => { setResult(''); setInput(''); }}>清空</button>}
        </div>

        {loading && <div className="loading" style={{ padding: 40 }}><div className="spinner" />AI 正在拆解…</div>}
        {result && !loading && (
          <div className="panel" style={{ marginTop: 18 }}>
            <div className="panel-title"><IconFire size={14} /> 拆解结果</div>
            <div className="skill-body-md" dangerouslySetInnerHTML={{ __html: renderMarkdown(result) }} />
          </div>
        )}
      </div>

      {toast && <div className="toast ok"><span className="toast-icon">✓</span>{toast}</div>}
    </div>
  );
}
