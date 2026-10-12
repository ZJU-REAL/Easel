/**
 * Platform auto-detection — figure out whether the user is logged into
 * mainland Xiaohongshu (xiaohongshu.com) or global RedNote (rednote.com),
 * so callers never have to pass --global.
 *
 * A user can only be signed into ONE of the two on a given machine (RedNote
 * routes you to mainland vs global by IP/region), but the *other* domain may
 * still hold a stale guest cookie. So "has cookies" is not enough — we probe
 * both domains and, when both have cookies, verify which one is actually
 * authenticated via a single lightweight /user/me call. The result is cached
 * by a fingerprint of the winning cookies so we don't re-hit the API on every
 * command; the cache self-invalidates when the login (cookies) changes.
 */

import crypto from "node:crypto";
import { homedir } from "node:os";
import { join } from "node:path";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import kleur from "kleur";
import { PLATFORMS, type PlatformConfig, type PlatformId } from "./platform.js";
import {
  probeCookies,
  type XhsCookies,
  type CookieSource,
} from "./cookies.js";
import { XhsClient } from "./client.js";

const CACHE_DIR = join(homedir(), ".redbook");
const CACHE_FILE = join(CACHE_DIR, "platform-cache.json");

interface DetectResult {
  /** Resolved platform config to use. */
  platform: PlatformConfig;
  /** Cookies already read during probing (reuse to avoid a re-read), or null
   *  when nothing could be probed (caller should do a full extract). */
  cookies: XhsCookies | null;
}

interface CacheEntry {
  platform: PlatformId;
  fingerprint: string;
  detectedAt: string;
}

function log(msg: string): void {
  console.error(kleur.dim(msg));
}

function fingerprint(c: XhsCookies): string {
  return crypto
    .createHash("sha256")
    .update(`${c.a1 ?? ""}|${c.web_session ?? ""}`)
    .digest("hex")
    .slice(0, 16);
}

/** A logged-in web_session looks different from a guest one (guest tends to
 *  start with "03", authenticated with "04"). This is only used to ORDER the
 *  verification calls (check the likely-authenticated domain first) — never
 *  for correctness, which always comes from the /user/me check. */
function looksGuest(c: XhsCookies | null): boolean {
  return !c || /^03/.test(c.web_session ?? "");
}

function readCache(): CacheEntry | null {
  try {
    return JSON.parse(readFileSync(CACHE_FILE, "utf-8")) as CacheEntry;
  } catch {
    return null;
  }
}

function writeCache(platform: PlatformId, cookies: XhsCookies): void {
  try {
    mkdirSync(CACHE_DIR, { recursive: true });
    const entry: CacheEntry = {
      platform,
      fingerprint: fingerprint(cookies),
      detectedAt: new Date().toISOString(),
    };
    writeFileSync(CACHE_FILE, JSON.stringify(entry, null, 2));
  } catch {
    // cache is best-effort — never fail a command over it
  }
}

async function isAuthenticated(
  cookies: XhsCookies,
  platform: PlatformConfig
): Promise<boolean> {
  try {
    const info = (await new XhsClient(cookies, platform).getSelfInfo()) as {
      guest?: boolean;
    };
    return info?.guest === false;
  } catch {
    // -100 session expired, network error, etc. → treat as not authenticated
    return false;
  }
}

function label(id: PlatformId): string {
  return id === "rednote"
    ? "RedNote (global, rednote.com)"
    : "Xiaohongshu (mainland, xiaohongshu.com)";
}

/**
 * Detect which platform the user is logged into. `source`/`chromeProfile` are
 * passed through to cookie reading.
 */
export async function detectPlatform(
  source: CookieSource,
  chromeProfile: string | undefined
): Promise<DetectResult> {
  // 1. Warm path: trust the cache if the winning domain's cookies are unchanged.
  const cached = readCache();
  if (cached && (cached.platform === "xhs" || cached.platform === "rednote")) {
    const cfg = PLATFORMS[cached.platform];
    const c = await probeCookies(source, chromeProfile, cfg.cookieUrl);
    if (c && fingerprint(c) === cached.fingerprint) {
      log(kleur.dim(`Platform: ${label(cfg.id)} [cached].`));
      return { platform: cfg, cookies: c };
    }
  }

  // 2. Cold path: probe both domains.
  const ids: PlatformId[] = ["xhs", "rednote"];
  const probed = await Promise.all(
    ids.map(async (id) => ({
      id,
      cfg: PLATFORMS[id],
      cookies: await probeCookies(source, chromeProfile, PLATFORMS[id].cookieUrl),
    }))
  );
  const candidates = probed.filter((p) => p.cookies) as Array<{
    id: PlatformId;
    cfg: PlatformConfig;
    cookies: XhsCookies;
  }>;

  // No cookies on either domain → let the caller do a full extract (with CDP
  // fallback for Windows) against the mainland default and surface its error.
  if (candidates.length === 0) {
    return { platform: PLATFORMS.xhs, cookies: null };
  }

  // Exactly one domain has cookies → use it (no API call). If it happens to be
  // a guest session, the command itself will report "session expired", which is
  // the correct, informative behavior.
  if (candidates.length === 1) {
    const only = candidates[0];
    writeCache(only.id, only.cookies);
    log(kleur.dim(`Platform: ${label(only.id)} [auto].`));
    return { platform: only.cfg, cookies: only.cookies };
  }

  // Both domains have cookies (e.g. a stale guest cookie on the unused one).
  // Verify which is actually logged in — check the likely-authenticated one
  // first to minimize API calls.
  candidates.sort((a, b) => Number(looksGuest(a.cookies)) - Number(looksGuest(b.cookies)));
  for (const cand of candidates) {
    if (await isAuthenticated(cand.cookies, cand.cfg)) {
      writeCache(cand.id, cand.cookies);
      log(kleur.dim(`Platform: ${label(cand.id)} [auto-detected].`));
      return { platform: cand.cfg, cookies: cand.cookies };
    }
  }

  // Neither authenticated (logged out everywhere). Don't cache — re-detect once
  // the user logs in. Return the likely one so the command's own error is clear.
  log(
    kleur.yellow(
      "Not logged in on either xiaohongshu.com or rednote.com — log into one in Chrome."
    )
  );
  return { platform: candidates[0].cfg, cookies: candidates[0].cookies };
}

/**
 * For the manual --cookie-string path: the user pasted cookies for one domain
 * but we don't know which. Try each backend's /user/me and use whichever
 * authenticates (default mainland).
 */
export async function detectPlatformForCookies(
  cookies: XhsCookies
): Promise<PlatformConfig> {
  const ids: PlatformId[] = looksGuest(cookies)
    ? ["xhs", "rednote"]
    : ["rednote", "xhs"];
  for (const id of ids) {
    if (await isAuthenticated(cookies, PLATFORMS[id])) {
      log(kleur.dim(`Platform: ${label(id)} [auto-detected from cookie string].`));
      return PLATFORMS[id];
    }
  }
  return PLATFORMS.xhs;
}
