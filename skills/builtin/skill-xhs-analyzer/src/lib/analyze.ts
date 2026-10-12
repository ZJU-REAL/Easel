/**
 * Viral note analysis — deterministic, no LLM dependency.
 *
 * Analyzes WHY a note works: hook patterns, engagement ratios,
 * content structure, and performance vs author baseline.
 */

import kleur from "kleur";

// ─── Interfaces ─────────────────────────────────────────────────────────────

export interface HookAnalysis {
  title: string;
  titleLength: number;
  emojiCount: number;
  emojis: string[];
  hasNumber: boolean;
  hasQuestion: boolean;
  hasExclamation: boolean;
  isListFormat: boolean;
  hasIdentityHook: boolean;
  hasEmotionWord: boolean;
  hasContrastHook: boolean;
  hasSeriesFormat: boolean;
  hookPatterns: string[];
}

export interface ContentStructure {
  bodyLength: number;
  paragraphCount: number;
  avgParagraphLength: number;
  lineBreakDensity: number;
  emojiDensity: number;
  hashtagCount: number;
  hashtags: string[];
  hasCallToAction: boolean;
  bulletOrListUsage: boolean;
}

export interface VisualStrategy {
  imageCount: number;
  noteType: string;
}

export interface EngagementMetrics {
  likes: number;
  comments: number;
  collects: number;
  shares: number;
  totalEngagement: number;
  commentToLikeRatio: number;
  collectToLikeRatio: number;
  shareToLikeRatio: number;
}

export interface CommentInfo {
  author: string;
  content: string;
  likes: number;
}

export interface CommentPatterns {
  totalFetched: number;
  topComments: CommentInfo[];
  avgCommentLength: number;
  avgCommentLikes: number;
  themes: Array<{ keyword: string; count: number }>;
  questionCount: number;
  questionRate: number;
}

export interface RelativePerformance {
  authorPostCount: number;
  authorAvgLikes: number;
  authorMedianLikes: number;
  authorMaxLikes: number;
  thisNoteLikes: number;
  viralMultiplier: number;
  percentileRank: number;
  isOutlier: boolean;
  authorFollowers: number;
  likesToFollowerRatio: number;
}

export interface ViralScore {
  overall: number;
  breakdown: {
    hook: number;
    engagement: number;
    relative: number;
    content: number;
    comments: number;
  };
}

export interface ViralAnalysis {
  note: {
    id: string;
    title: string;
    url: string;
    author: { nickname: string; userId: string; followers: number };
    type: string;
  };
  score: ViralScore;
  hook: HookAnalysis;
  content: ContentStructure;
  visual: VisualStrategy;
  engagement: EngagementMetrics;
  comments: CommentPatterns;
  relative: RelativePerformance;
  fetchedAt: string;
}

// ─── Shared Patterns ────────────────────────────────────────────────────────

export const QUESTION_PATTERN = /[？?]\s*$/;

// ─── Chinese Pattern Dictionaries ───────────────────────────────────────────

const EMOTION_WORDS = [
  "太香了", "绝了", "震惊", "真香", "丝滑", "上头", "离谱", "爆了",
  "神了", "逆天", "炸裂", "牛逼", "绝绝子", "泪目", "笑死", "裂开",
  "麻了", "吐血", "哭了", "天花板", "yyds", "YYDS",
];

const IDENTITY_MARKERS = [
  "小白", "文科生", "非技术", "新手", "零基础", "0基础", "不会编程",
  "普通人", "打工人", "宝妈", "学生党", "上班族", "大龄", "转行",
];

const CONTRAST_PATTERNS = [
  /不是.{1,8}才/, /竟然/, /居然/, /没想到/, /万万没想到/,
  /以为.{1,8}(其实|结果|没想到)/, /才发现/, /原来/,
];

const NUMBER_PATTERN = /\d+[个分秒招步天种条件套款篇张页]/;
const LIST_PATTERN = /^(\d+[\.、]|[①②③④⑤⑥⑦⑧⑨⑩]|[一二三四五六七八九十][、.])/m;
const SERIES_PATTERN = /[（(]\s*[一二三四五六七八九十\d]+\s*[)）]|[Pp]art\s*\d+|第[一二三四五六七八九十\d]+[期篇章集部]/;
const CTA_PATTERN = /关注|点赞|收藏|转发|双击|评论区|留言|私信/;
const HASHTAG_PATTERN = /#[^\s#]+/g;
const EMOJI_PATTERN = /\p{Emoji_Presentation}|\p{Emoji}\uFE0F/gu;

