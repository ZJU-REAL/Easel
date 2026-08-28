/**
 * Card rendering module — converts markdown to styled PNG image cards for Xiaohongshu.
 *
 * Uses puppeteer-core (optional dependency) to screenshot HTML templates via the user's
 * existing Chrome installation. No XHS API or cookies needed — purely offline rendering.
 */

import { existsSync, readFileSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import kleur from "kleur";

// ─── Types ──────────────────────────────────────────────────────────────────

export type ColorStyleName =
  | "purple"
  | "xiaohongshu"
  | "mint"
  | "sunset"
  | "ocean"
  | "elegant"
  | "dark";

export interface CardFrontmatter {
  emoji?: string;
  title: string;
  subtitle?: string;
  style?: ColorStyleName;
}

export interface RenderOptions {
  outputDir: string;
  style: ColorStyleName;
  pagination: "auto" | "separator";
  width: number;
  height: number;
  dpr: number;
}

export interface RenderResult {
  coverPath: string;
  cardPaths: string[];
  totalCards: number;
}

interface ColorStyle {
  name: string;
  coverGradient: string;
  cardBg: string;
  cardBorder: string;
  titleColor: string;
  subtitleColor: string;
  textColor: string;
  accentColor: string;
  mutedColor: string;
  codeBg: string;
  codeColor: string;
  blockquoteBg: string;
  blockquoteBorder: string;
  isDark: boolean;
}

// ─── Color Styles (ported from Auto-Redbook-Skills V2) ─────────────────────

const COLOR_STYLES: Record<ColorStyleName, ColorStyle> = {
  purple: {
    name: "Purple",
    coverGradient: "linear-gradient(135deg, #3450E4 0%, #D266DA 100%)",
    cardBg: "#ffffff",
    cardBorder: "linear-gradient(135deg, #6366f1 0%, #a855f7 100%)",
    titleColor: "#1e1b4b",
    subtitleColor: "#4338ca",
    textColor: "#334155",
    accentColor: "#6366f1",
    mutedColor: "#64748b",
    codeBg: "#f1f5f9",
    codeColor: "#6366f1",
    blockquoteBg: "#eef2ff",
    blockquoteBorder: "#6366f1",
    isDark: false,
  },
  xiaohongshu: {
    name: "Xiaohongshu",
    coverGradient: "linear-gradient(135deg, #FF2442 0%, #FF6B81 100%)",
    cardBg: "#ffffff",
    cardBorder: "linear-gradient(135deg, #FF2442 0%, #FF6B81 100%)",
    titleColor: "#1a1a2e",
    subtitleColor: "#FF2442",
    textColor: "#334155",
    accentColor: "#FF2442",
    mutedColor: "#64748b",
    codeBg: "#fff5f5",
    codeColor: "#FF2442",
    blockquoteBg: "#fff5f5",
    blockquoteBorder: "#FF2442",
    isDark: false,
  },
  mint: {
    name: "Mint",
    coverGradient: "linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)",
    cardBg: "#ffffff",
    cardBorder: "linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)",
    titleColor: "#064e3b",
    subtitleColor: "#059669",
    textColor: "#334155",
    accentColor: "#10b981",
    mutedColor: "#64748b",
    codeBg: "#ecfdf5",
    codeColor: "#059669",
    blockquoteBg: "#ecfdf5",
    blockquoteBorder: "#10b981",
    isDark: false,
  },
  sunset: {
    name: "Sunset",
    coverGradient: "linear-gradient(135deg, #fa709a 0%, #fee140 100%)",
    cardBg: "#ffffff",
    cardBorder: "linear-gradient(135deg, #fa709a 0%, #fee140 100%)",
    titleColor: "#7c2d12",
    subtitleColor: "#ea580c",
    textColor: "#334155",
    accentColor: "#f97316",
    mutedColor: "#64748b",
    codeBg: "#fff7ed",
    codeColor: "#ea580c",
    blockquoteBg: "#fff7ed",
    blockquoteBorder: "#f97316",
    isDark: false,
  },
  ocean: {
    name: "Ocean",
    coverGradient: "linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)",
    cardBg: "#ffffff",
    cardBorder: "linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)",
    titleColor: "#0c4a6e",
    subtitleColor: "#0284c7",
    textColor: "#334155",
    accentColor: "#0ea5e9",
    mutedColor: "#64748b",
    codeBg: "#f0f9ff",
    codeColor: "#0284c7",
    blockquoteBg: "#f0f9ff",
    blockquoteBorder: "#0ea5e9",
    isDark: false,
  },
  elegant: {
    name: "Elegant",
    coverGradient: "linear-gradient(135deg, #e2e8f0 0%, #f8fafc 100%)",
    cardBg: "#ffffff",
    cardBorder: "linear-gradient(135deg, #94a3b8 0%, #cbd5e1 100%)",
    titleColor: "#0f172a",
    subtitleColor: "#334155",
    textColor: "#334155",
    accentColor: "#475569",
    mutedColor: "#64748b",
    codeBg: "#f8fafc",
    codeColor: "#334155",
    blockquoteBg: "#f8fafc",
    blockquoteBorder: "#94a3b8",
    isDark: false,
  },
  dark: {
    name: "Dark",
    coverGradient: "linear-gradient(135deg, #0f172a 0%, #1e293b 100%)",
    cardBg: "#1e293b",
    cardBorder: "linear-gradient(135deg, #e94560 0%, #f97316 100%)",
    titleColor: "#f1f5f9",
    subtitleColor: "#e94560",
    textColor: "#cbd5e1",
    accentColor: "#e94560",
    mutedColor: "#94a3b8",
    codeBg: "#0f172a",
    codeColor: "#fbbf24",
    blockquoteBg: "#0f172a",
    blockquoteBorder: "#e94560",
    isDark: true,
  },
};

// ─── Frontmatter Parsing ────────────────────────────────────────────────────

export function parseCardMarkdown(content: string): {
  frontmatter: CardFrontmatter;
  body: string;
} {
  const fmMatch = content.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/);
  if (!fmMatch) {
    return { frontmatter: { title: "Untitled" }, body: content };
  }
  const fmRaw = fmMatch[1];
  const body = content.slice(fmMatch[0].length);

  const fm: Record<string, string> = {};
  for (const line of fmRaw.split("\n")) {
    const m = line.match(/^(\w+)\s*:\s*(.+)$/);
    if (m) fm[m[1]] = m[2].trim().replace(/^["']|["']$/g, "");
  }

  return {
    frontmatter: {
      emoji: fm.emoji,
      title: fm.title ?? "Untitled",
      subtitle: fm.subtitle,
      style: fm.style as ColorStyleName | undefined,
    },
    body,
  };
}

// ─── Pagination ─────────────────────────────────────────────────────────────

export function paginateContent(
  body: string,
  mode: "auto" | "separator"
): string[] {
  if (mode === "separator") {
    return body
      .split(/\n(?:---+|___+|\*\*\*+)\n/)
      .map((s) => s.trim())
      .filter(Boolean);
  }

  // Auto mode: split on block boundaries using character-count heuristic
  const lines = body.split("\n");
  const blocks: string[] = [];
  let currentBlock = "";

  // Group lines into logical blocks (headings, paragraphs, code blocks, lists)
  let inCodeBlock = false;
  for (const line of lines) {
    if (line.startsWith("```")) {
      inCodeBlock = !inCodeBlock;
      currentBlock += line + "\n";
      if (!inCodeBlock) {
        blocks.push(currentBlock.trim());
        currentBlock = "";
      }
      continue;
    }

    if (inCodeBlock) {
      currentBlock += line + "\n";
      continue;
    }

    // Headings start new blocks
    if (line.match(/^#{1,3}\s/) && currentBlock.trim()) {
      blocks.push(currentBlock.trim());
      currentBlock = line + "\n";
      continue;
    }

    // Empty lines separate paragraphs
    if (line.trim() === "" && currentBlock.trim()) {
      blocks.push(currentBlock.trim());
      currentBlock = "";
      continue;
    }

    currentBlock += line + "\n";
  }
  if (currentBlock.trim()) blocks.push(currentBlock.trim());

  // Estimate height per block and split into pages
  // Target: ~600 Chinese chars or ~1200 Latin chars per card (safe content area)
  const MAX_CHARS_PER_PAGE = 600;
  const pages: string[] = [];
  let currentPage = "";
  let currentChars = 0;

  for (const block of blocks) {
    const blockChars = estimateChars(block);

    // If adding this block exceeds limit and page isn't empty, start new page
    if (currentChars + blockChars > MAX_CHARS_PER_PAGE && currentPage.trim()) {
      pages.push(currentPage.trim());
      currentPage = block + "\n\n";
      currentChars = blockChars;
    } else {
      currentPage += block + "\n\n";
      currentChars += blockChars;
    }
  }
  if (currentPage.trim()) pages.push(currentPage.trim());

  return pages.length > 0 ? pages : [body.trim()];
}

function estimateChars(block: string): number {
  // Chinese characters count as ~1.5x Latin for height estimation
  let count = 0;
  for (const char of block) {
    if (char.charCodeAt(0) > 0x4e00) {
      count += 1.5;
    } else {
      count += 1;
    }
  }
  // Headings take more vertical space
  if (block.match(/^#{1,3}\s/)) count += 80;
  // Code blocks take more space
  if (block.includes("```")) count += 60;
  return Math.ceil(count);
}

// ─── HTML Templates ─────────────────────────────────────────────────────────

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function buildCoverHtml(
  fm: CardFrontmatter,
  style: ColorStyle,
  width: number,
  height: number
): string {
  const emojiSize = Math.round(width * 0.13);
  const titleSize = Math.round(width * 0.065);
  const subtitleSize = Math.round(width * 0.035);
  const innerWidth = Math.round(width * 0.88);
  const innerHeight = Math.round(height * 0.88);
  const offset = Math.round(width * 0.06);
  const borderRadius = Math.round(width * 0.03);

  return `<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  width: ${width}px; height: ${height}px;
  background: ${style.coverGradient};
  font-family: -apple-system, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  overflow: hidden;
}
.cover-outer {
  position: absolute;
  top: ${offset}px; left: ${offset}px;
  width: ${innerWidth}px; height: ${innerHeight}px;
  background: ${style.cardBg};
  border-radius: ${borderRadius}px;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  box-shadow: 0 25px 60px rgba(0,0,0,0.15);
}
.emoji { font-size: ${emojiSize}px; margin-bottom: ${Math.round(height * 0.03)}px; }
.title {
  font-size: ${titleSize}px; font-weight: 800;
  color: ${style.titleColor}; text-align: center;
  max-width: ${Math.round(innerWidth * 0.85)}px;
  line-height: 1.35; padding: 0 ${Math.round(width * 0.05)}px;
}
.subtitle {
  font-size: ${subtitleSize}px; font-weight: 400;
  color: ${style.subtitleColor}; text-align: center;
  margin-top: ${Math.round(height * 0.02)}px;
  opacity: 0.85;
}
</style></head>
<body>
<div class="cover-outer">
  ${fm.emoji ? `<div class="emoji">${fm.emoji}</div>` : ""}
  <div class="title">${escapeHtml(fm.title)}</div>
  ${fm.subtitle ? `<div class="subtitle">${escapeHtml(fm.subtitle)}</div>` : ""}
</div>
</body></html>`;
}

function buildCardHtml(
  htmlContent: string,
  pageNum: number,
  totalPages: number,
  style: ColorStyle,
  width: number,
  height: number
): string {
  const padding = Math.round(width * 0.055);
  const borderRadius = Math.round(width * 0.025);
  const fontSize = Math.round(width * 0.038);
  const h1Size = Math.round(width * 0.055);
  const h2Size = Math.round(width * 0.048);
  const h3Size = Math.round(width * 0.042);

  return `<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  width: ${width}px; height: ${height}px;
  background: ${style.cardBorder};
  font-family: -apple-system, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  overflow: hidden;
}
.card-outer {
  position: absolute;
  top: ${Math.round(width * 0.04)}px;
  left: ${Math.round(width * 0.04)}px;
  right: ${Math.round(width * 0.04)}px;
  bottom: ${Math.round(width * 0.04)}px;
  background: ${style.cardBg};
  border-radius: ${borderRadius}px;
  box-shadow: 0 8px 30px rgba(0,0,0,0.08);
  overflow: hidden;
}
.card-content {
  padding: ${padding}px;
  padding-bottom: ${padding + 40}px;
  color: ${style.textColor};
  font-size: ${fontSize}px;
  line-height: 1.75;
}
.card-content h1 {
  font-size: ${h1Size}px; font-weight: 700;
  color: ${style.titleColor}; margin: 0 0 ${Math.round(fontSize * 0.8)}px 0;
  line-height: 1.35;
}
.card-content h2 {
  font-size: ${h2Size}px; font-weight: 600;
  color: ${style.titleColor}; margin: ${Math.round(fontSize * 1.2)}px 0 ${Math.round(fontSize * 0.6)}px 0;
  line-height: 1.4;
}
.card-content h3 {
  font-size: ${h3Size}px; font-weight: 600;
  color: ${style.subtitleColor}; margin: ${Math.round(fontSize * 1)}px 0 ${Math.round(fontSize * 0.5)}px 0;
  line-height: 1.4;
}
.card-content p {
  margin: 0 0 ${Math.round(fontSize * 0.7)}px 0;
}
.card-content strong { color: ${style.titleColor}; }
.card-content em { color: ${style.accentColor}; font-style: italic; }
.card-content a {
  color: ${style.accentColor}; text-decoration: none;
  border-bottom: 2px solid ${style.accentColor};
}
.card-content ul, .card-content ol {
  padding-left: ${Math.round(fontSize * 1.4)}px;
  margin: 0 0 ${Math.round(fontSize * 0.7)}px 0;
}
.card-content li { margin-bottom: ${Math.round(fontSize * 0.4)}px; }
.card-content code {
  background: ${style.codeBg}; color: ${style.codeColor};
  padding: 3px 8px; border-radius: 6px;
  font-size: 0.88em; font-family: "SF Mono", "Monaco", "Consolas", monospace;
}
.card-content pre {
  background: ${style.isDark ? "#0f172a" : "#1e293b"}; color: #e2e8f0;
  padding: ${Math.round(fontSize * 0.8)}px; border-radius: 12px;
  margin: ${Math.round(fontSize * 0.6)}px 0;
  overflow-x: auto; font-size: 0.85em;
  line-height: 1.6;
}
.card-content pre code {
  background: none; color: inherit; padding: 0;
  font-size: inherit;
}
.card-content blockquote {
  background: ${style.blockquoteBg};
  border-left: 6px solid ${style.blockquoteBorder};
  padding: ${Math.round(fontSize * 0.6)}px ${Math.round(fontSize * 0.8)}px;
  margin: ${Math.round(fontSize * 0.6)}px 0;
  border-radius: 0 10px 10px 0;
  color: ${style.mutedColor};
}
.card-content hr {
  border: none; height: 2px;
  background: ${style.isDark ? "#334155" : "#e2e8f0"};
  margin: ${Math.round(fontSize * 1)}px 0;
}
.card-content img {
  max-width: 100%; border-radius: 12px;
  margin: ${Math.round(fontSize * 0.5)}px 0;
}
.page-num {
  position: absolute; bottom: ${Math.round(width * 0.03)}px; right: ${Math.round(width * 0.05)}px;
  font-size: ${Math.round(fontSize * 0.7)}px; color: ${style.mutedColor};
  opacity: 0.6;
}
</style></head>
<body>
<div class="card-outer">
  <div class="card-content">${htmlContent}</div>
  <div class="page-num">${pageNum}/${totalPages}</div>
</div>
</body></html>`;
}

// ─── Chrome Discovery ───────────────────────────────────────────────────────

function findChromeExecutable(): string {
  // Allow override via environment variable
  if (process.env.CHROME_PATH && existsSync(process.env.CHROME_PATH)) {
    return process.env.CHROME_PATH;
  }

  if (process.platform === "darwin") {
    const candidates = [
      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
      "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
      "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ];
    for (const p of candidates) {
      if (existsSync(p)) return p;
    }
  }

  throw new Error(
    "Chrome not found. Install Google Chrome or set CHROME_PATH environment variable.\n" +
      "Expected: /Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  );
}

// ─── Lazy Dependency Loading ────────────────────────────────────────────────

// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function importPuppeteer(): Promise<any> {
  try {
    return await import("puppeteer-core");
  } catch {
    console.error(kleur.red("Card rendering requires puppeteer-core."));
    console.error(kleur.dim("Install it with:"));
    console.error(kleur.dim("  npm install -g puppeteer-core"));
    process.exit(1);
  }
}

async function markdownToHtml(md: string): Promise<string> {
  try {
    const { marked } = await import("marked");
    return await marked.parse(md);
  } catch {
    console.error(kleur.red("Card rendering requires marked."));
    console.error(kleur.dim("Install it with:"));
    console.error(kleur.dim("  npm install -g marked"));
    process.exit(1);
  }
}

// ─── Main Render Function ───────────────────────────────────────────────────

const DEFAULT_OPTIONS: RenderOptions = {
  outputDir: ".",
  style: "xiaohongshu",
  pagination: "auto",
  width: 1080,
  height: 1440,
  dpr: 2,
};

export async function renderCards(
  inputPath: string,
  options: Partial<RenderOptions>
): Promise<RenderResult> {
  const absPath = resolve(inputPath);
  if (!existsSync(absPath)) {
    throw new Error(`File not found: ${absPath}`);
  }

  const content = readFileSync(absPath, "utf-8");
  const { frontmatter, body } = parseCardMarkdown(content);

  // Merge options: defaults → CLI opts → frontmatter overrides
  const opts: RenderOptions = {
    ...DEFAULT_OPTIONS,
    ...options,
    style: options.style ?? frontmatter.style ?? DEFAULT_OPTIONS.style,
    outputDir: options.outputDir ?? dirname(absPath),
  };

  const style = COLOR_STYLES[opts.style];
  if (!style) {
    const valid = Object.keys(COLOR_STYLES).join(", ");
    throw new Error(`Unknown style "${opts.style}". Valid styles: ${valid}`);
  }

  // Ensure output directory exists
  if (!existsSync(opts.outputDir)) {
    mkdirSync(opts.outputDir, { recursive: true });
  }

  // Paginate content
  const pages = paginateContent(body, opts.pagination);

  // Lazy-load dependencies
  const puppeteer = await importPuppeteer();
  const chromePath = findChromeExecutable();

  console.error(kleur.dim(`Using Chrome: ${chromePath}`));
  console.error(kleur.dim(`Style: ${style.name} | Pages: ${pages.length} | ${opts.width}x${opts.height} @${opts.dpr}x`));

  const launch = puppeteer.default?.launch ?? puppeteer.launch;
  const browser = await launch.call(puppeteer.default ?? puppeteer, {
    executablePath: chromePath,
    headless: true,
    args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu"],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({
      width: opts.width,
      height: opts.height,
      deviceScaleFactor: opts.dpr,
    });

    // Render cover
    const coverHtml = buildCoverHtml(frontmatter, style, opts.width, opts.height);
    await page.setContent(coverHtml, { waitUntil: "domcontentloaded" });
    const coverPath = join(opts.outputDir, "cover.png");
    await page.screenshot({
      path: coverPath,
      type: "png",
      clip: { x: 0, y: 0, width: opts.width, height: opts.height },
    });
    console.error(kleur.dim(`  Rendered: cover.png`));

    // Render content cards
    const cardPaths: string[] = [];
    for (let i = 0; i < pages.length; i++) {
      const html = await markdownToHtml(pages[i]);
      const cardHtml = buildCardHtml(
        html,
        i + 1,
        pages.length,
        style,
        opts.width,
        opts.height
      );
      await page.setContent(cardHtml, { waitUntil: "domcontentloaded" });
      const cardPath = join(opts.outputDir, `card_${i + 1}.png`);
      await page.screenshot({
        path: cardPath,
        type: "png",
        clip: { x: 0, y: 0, width: opts.width, height: opts.height },
      });
      cardPaths.push(cardPath);
      console.error(kleur.dim(`  Rendered: card_${i + 1}.png`));
    }

    return { coverPath, cardPaths, totalCards: pages.length };
  } finally {
    await browser.close();
  }
}
