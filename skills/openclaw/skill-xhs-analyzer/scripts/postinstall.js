#!/usr/bin/env node
/**
 * Post-install script for redbook CLI.
 *
 * Sets up Claude Code skill by creating a symlink:
 *   ~/.claude/skills/redbook -> <npm-package-location>
 *
 * This gives Claude Code a /redbook slash command automatically.
 */

import { existsSync, mkdirSync, unlinkSync, symlinkSync, lstatSync, readlinkSync, rmSync, readFileSync, writeFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { homedir } from 'os';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const PACKAGE_ROOT = join(__dirname, '..');
const SKILL_DIR = join(homedir(), '.claude', 'skills');
const SKILL_LINK = join(SKILL_DIR, 'redbook');

function setupClaudeSkill() {
  try {
    if (!existsSync(SKILL_DIR)) {
      mkdirSync(SKILL_DIR, { recursive: true });
    }

    if (existsSync(SKILL_LINK)) {
      try {
        const stats = lstatSync(SKILL_LINK);
        if (stats.isSymbolicLink()) {
          const currentTarget = readlinkSync(SKILL_LINK);
          if (currentTarget === PACKAGE_ROOT) {
            console.log('[redbook] Claude Code skill already configured.');
            return true;
          }
          unlinkSync(SKILL_LINK);
        } else {
          rmSync(SKILL_LINK, { recursive: true });
        }
      } catch (err) {
        console.log(`[redbook] Warning: ${err.message}`);
      }
    }

    symlinkSync(PACKAGE_ROOT, SKILL_LINK);
    console.log('[redbook] Claude Code skill installed:');
    console.log(`[redbook]   ~/.claude/skills/redbook -> ${PACKAGE_ROOT}`);
    return true;
  } catch (error) {
    console.error(`[redbook] Failed to set up skill: ${error.message}`);
    console.log('[redbook] You can manually create the symlink:');
    console.log(`[redbook]   ln -s "${PACKAGE_ROOT}" "${SKILL_LINK}"`);
    return false;
  }
}

/**
 * Patch @steipete/sweet-cookie keychain timeout bug.
 *
 * Published v0.1.0 hardcodes `timeoutMs: 3_000` in chromeSqliteMac.js,
 * ignoring the caller's value. The macOS `security` CLI often needs >3s
 * (especially on first keychain prompt). This patch makes it respect
 * the caller's timeout with a 30s default.
 */
function patchSweetCookieTimeout() {
  const target = join(
    PACKAGE_ROOT,
    'node_modules',
    '@steipete',
    'sweet-cookie',
    'dist',
    'providers',
    'chromeSqliteMac.js'
  );

  if (!existsSync(target)) return;

  try {
    const content = readFileSync(target, 'utf-8');
    const needle = 'timeoutMs: 3_000,';
    if (!content.includes(needle)) {
      // Already patched or upstream fixed
      return;
    }
    const patched = content.replace(needle, 'timeoutMs: options.timeoutMs ?? 30_000,');
    writeFileSync(target, patched, 'utf-8');
    console.log('[redbook] Patched sweet-cookie keychain timeout (3s -> 30s).');
  } catch (err) {
    console.log(`[redbook] Warning: could not patch sweet-cookie: ${err.message}`);
  }
}

/**
 * Patch node:sqlite BigInt overflow on Node < 24.4.
 *
 * Chrome stores expires_utc as microseconds since 1601 — values like
 * 13448382439000000 exceed Number.MAX_SAFE_INTEGER. Node < 24.4 lacks
 * the `readBigInts` option, so node:sqlite throws instead of returning
 * a BigInt. Casting to TEXT in the SQL avoids the overflow; the existing
 * JS code already handles string values via tryParseInt/normalizeExpiration.
 */
function patchSweetCookieBigInt() {
  const target = join(
    PACKAGE_ROOT,
    'node_modules',
    '@steipete',
    'sweet-cookie',
    'dist',
    'providers',
    'chromeSqlite',
    'shared.js'
  );

  if (!existsSync(target)) return;

  try {
    const content = readFileSync(target, 'utf-8');
    const needle = 'SELECT name, value, host_key, path, expires_utc, samesite, encrypted_value,';
    if (!content.includes(needle)) {
      // Already patched or upstream fixed
      return;
    }
    const patched = content.replace(
      needle,
      'SELECT name, value, host_key, path, CAST(expires_utc AS TEXT) AS expires_utc, samesite, encrypted_value,'
    );
    writeFileSync(target, patched, 'utf-8');
    console.log('[redbook] Patched sweet-cookie BigInt overflow (CAST expires_utc).');
  } catch (err) {
    console.log(`[redbook] Warning: could not patch sweet-cookie BigInt: ${err.message}`);
  }
}

function main() {
  console.log('[redbook] Running post-install...');
  const success = setupClaudeSkill();
  patchSweetCookieTimeout();
  patchSweetCookieBigInt();
  console.log('');
  console.log('[redbook] Installation complete!');
  if (success) {
    console.log('[redbook] Use /redbook in Claude Code, or run: redbook --help');
  }
}

main();
