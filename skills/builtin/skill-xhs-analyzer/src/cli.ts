#!/usr/bin/env node

/**
 * redbook CLI — Xiaohongshu (Red Note) from the command line
 *
 * Usage:
 *   redbook whoami --cookie-source chrome
 *   redbook search "Claude Code" --cookie-source chrome --json
 *   redbook read <url> --cookie-source chrome --json
 *   redbook comments <url> --cookie-source chrome --json
 *   redbook user <user-id-or-profile-url> --cookie-source chrome --json
 *   redbook user-posts <user-id-or-profile-url> --cookie-source chrome --json
 *   redbook account-report <user-id-or-profile-url...> --cookie-source chrome --json
 *   redbook feed --cookie-source chrome --json
 *   redbook post --title "..." --body "..." --images img1.jpg --cookie-source chrome
 *   redbook topics "keyword" --cookie-source chrome
 *   redbook favorites --cookie-source chrome --json
 *   redbook collect <url> --cookie-source chrome
 *   redbook uncollect <url> --cookie-source chrome
 *   redbook like <url> --cookie-source chrome
 *   redbook like <url> --undo --cookie-source chrome
 *   redbook followers <user-id> --cookie-source chrome --json
 *   redbook following <user-id> --cookie-source chrome --json
 *   redbook delete <url> --cookie-source chrome
 *   redbook health --cookie-source chrome --json
 *   redbook board <board-url> --cookie-source chrome --json
 */

import { Command } from "commander";
import kleur from "kleur";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  readFileSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, isAbsolute, join, resolve } from "node:path";
import {
  extractCookies,
  parseCookieString,
  type CookieSource,
  type XhsCookies,
} from "./lib/cookies.js";
import { resolvePlatform, type PlatformId } from "./lib/platform.js";
import { detectPlatform, detectPlatformForCookies } from "./lib/detect.js";
import { XhsClient, XhsApiError } from "./lib/client.js";
import { analyzeViral, formatViralAnalysis } from "./lib/analyze.js";
import {
  selectCandidates,
  executeReplies,
  DEFAULT_DELAY_MS,
  MIN_DELAY_MS as MIN_REPLY_DELAY,
  MAX_REPLIES_HARD_CAP,
  type StrategyName,
} from "./lib/reply-strategy.js";
import { extractTemplate, formatTemplate } from "./lib/template.js";
import { buildHealthReport, type NoteDiagnostics } from "./lib/health.js";
import { buildWebUrl, enrichWithWebUrl } from "./lib/url.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const pkg = JSON.parse(readFileSync(join(__dirname, "..", "package.json"), "utf-8"));
const REDBOOK_DIR = join(homedir(), ".redbook");
const DEFAULT_COOKIE_FILE = join(REDBOOK_DIR, "cookies.json");

const program = new Command();

program
  .name("redbook")
  .description("CLI tool for Xiaohongshu (Red Note)")
  .version(pkg.version);

// Global option for cookie source
function addCookieOption(cmd: Command): Command {
  return cmd
    .option(
      "--cookie-source <browser>",
      "Browser to read cookies from (chrome, safari, firefox)",
      "chrome"
    )
    .option(
      "--chrome-profile <name>",
      'Chrome profile directory name (e.g., "Profile 1")'
    )
    .option(
      "--cookie-string <cookies>",
      'Manual cookie string: "a1=VALUE; web_session=VALUE" (from Chrome DevTools)'
    )
    .option(
      "--platform <name>",
      "Force backend: 'xhs' (mainland xiaohongshu.com) or 'rednote' (global rednote.com). Default: auto-detect from your login."
    )
    .option(
      "--global",
      "Force the global RedNote backend (shorthand for --platform rednote)"
    );
}

function addJsonOption(cmd: Command): Command {
  return cmd.option("--json", "Output as JSON");
}

function addUserPageOptions(cmd: Command): Command {
  return cmd
    .option("--xsec-token <token>", "xsec_token from a user profile URL or search result")
    .option("--xsec-source <source>", "xsec_source paired with the user profile token");
}

interface LoadedCookieFile {
  path: string;
  cookies: XhsCookies;
  platform?: PlatformId;
  createdAt?: string;
}

interface SavedCookieSummary {
  path: string;
  platform: PlatformId | null;
  createdAt: string | null;
  keyCount: number;
  keys: string[];
  hasA1: boolean;
  hasWebSession: boolean;
}

function expandHomePath(filePath: string): string {
  if (filePath === "~") return homedir();
  if (filePath.startsWith("~/")) return join(homedir(), filePath.slice(2));
  return filePath;
}

function resolveCookieFilePath(filePath?: string): string {
  const raw = expandHomePath(filePath || process.env.REDBOOK_COOKIE_FILE || DEFAULT_COOKIE_FILE);
  return isAbsolute(raw) ? raw : resolve(process.cwd(), raw);
}

function defaultCookieFileForRead(): string | null {
  if (process.env.REDBOOK_COOKIE_FILE) {
    return resolveCookieFilePath(process.env.REDBOOK_COOKIE_FILE);
  }
  return existsSync(DEFAULT_COOKIE_FILE) ? DEFAULT_COOKIE_FILE : null;
}

function parsePlatformId(value: unknown, source: string): PlatformId | undefined {
  if (value == null || value === "") return undefined;
  if (typeof value !== "string") {
    throw new Error(`${source} has an invalid platform value.`);
  }
  const raw = value.toLowerCase();
  if (raw === "xhs" || raw === "xiaohongshu" || raw === "mainland") return "xhs";
  if (raw === "rednote" || raw === "global") return "rednote";
  throw new Error(`${source} platform must be 'xhs' or 'rednote'.`);
}

function validateCookieMap(cookies: XhsCookies, source: string): XhsCookies {
  if (!cookies.a1 || !cookies.web_session) {
    throw new Error(
      `${source} must contain at least 'a1' and 'web_session'. ` +
      "Copy them from Chrome DevTools > Application > Cookies."
    );
  }
  return cookies;
}

function cookieMapFromRecord(record: Record<string, unknown>, source: string): XhsCookies {
  const cookies: Record<string, string> = {};
  for (const [key, value] of Object.entries(record)) {
    if (typeof value === "string") cookies[key] = value;
  }
  return validateCookieMap(cookies as XhsCookies, source);
}

