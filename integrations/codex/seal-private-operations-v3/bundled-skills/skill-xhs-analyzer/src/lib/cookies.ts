/**
 * Cookie extraction module — wraps @steipete/sweet-cookie
 * Same pattern as bird.fast for Chrome/Safari/Firefox cookie extraction
 */

import { getCookies } from "@steipete/sweet-cookie";
import { readFileSync, existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import kleur from "kleur";
import { extractCookiesViaCdp } from "./cdp-cookies.js";

export interface XhsCookies {
  a1: string;
  web_session: string;
  webId: string;
  [key: string]: string;
}

export type CookieSource = "chrome" | "safari" | "firefox";

interface ChromeProfileInfo {
  dirName: string;
  displayName: string;
}

/**
 * Parse a raw cookie header string into XhsCookies.
 * Accepts format: "a1=xxx; web_session=yyy; webId=zzz"
 */
export function parseCookieString(cookieString: string): XhsCookies {
  const map: Record<string, string> = {};
  for (const pair of cookieString.split(";")) {
    const eqIdx = pair.indexOf("=");
    if (eqIdx === -1) continue;
    const name = pair.slice(0, eqIdx).trim();
    const value = pair.slice(eqIdx + 1).trim();
    if (name) map[name] = value;
  }
  return map as XhsCookies;
}

/**
 * Resolve the Chrome "Local State" file path for the current platform.
 */
function getChromeLocalStatePath(): string | null {
  if (process.platform === "darwin") {
    return join(
      homedir(),
      "Library",
      "Application Support",
      "Google",
      "Chrome",
      "Local State"
    );
  }
  if (process.platform === "win32") {
    const localAppData = process.env.LOCALAPPDATA;
    if (!localAppData) return null;
    return join(localAppData, "Google", "Chrome", "User Data", "Local State");
  }
  if (process.platform === "linux") {
    return join(homedir(), ".config", "google-chrome", "Local State");
  }
  return null;
}

/**
 * Discover Chrome profiles from Local State file.
 * Works on macOS, Windows, and Linux.
 * Returns profiles sorted with "Default" first.
 */
function discoverChromeProfiles(): ChromeProfileInfo[] {
  const localStatePath = getChromeLocalStatePath();
  if (!localStatePath || !existsSync(localStatePath)) return [];

  try {
    const raw = readFileSync(localStatePath, "utf-8");
    const state = JSON.parse(raw);
    const infoCache = state?.profile?.info_cache;
    if (!infoCache || typeof infoCache !== "object") return [];

    const profiles: ChromeProfileInfo[] = [];
    for (const [dirName, meta] of Object.entries(infoCache)) {
      const m = meta as Record<string, unknown>;
      const displayName = String(m.name || m.gaia_name || dirName);
      profiles.push({ dirName, displayName });
    }

    profiles.sort((a, b) => {
      if (a.dirName === "Default") return -1;
      if (b.dirName === "Default") return 1;
      return a.dirName.localeCompare(b.dirName);
    });

    return profiles;
  } catch {
    return [];
  }
}

function toCookieMap(cookies: Array<{ name: string; value: string }>): Record<string, string> {
  const map: Record<string, string> = {};
  for (const cookie of cookies) {
    map[cookie.name] = cookie.value;
  }
  return map;
}

function buildNoCookieError(
  source: CookieSource,
  warnings: string[],
  checkedProfiles?: ChromeProfileInfo[],
  partialCookies?: Record<string, string>
): Error {
  const missing = partialCookies
    ? `Found cookies but missing required keys: ${
        !partialCookies.a1 ? "'a1' " : ""
      }${!partialCookies.web_session ? "'web_session'" : ""}`
    : `No 'a1' cookie found for xiaohongshu.com in ${source}.`;

  const lines: string[] = [missing, ""];

  if (checkedProfiles && checkedProfiles.length > 0) {
    lines.push(
      `Checked ${checkedProfiles.length} Chrome profile(s): ` +
        checkedProfiles.map((p) => `"${p.dirName}" (${p.displayName})`).join(", ")
    );
    lines.push("");
  }

  if (warnings.length > 0) {
    lines.push("Warnings from cookie extraction:");
    for (const w of warnings) {
      lines.push(`  - ${w}`);
    }
    lines.push("");
  }

  lines.push(
    `Debug info:`,
    `  - Platform: ${process.platform}`,
    `  - Node: ${process.version}`,
    `  - Cookie source: ${source}`,
    "",
    "Troubleshooting:",
  );

  if (process.platform === "win32") {
    lines.push(
      "  1. Chrome 127+ on Windows uses App-Bound Encryption which may prevent",
      "     external tools from reading cookies. Use --cookie-string as a workaround:",
      "     Open Chrome DevTools (F12) > Application > Cookies > xiaohongshu.com,",
      "     then copy the cookie values and pass them as:",
      '     redbook whoami --cookie-string "a1=VALUE; web_session=VALUE"',
      "  2. Login: open Chrome and visit https://www.xiaohongshu.com/ — make sure you",
      "     are logged in and can see your feed.",
      "  3. Cookie expired: try logging out and back in on xiaohongshu.com.",
      "  4. Chrome must be closed: on some Windows setups, Chrome locks its cookie",
      "     database. Try closing Chrome before running the command.",
    );
  } else {
    lines.push(
      "  1. Keychain access: when macOS prompts for your password, click 'Always Allow'",
      "     to avoid being asked again. If you clicked 'Deny', re-run the command.",
      "  2. Login: open Chrome and visit https://www.xiaohongshu.com/ — make sure you",
      "     are logged in and can see your feed.",
      "  3. Cookie expired: even if Chrome shows you as logged in, the 'a1' cookie may",
      "     have expired. Try logging out and back in on xiaohongshu.com.",
      "  4. Non-standard browser: if you use Brave, Arc, or another Chromium browser,",
      "     cookies are stored in a different location. Try --cookie-source safari instead.",
    );
  }

  lines.push(
    "",
    "  Manual fallback (all platforms):",
    "  Open Chrome DevTools (F12) > Application > Cookies > xiaohongshu.com,",
    '  then: redbook whoami --cookie-string "a1=VALUE; web_session=VALUE"',
  );

  return new Error(lines.join("\n"));
}

/**
 * Check whether a cookie map has the required keys for XHS API calls.
 */
function hasRequiredCookies(cookieMap: Record<string, string>): boolean {
  return Boolean(cookieMap.a1 && cookieMap.web_session);
}

/**
 * Warn if cookies were extracted but are incomplete (e.g., a1 present but web_session missing).
 * This commonly happens on Windows with Chrome 127+ App-Bound Encryption.
 * Uses console.error directly (not the dim logger) so warnings show in yellow.
 */
function warnPartialCookies(cookieMap: Record<string, string>): void {
  if (cookieMap.a1 && !cookieMap.web_session) {
    console.error(
      kleur.yellow(
        "Warning: found 'a1' cookie but 'web_session' is missing.\n" +
          "  This often happens on Windows where Chrome 127+ App-Bound Encryption\n" +
          "  prevents external tools from decrypting newer cookies."
      )
    );
  }
}

/**
 * Internal: try extracting cookies via sweet-cookie (direct DB read).
 * Returns cookies if successful, throws on failure.
 */
async function extractViaSweetCookie(
  source: CookieSource,
  chromeProfile: string | undefined,
  log: (msg: string) => void,
  cookieUrl: string
): Promise<XhsCookies> {
  // Explicit profile or non-Chrome browser: single try
  if (chromeProfile || source !== "chrome") {
    log(`Reading cookies from ${source}${chromeProfile ? ` (profile: ${chromeProfile})` : ""}...`);
    const result = await getCookies({
      url: cookieUrl,
      browsers: [source],
      timeoutMs: 30_000,
      ...(chromeProfile ? { chromeProfile } : {}),
    });
    const cookieMap = toCookieMap(result.cookies);

    if (!cookieMap.a1) {
      throw buildNoCookieError(source, result.warnings);
    }
    if (!hasRequiredCookies(cookieMap)) {
      warnPartialCookies(cookieMap);
      throw buildNoCookieError(source, result.warnings, undefined, cookieMap);
    }
    log(`Authenticated via ${source}${chromeProfile ? ` profile "${chromeProfile}"` : ""}.`);
    return cookieMap as XhsCookies;
  }

  // Auto-discover Chrome profiles
  const profiles = discoverChromeProfiles();

  if (profiles.length === 0) {
    log("Reading cookies from Chrome (default profile)...");
    const result = await getCookies({
      url: cookieUrl,
      browsers: [source],
      timeoutMs: 30_000,
    });
    const cookieMap = toCookieMap(result.cookies);
    if (!cookieMap.a1) {
      throw buildNoCookieError(source, result.warnings);
    }
    if (!hasRequiredCookies(cookieMap)) {
      warnPartialCookies(cookieMap);
      throw buildNoCookieError(source, result.warnings, undefined, cookieMap);
    }
    log("Authenticated via Chrome.");
    return cookieMap as XhsCookies;
  }

  log(`Found ${profiles.length} Chrome profile(s): ${profiles.map((p) => `${p.dirName} (${p.displayName})`).join(", ")}`);

  // Try each profile, collect those that have the required cookies
  const found: Array<{ profile: ChromeProfileInfo; cookies: Record<string, string> }> = [];
  let lastWarnings: string[] = [];
  let partialMatch: Record<string, string> | undefined;

  for (const profile of profiles) {
    log(`  Checking "${profile.dirName}" (${profile.displayName})...`);
    const result = await getCookies({
      url: cookieUrl,
      browsers: ["chrome"],
      chromeProfile: profile.dirName,
      timeoutMs: 30_000,
    });
    lastWarnings = result.warnings;

    const cookieMap = toCookieMap(result.cookies);
    if (hasRequiredCookies(cookieMap)) {
      log(`  -> Found XHS session in "${profile.dirName}"`);
      found.push({ profile, cookies: cookieMap });
    } else if (cookieMap.a1 && !partialMatch) {
      partialMatch = cookieMap;
      log(`  -> Partial match (a1 found, web_session missing)`);
    } else {
      log(`  -> No XHS session`);
    }
  }

  if (found.length === 0) {
    if (partialMatch) {
      warnPartialCookies(partialMatch);
    }
    throw buildNoCookieError(source, lastWarnings, profiles, partialMatch);
  }

  if (found.length === 1) {
    log(`Authenticated via Chrome profile "${found[0].profile.dirName}" (${found[0].profile.displayName}).`);
  } else {
    const names = found.map((f) => `"${f.profile.dirName}" (${f.profile.displayName})`);
    log(
      `Found XHS sessions in ${found.length} profiles: ${names.join(", ")}. ` +
        `Using "${found[0].profile.dirName}". ` +
        `To choose a specific one: --chrome-profile "${found[found.length - 1].profile.dirName}"`
    );
  }

  return found[0].cookies as XhsCookies;
}

/**
 * Extract XHS cookies from browser cookie store.
 *
 * Strategy (for Chrome source):
 *  1. Try sweet-cookie (direct SQLite read + DPAPI/Keychain decrypt)
 *  2. If incomplete (common on Windows with Chrome 127+ App-Bound Encryption),
 *     fall back to CDP — launch Chrome headless and read cookies via DevTools Protocol
 *  3. If both fail, throw with detailed troubleshooting for the user's platform
 */
export async function extractCookies(
  source: CookieSource = "chrome",
  chromeProfile?: string,
  cookieUrl: string = "https://www.xiaohongshu.com/"
): Promise<XhsCookies> {
  const log = (msg: string) => console.error(kleur.dim(msg));

  // 1. Try sweet-cookie (fast path — works on macOS, some Windows/Linux)
  try {
    return await extractViaSweetCookie(source, chromeProfile, log, cookieUrl);
  } catch (sweetCookieErr) {
    // For non-Chrome sources, no CDP fallback — rethrow
    if (source !== "chrome") {
      throw sweetCookieErr;
    }

    // 2. Try CDP fallback (Chrome only)
    console.error("");
    console.error(
      kleur.yellow(
        "Standard cookie extraction failed. Trying Chrome DevTools Protocol (CDP) fallback..."
      )
    );
    console.error(
      kleur.dim(
        "CDP launches Chrome headless to read cookies directly, bypassing encryption."
      )
    );
    console.error("");

    try {
      const cdpResult = await extractCookiesViaCdp({
        profile: chromeProfile,
        log,
      });

      if (cdpResult && hasRequiredCookies(cdpResult.cookies)) {
        console.error(kleur.green("Authenticated via Chrome DevTools Protocol (CDP)."));
        return cdpResult.cookies as XhsCookies;
      }

      if (cdpResult && cdpResult.cookies.a1 && !cdpResult.cookies.web_session) {
        console.error(
          kleur.yellow(
            "CDP also returned incomplete cookies (a1 found, web_session missing).\n" +
              "You may not be logged in to xiaohongshu.com, or your session has expired."
          )
        );
      }
    } catch {
      // CDP also failed — fall through to rethrow original error
    }

    // 3. Both failed — rethrow original sweet-cookie error (has detailed troubleshooting)
    throw sweetCookieErr;
  }
}

/**
 * Lightweight, non-throwing cookie probe for platform auto-detection.
 * Reads only via sweet-cookie (no CDP fallback, no keychain retries, no logs)
 * for a specific cookie domain (via cookieUrl). Returns null if the required
 * cookies (a1 + web_session) are not present for that domain.
 *
 * Used to check both xiaohongshu.com and rednote.com and decide which one the
 * user is actually logged into, without side effects or noise.
 */
export async function probeCookies(
  source: CookieSource,
  chromeProfile: string | undefined,
  cookieUrl: string
): Promise<XhsCookies | null> {
  try {
    return await extractViaSweetCookie(source, chromeProfile, () => {}, cookieUrl);
  } catch {
    return null;
  }
}

/**
 * Format cookies as a cookie header string: "a1=xxx; web_session=yyy; ..."
 */
export function cookiesToString(cookies: XhsCookies): string {
  return Object.entries(cookies)
    .map(([k, v]) => `${k}=${v}`)
    .join("; ");
}
