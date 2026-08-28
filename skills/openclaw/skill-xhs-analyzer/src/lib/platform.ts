/**
 * Platform configuration — Xiaohongshu (mainland) vs RedNote (global).
 *
 * XHS runs two separate backends that do NOT share sessions:
 *  - Mainland Xiaohongshu:  xiaohongshu.com / edith.xiaohongshu.com, cookies on .xiaohongshu.com
 *  - Global RedNote:        rednote.com     / edith.rednote.com,     cookies on .rednote.com
 *
 * The web signing algorithm (x-s/x-t) is shared — only hosts, cookie domain,
 * and the fingerprint `location` differ. This module makes those swappable so
 * the same client can talk to either backend.
 */

export type PlatformId = "xhs" | "rednote";

export interface PlatformConfig {
  id: PlatformId;
  /** Main read/write API host (signed x-s/x-t endpoints). */
  edithHost: string;
  /** Creator backend host (posting, analytics, note health). */
  creatorHost: string;
  /** Web home origin — used for origin/referer headers and display URLs. */
  homeUrl: string;
  /** Image/video upload host. */
  uploadHost: string;
  /** URL handed to the cookie extractor to select the right cookie domain. */
  cookieUrl: string;
  /** Value embedded as the fingerprint `location` in the signing payload. */
  signLocation: string;
}

export const PLATFORMS: Record<PlatformId, PlatformConfig> = {
  xhs: {
    id: "xhs",
    edithHost: "https://edith.xiaohongshu.com",
    creatorHost: "https://creator.xiaohongshu.com",
    homeUrl: "https://www.xiaohongshu.com",
    uploadHost: "https://ros-upload.xiaohongshu.com",
    cookieUrl: "https://www.xiaohongshu.com/",
    signLocation: "https://www.xiaohongshu.com/explore",
  },
  rednote: {
    id: "rednote",
    // Global RedNote serves the signed /api/sns/web/* endpoints from webapi.rednote.com
    // (there is no edith.rednote.com). Verified against /api/sns/web/v2/user/me.
    edithHost: "https://webapi.rednote.com",
    creatorHost: "https://creator.rednote.com",
    homeUrl: "https://www.rednote.com",
    uploadHost: "https://ros-upload.rednote.com",
    cookieUrl: "https://www.rednote.com/",
    signLocation: "https://www.rednote.com/explore",
  },
};

/**
 * Resolve a platform config from an explicit id, the REDBOOK_PLATFORM env var,
 * or the default (xhs). Accepts "global" as an alias for "rednote".
 * Host env overrides (REDBOOK_EDITH_HOST / REDBOOK_CREATOR_HOST) are honored
 * for probing/testing alternate API hosts.
 */
export function resolvePlatform(explicit?: string): PlatformConfig {
  const raw = (explicit || process.env.REDBOOK_PLATFORM || "xhs").toLowerCase();
  const base =
    raw === "rednote" || raw === "global" ? PLATFORMS.rednote : PLATFORMS.xhs;
  return {
    ...base,
    edithHost: process.env.REDBOOK_EDITH_HOST || base.edithHost,
    creatorHost: process.env.REDBOOK_CREATOR_HOST || base.creatorHost,
  };
}