function parseManualCookies(cookieString: string, source: string): XhsCookies {
  return validateCookieMap(parseCookieString(cookieString), source);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function loadSavedCookieFile(filePath?: string): LoadedCookieFile {
  const path = resolveCookieFilePath(filePath);
  const raw = readFileSync(path, "utf-8").trim();
  if (!raw) throw new Error(`Cookie file is empty: ${path}`);

  if (!raw.startsWith("{")) {
    return {
      path,
      cookies: parseManualCookies(raw, `Cookie file ${path}`),
    };
  }

  const parsed = JSON.parse(raw) as unknown;
  if (!isRecord(parsed)) throw new Error(`Cookie file must be a JSON object: ${path}`);

  const platform = parsePlatformId(parsed.platform, `Cookie file ${path}`);
  const createdAt = typeof parsed.createdAt === "string" ? parsed.createdAt : undefined;

  if (typeof parsed.cookieString === "string") {
    return {
      path,
      platform,
      createdAt,
      cookies: parseManualCookies(parsed.cookieString, `Cookie file ${path}`),
    };
  }

  if (isRecord(parsed.cookies)) {
    return {
      path,
      platform,
      createdAt,
      cookies: cookieMapFromRecord(parsed.cookies, `Cookie file ${path}`),
    };
  }

  return {
    path,
    platform,
    createdAt,
    cookies: cookieMapFromRecord(parsed, `Cookie file ${path}`),
  };
}

function writeSavedCookieFile(filePath: string, cookies: XhsCookies, platform: PlatformId): LoadedCookieFile {
  const path = resolveCookieFilePath(filePath);
  validateCookieMap(cookies, "Cookie data");
  mkdirSync(dirname(path), { recursive: true });
  const createdAt = new Date().toISOString();
  const sortedCookies = Object.fromEntries(
    Object.entries(cookies).sort(([a], [b]) => a.localeCompare(b))
  );
  writeFileSync(
    path,
    JSON.stringify(
      {
        version: 1,
        platform,
        createdAt,
        cookies: sortedCookies,
      },
      null,
      2
    ) + "\n",
    { mode: 0o600 }
  );
  try {
    chmodSync(path, 0o600);
  } catch {
    // Best effort on platforms/filesystems that do not support POSIX modes.
  }
  return { path, cookies, platform, createdAt };
}

function summarizeCookieFile(loaded: LoadedCookieFile): SavedCookieSummary {
  const keys = Object.keys(loaded.cookies).sort();
  return {
    path: loaded.path,
    platform: loaded.platform ?? null,
    createdAt: loaded.createdAt ?? null,
    keyCount: keys.length,
    keys,
    hasA1: Boolean(loaded.cookies.a1),
    hasWebSession: Boolean(loaded.cookies.web_session),
  };
}

function printCookieSummary(summary: SavedCookieSummary, verb: string): void {
  console.log(kleur.green(`${verb}: ${summary.path}`));
  console.log(`  Platform: ${summary.platform ?? "not stored"}`);
  console.log(`  Keys: ${summary.keys.join(", ")}`);
  if (summary.createdAt) console.log(`  Created: ${summary.createdAt}`);
}

function optionPlatform(opts: { global?: boolean; platform?: string }): string | undefined {
  return opts.global ? "rednote" : opts.platform;
}

async function getClient(cookieSource: string, chromeProfile?: string, cookieString?: string, platform?: string): Promise<XhsClient> {
  // An explicit choice (--platform / --global / REDBOOK_PLATFORM) skips detection.
  const explicit = platform || process.env.REDBOOK_PLATFORM;
  const cookieStringInput = cookieString || process.env.REDBOOK_COOKIE_STRING;

  // ── Manual cookie string ──
  if (cookieStringInput) {
    const cookies = parseManualCookies(
      cookieStringInput,
      cookieString ? "--cookie-string" : "REDBOOK_COOKIE_STRING"
    );
    console.error(kleur.dim(cookieString ? "Using manual cookie string." : "Using REDBOOK_COOKIE_STRING."));
    const cfg = explicit ? resolvePlatform(explicit) : await detectPlatformForCookies(cookies);
    return new XhsClient(cookies, cfg);
  }

  // ── Saved cookie file ──
  const savedCookiePath = defaultCookieFileForRead();
  if (savedCookiePath) {
    const saved = loadSavedCookieFile(savedCookiePath);
    const cfg = explicit
      ? resolvePlatform(explicit)
      : saved.platform
        ? resolvePlatform(saved.platform)
        : resolvePlatform();
    console.error(kleur.dim(`Using saved cookie file: ${saved.path}`));
    return new XhsClient(saved.cookies, cfg);
  }

  // ── Explicit platform ──
  if (explicit) {
    const cfg = resolvePlatform(explicit);
    if (cfg.id === "rednote") console.error(kleur.dim("Platform: RedNote (global, rednote.com)."));
    const cookies = await extractCookies(cookieSource as CookieSource, chromeProfile, cfg.cookieUrl);
    return new XhsClient(cookies, cfg);
  }

  // ── Auto-detect (default): find whichever of xiaohongshu.com / rednote.com
  //    the user is actually logged into. ──
  const det = await detectPlatform(cookieSource as CookieSource, chromeProfile);
  const cookies = det.cookies
    ?? await extractCookies(cookieSource as CookieSource, chromeProfile, det.platform.cookieUrl);
  return new XhsClient(cookies, det.platform);
}

function output(data: unknown, json: boolean): void {
  if (json) {
    console.log(JSON.stringify(data, null, 2));
  } else {
    console.log(data);
  }
}

function handleError(err: unknown): never {
  if (err instanceof XhsApiError) {
    console.error(kleur.red(`Error: ${err.message}`));
    if (err.code) console.error(kleur.dim(`Code: ${err.code}`));
  } else if (err instanceof Error) {
    console.error(kleur.red(`Error: ${err.message}`));
  } else {
    console.error(kleur.red("Unknown error"));
  }
  process.exit(1);
}

// ─── whoami ─────────────────────────────────────────────────────────────────

const whoamiCmd = program.command("whoami").description("Check connection and show current user info");
addCookieOption(whoamiCmd);
addJsonOption(whoamiCmd);

whoamiCmd.action(async (opts) => {
  try {
    const client = await getClient(opts.cookieSource, opts.chromeProfile, opts.cookieString, opts.global ? "rednote" : opts.platform);
    const info = await client.getSelfInfo();
    if (opts.json) {
      output(info, true);
    } else {
      const user = info as Record<string, unknown>;
      console.log(kleur.green(`Connected to ${client.platformLabel}`));
      console.log(`  User: ${kleur.bold(String(user.nickname ?? user.nick_name ?? "unknown"))}`);
      console.log(`  ID:   ${user.user_id ?? "unknown"}`);
      if (user.red_id) console.log(`  RedID: ${user.red_id}`);
    }
  } catch (err) {
    handleError(err);
  }
});

// ─── auth ──────────────────────────────────────────────────────────────────

const authCmd = program
  .command("auth")
  .description("Manage saved cookies for cloud/CI environments");

const authPathCmd = authCmd
  .command("path")
  .description("Print the default saved cookie file path");
addJsonOption(authPathCmd);

authPathCmd.action((opts) => {
  const data = { path: resolveCookieFilePath() };
  if (opts.json) output(data, true);
  else console.log(data.path);
});

const authSaveCmd = authCmd
  .command("save")
  .description("Save a manual cookie string to a reusable cookie file")
  .requiredOption(
    "--cookie-string <cookies>",
    'Cookie string from Chrome DevTools, e.g. "a1=VALUE; web_session=VALUE"'
  )
  .option("--output <path>", "Cookie file to write (default: ~/.redbook/cookies.json)")
  .option(
    "--platform <name>",
    "Cookie backend: 'xhs' (mainland xiaohongshu.com) or 'rednote' (global rednote.com)",
    "xhs"
  )
  .option("--global", "Save as global RedNote cookies (shorthand for --platform rednote)");
addJsonOption(authSaveCmd);

authSaveCmd.action((opts) => {
  try {
    const cfg = resolvePlatform(optionPlatform(opts));
    const cookies = parseManualCookies(opts.cookieString, "--cookie-string");
    const saved = writeSavedCookieFile(resolveCookieFilePath(opts.output), cookies, cfg.id);
    const summary = summarizeCookieFile(saved);
    if (opts.json) output(summary, true);
    else printCookieSummary(summary, "Saved cookie file");
  } catch (err) {
    handleError(err);
  }
});

const authExportCmd = authCmd
  .command("export [output]")
  .description("Export browser cookies to a reusable cookie file")
  .option("--output <path>", "Cookie file to write (default: ~/.redbook/cookies.json)")
  .option(
    "--cookie-source <browser>",
    "Browser to read cookies from (chrome, safari, firefox)",
    "chrome"
  )
  .option(
    "--chrome-profile <name>",
    'Chrome profile directory name (e.g., "Profile 1")'
  )
  .option(
    "--platform <name>",
    "Force backend: 'xhs' (mainland xiaohongshu.com) or 'rednote' (global rednote.com). Default: auto-detect."
  )
  .option("--global", "Force the global RedNote backend (shorthand for --platform rednote)");
addJsonOption(authExportCmd);

authExportCmd.action(async (outputPath: string | undefined, opts) => {
  try {
    const explicit = optionPlatform(opts);
    const source = opts.cookieSource as CookieSource;
    const cfg = explicit ? resolvePlatform(explicit) : undefined;
    const detected = cfg ? null : await detectPlatform(source, opts.chromeProfile);
    const platform = cfg ?? detected!.platform;
    const cookies = detected?.cookies ?? await extractCookies(
      source,
      opts.chromeProfile,
      platform.cookieUrl
    );
    const saved = writeSavedCookieFile(resolveCookieFilePath(outputPath || opts.output), cookies, platform.id);
    const summary = summarizeCookieFile(saved);
    if (opts.json) output(summary, true);
    else printCookieSummary(summary, "Exported cookie file");
  } catch (err) {
    handleError(err);
  }
});

const authInspectCmd = authCmd
  .command("inspect [file]")
  .description("Inspect a saved cookie file without printing secret values");
addJsonOption(authInspectCmd);

authInspectCmd.action((file: string | undefined, opts) => {
  try {
    const summary = summarizeCookieFile(loadSavedCookieFile(file));
    if (opts.json) output(summary, true);
    else printCookieSummary(summary, "Cookie file");
  } catch (err) {
    handleError(err);
  }
});

const authClearCmd = authCmd
  .command("clear [file]")
  .description("Remove a saved cookie file");
addJsonOption(authClearCmd);

authClearCmd.action((file: string | undefined, opts) => {
  try {
    const path = resolveCookieFilePath(file);
    const existed = existsSync(path);
    if (existed) unlinkSync(path);
    const result = { path, removed: existed };
    if (opts.json) output(result, true);
    else console.log(existed ? kleur.green(`Removed: ${path}`) : kleur.yellow(`Not found: ${path}`));
  } catch (err) {
    handleError(err);
  }
});

// ─── search ─────────────────────────────────────────────────────────────────

const searchCmd = program
  .command("search <keyword>")
  .description("Search notes by keyword")
  .option("--page <n>", "Page number", "1")
  .option("--sort <type>", "Sort: general, popular, latest", "general")
  .option("--type <type>", "Note type: all, video, image", "all");
addCookieOption(searchCmd);
addJsonOption(searchCmd);

searchCmd.action(async (keyword, opts) => {
  try {
    const client = await getClient(opts.cookieSource, opts.chromeProfile, opts.cookieString, opts.global ? "rednote" : opts.platform);
    const sortMap: Record<string, "general" | "popularity_descending" | "time_descending"> = {
      general: "general",
      popular: "popularity_descending",
      latest: "time_descending",
    };
    const typeMap: Record<string, 0 | 1 | 2> = { all: 0, video: 1, image: 2 };

    const result = await client.searchNotes(
      keyword,
      parseInt(opts.page),
      20,
      sortMap[opts.sort] ?? "general",
      typeMap[opts.type] ?? 0
    );
    enrichWithWebUrl(result, "pc_search");

    if (opts.json) {
      output(result, true);
    } else {
      const data = result as { items?: Array<{ note_card?: { title?: string; user?: { nickname?: string }; note_id?: string; interact_info?: Record<string, string> } }> };
      if (data.items) {
        for (const item of data.items) {
          const card = item.note_card;
          if (!card) continue;
          console.log(
            `${kleur.bold(card.title ?? "(no title)")} — ${kleur.dim(`@${card.user?.nickname ?? "?"}`)}` +
            `  ${kleur.cyan(card.note_id ?? "")}`
          );
          if (card.interact_info) {
            const info = card.interact_info;
            console.log(
              `  ${kleur.dim(`♥ ${info.liked_count ?? 0}  💬 ${info.comment_count ?? 0}  ⭐ ${info.collected_count ?? 0}`)}`
            );
          }
        }
      }
    }
  } catch (err) {
    handleError(err);
  }
});

// ─── read ───────────────────────────────────────────────────────────────────

const readCmd = program
  .command("read <url>")
  .description("Read a note by URL (tries HTML fallback first)")
  .option("--api", "Force API mode (requires xsec_token in URL)");
addCookieOption(readCmd);
addJsonOption(readCmd);

readCmd.action(async (url, opts) => {
  try {
    const client = await getClient(opts.cookieSource, opts.chromeProfile, opts.cookieString, opts.global ? "rednote" : opts.platform);
    const { noteId, xsecToken } = parseNoteUrl(url);

    let result: unknown;
    if (opts.api || xsecToken) {
      try {
        const feedResult = (await client.getNoteById(
          noteId,
          xsecToken ?? ""
        )) as { items?: Array<{ note_card?: unknown }> };
        result = feedResult?.items?.[0]?.note_card ?? feedResult;
      } catch {
        // Fall back to HTML
        result = await client.getNoteFromHtml(noteId, xsecToken ?? "");
      }
    } else {
      result = await client.getNoteFromHtml(noteId, xsecToken ?? "");
    }

    // Attach the fully-signed webUrl (uses the token passed in on the URL).
    // Without a token any `/explore/<id>` URL 302s to the xhs_sec_server gate.
    if (result && typeof result === "object" && xsecToken) {
      const r = result as Record<string, unknown>;
      if (!r.webUrl) r.webUrl = buildWebUrl(noteId, xsecToken, "pc_share");
    }

    const isEmptyResult =
      !result ||
      (typeof result === "object" &&
        !Array.isArray(result) &&
        Object.keys(result as Record<string, unknown>).length === 0);
    if (isEmptyResult && !xsecToken) {
      console.error(kleur.yellow(
        "Note returned empty. This usually means the request needs an xsec_token.\n" +
        "Tip: use a full note URL from search results or the browser address bar, e.g.:\n" +
        `  redbook read "https://www.xiaohongshu.com/explore/${noteId}?xsec_token=TOKEN&xsec_source=pc_search"`
      ));
    }

    if (opts.json) {
      output(result, true);
    } else {
      const note = result as Record<string, unknown>;
      console.log(kleur.bold(String(note.title ?? "(no title)")));
      console.log(kleur.dim(`by @${(note.user as Record<string, unknown>)?.nickname ?? "unknown"}`));
      console.log();
      console.log(String(note.desc ?? ""));
      if (note.interact_info) {
        const info = note.interact_info as Record<string, string>;
        console.log();
        console.log(
          `♥ ${info.liked_count ?? 0}  💬 ${info.comment_count ?? 0}  ⭐ ${info.collected_count ?? 0}  📤 ${info.share_count ?? 0}`
        );
      }
    }
  } catch (err) {
    handleError(err);
  }
});

// ─── comments ───────────────────────────────────────────────────────────────

const commentsCmd = program
  .command("comments <url>")
  .description("Get comments on a note")
  .option("--all", "Fetch all pages of comments");
addCookieOption(commentsCmd);
addJsonOption(commentsCmd);

commentsCmd.action(async (url, opts) => {
  try {
    const client = await getClient(opts.cookieSource, opts.chromeProfile, opts.cookieString, opts.global ? "rednote" : opts.platform);
    const { noteId, xsecToken } = parseNoteUrl(url);

    const allComments: unknown[] = [];
    let cursor = "";
    let hasMore = true;

    while (hasMore) {
      const res = (await client.getComments(noteId, cursor, xsecToken ?? "")) as {
        comments?: unknown[];
        has_more?: boolean;
        cursor?: string;
      };

      if (res.comments) allComments.push(...res.comments);
      hasMore = opts.all ? (res.has_more ?? false) : false;
      cursor = res.cursor ?? "";
    }

    if (opts.json) {
      output(allComments, true);
    } else {
      for (const comment of allComments) {
        const c = comment as Record<string, unknown>;
        const user = c.user_info as Record<string, unknown> | undefined;
        console.log(
          `${kleur.bold(`@${user?.nickname ?? "?"}`)} — ${String(c.content ?? "")}`
        );
        if (c.like_count) console.log(kleur.dim(`  ♥ ${c.like_count}`));
      }
      console.log(kleur.dim(`\n${allComments.length} comments`));
    }
  } catch (err) {
    handleError(err);
  }
});

// ─── user ───────────────────────────────────────────────────────────────────

const userCmd = program
  .command("user <user>")
  .description("Get user profile info");
addCookieOption(userCmd);
addJsonOption(userCmd);
addUserPageOptions(userCmd);

userCmd.action(async (userArg, opts) => {
  try {
    const client = await getClient(opts.cookieSource, opts.chromeProfile, opts.cookieString, opts.global ? "rednote" : opts.platform);
    const user = parseUserProfileArg(userArg, opts);
    const info = await client.getUserInfo(user.userId, user);
    output(info, opts.json ?? false);
  } catch (err) {
    handleError(err);
  }
});

// ─── user-posts ─────────────────────────────────────────────────────────────

const userPostsCmd = program
  .command("user-posts <user>")
  .description("List a user's posted notes");
addCookieOption(userPostsCmd);
addJsonOption(userPostsCmd);
addUserPageOptions(userPostsCmd);
userPostsCmd.option("--cursor <cursor>", "Resume pagination from a cursor (last note_id)");
userPostsCmd.option("--all", "Fetch all pages (paginate until no more results)");
userPostsCmd.option("--delay <ms>", "Delay in ms between page fetches (default: 3000)", "3000");

userPostsCmd.action(async (userArg, opts) => {
  try {
    const client = await getClient(opts.cookieSource, opts.chromeProfile, opts.cookieString, opts.global ? "rednote" : opts.platform);
    const user = parseUserProfileArg(userArg, opts);

    if (opts.all) {
      let cursor: string = opts.cursor ?? "";
      const allNotes: Array<Record<string, unknown>> = [];
      let page = 1;
      while (true) {
        const res = (await client.getUserNotes(user.userId, cursor, user)) as {
          notes?: Array<Record<string, unknown>>;
          has_more?: boolean;
          cursor?: string;
        };
        const notes = res.notes ?? [];
        enrichWithWebUrl(notes, "pc_user");
        allNotes.push(...notes);
        process.stderr.write(`Page ${page}: +${notes.length} notes (total: ${allNotes.length})\n`);
        if (!res.has_more || !res.cursor || notes.length === 0) break;
        cursor = res.cursor;
        page++;
        await new Promise((r) => setTimeout(r, parseInt(opts.delay)));
      }
      if (opts.json) {
        output({ notes: allNotes, total: allNotes.length }, true);
      } else {
        for (const note of allNotes) {
          console.log(
            `${kleur.bold(String(note.display_title ?? "(no title)"))}  ${kleur.dim(String(note.note_id ?? ""))}  [${String(note.type ?? "?")}]`
          );
        }
        console.log(kleur.dim(`\n${allNotes.length} notes total`));
      }
      return;
    }

    const result = await client.getUserNotes(user.userId, opts.cursor ?? "", user);
    enrichWithWebUrl(result, "pc_user");
    if (opts.json) {
      output(result, true);
    } else {
      const data = result as { notes?: Array<{ display_title?: string; note_id?: string; type?: string }> };
      if (data.notes) {
        for (const note of data.notes) {
          console.log(
            `${kleur.bold(note.display_title ?? "(no title)")}  ${kleur.dim(note.note_id ?? "")}  [${note.type ?? "?"}]`
          );
        }
        console.log(kleur.dim(`\n${data.notes.length} notes`));
      }
    }
  } catch (err) {
    handleError(err);
  }
});

// ─── account-report ─────────────────────────────────────────────────────────

const accountReportCmd = program
  .command("account-report [users...]")
  .alias("creator-report")
  .description("Summarize posting activity and engagement for one or more accounts");
addCookieOption(accountReportCmd);
addJsonOption(accountReportCmd);
addUserPageOptions(accountReportCmd);
accountReportCmd.option("--file <path>", "Read account IDs/profile URLs from a newline-separated file");
accountReportCmd.option("--month <yyyy-mm>", "Month to count posts for (default: current month)");
accountReportCmd.option("--all", "Fetch all pages for each account");
accountReportCmd.option("--max-pages <n>", "Max pages per account when --all is not set (default: 1)");
accountReportCmd.option("--delay <ms>", "Delay in ms between page/account fetches (default: 3000)");

accountReportCmd.action(async (users: string[] | undefined, opts) => {
  try {
    const inputs = collectAccountInputs(users ?? [], opts.file);
    if (inputs.length === 0) {
      console.error(kleur.red("Provide at least one account ID/profile URL, or use --file <path>."));
      process.exit(1);
    }

    const month = parseReportMonth(opts.month);
    const delayMs = Math.max(0, parseInt(opts.delay ?? "3000", 10) || 0);
    const maxPages = opts.all
      ? Number.POSITIVE_INFINITY
      : Math.max(1, parseInt(opts.maxPages ?? "1", 10) || 1);
    const client = await getClient(opts.cookieSource, opts.chromeProfile, opts.cookieString, opts.global ? "rednote" : opts.platform);
    const reports: AccountReport[] = [];
    const errors: Array<{ input: string; userId?: string; error: string }> = [];

    for (let idx = 0; idx < inputs.length; idx++) {
      const input = inputs[idx];
      const user = parseUserProfileArg(input, opts);
      try {
        const report = await buildAccountReport(client, input, user, month, maxPages, delayMs);
        reports.push(report);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        errors.push({ input, userId: user.userId, error: message });
        console.error(kleur.red(`Failed ${user.userId}: ${message}`));
      }

      if (idx < inputs.length - 1 && delayMs > 0) {
        await sleep(delayMs);
      }
    }

    const result = {
      month: month.label,
      generatedAt: new Date().toISOString(),
      accounts: reports,
      errors,
    };

    if (opts.json) {
      output(result, true);
    } else {
      printAccountReport(result);
    }

    if (errors.length > 0) process.exitCode = 1;
  } catch (err) {
    handleError(err);
  }
});

// ─── feed ───────────────────────────────────────────────────────────────────

const feedCmd = program
  .command("feed")
  .description("Get homepage feed")
  .option("--category <cat>", "Feed category", "homefeed_recommend");
addCookieOption(feedCmd);
addJsonOption(feedCmd);

feedCmd.action(async (opts) => {
  try {
    const client = await getClient(opts.cookieSource, opts.chromeProfile, opts.cookieString, opts.global ? "rednote" : opts.platform);
    const result = await client.getHomeFeed(opts.category);
    enrichWithWebUrl(result, "pc_feed");
    output(result, opts.json ?? false);
  } catch (err) {
    handleError(err);
  }
});

// ─── post ───────────────────────────────────────────────────────────────────

const postCmd = program
  .command("post")
  .description("Publish an image note")
  .requiredOption("--title <title>", "Note title")
  .requiredOption("--body <body>", "Note body text")
  .option("--images <paths...>", "Image file paths")
  .option("--topic <keyword>", "Topic/hashtag keyword to search and attach")
  .option("--private", "Publish as private note");
addCookieOption(postCmd);
addJsonOption(postCmd);

postCmd.action(async (opts) => {
  try {
    const client = await getClient(opts.cookieSource, opts.chromeProfile, opts.cookieString, opts.global ? "rednote" : opts.platform);
    const imageFiles: string[] = opts.images ?? [];

    if (imageFiles.length === 0) {
      console.error(kleur.red("At least one image is required. Use --images <path>"));
      process.exit(1);
    }

    // Upload images
    console.log(kleur.dim("Uploading images..."));
    const fileIds: string[] = [];
    for (const filePath of imageFiles) {
      const { fileId, token } = await client.getUploadPermit("image");
      const ext = filePath.toLowerCase().split(".").pop();
      const contentType =
        ext === "png" ? "image/png" : ext === "webp" ? "image/webp" : "image/jpeg";
      await client.uploadFile(fileId, token, filePath, contentType);
      fileIds.push(fileId);
      console.log(kleur.dim(`  Uploaded: ${filePath} → ${fileId}`));
    }

    // Search for topic if specified
    let topics: Array<{ id: string; name: string; type: string }> = [];
    if (opts.topic) {
      const topicResult = (await client.searchTopics(opts.topic)) as Array<{
        id: string;
        name: string;
        type: string;
      }>;
      if (topicResult.length > 0) {
        topics = [topicResult[0]];
        console.log(kleur.dim(`  Topic: #${topicResult[0].name}`));
      }
    }

    // Create the note
    console.log(kleur.dim("Publishing note..."));
    const result = await client.createImageNote(opts.title, opts.body, fileIds, {
      topics,
      isPrivate: opts.private ?? false,
    });

    const r = result as Record<string, unknown>;
    if (r.note_id && typeof r.xsec_token === "string") {
      r.webUrl = buildWebUrl(r.note_id as string, r.xsec_token, "pc_share");
    }
    if (opts.json) {
      output(result, true);
    } else {
      console.log(kleur.green("Note published!"));
      if (r.note_id) {
        const url = typeof r.webUrl === "string"
          ? r.webUrl
          : `https://www.xiaohongshu.com/explore/${r.note_id}`;
        console.log(`  URL: ${url}`);
      }
      console.error(kleur.yellow("⚠ Rate limit: wait ≥3-4 hours before the next post (2-3 notes/day max)."));
    }
  } catch (err) {
    handleError(err);
  }
});

// ─── topics ─────────────────────────────────────────────────────────────────

const topicsCmd = program
  .command("topics <keyword>")
  .description("Search for topics/hashtags to use in posts");
addCookieOption(topicsCmd);
addJsonOption(topicsCmd);

topicsCmd.action(async (keyword, opts) => {
  try {
    const client = await getClient(opts.cookieSource, opts.chromeProfile, opts.cookieString, opts.global ? "rednote" : opts.platform);
    const result = await client.searchTopics(keyword);
    if (opts.json) {
      output(result, true);
    } else {
      const data = result as { topic_info_dtos?: Array<{ name?: string; id?: string; view_num?: number }> };
      const topics = data.topic_info_dtos ?? (Array.isArray(result) ? result as Array<{ name?: string; id?: string; view_num?: number }> : []);
      for (const topic of topics) {
        console.log(
          `#${kleur.bold(topic.name ?? "?")}  ${kleur.dim(`id:${topic.id ?? "?"}`)}  ${kleur.dim(`views:${topic.view_num ?? "?"}`)}`
        );
      }
    }
  } catch (err) {
    handleError(err);
  }
});

// ─── favorites ──────────────────────────────────────────────────────────────

const favoritesCmd = program
  .command("favorites [userId]")
  .description("List a user's collected/favorited notes (defaults to current user)")
  .option("--all", "Fetch all pages");
addCookieOption(favoritesCmd);
addJsonOption(favoritesCmd);

favoritesCmd.action(async (userId, opts) => {
  try {
    const client = await getClient(opts.cookieSource, opts.chromeProfile, opts.cookieString, opts.global ? "rednote" : opts.platform);

    if (!userId) {
      const me = (await client.getSelfInfo()) as Record<string, unknown>;
      userId = String(me.user_id ?? "");
      if (!userId) {
        console.error(kleur.red("Could not determine current user ID"));
        process.exit(1);
      }
    }

    const allNotes: unknown[] = [];
    let cursor = "";
    let hasMore = true;

    while (hasMore) {
      const res = (await client.getUserCollectedNotes(userId, 30, cursor)) as {
        notes?: unknown[];
        has_more?: boolean;
        cursor?: string;
      };

      if (res.notes) {
        enrichWithWebUrl(res.notes, "pc_user");
        allNotes.push(...res.notes);
      }
      hasMore = opts.all ? (res.has_more ?? false) : false;
      cursor = res.cursor ?? "";
    }

    if (opts.json) {
      output(allNotes, true);
    } else {
      for (const note of allNotes) {
        const n = note as Record<string, unknown>;
        const user = n.user as Record<string, unknown> | undefined;
        console.log(
          `${kleur.bold(String(n.display_title ?? n.title ?? "(no title)"))}  ${kleur.dim(String(n.note_id ?? ""))}  ${kleur.dim(`@${user?.nickname ?? "?"}`)}`
        );
      }
      console.log(kleur.dim(`\n${allNotes.length} collected notes`));
    }
  } catch (err) {
    handleError(err);
  }
});

// ─── collect ────────────────────────────────────────────────────────────────

const collectCmd = program
  .command("collect <url>")
  .description("Collect (bookmark) a note");
addCookieOption(collectCmd);
addJsonOption(collectCmd);

collectCmd.action(async (url, opts) => {
  try {
    const client = await getClient(opts.cookieSource, opts.chromeProfile, opts.cookieString, opts.global ? "rednote" : opts.platform);
    const { noteId } = parseNoteUrl(url);
    const result = await client.collectNote(noteId);
    if (opts.json) {
      output(result, true);
    } else {
      console.log(kleur.green("Note collected!"));
    }
  } catch (err) {
    handleError(err);
  }
});

// ─── uncollect ──────────────────────────────────────────────────────────────

const uncollectCmd = program
  .command("uncollect <url>")
  .description("Remove a note from your collection");
addCookieOption(uncollectCmd);
addJsonOption(uncollectCmd);

uncollectCmd.action(async (url, opts) => {
  try {
    const client = await getClient(opts.cookieSource, opts.chromeProfile, opts.cookieString, opts.global ? "rednote" : opts.platform);
    const { noteId } = parseNoteUrl(url);
    const result = await client.uncollectNote(noteId);
    if (opts.json) {
      output(result, true);
    } else {
      console.log(kleur.green("Note removed from collection!"));
    }
  } catch (err) {
    handleError(err);
  }
});

// ─── like ──────────────────────────────────────────────────────────────────

const likeCmd = program
  .command("like <url>")
  .description("Like a note")
  .option("--undo", "Unlike the note instead");
addCookieOption(likeCmd);
addJsonOption(likeCmd);

likeCmd.action(async (url, opts) => {
  try {
    const client = await getClient(opts.cookieSource, opts.chromeProfile, opts.cookieString, opts.global ? "rednote" : opts.platform);
    const { noteId } = parseNoteUrl(url);
    if (opts.undo) {
      const result = await client.unlikeNote(noteId);
      if (opts.json) { output(result, true); } else { console.log(kleur.green("Note unliked!")); }
    } else {
      const result = await client.likeNote(noteId);
      if (opts.json) { output(result, true); } else { console.log(kleur.green("Note liked!")); }
    }
  } catch (err) {
    handleError(err);
  }
});

// ─── followers ─────────────────────────────────────────────────────────────

const followersCmd = program
  .command("followers <userId>")
  .description("List a user's followers")
  .option("--all", "Fetch all pages");
addCookieOption(followersCmd);
addJsonOption(followersCmd);

followersCmd.action(async (userId, opts) => {
  try {
    const client = await getClient(opts.cookieSource, opts.chromeProfile, opts.cookieString, opts.global ? "rednote" : opts.platform);
    const allUsers: unknown[] = [];
    let cursor = "";
    let hasMore = true;

    while (hasMore) {
      const res = (await client.getUserFollowers(userId, cursor)) as {
        users?: unknown[];
        has_more?: boolean;
        cursor?: string;
      };
      if (res.users) allUsers.push(...res.users);
      hasMore = opts.all ? (res.has_more ?? false) : false;
      cursor = res.cursor ?? "";
    }

    if (opts.json) {
      output(allUsers, true);
    } else {
      for (const user of allUsers) {
        const u = user as Record<string, unknown>;
        console.log(
          `${kleur.bold(String(u.nickname ?? "?"))}  ${kleur.dim(String(u.user_id ?? ""))}  ${kleur.dim(String(u.desc ?? "").slice(0, 60))}`
        );
      }
      console.log(kleur.dim(`\n${allUsers.length} followers`));
    }
  } catch (err) {
    handleError(err);
  }
});

// ─── following ─────────────────────────────────────────────────────────────

const followingCmd = program
  .command("following <userId>")
  .description("List accounts a user follows")
  .option("--all", "Fetch all pages");
addCookieOption(followingCmd);
addJsonOption(followingCmd);

followingCmd.action(async (userId, opts) => {
  try {
    const client = await getClient(opts.cookieSource, opts.chromeProfile, opts.cookieString, opts.global ? "rednote" : opts.platform);
    const allUsers: unknown[] = [];
    let cursor = "";
    let hasMore = true;

    while (hasMore) {
      const res = (await client.getUserFollowing(userId, cursor)) as {
        users?: unknown[];
        has_more?: boolean;
        cursor?: string;
      };
      if (res.users) allUsers.push(...res.users);
      hasMore = opts.all ? (res.has_more ?? false) : false;
      cursor = res.cursor ?? "";
    }

    if (opts.json) {
      output(allUsers, true);
    } else {
      for (const user of allUsers) {
        const u = user as Record<string, unknown>;
        console.log(
          `${kleur.bold(String(u.nickname ?? "?"))}  ${kleur.dim(String(u.user_id ?? ""))}  ${kleur.dim(String(u.desc ?? "").slice(0, 60))}`
        );
      }
      console.log(kleur.dim(`\n${allUsers.length} following`));
    }
  } catch (err) {
    handleError(err);
  }
});

// ─── delete ────────────────────────────────────────────────────────────────

const deleteCmd = program
  .command("delete <url>")
  .description("Delete your own note");
addCookieOption(deleteCmd);
addJsonOption(deleteCmd);

deleteCmd.action(async (url, opts) => {
  try {
    const client = await getClient(opts.cookieSource, opts.chromeProfile, opts.cookieString, opts.global ? "rednote" : opts.platform);
    const { noteId } = parseNoteUrl(url);
    const result = await client.deleteNote(noteId);
    if (opts.json) {
      output(result, true);
    } else {
      console.log(kleur.green("Note deleted!"));
    }
  } catch (err) {
    handleError(err);
  }
});

// ─── boards ──────────────────────────────────────────────────────────────────

const boardsCmd = program
  .command("boards [user-id]")
  .description("List user's collection boards (收藏专辑列表)");
addCookieOption(boardsCmd);
addJsonOption(boardsCmd);

boardsCmd.action(async (userId, opts) => {
  try {
    const client = await getClient(opts.cookieSource, opts.chromeProfile, opts.cookieString, opts.global ? "rednote" : opts.platform);
    let uid = userId;
    if (!uid) {
      const me = (await client.getSelfInfo()) as Record<string, string>;
      uid = me.user_id;
    }
    console.error(kleur.dim(`Listing boards for ${uid}...`));
    const data = (await client.getUserBoards(uid)) as Record<string, unknown>;
    if (opts.json) {
      output(data, true);
    } else {
      const boards = (data.boards ?? []) as Array<Record<string, unknown>>;
      const count = (data.board_count ?? boards.length) as number;
      console.log(kleur.dim(`${count} board(s)\n`));
      for (const b of boards) {
        const id = (b.id ?? "") as string;
        const name = (b.name ?? "(untitled)") as string;
        const total = (b.total ?? 0) as number;
        const privacy = b.privacy === 1 ? kleur.yellow(" [private]") : "";
        console.log(`  ${kleur.bold(name)}  ${kleur.dim(`${total} notes`)}${privacy}  ${kleur.dim(id)}`);
        if (b.desc && b.desc !== "暂无简介") console.log(`    ${kleur.dim(b.desc as string)}`);
      }
    }
  } catch (err) {
    handleError(err);
  }
});

// ─── board ───────────────────────────────────────────────────────────────────

const boardCmd = program
  .command("board <url>")
  .description("List notes in a collection album (收藏专辑)");
addCookieOption(boardCmd);
addJsonOption(boardCmd);

boardCmd.action(async (url, opts) => {
  try {
    const client = await getClient(opts.cookieSource, opts.chromeProfile, opts.cookieString, opts.global ? "rednote" : opts.platform);
    const boardId = parseBoardUrl(url);

    console.error(kleur.dim(`Fetching board ${boardId}...`));

    let result: {
      boardId: string;
      name: string;
      desc: string;
      noteCount: number;
      notes: Array<{
        note_id: string;
        xsec_token?: string;
        title: string;
        author: string;
        type: string;
        url: string;
        webUrl?: string;
      }>;
    };

    // Try REST API first, fall back to HTML scraping
    try {
      const [info, feeds] = await Promise.all([
        client.getBoardInfo(boardId) as Promise<Record<string, unknown>>,
        client.getBoardNotes(boardId) as Promise<Record<string, unknown>>,
      ]);
      const rawNotes = (feeds.notes ?? []) as Array<Record<string, unknown>>;
      const notes = rawNotes.map((n) => {
        const noteId = (n.note_id ?? n.id ?? "") as string;
        const token = (n.xsec_token ?? "") as string;
        return {
          note_id: noteId,
          xsec_token: token,
          title: (n.display_title ?? n.title ?? "") as string,
          type: (n.type ?? "") as string,
          author: ((n.user as Record<string, unknown>)?.nick_name ??
                   (n.user as Record<string, unknown>)?.nickname ?? "") as string,
          url: buildWebUrl(noteId, token, "pc_board"),
          webUrl: buildWebUrl(noteId, token, "pc_board"),
        };
      });
      result = {
        boardId,
        name: (info.name ?? "") as string,
        desc: (info.desc ?? "") as string,
        noteCount: (info.total ?? notes.length) as number,
        notes,
      };
    } catch {
      // REST API failed — fall back to HTML scraping
      console.error(kleur.dim("REST API unavailable, falling back to HTML scraping..."));
      result = (await client.getBoardFromHtml(boardId)) as typeof result;
    }

    if (opts.json) {
      output(result, true);
    } else {
      if (result.name) console.log(kleur.bold(result.name));
      if (result.desc) console.log(kleur.dim(result.desc));
      console.log();
      for (const note of result.notes) {
        console.log(
          `  ${kleur.bold(note.title || "(no title)")}  ${kleur.dim(`@${note.author || "?"}`)}  [${note.type || "?"}]`
        );
        console.log(`    ${kleur.cyan(note.url)}`);
      }
      console.log(kleur.dim(`\n${result.notes.length} notes`));
    }
  } catch (err) {
    handleError(err);
  }
});

// ─── health ──────────────────────────────────────────────────────────────────

const healthCmd = program
  .command("health")
  .description("Check note distribution health — detect hidden rate-limiting (限流)")
  .option("--all", "Fetch all pages of notes");
addCookieOption(healthCmd);
addJsonOption(healthCmd);

healthCmd.action(async (opts) => {
  try {
    const client = await getClient(opts.cookieSource, opts.chromeProfile, opts.cookieString, opts.global ? "rednote" : opts.platform);

    // Fetch notes from creator backend (v2 endpoint returns hidden level field)
    console.error(kleur.dim("Fetching notes from creator backend..."));
    const allNotes: Record<string, unknown>[] = [];
    let page = 0;
    let hasMore = true;

    while (hasMore) {
      const res = (await client.getCreatorNoteList(0, page)) as {
        notes?: Record<string, unknown>[];
        has_more?: boolean;
      };
      if (res.notes) allNotes.push(...res.notes);
      hasMore = opts.all ? (res.has_more ?? false) : false;
      page++;
    }

    if (allNotes.length === 0) {
      console.log(kleur.yellow("No notes found."));
      return;
    }

    const report = buildHealthReport(allNotes);

    if (opts.json) {
      output(report, true);
      return;
    }

    // ─── Terminal Dashboard ──────────────────────────────────────────────
    console.log(kleur.bold("\n📊 Note Health Report"));
    console.log(kleur.dim("───────────────────────────────────────"));

    // Distribution summary
    for (const [label, count] of Object.entries(report.distribution)) {
      const bar = "█".repeat(Math.min(count, 40));
      console.log(`  ${label.padEnd(14)} ${kleur.dim(bar)} ${count}`);
    }

    console.log(kleur.dim(`\n  Total: ${report.totalNotes} notes`));

    // Limited notes (level < 1)
    if (report.limitedNotes.length > 0) {
      console.log(kleur.red(kleur.bold(`\n⚠ ${report.limitedNotes.length} notes with limited distribution:`)));
      for (const n of report.limitedNotes) {
        const flags = formatFlags(n);
        console.log(`  ${n.levelMeta.emoji} ${kleur.red(`L${n.level}`.padEnd(6))} ${truncate(n.title, 50)}${flags}`);
      }
    } else {
      console.log(kleur.green("\n✓ All notes have normal distribution!"));
    }

    // Sensitive word warnings
    if (report.sensitiveNotes.length > 0) {
      console.log(kleur.yellow(`\n⚠ ${report.sensitiveNotes.length} notes with risk factors:`));
      for (const n of report.sensitiveNotes) {
        const reasons: string[] = [];
        if (n.sensitiveHits.length > 0) reasons.push(`敏感词: ${n.sensitiveHits.join("、")}`);
        if (n.tagWarning) reasons.push(`标签过多(${n.tagCount}个)`);
        console.log(`  ${kleur.dim(n.noteId.slice(0, 8))} ${truncate(n.title, 40)} ${kleur.yellow(reasons.join(" | "))}`);
      }
    }

    console.log();
  } catch (err) {
    handleError(err);
  }
});

function formatFlags(n: NoteDiagnostics): string {
  const parts: string[] = [];
  if (n.sensitiveHits.length > 0) parts.push(kleur.yellow(`⚠️${n.sensitiveHits.join("、")}`));
  if (n.tagWarning) parts.push(kleur.yellow(`📛${n.tagCount}tags`));
  return parts.length > 0 ? "  " + parts.join(" ") : "";
}

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max) + "…" : s;
}

