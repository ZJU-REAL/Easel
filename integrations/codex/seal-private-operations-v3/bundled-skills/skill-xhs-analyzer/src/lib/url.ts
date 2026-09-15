/**
 * Build a shareable web URL for an XHS note.
 *
 * A bare `/explore/<id>` URL without `xsec_token` is 302-redirected to
 * `/404/sec_*?source=xhs_sec_server` by XHS's anti-scrape gate. The token is
 * per-note and context-scoped; `xsec_source` identifies which surface minted
 * it (feed, search, share, etc.). Any consumer clicking a bare URL — Safari,
 * an iOS link preview, an agent's action button — hits the gate.
 *
 * Common source values: `pc_feed`, `pc_search`, `pc_user`, `pc_share`,
 * `pc_creatormng`, `app_share`.
 */
export function buildWebUrl(
  noteId: string,
  xsecToken: string | null | undefined,
  source: string = "pc_feed",
): string {
  const base = `https://www.xiaohongshu.com/explore/${noteId}`;
  if (!xsecToken) return base;
  const params = new URLSearchParams({ xsec_token: xsecToken, xsec_source: source });
  return `${base}?${params.toString()}`;
}

/**
 * Recursively walk a response and add `webUrl` to any object that looks like a
 * note (has a note id plus an `xsec_token`). Mutates in place and returns the
 * same object for chaining. Idempotent — won't overwrite an existing `webUrl`.
 */
export function enrichWithWebUrl<T>(obj: T, source: string = "pc_feed"): T {
  walk(obj as unknown, source);
  return obj;
}

function walk(value: unknown, source: string): void {
  if (!value || typeof value !== "object") return;
  if (Array.isArray(value)) {
    for (const item of value) walk(item, source);
    return;
  }
  const o = value as Record<string, unknown>;
  const noteId = (o.note_id ?? o.id) as string | undefined;
  const token = o.xsec_token as string | undefined;
  if (typeof noteId === "string" && typeof token === "string" && token && !o.webUrl) {
    o.webUrl = buildWebUrl(noteId, token, source);
  }
  for (const v of Object.values(o)) walk(v, source);
}
