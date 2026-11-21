import { useEffect, useRef, useState } from 'react';
import { fetchHarnessModels, fetchHarnessSettings, saveHarnessSettings } from '../lib/api';
import type { HarnessModel, HarnessSettingsResponse } from '../lib/api';
import SettingsSelect from './SettingsSelect';
import CodexConnection from './CodexConnection';

export default function HarnessSettings({ onChange, onSelect, previewRequest, onPreviewHandled }: {
  onChange: (runtime: string) => void;
  onSelect: (runtime: string) => void;
  previewRequest?: { runtime: string };
  onPreviewHandled?: () => void;
}) {
  const [settings, setSettings] = useState<HarnessSettingsResponse | null>(null);
  const [runtime, setRuntime] = useState('api');
  const [model, setModel] = useState('');
  const [effort, setEffort] = useState('');
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const [catalogs, setCatalogs] = useState<Record<string, HarnessModel[]>>({});
  const [modelLoading, setModelLoading] = useState(false);
  const [modelNote, setModelNote] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const modelRequest = useRef(0);
  const handledPreview = useRef<{ runtime: string } | undefined>(undefined);

  useEffect(() => {
    let alive = true;
    setSettingsLoading(true);
    setNote('');
    fetchHarnessSettings().then((value) => {
      if (!alive) return;
      setSettings(value);
      setRuntime(value.runtime);
      setModel(value.models[value.runtime] || '');
      setEffort(value.codex_effort || '');
      onChange(value.runtime);
      onSelect(value.runtime);
    }).catch((error) => {
      if (alive) setNote(`读取失败：${error instanceof Error ? error.message : String(error)}`);
    }).finally(() => {
      if (alive) setSettingsLoading(false);
    });
    return () => { alive = false; modelRequest.current += 1; };
  }, [onChange, onSelect, refresh]);

  // A session or a detected local CLI can request a preview without changing the saved engine.
  useEffect(() => {
    if (!previewRequest || previewRequest === handledPreview.current || settingsLoading || !settings || busy) return;
    handledPreview.current = previewRequest;
    onPreviewHandled?.();
    if (settings.locked) {
      setNote('启动环境已固定底座，无法切换执行引擎。');
      return;
    }
    const agent = settings.agents.find((item) => item.id === previewRequest.runtime);
    if (!agent) return;
    setRuntime(agent.id);
    setModel(settings.models[agent.id] || '');
    setEffort(settings.codex_effort || '');
    modelRequest.current += 1;
    setModelLoading(false);
    setModelNote('');
    setNote('');
    onSelect(agent.id);
  }, [previewRequest, settingsLoading, settings, busy, onSelect, onPreviewHandled]);

  const selected = settings?.agents.find((agent) => agent.id === runtime);
  const nativeModels = catalogs[runtime] || [];
  const pullModels = async () => {
    const requested = runtime;
    const sequence = ++modelRequest.current;
    setModelLoading(true);
    setModelNote('');
    try {
      const result = await fetchHarnessModels(requested);
      if (modelRequest.current !== sequence) return;
      setCatalogs((previous) => ({ ...previous, [requested]: result.models }));
      if (!result.models.length) setModelNote('原生 CLI 没有返回模型，可使用默认模型或手动填写。');
    } catch (error) {
      if (modelRequest.current === sequence) {
        setModelNote(`读取失败：${error instanceof Error ? error.message : String(error)}`);
      }
    } finally {
      if (modelRequest.current === sequence) setModelLoading(false);
    }
  };
  const save = async () => {
    setBusy(true);
    setNote('');
    try {
      const value = await saveHarnessSettings(runtime, model, undefined, undefined,
        runtime === 'codex' ? effort : undefined);
      setSettings(value);
      onChange(value.runtime);
      setNote('已保存，请新建对话以使用这组设置。');
    } catch (error) {
      setNote(`保存失败：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setBusy(false);
    }
  };

  const hasCatalog = ['codex', 'opencode', 'hermes'].includes(runtime);
  const native = runtime !== 'api' && runtime !== 'openclaw';
  const changed = settings && (runtime !== settings.runtime || model !== (settings.models[runtime] || '')
    || (runtime === 'codex' && effort !== (settings.codex_effort || '')));

  const modelInput = (
    <input id="harness-model" className="mock" value={model} disabled={busy || settings?.locked} maxLength={240}
      onChange={event => { setModel(event.target.value); setEffort(''); }}
      placeholder={runtime === 'codex' ? '留空使用 Codex 原生配置'
        : runtime === 'hermes' ? '留空使用 Hermes 原生配置' : 'provider/model；留空使用原生配置'} />
  );
  const effortOptions = nativeModels.find(item => model ? item.id === model : item.default)?.efforts || [];

  return (
    <section className="st-panel active harness-settings" aria-label="Agent 底座设置">
      <div className="engine-summary">
        <div className="engine-identity">
          <span className="engine-symbol" aria-hidden="true"><svg width="23" height="23" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="m4.5 6.5 6 5.5-6 5.5M13 17.5h6.5" /></svg></span>
          <div className="engine-choice"><div className="form-caption">执行引擎
            {settings && <span className={'engine-state' + (changed ? ' pending' : '')}>{changed ? '待应用' : '已应用'}</span>}
          </div>
          <SettingsSelect label="执行引擎" value={runtime} disabled={!settings || settingsLoading || busy || settings.locked}
              options={(settings?.agents || [{ id: 'api', label: '仅聊天模式', installed: true }])
                .map((agent) => ({
                value: agent.id,
                label: `${agent.label}${agent.installed ? '' : '（未安装 / 未配置）'}`,
              }))}
              onChange={(value) => {
                setRuntime(value);
                setModel(settings?.models[value] || '');
                setEffort(settings?.codex_effort || '');
                modelRequest.current += 1;
                setModelLoading(false);
                setModelNote('');
                setNote('');
                onSelect(value);
              }} />
          </div>
        </div>
        <div className="engine-actions">
          <button className="btn btn-sm engine-apply" disabled={!settings || settingsLoading || busy || settings.locked || !selected?.installed}
            onClick={() => void save()}>{busy ? '保存中…' : '应用设置'}</button>
          <button className="btn btn-sm engine-reload" disabled={settingsLoading || busy}
            onClick={() => setRefresh(previous => previous + 1)}>{settingsLoading ? '读取中…' : '重新读取'}</button>
        </div>
      </div>
      {note && <div className={'save-note' + (note.includes('失败') ? ' err' : '')} role="status">{note}</div>}
      {settings?.locked && <p className="engine-notice">启动环境 EASEL_AGENT_RUNTIME 已固定底座，请修改启动环境后重启。</p>}
      {settings && runtime !== settings.runtime && <p className="engine-notice">当前为配置预览。应用后，新对话将使用所选引擎。</p>}
      {selected && !selected.installed && <div className="engine-notice" role="status">未检测到 {selected.label}。原有配置未删除。请确认 CLI 已安装在服务所用账户，更新 PATH 后重启画板。
        {selected.install_hint && <code>{selected.install_hint}</code>}</div>}
      {!native && <div className="engine-api-note">{runtime === 'api' ? '模型 API 直连，无需安装 Agent。' : 'OpenClaw 的模型、API 地址和 Key 在下方配置。'}
        {runtime === 'api' && <span className="settings-help">
              <button type="button" className="settings-help-trigger" aria-label="仅聊天模式说明"
                aria-describedby="chat-only-help">ⓘ</button>
              <span id="chat-only-help" className="settings-help-tooltip" role="tooltip">
                仅聊天模式直接调用模型 API，适合问答、写作和内容分析，不启动 Agent，
                不能操作本机文件、运行命令、使用浏览器或执行技能。请在下方配置模型、API 地址和 Key；
                需要工具时可切换到 OpenClaw、OpenCode、Codex、Hermes 或其它 Agent。切换后请新建对话，旧历史保留。
              </span>
            </span>}</div>}
      {native && <section className="engine-form">
        <h3>生成参数</h3>
        <div className="engine-form-grid">
          <div className="engine-field">
            <span className="form-caption">模型</span>
            {hasCatalog ? <div className="engine-model-row">
              <SettingsSelect label="原生模型" value={model} disabled={busy || settings?.locked}
                    options={[
                      { value: '', label: '引擎默认模型' },
                      ...nativeModels.map((item) => ({ value: item.id,
                        label: `${item.label}${item.default ? '（原生默认）' : ''}` })),
                      ...(model && !nativeModels.some((item) => item.id === model)
                        ? [{ value: model, label: model }] : []),
                    ]} onChange={(value) => { setModel(value); setEffort(''); }} />
                  <button className="btn btn-sm" disabled={modelLoading || busy || !selected?.installed}
                    onClick={() => void pullModels()}>{modelLoading ? '读取中…' : '拉取模型'}</button>
            </div> : <label className="manual-model">模型标识{modelInput}</label>}
          </div>
          {runtime === 'codex' && <div className="engine-field">
            <span className="form-caption">推理强度</span>
            <SettingsSelect label="Codex 推理强度" value={effort} disabled={busy || settings?.locked}
                  options={[
                    { value: '', label: '引擎默认强度' },
                    ...effortOptions.map(value => ({ value, label: value })),
                    ...(effort && !effortOptions.includes(effort)
                      ? [{ value: effort, label: effort }] : []),
                  ]} onChange={setEffort} />
          </div>}
        </div>
        {modelNote && <p className="engine-note" role="status">{modelNote}</p>}
        {hasCatalog && <details className="engine-details" key={runtime}><summary>手动填写模型</summary>
          <label className="manual-model">模型标识{modelInput}</label>
          <p>留空使用引擎默认模型。拉取模型后可选择它支持的推理强度。</p>
        </details>}
      </section>}
      {runtime === 'codex' && <CodexConnection model={model} effort={effort} disabled={!selected?.installed || settingsLoading} />}
      {native && <details className="engine-details engine-info"><summary>引擎与认证说明</summary>
        <p>{selected?.protocol ? selected.protocol + ' · ' : ''}连接由适配器管理，无需另选连接方式。认证沿用本机 CLI 配置，工具审批在「访问权限」中设置。</p>
        {runtime === 'codex' && <p>登录后可用「测试连接」确认模型可用。</p>}
        {runtime !== 'codex' && <p>检测到 CLI 不代表模型已登录。应用后可发送消息验证。</p>}
        {runtime === 'hermes' && <p>Hermes 使用独立的 easel profile。请先创建并配置该 profile，再将 Easel 技能同步到它的 HERMES_HOME。</p>}
      </details>}
    </section>
  );
}