// ─── analyze-viral ──────────────────────────────────────────────────────────

const analyzeViralCmd = program
  .command("analyze-viral <url>")
  .description("Analyze why a viral note works — hooks, engagement, structure");
analyzeViralCmd.option("--comment-pages <n>", "Comment pages to fetch (max 10)", "3");
addCookieOption(analyzeViralCmd);
addJsonOption(analyzeViralCmd);

analyzeViralCmd.action(async (url, opts) => {
  try {
    const client = await getClient(opts.cookieSource, opts.chromeProfile, opts.cookieString, opts.global ? "rednote" : opts.platform);
    const { noteId, xsecToken } = parseNoteUrl(url);

    // 1. Fetch the note (same pattern as `read` — prefer HTML, API when xsec_token present)
    let note: Record<string, unknown>;
    if (xsecToken) {
      try {
        const feedResult = (await client.getNoteById(
          noteId,
          xsecToken
        )) as { items?: Array<{ note_card?: Record<string, unknown> }> };
        note = feedResult?.items?.[0]?.note_card ?? {};
        if (!note.user) {
          note = (await client.getNoteFromHtml(noteId, xsecToken)) as Record<string, unknown>;
        }
      } catch {
        note = (await client.getNoteFromHtml(noteId, xsecToken)) as Record<string, unknown>;
      }
    } else {
      note = (await client.getNoteFromHtml(noteId, "")) as Record<string, unknown>;
    }

    const user = (note.user as Record<string, unknown>) ?? {};
    const userId = String(user.user_id ?? "");

    if (!userId) {
      console.error(kleur.red("Could not extract author user_id from note"));
      process.exit(1);
    }

    // 2. Fetch comments, author posts, and author info in parallel
    const commentPages = Math.min(parseInt(opts.commentPages) || 3, 10);

    const fetchComments = async () => {
      const all: Record<string, unknown>[] = [];
      let cursor = "";
      for (let i = 0; i < commentPages; i++) {
        try {
          const res = (await client.getComments(noteId, cursor, xsecToken ?? "")) as {
            comments?: Record<string, unknown>[];
            has_more?: boolean;
            cursor?: string;
          };
          if (res.comments) all.push(...res.comments);
          if (!res.has_more) break;
          cursor = res.cursor ?? "";
        } catch {
          break; // Comment fetch failed, continue with what we have
        }
      }
      return all;
    };

    const fetchAuthorPosts = async () => {
      try {
        const res = (await client.getUserNotes(userId)) as {
          notes?: Record<string, unknown>[];
        };
        return res.notes ?? [];
      } catch {
        return [];
      }
    };

    const fetchAuthorInfo = async () => {
      try {
        const res = (await client.getUserInfo(userId)) as Record<string, unknown>;
        // Follower count is in interactions array: {type: "fans", count: "30510"}
        const interactions = (res.interactions ?? []) as Array<{ type?: string; count?: string }>;
        const fansEntry = interactions.find((i) => i.type === "fans");
        if (fansEntry?.count) {
          // Handle Chinese abbreviated numbers (e.g., "3.1万")
          const s = fansEntry.count.trim();
          if (s.endsWith("万")) return Math.round(parseFloat(s.slice(0, -1)) * 10000);
          if (s.endsWith("亿")) return Math.round(parseFloat(s.slice(0, -1)) * 100000000);
          return parseInt(s, 10) || 0;
        }
        return 0;
      } catch {
        return 0;
      }
    };

    console.error(kleur.dim("Fetching comments, author posts, and profile..."));
    const [comments, authorPosts, authorFollowers] = await Promise.all([
      fetchComments(),
      fetchAuthorPosts(),
      fetchAuthorInfo(),
    ]);

    // 3. Run analysis
    const analysis = analyzeViral(noteId, note, comments, authorPosts, authorFollowers);

    if (opts.json) {
      output(analysis, true);
    } else {
      console.log(formatViralAnalysis(analysis));
    }
  } catch (err) {
    handleError(err);
  }
});