// Bigram stop words — common Chinese chars that don't carry topic meaning
const BIGRAM_STOP = new Set([
  "的是", "是的", "了吗", "吗？", "啊啊", "哈哈", "嘿嘿", "呢？",
  "不是", "没有", "可以", "这个", "那个", "什么", "怎么", "真的",
  "一个", "我的", "你的", "他的", "她的", "是不", "有没", "也是",
  "就是", "还是", "但是", "不过", "所以", "因为", "然后", "已经",
]);

// ─── Analysis Functions ─────────────────────────────────────────────────────

export function analyzeHook(title: string): HookAnalysis {
  const emojis = title.match(EMOJI_PATTERN) ?? [];
  const patterns: string[] = [];

  const hasNumber = NUMBER_PATTERN.test(title);
  if (hasNumber) patterns.push("Number Hook");

  const hasQuestion = QUESTION_PATTERN.test(title);
  if (hasQuestion) patterns.push("Question");

  const hasExclamation = /[！!]\s*$/.test(title);
  if (hasExclamation) patterns.push("Exclamation");

  const isListFormat = LIST_PATTERN.test(title);
  if (isListFormat) patterns.push("List Format");

  const hasIdentityHook = IDENTITY_MARKERS.some((w) => title.includes(w));
  if (hasIdentityHook) patterns.push("Identity Hook");

  const hasEmotionWord = EMOTION_WORDS.some((w) => title.includes(w));
  if (hasEmotionWord) patterns.push("Emotion Word");

  const hasContrastHook = CONTRAST_PATTERNS.some((p) => p.test(title));
  if (hasContrastHook) patterns.push("Contrast Hook");

  const hasSeriesFormat = SERIES_PATTERN.test(title);
  if (hasSeriesFormat) patterns.push("Series Format");

  if (emojis.length > 0) patterns.push("Emoji");

  return {
    title,
    titleLength: [...title].length,
    emojiCount: emojis.length,
    emojis,
    hasNumber,
    hasQuestion,
    hasExclamation,
    isListFormat,
    hasIdentityHook,
    hasEmotionWord,
    hasContrastHook,
    hasSeriesFormat,
    hookPatterns: patterns,
  };
}

export function analyzeContent(desc: string): ContentStructure {
  const paragraphs = desc.split(/\n\s*\n|\n/).filter((p) => p.trim());
  const bodyLength = desc.length;
  const paragraphCount = paragraphs.length;
  const avgParagraphLength = paragraphCount > 0 ? Math.round(bodyLength / paragraphCount) : 0;

  const lineBreaks = (desc.match(/\n/g) ?? []).length;
  const lineBreakDensity = bodyLength > 0 ? (lineBreaks / bodyLength) * 100 : 0;

  const emojis = desc.match(EMOJI_PATTERN) ?? [];
  const emojiDensity = bodyLength > 0 ? (emojis.length / bodyLength) * 100 : 0;

  const hashtags = desc.match(HASHTAG_PATTERN) ?? [];
  const hasCallToAction = CTA_PATTERN.test(desc);
  const bulletOrListUsage = LIST_PATTERN.test(desc);

  return {
    bodyLength,
    paragraphCount,
    avgParagraphLength,
    lineBreakDensity: round2(lineBreakDensity),
    emojiDensity: round2(emojiDensity),
    hashtagCount: hashtags.length,
    hashtags,
    hasCallToAction,
    bulletOrListUsage,
  };
}

export function analyzeVisual(note: Record<string, unknown>): VisualStrategy {
  const imageList = (note.image_list ?? note.images ?? []) as unknown[];
  return {
    imageCount: imageList.length,
    noteType: String(note.type ?? "normal"),
  };
}

export function computeEngagement(
  interactInfo: Record<string, unknown>
): EngagementMetrics {
  const likes = num(interactInfo.liked_count);
  const comments = num(interactInfo.comment_count);
  const collects = num(interactInfo.collected_count);
  const shares = num(interactInfo.share_count);
  const total = likes + comments + collects + shares;

  return {
    likes,
    comments,
    collects,
    shares,
    totalEngagement: total,
    commentToLikeRatio: ratio(comments, likes),
    collectToLikeRatio: ratio(collects, likes),
    shareToLikeRatio: ratio(shares, likes),
  };
}

