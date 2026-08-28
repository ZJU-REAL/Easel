#!/usr/bin/env node
/**
 * Pre-uninstall script for redbook CLI.
 *
 * Removes the Claude Code skill symlink at ~/.claude/skills/redbook
 * (only if it points to this package).
 */

import { existsSync, unlinkSync, lstatSync, readlinkSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { homedir } from 'os';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const PACKAGE_ROOT = join(__dirname, '..');
const SKILL_LINK = join(homedir(), '.claude', 'skills', 'redbook');

function main() {
  console.log('[redbook] Running pre-uninstall...');

  if (!existsSync(SKILL_LINK)) {
    console.log('[redbook] No skill symlink found, nothing to clean up.');
    return;
  }

  try {
    const stats = lstatSync(SKILL_LINK);
    if (!stats.isSymbolicLink()) {
      console.log('[redbook] Skill path is not a symlink, leaving it alone.');
      return;
    }

    const target = readlinkSync(SKILL_LINK);
    if (target === PACKAGE_ROOT || target.includes('node_modules/@lucasygu/redbook')) {
      unlinkSync(SKILL_LINK);
      console.log('[redbook] Removed Claude Code skill symlink.');
    } else {
      console.log('[redbook] Skill symlink points elsewhere, leaving it alone.');
    }
  } catch (error) {
    console.error(`[redbook] Warning: Could not remove skill: ${error.message}`);
  }

  console.log('[redbook] Uninstall cleanup complete.');
}

main();