// ─── viral-template ──────────────────────────────────────────────────────────

const viralTemplateCmd = program
  .command("viral-template <urls...>")
  .description("Extract a content template from 1-3 viral notes")
  .option("--comment-pages <n>", "Comment pages to fetch per note (max 10)", "3");
addCookieOption(viralTemplateCmd);
addJsonOption(viralTemplateCmd);

viralTemplateCmd.action(async (urls: string[], opts) => {
  try {
    if (urls.length > 3) {
      console.error(kleur.red("Maximum 3 URLs allowed"));
      process.exit(1);
    }

    const client = await getClient(opts.cookieSource, opts.chromeProfile, opts.cookieString, opts.global ? "rednote" : opts.platform);
    const commentPages = Math.min(parseInt(opts.commentPages) || 3, 10);
    const analyses = [];

    for (const url of urls) {
      const { noteId, xsecToken } = parseNoteUrl(url);
      console.error(kleur.dim(`Analyzing ${noteId}...`));

      // Fetch note
      let note: Record<string, unknown>;
      if (xsecToken) {
        try {
          const feedResult = (await client.getNoteById(noteId, xsecToken)) as {
            items?: Array<{ note_card?: Record<string, unknown> }>;
          };
          note = feedResult?.items?.[0]?.note_card ?? {};
          if (!note.user) {
            note = (await client.getNoteFromHtml(noteId, xsecToken)) as Record<string, unknown>;
          }
        } catch {
          note = (await client.getNoteFromHtml(noteId, xsecToken)) as Record<string, unknown>;
        }
      } else {
        note = (await client.getNoteFromHtml(noteId, "")) as Record<string, unknown>;
      }

      const user = (note.user as Record<string, unknown>) ?? {};
      const userId = String(user.user_id ?? "");
      if (!userId) {
        console.error(kleur.yellow(`Skipping ${noteId} — could not extract author`));
        continue;
      }

      // Fetch comments, author posts, author info in parallel
      const fetchComments = async () => {
        const all: Record<string, unknown>[] = [];
        let cursor = "";
        for (let i = 0; i < commentPages; i++) {
          try {
            const res = (await client.getComments(noteId, cursor, xsecToken ?? "")) as {
              comments?: Record<string, unknown>[];
              has_more?: boolean;
              cursor?: string;
            };
            if (res.comments) all.push(...res.comments);
            if (!res.has_more) break;
            cursor = res.cursor ?? "";
          } catch { break; }
        }
        return all;
      };

      const fetchAuthorPosts = async () => {
        try {
          const res = (await client.getUserNotes(userId)) as { notes?: Record<string, unknown>[] };
          return res.notes ?? [];
        } catch { return []; }
      };

      const fetchAuthorInfo = async () => {
        try {
          const res = (await client.getUserInfo(userId)) as Record<string, unknown>;
          const interactions = (res.interactions ?? []) as Array<{ type?: string; count?: string }>;
          const fansEntry = interactions.find((i) => i.type === "fans");
          if (fansEntry?.count) {
            const s = fansEntry.count.trim();
            if (s.endsWith("万")) return Math.round(parseFloat(s.slice(0, -1)) * 10000);
            if (s.endsWith("亿")) return Math.round(parseFloat(s.slice(0, -1)) * 100000000);
            return parseInt(s, 10) || 0;
          }
          return 0;
        } catch { return 0; }
      };

      const [comments, authorPosts, authorFollowers] = await Promise.all([
        fetchComments(), fetchAuthorPosts(), fetchAuthorInfo(),
      ]);

      analyses.push(analyzeViral(noteId, note, comments, authorPosts, authorFollowers));
    }

    if (analyses.length === 0) {
      console.error(kleur.red("No notes could be analyzed"));
      process.exit(1);
    }

    const template = extractTemplate(analyses);

    if (opts.json) {
      output(template, true);
    } else {
      console.log(formatTemplate(template));
    }
  } catch (err) {
    handleError(err);
  }
});

