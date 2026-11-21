import { useEffect, useState } from 'react';
import { fetchPublishingPolicy } from '../lib/api';
import type { PublishingPolicy } from '../lib/api';
import AutomatedPublishPage from './PublishPage';
import ManualPublishPage from './ManualPublishPage';

export default function PublishingPage({ persona }: { persona: string }) {
  const [policy, setPolicy] = useState<PublishingPolicy | null>(null);
  const [mode, setMode] = useState<PublishingPolicy['mode']>('automated');
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setError('');
    fetchPublishingPolicy().then((value) => {
      if (active) {
        setPolicy(value);
        setMode(value.mode === 'automated' && value.automaticSubmission ? 'automated' : 'manual');
      }
    })
      .catch(() => { if (active) setError('无法读取发布方式，请重试。'); });
    return () => { active = false; };
  }, [retry]);
  if (error) return <div className="panel" role="alert">{error}
    <button className="btn btn-sm" onClick={() => setRetry((value) => value + 1)}>重新读取</button>
  </div>;
  if (!policy) return <div className="dash-empty">正在读取发布方式…</div>;
  const automaticAllowed = policy.mode === 'automated' && policy.automaticSubmission;
  const manual = mode === 'manual' || !automaticAllowed;
  return <div className="publishing-workspace">
    <div className="publishing-mode-bar">
      <div className="subnav-tabs" role="group" aria-label="发布方式">
        <button type="button" className={`subnav-tab ${!manual ? 'active' : ''}`}
          aria-pressed={!manual} disabled={!automaticAllowed} onClick={() => setMode('automated')}>
          自动发布
        </button>
        <button type="button" className={`subnav-tab ${manual ? 'active' : ''}`}
          aria-pressed={manual} onClick={() => setMode('manual')}>
          人工审核发布
        </button>
      </div>
      <span className="pv-hint">{!automaticAllowed
        ? '管理员已禁用自动发布，当前仅提供人工审核路径。'
        : manual ? '审核后复制或导出，在平台官方页面提交。'
          : '检查账号和预览，确认后提交至所选平台。'}</span>
    </div>
    <div className="publishing-mode-content">
      {manual ? <ManualPublishPage persona={persona} /> : <AutomatedPublishPage persona={persona} />}
    </div>
  </div>;
}
