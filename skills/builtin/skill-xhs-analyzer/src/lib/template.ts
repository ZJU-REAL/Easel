/**
 * Viral template extraction — synthesize structural patterns from multiple viral notes.
 *
 * Given 1-3 ViralAnalysis results, extracts a ContentTemplate capturing
 * the common structural formula: hook patterns, title/body structure,
 * engagement profile, and audience signals.
 *
 * Deterministic, no LLM dependency.
 */

import kleur from "kleur";
import type { ViralAnalysis } from "./analyze.js";

// ─── Interfaces ─────────────────────────────────────────────────────────────

export interface ContentTemplate {
  dominantHookPatterns: string[];
  titleStructure: {
    avgLength: number;
    commonPatterns: string[];
    hasEmoji: boolean;
    hasNumber: boolean;
  };
  bodyStructure: {
    lengthRange: [number, number];
    paragraphRange: [number, number];
    emojiDensityRange: [number, number];
    hashtagRange: [number, number];
    hasCallToAction: boolean;
    usesBulletFormat: boolean;
  };
  engagementProfile: {
    type: "reference" | "insight" | "entertainment";
    avgCollectToLikeRatio: number;
    avgCommentToLikeRatio: number;
    avgShareToLikeRatio: number;
  };
  audienceSignals: {
    commonThemes: Array<{ keyword: string; count: number }>;
    avgQuestionRate: number;
  };
  sourceNotes: Array<{
    id: string;
    title: string;
    url: string;
    score: number;
  }>;
  generatedAt: string;
}

// ─── Extraction ─────────────────────────────────────────────────────────────

export function extractTemplate(analyses: ViralAnalysis[]): ContentTemplate {
  const n = analyses.length;

  // Hook patterns — count occurrences across notes, keep those appearing in majority
  const hookCounts = new Map<string, number>();
  for (const a of analyses) {
    for (const p of a.hook.hookPatterns) {
      hookCounts.set(p, (hookCounts.get(p) ?? 0) + 1);
    }
  }
  const threshold = n === 1 ? 1 : Math.ceil(n / 2);
  const dominantHookPatterns = [...hookCounts.entries()]
    .filter(([, count]) => count >= threshold)
    .sort((a, b) => b[1] - a[1])
    .map(([pattern]) => pattern);

  // Title structure
  const titleLengths = analyses.map((a) => a.hook.titleLength);
  const hasEmoji = analyses.some((a) => a.hook.emojiCount > 0);
  const hasNumber = analyses.some((a) => a.hook.hasNumber);

  // Body structure — compute ranges
  const bodyLengths = analyses.map((a) => a.content.bodyLength);
  const paragraphs = analyses.map((a) => a.content.paragraphCount);
  const emojiDensities = analyses.map((a) => a.content.emojiDensity);
  const hashtags = analyses.map((a) => a.content.hashtagCount);
  const hasCTA = analyses.some((a) => a.content.hasCallToAction);
  const usesBullets = analyses.some((a) => a.content.bulletOrListUsage);

  // Engagement profile — classify by average collect/like ratio
  const avgCollectRatio = avg(analyses.map((a) => a.engagement.collectToLikeRatio));
  const avgCommentRatio = avg(analyses.map((a) => a.engagement.commentToLikeRatio));
  const avgShareRatio = avg(analyses.map((a) => a.engagement.shareToLikeRatio));

  let profileType: "reference" | "insight" | "entertainment";
  if (avgCollectRatio > 40) profileType = "reference";
  else if (avgCollectRatio > 20) profileType = "insight";
  else profileType = "entertainment";

  // Audience signals — merge comment themes across notes
  const themeCounts = new Map<string, number>();
  for (const a of analyses) {
    for (const t of a.comments.themes) {
      themeCounts.set(t.keyword, (themeCounts.get(t.keyword) ?? 0) + t.count);
    }
  }
  const commonThemes = [...themeCounts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([keyword, count]) => ({ keyword, count }));

  return {
    dominantHookPatterns,
    titleStructure: {
      avgLength: Math.round(avg(titleLengths)),
      commonPatterns: dominantHookPatterns,
      hasEmoji,
      hasNumber,
    },
    bodyStructure: {
      lengthRange: [Math.min(...bodyLengths), Math.max(...bodyLengths)],
      paragraphRange: [Math.min(...paragraphs), Math.max(...paragraphs)],
      emojiDensityRange: [
        round2(Math.min(...emojiDensities)),
        round2(Math.max(...emojiDensities)),
      ],
      hashtagRange: [Math.min(...hashtags), Math.max(...hashtags)],
      hasCallToAction: hasCTA,
      usesBulletFormat: usesBullets,
    },
    engagementProfile: {
      type: profileType,
      avgCollectToLikeRatio: round2(avgCollectRatio),
      avgCommentToLikeRatio: round2(avgCommentRatio),
      avgShareToLikeRatio: round2(avgShareRatio),
    },
    audienceSignals: {
      commonThemes,
      avgQuestionRate: round2(avg(analyses.map((a) => a.comments.questionRate))),
    },
    sourceNotes: analyses.map((a) => ({
      id: a.note.id,
      title: a.note.title,
      url: a.note.url,
      score: a.score.overall,
    })),
    generatedAt: new Date().toISOString(),
  };
}