// ─── comment ─────────────────────────────────────────────────────────────────

const commentCmd = program
  .command("comment <url>")
  .description("Post a top-level comment on a note")
  .requiredOption("--content <text>", "Comment text");
addCookieOption(commentCmd);
addJsonOption(commentCmd);

commentCmd.action(async (url, opts) => {
  try {
    const client = await getClient(opts.cookieSource, opts.chromeProfile, opts.cookieString, opts.global ? "rednote" : opts.platform);
    const { noteId } = parseNoteUrl(url);
    const result = await client.postComment(noteId, opts.content);
    if (opts.json) {
      output(result, true);
    } else {
      console.log(kleur.green("Comment posted!"));
      console.error(kleur.yellow("⚠ Rate limit: wait ≥3 minutes before the next comment to avoid risk control."));
    }
  } catch (err) {
    handleError(err);
  }
});

// ─── reply ───────────────────────────────────────────────────────────────────

const replyCmd = program
  .command("reply <url>")
  .description("Reply to a comment on a note")
  .requiredOption("--comment-id <id>", "Comment ID to reply to")
  .requiredOption("--content <text>", "Reply text");
addCookieOption(replyCmd);
addJsonOption(replyCmd);

replyCmd.action(async (url, opts) => {
  try {
    const client = await getClient(opts.cookieSource, opts.chromeProfile, opts.cookieString, opts.global ? "rednote" : opts.platform);
    const { noteId } = parseNoteUrl(url);
    const result = await client.replyComment(noteId, opts.commentId, opts.content);
    if (opts.json) {
      output(result, true);
    } else {
      console.log(kleur.green("Reply posted!"));
      console.error(kleur.yellow("⚠ Rate limit: wait ≥3 minutes before the next reply to avoid risk control."));
    }
  } catch (err) {
    handleError(err);
  }
});

