/**
 * Batch reply strategy — deterministic comment filtering and reply orchestration.
 *
 * Selects which comments deserve a reply based on strategy, expands templates,
 * and executes replies with rate limiting and safety guards.
 */

import { QUESTION_PATTERN } from "./analyze.js";
import { XhsClient, NeedVerifyError } from "./client.js";

// ─── Interfaces ─────────────────────────────────────────────────────────────

export interface ReplyCandidate {
  commentId: string;
  author: string;
  content: string;
  likes: number;
  hasSubReplies: boolean;
  isQuestion: boolean;
  matchedStrategy: string;
}

export interface ReplyPlan {
  noteId: string;
  strategy: string;
  candidates: ReplyCandidate[];
  skipped: number;
  totalComments: number;
}

export interface ReplyResult {
  commentId: string;
  author: string;
  success: boolean;
  error?: string;
}

export type StrategyName = "questions" | "top-engaged" | "all-unanswered";

// ─── Constants ──────────────────────────────────────────────────────────────
// Based on XHS risk control research: 3+ minute intervals between replies,
// uniform timing patterns trigger bot detection.

const MAX_REPLIES_HARD_CAP = 30;
const MIN_DELAY_MS = 180_000; // 3 minutes — XHS minimum safe interval
const DEFAULT_DELAY_MS = 300_000; // 5 minutes — recommended safe interval
const JITTER_FACTOR = 0.3; // ±30% random variation to avoid uniform patterns

// ─── Strategy Selection ─────────────────────────────────────────────────────

export function selectCandidates(
  comments: Array<Record<string, unknown>>,
  strategy: StrategyName,
  max: number
): ReplyPlan {
  const cap = Math.min(max, MAX_REPLIES_HARD_CAP);
  const total = comments.length;

  const mapped = comments.map((c) => {
    const userInfo = (c.user_info ?? {}) as Record<string, unknown>;
    const content = String(c.content ?? "");
    const likes = toNum(c.like_count);
    const subCount = toNum(c.sub_comment_count);
    return {
      commentId: String(c.id ?? c.comment_id ?? ""),
      author: String(userInfo.nickname ?? ""),
      content,
      likes,
      hasSubReplies: subCount > 0,
      isQuestion: QUESTION_PATTERN.test(content),
      matchedStrategy: strategy,
    };
  });

  let selected: ReplyCandidate[];

  switch (strategy) {
    case "questions":
      selected = mapped.filter((c) => c.isQuestion);
      break;

    case "top-engaged":
      selected = [...mapped].sort((a, b) => b.likes - a.likes);
      break;

    case "all-unanswered":
      selected = mapped.filter((c) => !c.hasSubReplies);
      break;

    default:
      selected = mapped;
  }

  const candidates = selected.slice(0, cap);
  return {
    noteId: "",
    strategy,
    candidates,
    skipped: total - candidates.length,
    totalComments: total,
  };
}

// ─── Template Expansion ─────────────────────────────────────────────────────

export function expandTemplate(
  template: string,
  candidate: ReplyCandidate,
  context: { noteTitle?: string }
): string {
  return template
    .replace(/\{author\}/g, candidate.author)
    .replace(/\{content\}/g, candidate.content)
    .replace(/\{noteTitle\}/g, context.noteTitle ?? "");
}

// ─── Execution ──────────────────────────────────────────────────────────────

export async function executeReplies(
  client: XhsClient,
  noteId: string,
  candidates: ReplyCandidate[],
  template: string,
  delayMs: number,
  context: { noteTitle?: string }
): Promise<ReplyResult[]> {
  const delay = Math.max(delayMs, MIN_DELAY_MS);
  const results: ReplyResult[] = [];

  for (const candidate of candidates) {
    const replyText = expandTemplate(template, candidate, context);

    try {
      await client.replyComment(noteId, candidate.commentId, replyText);
      results.push({ commentId: candidate.commentId, author: candidate.author, success: true });
    } catch (err) {
      if (err instanceof NeedVerifyError) {
        results.push({
          commentId: candidate.commentId,
          author: candidate.author,
          success: false,
          error: "Captcha triggered — stopping batch",
        });
        break; // Stop immediately on captcha
      }
      results.push({
        commentId: candidate.commentId,
        author: candidate.author,
        success: false,
        error: err instanceof Error ? err.message : "Unknown error",
      });
    }

    // Rate limit between replies with jitter (skip after last)
    if (candidate !== candidates[candidates.length - 1]) {
      const jittered = addJitter(delay, JITTER_FACTOR);
      await sleep(jittered);
    }
  }

  return results;
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function toNum(v: unknown): number {
  if (typeof v === "number") return v;
  const s = String(v ?? "0").trim();
  if (s.endsWith("万")) return Math.round(parseFloat(s.slice(0, -1)) * 10000);
  if (s.endsWith("亿")) return Math.round(parseFloat(s.slice(0, -1)) * 100000000);
  return parseInt(s, 10) || 0;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function addJitter(ms: number, factor: number): number {
  const offset = ms * factor * (2 * Math.random() - 1); // ±factor
  return Math.max(MIN_DELAY_MS, Math.round(ms + offset));
}

export { DEFAULT_DELAY_MS, MIN_DELAY_MS, MAX_REPLIES_HARD_CAP };