export function analyzeComments(
  comments: Array<Record<string, unknown>>
): CommentPatterns {
  if (comments.length === 0) {
    return {
      totalFetched: 0,
      topComments: [],
      avgCommentLength: 0,
      avgCommentLikes: 0,
      themes: [],
      questionCount: 0,
      questionRate: 0,
    };
  }

  // Sort by likes descending, take top 5
  const sorted = [...comments].sort(
    (a, b) => num(b.like_count) - num(a.like_count)
  );
  const topComments = sorted.slice(0, 5).map((c) => ({
    author: String(
      (c.user_info as Record<string, unknown>)?.nickname ?? "?"
    ),
    content: String(c.content ?? ""),
    likes: num(c.like_count),
  }));

  const totalLength = comments.reduce(
    (sum, c) => sum + String(c.content ?? "").length,
    0
  );
  const totalLikes = comments.reduce((sum, c) => sum + num(c.like_count), 0);

  const questionCount = comments.filter((c) =>
    QUESTION_PATTERN.test(String(c.content ?? ""))
  ).length;

  // Bigram frequency for theme extraction
  const bigramCounts = new Map<string, number>();
  for (const c of comments) {
    const text = String(c.content ?? "");
    const chars = [...text].filter(
      (ch) => /[\u4e00-\u9fff]/.test(ch) // Chinese chars only
    );
    for (let i = 0; i < chars.length - 1; i++) {
      const bigram = chars[i] + chars[i + 1];
      if (!BIGRAM_STOP.has(bigram)) {
        bigramCounts.set(bigram, (bigramCounts.get(bigram) ?? 0) + 1);
      }
    }
  }
  const themes = [...bigramCounts.entries()]
    .filter(([, count]) => count >= 3)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([keyword, count]) => ({ keyword, count }));

  return {
    totalFetched: comments.length,
    topComments,
    avgCommentLength: Math.round(totalLength / comments.length),
    avgCommentLikes: Math.round(totalLikes / comments.length),
    themes,
    questionCount,
    questionRate: round2((questionCount / comments.length) * 100),
  };
}

export function computeRelativePerformance(
  thisNoteLikes: number,
  authorPosts: Array<Record<string, unknown>>,
  authorFollowers: number
): RelativePerformance {
  // Extract likes from author's posts
  const likesArr = authorPosts
    .map((p) => {
      const info = p.interact_info as Record<string, unknown> | undefined;
      return info ? num(info.liked_count) : num(p.liked_count);
    })
    .filter((n) => n >= 0);

  if (likesArr.length === 0) {
    return {
      authorPostCount: 0,
      authorAvgLikes: 0,
      authorMedianLikes: 0,
      authorMaxLikes: 0,
      thisNoteLikes,
      viralMultiplier: 0,
      percentileRank: 0,
      isOutlier: false,
      authorFollowers,
      likesToFollowerRatio: ratio(thisNoteLikes, authorFollowers),
    };
  }

  const sorted = [...likesArr].sort((a, b) => a - b);
  const median =
    sorted.length % 2 === 0
      ? (sorted[sorted.length / 2 - 1] + sorted[sorted.length / 2]) / 2
      : sorted[Math.floor(sorted.length / 2)];
  const avg = likesArr.reduce((s, n) => s + n, 0) / likesArr.length;
  const max = sorted[sorted.length - 1];

  const belowCount = likesArr.filter((l) => l < thisNoteLikes).length;
  const percentile = round2((belowCount / likesArr.length) * 100);
  const multiplier = median > 0 ? round2(thisNoteLikes / median) : 0;

  return {
    authorPostCount: likesArr.length,
    authorAvgLikes: Math.round(avg),
    authorMedianLikes: Math.round(median),
    authorMaxLikes: max,
    thisNoteLikes,
    viralMultiplier: multiplier,
    percentileRank: percentile,
    isOutlier: multiplier > 3,
    authorFollowers,
    likesToFollowerRatio: ratio(thisNoteLikes, authorFollowers),
  };
}