// ─── Formatting ─────────────────────────────────────────────────────────────

const TYPE_LABELS: Record<string, string> = {
  reference: "工具型 (Reference)",
  insight: "认知型 (Insight)",
  entertainment: "娱乐型 (Entertainment)",
};

export function formatTemplate(t: ContentTemplate): string {
  const lines: string[] = [];

  lines.push(kleur.bold("=== Content Template ===\n"));

  // Hook patterns
  lines.push(kleur.bold("Hook Patterns"));
  if (t.dominantHookPatterns.length > 0) {
    lines.push(`  ${t.dominantHookPatterns.map((p) => kleur.cyan(`[${p}]`)).join(" ")}`);
  } else {
    lines.push(kleur.dim("  No dominant patterns detected"));
  }
  lines.push("");

  // Title structure
  lines.push(kleur.bold("Title Structure"));
  lines.push(`  Avg length: ${t.titleStructure.avgLength} chars`);
  lines.push(`  Emoji: ${t.titleStructure.hasEmoji ? "Yes" : "No"}  |  Number: ${t.titleStructure.hasNumber ? "Yes" : "No"}`);
  lines.push("");

  // Body structure
  lines.push(kleur.bold("Body Structure"));
  lines.push(`  Length:     ${t.bodyStructure.lengthRange[0]}–${t.bodyStructure.lengthRange[1]} chars`);
  lines.push(`  Paragraphs: ${t.bodyStructure.paragraphRange[0]}–${t.bodyStructure.paragraphRange[1]}`);
  lines.push(`  Emoji density: ${t.bodyStructure.emojiDensityRange[0]}–${t.bodyStructure.emojiDensityRange[1]}%`);
  lines.push(`  Hashtags:  ${t.bodyStructure.hashtagRange[0]}–${t.bodyStructure.hashtagRange[1]}`);
  lines.push(`  CTA: ${t.bodyStructure.hasCallToAction ? "Yes" : "No"}  |  List/bullet format: ${t.bodyStructure.usesBulletFormat ? "Yes" : "No"}`);
  lines.push("");

  // Engagement profile
  lines.push(kleur.bold("Engagement Profile"));
  lines.push(`  Type: ${TYPE_LABELS[t.engagementProfile.type] ?? t.engagementProfile.type}`);
  lines.push(`  Collect/Like: ${t.engagementProfile.avgCollectToLikeRatio}%  |  Comment/Like: ${t.engagementProfile.avgCommentToLikeRatio}%  |  Share/Like: ${t.engagementProfile.avgShareToLikeRatio}%`);
  lines.push("");

  // Audience signals
  if (t.audienceSignals.commonThemes.length > 0) {
    lines.push(kleur.bold("Audience Signals"));
    lines.push(`  Question rate: ${t.audienceSignals.avgQuestionRate}%`);
    lines.push(`  Top themes: ${t.audienceSignals.commonThemes.map((t) => t.keyword).join(", ")}`);
    lines.push("");
  }

  // Source notes
  lines.push(kleur.bold("Source Notes"));
  for (const s of t.sourceNotes) {
    lines.push(`  ${kleur.dim(`[${s.score}/100]`)} ${s.title} ${kleur.dim(s.url)}`);
  }

  return lines.join("\n");
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function avg(nums: number[]): number {
  return nums.length === 0 ? 0 : nums.reduce((a, b) => a + b, 0) / nums.length;
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}