// ─── batch-reply ─────────────────────────────────────────────────────────────

const batchReplyCmd = program
  .command("batch-reply <url>")
  .description("Reply to multiple comments using a strategy")
  .option("--strategy <name>", "Filter strategy: questions, top-engaged, all-unanswered", "questions")
  .option("--template <text>", "Reply template with {author}, {content} placeholders")
  .option("--max <n>", `Max replies to send (hard cap: ${MAX_REPLIES_HARD_CAP})`, "10")
  .option("--delay <ms>", `Delay between replies in ms (min: ${MIN_REPLY_DELAY / 1000}s)`, String(DEFAULT_DELAY_MS))
  .option("--dry-run", "Preview candidates without posting");
addCookieOption(batchReplyCmd);
addJsonOption(batchReplyCmd);

batchReplyCmd.action(async (url, opts) => {
  try {
    const client = await getClient(opts.cookieSource, opts.chromeProfile, opts.cookieString, opts.global ? "rednote" : opts.platform);
    const { noteId, xsecToken } = parseNoteUrl(url);
    const strategy = opts.strategy as StrategyName;
    const max = Math.min(parseInt(opts.max) || 10, MAX_REPLIES_HARD_CAP);
    const isDryRun = opts.dryRun || !opts.template;

    // Fetch all comments
    console.error(kleur.dim("Fetching comments..."));
    const allComments: Record<string, unknown>[] = [];
    let cursor = "";
    let hasMore = true;
    while (hasMore) {
      const res = (await client.getComments(noteId, cursor, xsecToken ?? "")) as {
        comments?: Record<string, unknown>[];
        has_more?: boolean;
        cursor?: string;
      };
      if (res.comments) allComments.push(...res.comments);
      hasMore = res.has_more ?? false;
      cursor = res.cursor ?? "";
    }

    // Select candidates
    const plan = selectCandidates(allComments, strategy, max);
    plan.noteId = noteId;

    if (isDryRun || opts.json) {
      if (opts.json) {
        output(plan, true);
      } else {
        console.log(kleur.bold(`\nBatch Reply Plan — ${strategy}`));
        console.log(kleur.dim(`${plan.totalComments} comments → ${plan.candidates.length} candidates (${plan.skipped} skipped)\n`));
        for (const c of plan.candidates) {
          console.log(
            `  ${kleur.cyan(c.commentId.slice(0, 8))}  ${kleur.bold(`@${c.author}`)}  ${kleur.dim(`♥ ${c.likes}`)}`
          );
          console.log(`    ${c.content.slice(0, 80)}${c.content.length > 80 ? "..." : ""}`);
        }
        if (!opts.template) {
          console.log(kleur.yellow("\nDry run (no --template provided). Add --template to execute."));
        } else {
          console.log(kleur.yellow("\nDry run mode. Remove --dry-run to execute."));
        }
      }
      return;
    }

    // Execute replies
    const delayMs = parseInt(opts.delay) || DEFAULT_DELAY_MS;
    console.error(kleur.dim(`Sending ${plan.candidates.length} replies (delay: ~${Math.round(delayMs / 60000)}min ±30% jitter)...`));
    console.error(kleur.yellow("⚠ Rate limit: XHS enforces anti-spam — replies spaced ≥3min apart with jitter."));
    const results = await executeReplies(
      client,
      noteId,
      plan.candidates,
      opts.template,
      delayMs,
      {}
    );

    const succeeded = results.filter((r) => r.success).length;
    const failed = results.filter((r) => !r.success).length;

    if (opts.json) {
      output(results, true);
    } else {
      console.log(kleur.green(`\n${succeeded} replies sent`));
      if (failed > 0) {
        console.log(kleur.red(`${failed} failed`));
        for (const r of results.filter((r) => !r.success)) {
          console.log(kleur.dim(`  @${r.author}: ${r.error}`));
        }
      }
    }
  } catch (err) {
    handleError(err);
  }
});