export function computeViralScore(
  hook: HookAnalysis,
  engagement: EngagementMetrics,
  relative: RelativePerformance,
  content: ContentStructure,
  commentPatterns: CommentPatterns
): ViralScore {
  // Hook (0-20): +4 per detected pattern, capped
  const hookScore = Math.min(20, hook.hookPatterns.length * 4);

  // Engagement (0-20): threshold on absolute likes
  let engagementScore = 4;
  if (engagement.likes >= 500) engagementScore = 8;
  if (engagement.likes >= 1000) engagementScore = 12;
  if (engagement.likes >= 5000) engagementScore = 16;
  if (engagement.likes >= 10000) engagementScore = 20;

  // Relative (0-20): threshold on viral multiplier
  let relativeScore = 4;
  if (relative.viralMultiplier >= 1.5) relativeScore = 8;
  if (relative.viralMultiplier >= 3) relativeScore = 12;
  if (relative.viralMultiplier >= 5) relativeScore = 16;
  if (relative.viralMultiplier >= 10) relativeScore = 20;

  // Content (0-20): structural quality signals
  let contentScore = 0;
  if (content.bodyLength > 200) contentScore += 4;
  if (content.paragraphCount > 3) contentScore += 4;
  if (content.emojiDensity > 0.5 && content.emojiDensity < 8) contentScore += 4;
  if (content.hashtagCount >= 1 && content.hashtagCount <= 8) contentScore += 4;
  if (content.hasCallToAction) contentScore += 4;
  contentScore = Math.min(20, contentScore);

  // Comments (0-20): audience engagement quality
  let commentScore = 0;
  if (commentPatterns.totalFetched > 50) commentScore += 5;
  if (commentPatterns.avgCommentLength > 15) commentScore += 5;
  if (commentPatterns.questionRate > 5) commentScore += 5;
  if (commentPatterns.topComments[0]?.likes > 50) commentScore += 5;
  commentScore = Math.min(20, commentScore);

  return {
    overall: hookScore + engagementScore + relativeScore + contentScore + commentScore,
    breakdown: {
      hook: hookScore,
      engagement: engagementScore,
      relative: relativeScore,
      content: contentScore,
      comments: commentScore,
    },
  };
}

// ─── Top-Level Orchestrator ─────────────────────────────────────────────────

export function analyzeViral(
  noteId: string,
  note: Record<string, unknown>,
  comments: Array<Record<string, unknown>>,
  authorPosts: Array<Record<string, unknown>>,
  authorFollowers: number
): ViralAnalysis {
  const title = String(note.title ?? "");
  const desc = String(note.desc ?? "");
  const user = (note.user as Record<string, unknown>) ?? {};
  const interactInfo = (note.interact_info as Record<string, unknown>) ?? {};

  const hook = analyzeHook(title);
  const content = analyzeContent(desc);
  const visual = analyzeVisual(note);
  const engagement = computeEngagement(interactInfo);
  const commentPatterns = analyzeComments(comments);
  const relative = computeRelativePerformance(
    engagement.likes,
    authorPosts,
    authorFollowers
  );
  const score = computeViralScore(hook, engagement, relative, content, commentPatterns);

  return {
    note: {
      id: noteId,
      title,
      url: `https://www.xiaohongshu.com/explore/${noteId}`,
      author: {
        nickname: String(user.nickname ?? "unknown"),
        userId: String(user.user_id ?? ""),
        followers: authorFollowers,
      },
      type: visual.noteType,
    },
    score,
    hook,
    content,
    visual,
    engagement,
    comments: commentPatterns,
    relative,
    fetchedAt: new Date().toISOString(),
  };
}

// ─── Formatting ─────────────────────────────────────────────────────────────

