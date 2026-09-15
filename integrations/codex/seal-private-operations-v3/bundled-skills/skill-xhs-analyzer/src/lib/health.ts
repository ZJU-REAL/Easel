/**
 * Note Health Check — detect hidden rate-limiting (限流) via creator API level field
 *
 * XHS assigns a hidden `level` to each note in the creator backend API response.
 * This level controls recommendation distribution but is never shown in the UI.
 *
 * Discovery credit: @xxx111god (Jason Zuo)
 * Reference: https://github.com/jzOcb/xhs-note-health-checker
 */

// ─── Level Definitions ──────────────────────────────────────────────────────

export interface LevelMeta {
  label: string;
  color: "green" | "lightGreen" | "yellow" | "red" | "darkRed" | "severe" | "gray";
  emoji: string;
  description: string;
}

const LEVEL_META: Record<string, LevelMeta> = {
  normal: { label: "L4 正常", color: "green", emoji: "🟢", description: "Normal distribution" },
  baseline: { label: "L2 基本", color: "lightGreen", emoji: "🟡", description: "Basically normal" },
  newPost: { label: "L1 新帖", color: "yellow", emoji: "⚪", description: "New post, under review" },
  softLimit: { label: "L-1 限流", color: "red", emoji: "🔴", description: "Mild throttling" },
  moderate: { label: "中度限流", color: "darkRed", emoji: "🔴", description: "Moderate throttling" },
  severe: { label: "L-102 严重", color: "severe", emoji: "⛔", description: "Severe (irreversible)" },
  unknown: { label: "未知", color: "gray", emoji: "❓", description: "Unknown level" },
};

export function getLevelMeta(level: number): LevelMeta & { level: number } {
  let meta: LevelMeta;
  if (level === -102) meta = LEVEL_META.severe;
  else if (level <= -5) meta = { ...LEVEL_META.moderate, label: `L${level} 中度` };
  else if (level === -1) meta = LEVEL_META.softLimit;
  else if (level === 1) meta = LEVEL_META.newPost;
  else if (level >= 4) meta = LEVEL_META.normal;
  else if (level >= 2) meta = { ...LEVEL_META.baseline, label: `L${level} 基本` };
  else meta = { ...LEVEL_META.unknown, label: `L${level}` };
  return { ...meta, level };
}

// ─── Sensitive Word Detection ───────────────────────────────────────────────

const SENSITIVE_WORDS = [
  "自动化",
  "自动发布",
  "AI生成",
  "内容工厂",
  "批量",
  "全自动",
  "自动工作流",
  "AI自动",
];

export function detectSensitiveWords(title: string): string[] {
  return SENSITIVE_WORDS.filter((word) => title.includes(word));
}

// ─── Tag Count Check ────────────────────────────────────────────────────────

const MAX_RECOMMENDED_TAGS = 5;

export function checkTagCount(note: Record<string, unknown>): { count: number; warning: boolean } {
  const arrayCandidates = [
    note.tag_list, note.tags, note.topic_list,
    note.topics, note.hash_tag_list, note.hashtag_list, note.hash_tag,
  ];
  for (const candidate of arrayCandidates) {
    if (Array.isArray(candidate)) return { count: candidate.length, warning: candidate.length > MAX_RECOMMENDED_TAGS };
  }
  const numericCandidates = [note.tag_count, note.topic_count, note.hashtag_count];
  for (const candidate of numericCandidates) {
    if (typeof candidate === "number") return { count: candidate, warning: candidate > MAX_RECOMMENDED_TAGS };
  }
  return { count: 0, warning: false };
}

// ─── Note Diagnostics ───────────────────────────────────────────────────────

export interface NoteDiagnostics {
  noteId: string;
  title: string;
  level: number;
  levelMeta: LevelMeta;
  sensitiveHits: string[];
  tagCount: number;
  tagWarning: boolean;
}

export function diagnoseNote(note: Record<string, unknown>): NoteDiagnostics {
  const noteId = String(note.note_id ?? note.noteId ?? note.id ?? note.item_id ?? note.display_id ?? "");
  const title = String(note.display_title ?? note.title ?? note.note_title ?? note.name ?? "");

  // Level extraction with fallback cascade (matches Chrome extension logic)
  const levelValue = Number(
    note.level_ ?? note.level ?? note.distribution_level ?? note.status_level ?? NaN
  );
  const level = Number.isFinite(levelValue) ? levelValue : 1;

  const levelMeta = getLevelMeta(level);
  const sensitiveHits = detectSensitiveWords(title);
  const { count: tagCount, warning: tagWarning } = checkTagCount(note);

  return { noteId, title, level, levelMeta, sensitiveHits, tagCount, tagWarning };
}

// ─── Health Report ──────────────────────────────────────────────────────────

export interface HealthReport {
  totalNotes: number;
  notes: NoteDiagnostics[];
  distribution: Record<string, number>;
  limitedNotes: NoteDiagnostics[];
  sensitiveNotes: NoteDiagnostics[];
}

export function buildHealthReport(rawNotes: Record<string, unknown>[]): HealthReport {
  const notes = rawNotes.map(diagnoseNote);
  const distribution: Record<string, number> = {};

  for (const n of notes) {
    const key = n.levelMeta.emoji + " " + n.levelMeta.label;
    distribution[key] = (distribution[key] ?? 0) + 1;
  }

  const limitedNotes = notes.filter((n) => n.level < 1);
  const sensitiveNotes = notes.filter((n) => n.sensitiveHits.length > 0 || n.tagWarning);

  return { totalNotes: notes.length, notes, distribution, limitedNotes, sensitiveNotes };
}