// ─── render ──────────────────────────────────────────────────────────────────

const renderCmd = program
  .command("render <file>")
  .description("Render markdown to styled PNG cards for Xiaohongshu posts")
  .option("--style <name>", "Color style: purple, xiaohongshu, mint, sunset, ocean, elegant, dark", "xiaohongshu")
  .option("--pagination <mode>", "Pagination: auto, separator", "auto")
  .option("--output-dir <dir>", "Output directory (default: same as input file)")
  .option("--width <n>", "Card width in px", "1080")
  .option("--height <n>", "Card height in px", "1440")
  .option("--dpr <n>", "Device pixel ratio", "2");
addJsonOption(renderCmd);

renderCmd.action(async (file, opts) => {
  try {
    const { renderCards } = await import("./lib/render.js");
    const result = await renderCards(file, {
      style: opts.style,
      pagination: opts.pagination,
      outputDir: opts.outputDir,
      width: parseInt(opts.width),
      height: parseInt(opts.height),
      dpr: parseInt(opts.dpr),
    });

    if (opts.json) {
      output(result, true);
    } else {
      console.log(kleur.green(`\nRendered ${result.totalCards + 1} images:`));
      console.log(`  Cover: ${kleur.bold(result.coverPath)}`);
      for (const p of result.cardPaths) {
        console.log(`  Card:  ${kleur.bold(p)}`);
      }
    }
  } catch (err) {
    handleError(err);
  }
});

// ─── Helpers ────────────────────────────────────────────────────────────────

interface ParsedUserProfileArg {
  userId: string;
  xsecToken: string | null;
  xsecSource: string | null;
}

interface ReportMonth {
  label: string;
  start: Date;
  end: Date;
}

interface AccountReportNote {
  noteId: string;
  title: string;
  type: string;
  publishedAt: string | null;
  likes: number;
  comments: number;
  collects: number;
  shares: number;
  totalEngagement: number;
  webUrl?: string;
}

interface AccountReport {
  input: string;
  userId: string;
  month: string;
  fetchedPosts: number;
  postsInMonth: number;
  pagesFetched: number;
  complete: boolean;
  hasMore: boolean;
  nextCursor: string | null;
  totals: {
    likes: number;
    comments: number;
    collects: number;
    shares: number;
    totalEngagement: number;
  };
  monthTotals: {
    likes: number;
    comments: number;
    collects: number;
    shares: number;
    totalEngagement: number;
  };
  averages: {
    likes: number;
    comments: number;
    collects: number;
    shares: number;
    totalEngagement: number;
  };
  topByLikes: AccountReportNote | null;
  topByEngagement: AccountReportNote | null;
  notes: AccountReportNote[];
}

function parseBoardUrl(url: string): string {
  if (url.includes("xiaohongshu.com/board/")) {
    const urlObj = new URL(url);
    const parts = urlObj.pathname.split("/").filter(Boolean);
    return parts[parts.length - 1];
  }
  return url; // assume raw board ID
}

function parseNoteUrl(url: string): {
  noteId: string;
  xsecToken: string | null;
} {
  // Handle full URLs like https://www.xiaohongshu.com/explore/abc123?xsec_token=xxx
  // or https://www.xiaohongshu.com/discovery/item/abc123
  // or just a note ID
  let noteId: string;
  let xsecToken: string | null = null;

  if (url.includes("xiaohongshu.com")) {
    const urlObj = new URL(url);
    const pathParts = urlObj.pathname.split("/").filter(Boolean);
    noteId = pathParts[pathParts.length - 1];
    xsecToken = urlObj.searchParams.get("xsec_token");
  } else if (url.includes("xhslink.com")) {
    // Short link — just use it as-is, would need redirect following
    noteId = url;
  } else {
    noteId = url;
  }

  return { noteId, xsecToken };
}

