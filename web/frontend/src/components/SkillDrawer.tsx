import { useState, useEffect, useMemo, useRef } from 'react';
import { fetchSkillDetail, executeSkill, saveEnv } from '../lib/api';
import type { SkillDetail } from '../lib/api';
import { renderMarkdown } from '../lib/sanitize';

interface SkillDrawerProps {
  skillName: string;
  persona: string;
  onClose: () => void;
  onConfigured: () => void;   // 保存 API 后通知父组件刷新卡片状态
}

export default function SkillDrawer({ skillName, persona, onClose, onConfigured }: SkillDrawerProps) {
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [loadErr, setLoadErr] = useState('');

  // API 配置输入（env -> 明文，只提交非空项）
  const [envInputs, setEnvInputs] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [savedMsg, setSavedMsg] = useState('');

  // 执行区
  const [input, setInput] = useState('');
  const [result, setResult] = useState('');
  const [running, setRunning] = useState(false);
  const [runErr, setRunErr] = useState('');
  const reqSeq = useRef(0);

  const loadDetail = () => {
    let ignore = false;
    fetchSkillDetail(skillName)
      .then((d) => { if (!ignore) { setDetail(d); setLoadErr(''); } })
      .catch(() => { if (!ignore) setLoadErr('加载 SKILL 详情失败'); });
    return () => { ignore = true; };
  };

  useEffect(loadDetail, [skillName]);

  const bodyHtml = useMemo(() => renderMarkdown(detail?.body || ''), [detail?.body]);
  const resultHtml = useMemo(() => renderMarkdown(result), [result]);

  const handleSaveEnv = async () => {
    const updates = Object.fromEntries(
      Object.entries(envInputs).filter(([, v]) => v.trim() !== '')
    );
    if (Object.keys(updates).length === 0) { setSavedMsg('没有填写新值'); return; }
    setSaving(true);
    setSavedMsg('');
    try {
      await saveEnv(updates);
      setEnvInputs({});
      const seq = ++reqSeq.current;
      const fresh = await fetchSkillDetail(skillName);
      if (seq === reqSeq.current) setDetail(fresh);
      setSavedMsg('已保存 ✓');
      onConfigured();
      setTimeout(() => setSavedMsg(''), 2500);
    } catch (e) {
      setSavedMsg(e instanceof Error ? e.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleRun = async () => {
    if (!input.trim()) return;
    const seq = ++reqSeq.current;
    setRunning(true);
    setRunErr('');
    setResult('');
    try {
      const res = await executeSkill(skillName, input.trim(), persona || undefined);
      if (seq === reqSeq.current) setResult(res.response);
    } catch (e) {
      if (seq === reqSeq.current) setRunErr(e instanceof Error ? e.message : '执行失败');
    } finally {
      if (seq === reqSeq.current) setRunning(false);
    }
  };

  const blocked = detail?.needsApi && !detail.apiConfigured;

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-header">
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
            <div>
              <div className="skill-detail-title">{skillName}</div>
              <div className="skill-detail-meta">
                {detail?.layer && <span className="badge badge-accent">{detail.layer}</span>}
                {detail?.needsApi && (
                  detail.apiConfigured
                    ? <span className="badge badge-ok">✓ 已配置</span>
                    : <span className="badge badge-warn">❗ 需配置 API</span>
                )}
              </div>
            </div>
            <button className="icon-btn" onClick={onClose} title="关闭">×</button>
          </div>
        </div>

        <div className="drawer-body">
          {loadErr && <div style={{ color: 'var(--red)', fontSize: 14 }}>{loadErr}</div>}

          {/* API 配置 */}
          {detail?.needsApi && detail.apiSpec && (
            <div className="panel">
              <div className="panel-title">🔑 {detail.apiSpec.label} · API 配置
                <span style={{ fontWeight: 400, color: 'var(--text-secondary)', fontSize: 12 }}>
                  （任选一个服务商填齐即可用）
                </span>
              </div>
              {detail.apiSpec.settings.length > 0 && (
                <div className="provider-block">
                  <div className="provider-head"><strong style={{ fontSize: 13 }}>默认选择与能力</strong></div>
                  {detail.apiSpec.settings.map((k) => (
                    <div key={k.env}>
                      <label className="field-label">
                        {k.label} · 可选
                        {k.configured && <span style={{ color: 'var(--green)', marginLeft: 6 }}>
                          已配置{k.masked ? `：${k.masked}` : ''}
                        </span>}
                      </label>
                      {k.choices.length > 0 ? (
                        <select
                          className="field"
                          value={envInputs[k.env] ?? ''}
                          onChange={(e) => setEnvInputs((p) => ({ ...p, [k.env]: e.target.value }))}
                        >
                          <option value="">{k.configured ? `当前：${k.masked}` : `请选择 ${k.env}`}</option>
                          {k.choices.map((choice) => <option key={choice} value={choice}>{choice}</option>)}
                        </select>
                      ) : (
                        <input
                          className="field"
                          type={k.secret ? 'password' : 'text'}
                          placeholder={k.configured ? '留空则保持不变，输入以覆盖' : `请输入 ${k.env}`}
                          value={envInputs[k.env] || ''}
                          onChange={(e) => setEnvInputs((p) => ({ ...p, [k.env]: e.target.value }))}
                        />
                      )}
                    </div>
                  ))}
                </div>
              )}
              {detail.apiSpec.providers.map((prov) => {
                const provOk = prov.keys.filter(k => k.required).every(k => k.configured);
                return (
                  <div key={prov.id} className={`provider-block ${provOk ? 'configured' : ''}`}>
                    <div className="provider-head">
                      <strong style={{ fontSize: 13 }}>{prov.name}</strong>
                      {provOk
                        ? <span className="badge badge-ok">✓ 就绪</span>
                        : <span className="badge">未配置</span>}
                    </div>
                    {prov.keys.map((k) => (
                      <div key={k.env}>
                        <label className="field-label">
                          {k.label}{k.required ? '' : ' · 可选'}
                          {k.configured && <span style={{ color: 'var(--green)', marginLeft: 6 }}>
                            已配置{k.secret && k.masked ? `（${k.masked}）` : k.masked ? `：${k.masked}` : ''}
                          </span>}
                        </label>
                        {k.choices.length > 0 ? (
                          <select className="field" value={envInputs[k.env] ?? ''}
                            onChange={(e) => setEnvInputs((p) => ({ ...p, [k.env]: e.target.value }))}>
                            <option value="">{k.configured ? `当前：${k.masked}` : `请选择 ${k.env}`}</option>
                            {k.choices.map((choice) => <option key={choice} value={choice}>{choice}</option>)}
                          </select>
                        ) : (
                          <input
                            className="field"
                            type={k.secret ? 'password' : 'text'}
                            placeholder={k.configured ? '留空则保持不变，输入以覆盖' : `请输入 ${k.env}`}
                            value={envInputs[k.env] || ''}
                            onChange={(e) => setEnvInputs((p) => ({ ...p, [k.env]: e.target.value }))}
                          />
                        )}
                      </div>
                    ))}
                  </div>
                );
              })}
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 8 }}>
                <button className="btn btn-primary btn-sm" onClick={handleSaveEnv} disabled={saving}>
                  {saving ? '保存中…' : '保存到 .env'}
                </button>
                {savedMsg && <span style={{ fontSize: 13, color: savedMsg.includes('✓') ? 'var(--green)' : 'var(--text-secondary)' }}>{savedMsg}</span>}
              </div>
            </div>
          )}

          {/* 执行 */}
          <div className="panel">
            <div className="panel-title">▶ 运行</div>
            {blocked && (
              <div style={{ fontSize: 13, color: 'var(--amber)', marginBottom: 10 }}>
                该 SKILL 需要先配置上面的 API 才能运行。
              </div>
            )}
            <textarea
              className="field"
              placeholder="输入内容，例如主题 / 素材 / 要求…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              style={{ minHeight: 100 }}
            />
            <div style={{ marginTop: 10 }}>
              <button className="btn btn-primary" onClick={handleRun} disabled={running || !input.trim() || blocked}>
                {running
                  ? <><span className="spinner" style={{ width: 14, height: 14, margin: 0 }} />执行中…</>
                  : '执行'}
              </button>
            </div>
            {runErr && <div style={{ color: 'var(--red)', fontSize: 13, marginTop: 10 }}>{runErr}</div>}
            {resultHtml && (
              <div className="skill-result" dangerouslySetInnerHTML={{ __html: resultHtml }} />
            )}
          </div>

          {/* 描述 */}
          <div className="panel">
            <div className="panel-title">📖 说明</div>
            {detail
              ? <div className="skill-body-md" dangerouslySetInnerHTML={{ __html: bodyHtml }} />
              : !loadErr && <div className="loading"><div className="spinner" />加载中…</div>}
          </div>
        </div>
      </div>
    </div>
  );
}
