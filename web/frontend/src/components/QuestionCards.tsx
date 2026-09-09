import { useMemo, useState } from 'react';
import type { ChatQuestion, ChatQuestionItem } from '../lib/api';
import { answerQuestion } from '../lib/api';

/**
 * ask_user 问答题卡片。
 *
 * OpenClaw 的 ask_user 一次可带 1-3 个问题（question.questions[]）。gateway 的
 * question.resolve 要求 answers 里**每个问题都有答案**（单个缺失即报
 * QUESTION_INVALID_ANSWER: "question 'xxx' requires an answer"）。
 * 因此多问题时渲染全部题目，用户每问答完一项，全部选齐后自动提交一次。
 */
function QuestionCard({ question, onAnswered }: { question: ChatQuestion; onAnswered: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<Record<string, string>>({});
  const [custom, setCustom] = useState<Record<string, string>>({});
  const [showCustom, setShowCustom] = useState<Record<string, boolean>>({});

  const items: ChatQuestionItem[] = question.questions || [];
  const allAnswered = items.length > 0 && items.every((it) => (selected[it.questionId] || '').trim());

  const submitSingle = async (it: ChatQuestionItem, label: string) => {
    if (busy) return;
    setBusy(true); setError('');
    try {
      const res = await answerQuestion({
        questionId: question.id,
        answers: { [it.questionId]: [label] },
      });
      if (!res.ok) setError(res.error || '提交失败');
      else onAnswered();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const submitAll = async () => {
    if (busy || !allAnswered) return;
    setBusy(true); setError('');
    const answers: Record<string, string[]> = {};
    for (const it of items) {
      answers[it.questionId] = [selected[it.questionId]];
    }
    try {
      const res = await answerQuestion({ questionId: question.id, answers });
      if (!res.ok) setError(res.error || '提交失败');
      else onAnswered();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="message-row assistant">
      <div className="msg-col assistant" style={{ maxWidth: '80%' }}>
        <div className="question-card">
          {items.map((it, idx) => {
            const options: { label: string; description?: string }[] = it.options || [];
            const val = selected[it.questionId] || '';
            const ctl = showCustom[it.questionId];
            return (
              <div key={it.questionId} className="question-card__item">
                {idx > 0 && <div className="question-card__divider" />}
                {it.header && <div className="question-card__chip">{it.header}</div>}
                <div className="question-card__title">{it.question || '请选择'}</div>
                <div className="question-card__options">
                  {options.map((opt) => (
                    <button key={opt.label}
                      className={`question-card__option${val === opt.label ? ' question-card__option--selected' : ''}`}
                      disabled={busy}
                      onClick={() => setSelected((s) => ({ ...s, [it.questionId]: opt.label }))}>
                      <strong>{opt.label}</strong>
                      {opt.description && <span>{opt.description}</span>}
                    </button>
                  ))}
                  <button className="question-card__other" disabled={busy}
                    onClick={() => setShowCustom((s) => ({ ...s, [it.questionId]: !s[it.questionId] }))}>
                    {ctl ? '收起自定义输入' : '自行输入…'}
                  </button>
                </div>
                {ctl && (
                  <div className="question-card__custom">
                    <input
                      type="text"
                      value={custom[it.questionId] || ''}
                      placeholder="输入你的答案"
                      onChange={(e) => setCustom((c) => ({ ...c, [it.questionId]: e.target.value }))}
                    />
                    <button disabled={busy || !(custom[it.questionId] || '').trim()}
                      onClick={() => setSelected((s) => ({ ...s, [it.questionId]: custom[it.questionId].trim() }))}>
                      填入
                    </button>
                  </div>
                )}
              </div>
            );
          })}

          {/* 单问题：选完即提交；多问题：全部选齐后自动提交 */}
          {items.length === 1 ? (
            <div className="question-card__actions">
              <button className="question-card__submit" disabled={busy || !allAnswered}
                onClick={() => void submitSingle(items[0], selected[items[0].questionId])}>
                提交
              </button>
            </div>
          ) : (
            allAnswered && !busy && (
              <div className="question-card__actions">
                <button className="question-card__submit" disabled={busy} onClick={() => void submitAll()}>
                  全部已选，提交
                </button>
              </div>
            )
          )}
          {busy && <div className="question-card__hint">已提交，Agent 继续处理中…</div>}
          {error && <div className="question-card__hint question-card__error">{error}</div>}
        </div>
      </div>
    </div>
  );
}

/** 流式中的 ask_user 问答题列表（一次性卡片，答完即从当前流移除）。 */
export default function QuestionCards({ questions }: { questions: ChatQuestion[] }) {
  const [answered, setAnswered] = useState<Record<string, boolean>>({});
  const visible = useMemo(
    () => questions.filter((q) => !answered[q.id]),
    [questions, answered],
  );
  if (!visible.length) return null;
  return (
    <>
      {visible.map((q) => (
        <QuestionCard key={q.id} question={q} onAnswered={() => setAnswered((a) => ({ ...a, [q.id]: true }))} />
      ))}
    </>
  );
}