function parseUserProfileArg(
  input: string,
  opts: { xsecToken?: string; xsecSource?: string } = {}
): ParsedUserProfileArg {
  let userId = input;
  let xsecToken: string | null = opts.xsecToken ?? null;
  let xsecSource: string | null = opts.xsecSource ?? null;

  try {
    const url = new URL(input);
    const pathParts = url.pathname.split("/").filter(Boolean);
    const profileIdx = pathParts.findIndex((part) => part === "profile");
    userId = profileIdx >= 0 && pathParts[profileIdx + 1]
      ? pathParts[profileIdx + 1]
      : pathParts[pathParts.length - 1] ?? input;
    xsecToken = url.searchParams.get("xsec_token") ?? xsecToken;
    xsecSource = url.searchParams.get("xsec_source") ?? xsecSource;
  } catch {
    // Raw user id; optional token/source may still come from flags.
  }

  if (xsecToken && !xsecSource) xsecSource = "pc_search";

  return { userId, xsecToken, xsecSource };
}

function collectAccountInputs(users: string[], file?: string): string[] {
  const fromFile = file
    ? readFileSync(file, "utf-8")
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter((line) => line.length > 0 && !line.startsWith("#"))
    : [];

  const seen = new Set<string>();
  const inputs: string[] = [];
  for (const input of [...users, ...fromFile]) {
    const trimmed = input.trim();
    if (!trimmed || seen.has(trimmed)) continue;
    seen.add(trimmed);
    inputs.push(trimmed);
  }
  return inputs;
}

function parseReportMonth(input?: string): ReportMonth {
  const now = new Date();
  const label = input ?? `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const match = /^(\d{4})-(\d{2})$/.exec(label);
  if (!match) {
    throw new Error("Invalid --month. Use YYYY-MM, for example 2026-07.");
  }

  const year = Number(match[1]);
  const month = Number(match[2]);
  if (month < 1 || month > 12) {
    throw new Error("Invalid --month. Month must be 01-12.");
  }

  return {
    label,
    start: new Date(year, month - 1, 1),
    end: new Date(year, month, 1),
  };
}

async function buildAccountReport(
  client: XhsClient,
  input: string,
  user: ParsedUserProfileArg,
  month: ReportMonth,
  maxPages: number,
  delayMs: number
): Promise<AccountReport> {
  const rawNotes: Array<Record<string, unknown>> = [];
  let cursor = "";
  let pagesFetched = 0;
  let hasMore = false;
  let nextCursor: string | null = null;

  while (pagesFetched < maxPages) {
    const res = (await client.getUserNotes(user.userId, cursor, user)) as {
      notes?: Array<Record<string, unknown>>;
      has_more?: boolean;
      cursor?: string;
    };

    const notes = res.notes ?? [];
    enrichWithWebUrl(notes, "pc_user");
    rawNotes.push(...notes);
    pagesFetched++;

    hasMore = Boolean(res.has_more);
    nextCursor = typeof res.cursor === "string" && res.cursor.length > 0
      ? res.cursor
      : null;

    if (!hasMore || !nextCursor || notes.length === 0) break;
    if (pagesFetched >= maxPages) break;

    cursor = nextCursor;
    if (delayMs > 0) await sleep(delayMs);
  }

  const notes = rawNotes.map(normalizeAccountReportNote);
  const monthNotes = notes.filter((note) => isInReportMonth(note.publishedAt, month));
  const totals = sumReportNotes(notes);
  const monthTotals = sumReportNotes(monthNotes);

  return {
    input,
    userId: user.userId,
    month: month.label,
    fetchedPosts: notes.length,
    postsInMonth: monthNotes.length,
    pagesFetched,
    complete: !hasMore || !nextCursor,
    hasMore,
    nextCursor,
    totals,
    monthTotals,
    averages: averageReportNotes(totals, notes.length),
    topByLikes: topReportNote(notes, "likes"),
    topByEngagement: topReportNote(notes, "totalEngagement"),
    notes,
  };
}

function normalizeAccountReportNote(note: Record<string, unknown>): AccountReportNote {
  const interactInfo = (note.interact_info ?? {}) as Record<string, unknown>;
  const likes = metricNumber(interactInfo.liked_count ?? note.liked_count);
  const comments = metricNumber(interactInfo.comment_count ?? note.comment_count);
  const collects = metricNumber(interactInfo.collected_count ?? note.collected_count);
  const shares = metricNumber(interactInfo.share_count ?? note.share_count);
  const noteId = String(note.note_id ?? note.noteId ?? "");
  const title = String(note.display_title ?? note.title ?? note.desc ?? "(no title)");
  const publishedAt = parseNotePublishedAt(note);
  const webUrl = typeof note.webUrl === "string"
    ? note.webUrl
    : typeof note.url === "string"
      ? note.url
      : undefined;

  return {
    noteId,
    title,
    type: String(note.type ?? "unknown"),
    publishedAt: publishedAt ? publishedAt.toISOString() : null,
    likes,
    comments,
    collects,
    shares,
    totalEngagement: likes + comments + collects + shares,
    ...(webUrl ? { webUrl } : {}),
  };
}

function parseNotePublishedAt(note: Record<string, unknown>): Date | null {
  for (const key of [
    "time",
    "create_time",
    "createTime",
    "timestamp",
    "publish_time",
    "publishTime",
    "last_update_time",
    "lastUpdateTime",
  ]) {
    const parsed = parseTimestampValue(note[key]);
    if (parsed) return parsed;
  }
  return null;
}

function parseTimestampValue(value: unknown): Date | null {
  if (typeof value === "number") return timestampNumberToDate(value);
  if (typeof value !== "string") return null;

  const trimmed = value.trim();
  if (!trimmed) return null;

  if (/^\d+$/.test(trimmed)) {
    return timestampNumberToDate(Number(trimmed));
  }

  const parsed = Date.parse(trimmed);
  return Number.isNaN(parsed) ? null : new Date(parsed);
}

function timestampNumberToDate(value: number): Date | null {
  if (!Number.isFinite(value) || value <= 0) return null;
  const ms = value < 1_000_000_000_000 ? value * 1000 : value;
  const date = new Date(ms);
  return Number.isNaN(date.getTime()) ? null : date;
}

function isInReportMonth(isoDate: string | null, month: ReportMonth): boolean {
  if (!isoDate) return false;
  const date = new Date(isoDate);
  return date >= month.start && date < month.end;
}

function metricNumber(value: unknown): number {
  if (typeof value === "number") return Number.isFinite(value) ? value : 0;
  if (typeof value !== "string") return 0;

  const s = value.trim().replace(/,/g, "");
  if (!s) return 0;
  if (s.endsWith("万")) {
    const n = parseFloat(s.slice(0, -1));
    return Number.isNaN(n) ? 0 : Math.round(n * 10000);
  }
  if (s.endsWith("亿")) {
    const n = parseFloat(s.slice(0, -1));
    return Number.isNaN(n) ? 0 : Math.round(n * 100000000);
  }
  const n = parseFloat(s);
  return Number.isNaN(n) ? 0 : Math.round(n);
}

function sumReportNotes(notes: AccountReportNote[]): AccountReport["totals"] {
  return notes.reduce(
    (acc, note) => ({
      likes: acc.likes + note.likes,
      comments: acc.comments + note.comments,
      collects: acc.collects + note.collects,
      shares: acc.shares + note.shares,
      totalEngagement: acc.totalEngagement + note.totalEngagement,
    }),
    { likes: 0, comments: 0, collects: 0, shares: 0, totalEngagement: 0 }
  );
}

function averageReportNotes(
  totals: AccountReport["totals"],
  count: number
): AccountReport["averages"] {
  if (count === 0) {
    return { likes: 0, comments: 0, collects: 0, shares: 0, totalEngagement: 0 };
  }
  return {
    likes: round2(totals.likes / count),
    comments: round2(totals.comments / count),
    collects: round2(totals.collects / count),
    shares: round2(totals.shares / count),
    totalEngagement: round2(totals.totalEngagement / count),
  };
}

function topReportNote(
  notes: AccountReportNote[],
  field: "likes" | "totalEngagement"
): AccountReportNote | null {
  if (notes.length === 0) return null;
  return notes.reduce((best, note) => note[field] > best[field] ? note : best, notes[0]);
}

function printAccountReport(result: {
  month: string;
  accounts: AccountReport[];
  errors: Array<{ input: string; userId?: string; error: string }>;
}): void {
  console.log(kleur.bold(`Account report (${result.month})`));
  for (const account of result.accounts) {
    const partial = account.complete ? "" : kleur.yellow(" partial");
    const top = account.topByLikes
      ? `${formatNumber(account.topByLikes.likes)} likes - ${account.topByLikes.title}`
      : "n/a";
    console.log(
      `${kleur.bold(account.userId)}${partial}  ` +
        `posts:${account.fetchedPosts}  month:${account.postsInMonth}  ` +
        `likes:${formatNumber(account.totals.likes)}  ` +
        `avg:${formatNumber(account.averages.likes)}  top:${top}`
    );
  }

  if (result.errors.length > 0) {
    console.log(kleur.red(`\n${result.errors.length} account(s) failed:`));
    for (const err of result.errors) {
      console.log(`  ${err.userId ?? err.input}: ${err.error}`);
    }
  }
}

function formatNumber(value: number): string {
  return value.toLocaleString("en-US");
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

program.parse();