export function formatViralAnalysis(a: ViralAnalysis): string {
  const lines: string[] = [];
  const hr = (label: string) =>
    kleur.dim(`─── ${label} ` + "─".repeat(Math.max(0, 46 - label.length)));

  // Header
  lines.push(kleur.bold("═══ Viral Analysis ════════════════════════════════"));
  lines.push("");
  lines.push(`  ${kleur.bold(`"${a.note.title}"`)}`);
  lines.push(`  by ${kleur.dim(`@${a.note.author.nickname}`)}`);
  lines.push("");
  lines.push(`  Viral Score: ${kleur.bold(String(a.score.overall))}/100  ${progressBar(a.score.overall, 100, 20)}`);

  // Engagement
  lines.push("");
  lines.push(hr("Engagement"));
  lines.push("");
  lines.push(
    `  ${kleur.red("♥")} ${fmtNum(a.engagement.likes)}   ` +
    `${kleur.cyan("💬")} ${fmtNum(a.engagement.comments)}   ` +
    `${kleur.yellow("⭐")} ${fmtNum(a.engagement.collects)}   ` +
    `${kleur.blue("📤")} ${fmtNum(a.engagement.shares)}`
  );
  lines.push(
    kleur.dim(
      `  💬/♥ ${a.engagement.commentToLikeRatio}%   ` +
      `⭐/♥ ${a.engagement.collectToLikeRatio}%   ` +
      `📤/♥ ${a.engagement.shareToLikeRatio}%`
    )
  );

  // Relative Performance
  if (a.relative.authorPostCount > 0) {
    lines.push("");
    lines.push(hr("vs Author Baseline"));
    lines.push("");
    lines.push(
      `  Author avg: ${fmtNum(a.relative.authorAvgLikes)} ♥  |  ` +
      `This note: ${kleur.bold(fmtNum(a.relative.thisNoteLikes))} ♥`
    );
    lines.push(
      `  ${kleur.bold(String(a.relative.viralMultiplier) + "x")} median  |  ` +
      `Top ${round2(100 - a.relative.percentileRank)}%` +
      (a.relative.authorFollowers > 0
        ? `  |  ${a.relative.likesToFollowerRatio}% of followers`
        : "")
    );
  }

  // Hook Analysis
  lines.push("");
  lines.push(hr("Hook Patterns"));
  lines.push("");
  lines.push(
    `  Title (${a.hook.titleLength} chars): ${kleur.bold(`"${a.hook.title}"`)}`
  );
  if (a.hook.hookPatterns.length > 0) {
    lines.push(
      `  ${a.hook.hookPatterns.map((p) => kleur.cyan(`[${p}]`)).join(" ")}`
    );
  } else {
    lines.push(kleur.dim("  No hook patterns detected"));
  }

  // Content Structure
  lines.push("");
  lines.push(hr("Content"));
  lines.push("");
  lines.push(
    `  ${fmtNum(a.content.bodyLength)} chars  |  ` +
    `${a.content.paragraphCount} paras  |  ` +
    `${a.content.hashtagCount} #tags  |  ` +
    `CTA ${a.content.hasCallToAction ? kleur.green("✓") : kleur.dim("✗")}`
  );
  if (a.visual.imageCount > 0) {
    lines.push(`  ${a.visual.imageCount} images  |  ${a.visual.noteType}`);
  }

  // Top Comments
  if (a.comments.totalFetched > 0) {
    lines.push("");
    lines.push(hr("Top Comments"));
    lines.push("");
    for (const c of a.comments.topComments.slice(0, 3)) {
      const preview = c.content.length > 40 ? c.content.slice(0, 40) + "..." : c.content;
      lines.push(`  ${kleur.dim(`@${c.author}`)} (${c.likes}♥): "${preview}"`);
    }
    if (a.comments.themes.length > 0) {
      lines.push(
        `  Themes: ${a.comments.themes.slice(0, 6).map((t) => `${t.keyword}(${t.count})`).join(" ")}`
      );
    }
    lines.push(kleur.dim(`  Questions: ${a.comments.questionRate}%  |  ${a.comments.totalFetched} comments fetched`));
  }

  // Score Breakdown
  lines.push("");
  lines.push(hr("Score Breakdown"));
  lines.push("");
  const { breakdown } = a.score;
  for (const [label, val] of [
    ["Hook", breakdown.hook],
    ["Engagement", breakdown.engagement],
    ["Relative", breakdown.relative],
    ["Content", breakdown.content],
    ["Comments", breakdown.comments],
  ] as const) {
    const padded = label.padEnd(12);
    lines.push(`  ${padded} ${String(val).padStart(2)}/20  ${progressBar(val, 20, 20)}`);
  }

  lines.push("");
  return lines.join("\n");
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function num(v: unknown): number {
  if (typeof v === "number") return v;
  if (typeof v === "string") {
    // Handle Chinese abbreviated numbers: "1.5万" = 15000, "2.4亿" = 240000000
    const s = v.trim();
    if (s.endsWith("万")) {
      const n = parseFloat(s.slice(0, -1));
      return isNaN(n) ? 0 : Math.round(n * 10000);
    }
    if (s.endsWith("亿")) {
      const n = parseFloat(s.slice(0, -1));
      return isNaN(n) ? 0 : Math.round(n * 100000000);
    }
    const n = parseInt(s, 10);
    return isNaN(n) ? 0 : n;
  }
  return 0;
}

function ratio(a: number, b: number): number {
  return b > 0 ? round2((a / b) * 100) : 0;
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

function fmtNum(n: number): string {
  return n.toLocaleString("en-US");
}

function progressBar(value: number, max: number, width: number): string {
  const filled = Math.round((value / max) * width);
  return kleur.green("█".repeat(filled)) + kleur.dim("░".repeat(width - filled));
}
