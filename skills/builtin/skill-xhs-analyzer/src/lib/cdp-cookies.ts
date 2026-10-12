/**
 * CDP (Chrome DevTools Protocol) cookie extraction fallback.
 *
 * When sweet-cookie can't fully decrypt Chrome cookies on Windows
 * (Chrome 127+ uses App-Bound Encryption), this module connects to
 * Chrome via its DevTools Protocol to read cookies directly — Chrome
 * itself handles decryption, so all cookies are readable.
 *
 * Flow:
 *  1. Check for an existing Chrome debugging session on port 9222
 *  2. If unavailable, launch Chrome headless with --remote-debugging-port
 *  3. Use Network.getAllCookies via WebSocket to read decrypted cookies
 *  4. Shut down headless Chrome if we launched it
 */

import { spawn, execFileSync, type ChildProcess } from "node:child_process";
import { existsSync, mkdtempSync, mkdirSync, copyFileSync, rmSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";

const CDP_PORT = 9222;
const CDP_BASE = `http://127.0.0.1:${CDP_PORT}`;
const CDP_LAUNCH_TIMEOUT = 15_000;
const CDP_WS_TIMEOUT = 10_000;

interface CdpCookie {
  name: string;
  value: string;
  domain: string;
  path: string;
}

export interface CdpResult {
  cookies: Record<string, string>;
  warnings: string[];
}

export type CdpLogger = (msg: string) => void;

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

// ─── Chrome Binary Discovery ─────────────────────────────────────────────────

function findChromeBinary(): string | null {
  if (process.platform === "darwin") {
    const chromePath = process.env.CHROME_PATH ??
      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
    return existsSync(chromePath) ? chromePath : null;
  }

  if (process.platform === "win32") {
    const envPaths = [
      process.env.PROGRAMFILES,
      process.env["PROGRAMFILES(X86)"],
      process.env.LOCALAPPDATA,
    ].filter(Boolean) as string[];
    for (const base of envPaths) {
      const p = join(base, "Google", "Chrome", "Application", "chrome.exe");
      if (existsSync(p)) return p;
    }
    return null;
  }

  // Linux: try common binary names via which (hardcoded names, no user input)
  for (const name of ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"]) {
    try {
      const result = execFileSync("which", [name], {
        encoding: "utf-8",
        stdio: ["pipe", "pipe", "pipe"],
      }).trim();
      if (result && existsSync(result)) return result;
    } catch {
      // not found, try next
    }
  }
  return null;
}

function getChromeUserDataDir(): string | null {
  if (process.platform === "darwin") {
    return join(homedir(), "Library", "Application Support", "Google", "Chrome");
  }
  if (process.platform === "win32") {
    const localAppData = process.env.LOCALAPPDATA;
    return localAppData ? join(localAppData, "Google", "Chrome", "User Data") : null;
  }
  if (process.platform === "linux") {
    return join(homedir(), ".config", "google-chrome");
  }
  return null;
}

// ─── CDP Connection ──────────────────────────────────────────────────────────

async function getDebuggerWebSocketUrl(): Promise<string | null> {
  try {
    const res = await fetch(`${CDP_BASE}/json/version`, {
      signal: AbortSignal.timeout(3_000),
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { webSocketDebuggerUrl?: string };
    return data.webSocketDebuggerUrl ?? null;
  } catch {
    return null;
  }
}

async function getCookiesFromCdp(wsUrl: string): Promise<CdpCookie[]> {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    const timeout = setTimeout(() => {
      ws.close();
      reject(new Error("CDP WebSocket timed out after 10s"));
    }, CDP_WS_TIMEOUT);

    ws.addEventListener("open", () => {
      ws.send(JSON.stringify({ id: 1, method: "Network.getAllCookies" }));
    });

    ws.addEventListener("message", (event) => {
      clearTimeout(timeout);
      try {
        const msg = JSON.parse(String(event.data)) as {
          id?: number;
          result?: { cookies?: CdpCookie[] };
          error?: { message?: string };
        };
        if (msg.id === 1) {
          ws.close();
          if (msg.error) {
            reject(new Error(`CDP error: ${msg.error.message}`));
          } else {
            resolve(msg.result?.cookies ?? []);
          }
        }
      } catch (err) {
        ws.close();
        reject(err instanceof Error ? err : new Error(String(err)));
      }
    });

    ws.addEventListener("error", () => {
      clearTimeout(timeout);
      reject(new Error("CDP WebSocket connection failed"));
    });
  });
}

// ─── Chrome Launcher ─────────────────────────────────────────────────────────

async function launchChromeHeadless(
  chromeBinary: string,
  userDataDir: string,
  profile: string | undefined,
  log: CdpLogger
): Promise<ChildProcess> {
  const args = [
    `--remote-debugging-port=${CDP_PORT}`,
    "--headless=new",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-gpu",
    `--user-data-dir=${userDataDir}`,
  ];
  if (profile) {
    args.push(`--profile-directory=${profile}`);
  }

  log(`Launching: ${chromeBinary} ${args.join(" ")}`);

  const child = spawn(chromeBinary, args, {
    stdio: "ignore",
    detached: false,
    ...(process.platform === "win32" ? { windowsHide: true } : {}),
  });

  let exitCode: number | null = null;
  child.on("exit", (code) => { exitCode = code; });

  const start = Date.now();
  while (Date.now() - start < CDP_LAUNCH_TIMEOUT) {
    if (exitCode !== null) {
      throw new Error(
        "Chrome exited immediately (exit code " + exitCode + "). " +
        "This usually means Chrome is already running and holding the profile lock.\n" +
        "To fix: close all Chrome windows and re-run this command, " +
        "or use --cookie-string as a manual fallback."
      );
    }

    try {
      const res = await fetch(`${CDP_BASE}/json/version`, {
        signal: AbortSignal.timeout(2_000),
      });
      if (res.ok) {
        log("Headless Chrome is ready on port " + CDP_PORT + ".");
        return child;
      }
    } catch {
      // Not ready yet, keep polling
    }

    await sleep(500);
  }

  child.kill();
  throw new Error(
    "Chrome headless did not start within " + (CDP_LAUNCH_TIMEOUT / 1000) + "s. " +
    "Try closing other Chrome instances or use --cookie-string."
  );
}

// ─── Temp Profile Copy (for profile-lock workaround) ─────────────────────────

/**
 * Copy essential Chrome profile files to a temp directory so we can launch
 * headless Chrome without conflicting with the running Chrome's profile lock.
 * Chrome can still decrypt App-Bound Encrypted cookies because the same
 * IElevator COM service + DPAPI context is used (same binary, same OS user).
 */
function copyProfileToTempDir(
  userDataDir: string,
  profile: string,
  log: CdpLogger
): string | null {
  try {
    const tempBase = mkdtempSync(join(tmpdir(), "redbook-cdp-"));

    // Copy Local State (contains os_crypt.encrypted_key for cookie decryption)
    const localState = join(userDataDir, "Local State");
    if (existsSync(localState)) {
      copyFileSync(localState, join(tempBase, "Local State"));
    }

    // Create profile directory in temp
    const tempProfileDir = join(tempBase, profile);
    mkdirSync(tempProfileDir, { recursive: true });

    // Helper: copy a file if it exists, ignore errors (e.g. locked files)
    const tryCopy = (src: string, dest: string) => {
      try {
        if (existsSync(src)) copyFileSync(src, dest);
      } catch {
        // File may be locked; skip it
      }
    };

    const srcProfile = join(userDataDir, profile);

    // Copy Cookies database + journal/WAL files (older Chrome path)
    for (const f of ["Cookies", "Cookies-journal", "Cookies-wal", "Cookies-shm"]) {
      tryCopy(join(srcProfile, f), join(tempProfileDir, f));
    }

    // Copy Network/Cookies (newer Chrome versions store cookies here)
    const srcNetwork = join(srcProfile, "Network");
    if (existsSync(srcNetwork)) {
      const tempNetwork = join(tempProfileDir, "Network");
      mkdirSync(tempNetwork, { recursive: true });
      for (const f of ["Cookies", "Cookies-journal", "Cookies-wal", "Cookies-shm"]) {
        tryCopy(join(srcNetwork, f), join(tempNetwork, f));
      }
    }

    log("Copied Chrome profile to temp dir: " + tempBase);
    return tempBase;
  } catch (err) {
    log("Failed to copy profile to temp dir: " + (err instanceof Error ? err.message : String(err)));
    return null;
  }
}

function cleanupTempDir(dir: string, log: CdpLogger): void {
  try {
    rmSync(dir, { recursive: true, force: true });
    log("Cleaned up temporary profile directory.");
  } catch {
    // Ignore cleanup errors
  }
}

// ─── Public API ──────────────────────────────────────────────────────────────

/**
 * Attempt to extract XHS cookies via Chrome DevTools Protocol.
 * Returns null if CDP is not available or extraction fails.
 */
export async function extractCookiesViaCdp(options?: {
  profile?: string;
  log?: CdpLogger;
}): Promise<CdpResult | null> {
  const log = options?.log ?? (() => {});

  // Check WebSocket availability (Node 22+)
  if (typeof globalThis.WebSocket === "undefined") {
    log(
      "CDP fallback unavailable — WebSocket requires Node.js 22+. " +
      "Current: " + process.version + ". " +
      "Use --cookie-string as a manual fallback."
    );
    return null;
  }

  // 1. Try existing debugging session
  log("Checking for existing Chrome debugging session on port " + CDP_PORT + "...");
  let wsUrl = await getDebuggerWebSocketUrl();
  let launchedProcess: ChildProcess | null = null;
  let tempDir: string | null = null;

  if (wsUrl) {
    log("Found existing Chrome debugging session.");
  } else {
    // 2. Try launching Chrome headless
    const chromeBinary = findChromeBinary();
    if (!chromeBinary) {
      log(
        "Chrome binary not found. Searched standard install locations for " +
        process.platform + ". Cannot use CDP fallback."
      );
      return null;
    }
    log("Found Chrome: " + chromeBinary);

    const userDataDir = getChromeUserDataDir();
    if (!userDataDir || !existsSync(userDataDir)) {
      log("Chrome user data directory not found. Cannot use CDP fallback.");
      return null;
    }
    log("User data dir: " + userDataDir);

    try {
      launchedProcess = await launchChromeHeadless(
        chromeBinary,
        userDataDir,
        options?.profile,
        log
      );
      wsUrl = await getDebuggerWebSocketUrl();
    } catch (err) {
      log(err instanceof Error ? err.message : String(err));

      // Profile lock detected — retry with a temp copy of the profile
      const isProfileLock =
        err instanceof Error && err.message.includes("Chrome exited immediately");

      if (isProfileLock) {
        log("");
        log("Retrying with a temporary copy of the Chrome profile...");
        const profileName = options?.profile || "Default";
        tempDir = copyProfileToTempDir(userDataDir, profileName, log);

        if (tempDir) {
          try {
            launchedProcess = await launchChromeHeadless(
              chromeBinary,
              tempDir,
              profileName,
              log
            );
            wsUrl = await getDebuggerWebSocketUrl();
          } catch (retryErr) {
            log(retryErr instanceof Error ? retryErr.message : String(retryErr));
            cleanupTempDir(tempDir, log);
            return null;
          }
        } else {
          return null;
        }
      } else {
        return null;
      }
    }
  }

  if (!wsUrl) {
    launchedProcess?.kill();
    log("Could not obtain Chrome DevTools WebSocket URL.");
    return null;
  }

  // 3. Extract cookies
  try {
    log("Requesting all cookies via CDP (Network.getAllCookies)...");
    const allCookies = await getCookiesFromCdp(wsUrl);

    const xhsCookies: Record<string, string> = {};
    for (const c of allCookies) {
      if (c.domain.includes("xiaohongshu.com")) {
        xhsCookies[c.name] = c.value;
      }
    }

    const count = Object.keys(xhsCookies).length;
    if (count > 0) {
      log("Extracted " + count + " xiaohongshu.com cookies via CDP.");
    } else {
      log(
        "No xiaohongshu.com cookies found via CDP. " +
        "Make sure you are logged in at https://www.xiaohongshu.com/ in Chrome."
      );
    }

    return { cookies: xhsCookies, warnings: [] };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    log("CDP cookie extraction failed: " + msg);
    return null;
  } finally {
    if (launchedProcess) {
      log("Shutting down headless Chrome.");
      launchedProcess.kill();
      // Give Chrome a moment to clean up
      await sleep(500);
    }
    if (tempDir) {
      cleanupTempDir(tempDir, log);
    }
  }
}
