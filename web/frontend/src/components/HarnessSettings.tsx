import { useEffect, useRef, useState } from 'react';
import { fetchHarnessModels, fetchHarnessSettings, saveHarnessSettings } from '../lib/api';
import type { HarnessModel, HarnessSettingsResponse } from '../lib/api';
import SettingsSelect from './SettingsSelect';

export default function HarnessSettings({ onChange, onSelect }: {
  onChange: (runtime: string) => void;
  onSelect: (runtime: string) => void;
}) {
  const [settings, setSettings] = useState<HarnessSettingsResponse | null>(null);
  const [runtime, setRuntime] = useState('api');
  const [model, setModel] = useState('');
  const [sandbox, setSandbox] = useState('workspace-write');
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const [catalogs, setCatalogs] = useState<Record<string, HarnessModel[]>>({});
  const [modelLoading, setModelLoading] = useState(false);
  const [modelNote, setModelNote] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const modelRequest = useRef(0);

  useEffect(() => {
    let alive = true;
    setSettingsLoading(true);
    setNote('');
    fetchHarnessSettings().then((value) => {
      if (!alive) return;
      setSettings(value);
      setRuntime(value.runtime);
      setModel(value.models[value.runtime] || '');
      setSandbox(value.sandbox);
      onChange(value.runtime);
      onSelect(value.runtime);
    }).catch((error) => {
      if (alive) setNote(`读取失败：${error instanceof Error ? error.message : String(error)}`);
    }).finally(() => {
      if (alive) setSettingsLoading(false);
    });
    return () => { alive = false; modelRequest.current += 1; };
  }, [onChange, onSelect, refresh]);

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
      const value = await saveHarnessSettings(runtime, model, sandbox);
      setSettings(value);
      onChange(value.runtime);
      setNote('已保存，请新建对话；旧对话仍保留在原底座，不迁移历史。');
    } catch (error) {
      setNote(`保存失败：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="st-panel active harness-settings" aria-label="Agent 底座设置">
      <div className="panel-top">
        <strong>Agent 底座</strong>
        <span className="desc">选择仅聊天，或使用 Agent 执行工具</span>
        <span className="spacer" />
        <button className="btn btn-sm" disabled={!settings || settingsLoading || busy || settings.locked || !selected?.installed}
          onClick={() => void save()}>{busy ? '保存中…' : '保存底座'}</button>
        <button className="btn btn-sm" disabled={settingsLoading || busy}
          onClick={() => setRefresh((previous) => previous + 1)}>{settingsLoading ? '读取中…' : '重新读取'}</button>
      </div>
      <div className="settings-field">
        <span className="settings-field-label">执行引擎</span>
        <div className="settings-field-body">
          <div className="settings-engine-control">
            <SettingsSelect label="执行引擎" value={runtime} disabled={!settings || settingsLoading || busy || settings.locked}
              options={(settings?.agents || [{ id: 'api', label: '仅聊天模式', installed: true }])
                .map((agent) => ({
                value: agent.id,
                label: `${agent.label}${agent.installed ? '' : '（未安装 / 未配置）'}`,
              }))}
              onChange={(value) => {
                setRuntime(value);
                setModel(settings?.models[value] || '');
                modelRequest.current += 1;
                setModelLoading(false);
                setModelNote('');
                setNote('');
                onSelect(value);
              }} />
            <span className="settings-help">
              <button type="button" className="settings-help-trigger" aria-label="仅聊天模式说明"
                aria-describedby="chat-only-help">ⓘ</button>
              <span id="chat-only-help" className="settings-help-tooltip" role="tooltip">
                仅聊天模式直接调用模型 API，适合问答、写作和内容分析，不启动 Agent，
                不能操作本机文件、运行命令、使用浏览器或执行技能。请在下方配置模型、API 地址和 Key；
                需要工具时可切换到 OpenClaw、OpenCode、Codex 或其它 Agent。切换后请新建对话，旧历史保留。
              </span>
            </span>
          </div>
          <p className="desc">{runtime === 'api' ? '模型 API 直连 · 无需安装 Agent，模型在下方配置'
            : runtime === 'openclaw' ? 'OpenClaw 的模型、API 地址和 Key 在下方配置，保存后同步到 gateway'
            : `${selected?.protocol || ''} · 连接由适配器管理，无需另选连接方式`}</p>
          <p className="desc">安装时可选择 OpenClaw，也可先跳过，进入这里选择已安装的其它引擎。选择引擎可查看对应配置，只有「保存底座」才切换；认证沿用各引擎自身配置。</p>
          {selected && !selected.installed && (
            <p className="desc" role="status">未检测到 {selected.label}。请确认 CLI 已安装在运行 Web 的服务器账户下，并检查启动 PATH；
              安装或调整路径后重启 Web。原有配置未删除，安装前不能保存为执行引擎。</p>
          )}
          {runtime !== settings?.runtime && <p className="desc">当前为配置预览；请先「保存底座」，再保存下方 API 配置。旧对话不迁移。</p>}
        </div>
      </div>
      {runtime !== 'openclaw' && runtime !== 'api' && (
        <>
          <div className="settings-field">
            <label className="settings-field-label" htmlFor="harness-model">模型覆盖</label>
            <div className="settings-field-body">
              {(runtime === 'codex' || runtime === 'opencode') && (
                <div className="settings-native-models">
                  <SettingsSelect label="原生模型" value={model} disabled={busy || settings?.locked}
                    options={[
                      { value: '', label: '使用原生默认模型' },
                      ...nativeModels.map((item) => ({ value: item.id,
                        label: `${item.label}${item.default ? '（原生默认）' : ''}` })),
                      ...(model && !nativeModels.some((item) => item.id === model)
                        ? [{ value: model, label: `${model}（当前 / 自定义）` }] : []),
                    ]} onChange={setModel} />
                  <button className="btn btn-sm" disabled={modelLoading || busy || !selected?.installed}
                    onClick={() => void pullModels()}>{modelLoading ? '读取中…' : '拉取模型'}</button>
                </div>
              )}
              <input id="harness-model" className="mock" value={model} disabled={busy || settings?.locked} maxLength={240}
              onChange={(event) => setModel(event.target.value)}
              placeholder={runtime === 'codex' ? '留空使用 Codex 原生配置' : 'provider/model；留空使用原生配置'} />
              <p className="desc">可从原生 CLI 列表选择，也可手动填写；留空沿用原生默认模型，不修改其它底座的供应商配置。
                模型是否可用仍取决于当前账号、供应商和原生 CLI 支持。</p>
              {modelNote && <p className="desc" role="status">{modelNote}</p>}
            </div>
          </div>
          {runtime === 'codex' && (
            <div className="settings-field">
              <span className="settings-field-label">Codex 沙箱</span>
              <div className="settings-field-body">
                <SettingsSelect label="Codex 沙箱" value={sandbox} disabled={busy || settings?.locked}
                  options={[
                    { value: 'workspace-write', label: '项目工作区写入' },
                    { value: 'read-only', label: '只读' },
                  ]}
                  onChange={setSandbox} />
                <p className="desc">额外权限逐次确认，不自动授予完全访问权限。</p>
              </div>
            </div>
          )}
          <p className="desc">认证由原生 CLI 管理，Easel 不迁移密钥。工具请求额外权限时需在对话中确认；
            OpenCode / 通用 ACP 使用其原生权限策略，不是 Codex 沙箱。</p>
          <p className="desc"><code>{selected?.install_hint}</code></p>
          <p className="desc">“已安装”仅表示找到 CLI，不代表模型已登录；保存后请发送消息验证。</p>
        </>
      )}
      {settings?.locked && <p className="desc">启动环境 EASEL_AGENT_RUNTIME 已固定底座，请修改启动环境后重启。</p>}
      {note && <div className={`save-note${note.includes('失败') ? ' err' : ''}`} role="status">{note}</div>}
    </section>
  );
}
