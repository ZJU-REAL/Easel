/**
 * XHS API Client
 *
 * Handles all HTTP requests to edith.xiaohongshu.com and creator.xiaohongshu.com
 * with proper signing, headers, and error handling.
 */

import { signMainApi, USER_AGENT, buildGetUri, extractUri } from "./signing.js";
import { signCreator } from "./creator-signing.js";
import { cookiesToString, type XhsCookies } from "./cookies.js";
import { PLATFORMS, type PlatformConfig } from "./platform.js";

export class XhsApiError extends Error {
  constructor(
    message: string,
    public code?: number | string,
    public response?: unknown
  ) {
    super(message);
    this.name = "XhsApiError";
  }
}

export class NeedVerifyError extends XhsApiError {
  constructor(
    public verifyType: string,
    public verifyUuid: string
  ) {
    super(`Captcha required: type=${verifyType}, uuid=${verifyUuid}`);
    this.name = "NeedVerifyError";
  }
}

export interface UserPageRequestOptions {
  xsecToken?: string | null;
  xsecSource?: string | null;
}

export class XhsClient {
  private cookies: XhsCookies;
  private platform: PlatformConfig;

  constructor(cookies: XhsCookies, platform: PlatformConfig = PLATFORMS.xhs) {
    this.cookies = cookies;
    this.platform = platform;
  }

  /** Which backend this client talks to ("xhs" | "rednote"). */
  get platformId(): PlatformConfig["id"] {
    return this.platform.id;
  }

  /** Human label for the active backend. */
  get platformLabel(): string {
    return this.platform.id === "rednote" ? "RedNote (global)" : "Xiaohongshu";
  }

  private baseHeaders(): Record<string, string> {
    return {
      "user-agent": USER_AGENT,
      "content-type": "application/json",
      cookie: cookiesToString(this.cookies),
      origin: this.platform.homeUrl,
      referer: `${this.platform.homeUrl}/`,
    };
  }

  private async mainApiGet(
    uri: string,
    params?: Record<string, string | number | string[]>
  ): Promise<unknown> {
    const signHeaders = signMainApi("GET", uri, this.cookies, params, undefined, undefined, this.platform.signLocation);
    const fullUri = buildGetUri(uri, params);
    const url = `${this.platform.edithHost}${fullUri}`;

    const res = await fetch(url, {
      method: "GET",
      headers: { ...this.baseHeaders(), ...signHeaders },
    });

    return this.handleResponse(res);
  }

  private async mainApiPost(
    uri: string,
    data: Record<string, unknown>
  ): Promise<unknown> {
    const signHeaders = signMainApi("POST", uri, this.cookies, undefined, data, undefined, this.platform.signLocation);
    const url = `${this.platform.edithHost}${uri}`;

    const res = await fetch(url, {
      method: "POST",
      headers: { ...this.baseHeaders(), ...signHeaders },
      body: JSON.stringify(data),
    });

    return this.handleResponse(res);
  }

  // /web_api/ endpoints → edith host; /api/galaxy/ → creator host
  private creatorHost(uri: string): string {
    return uri.startsWith("/api/galaxy/") ? this.platform.creatorHost : this.platform.edithHost;
  }

  private async creatorGet(
    uri: string,
    params?: Record<string, string | number>
  ): Promise<unknown> {
    let apiStr = `url=${uri}`;
    if (params) {
      const qs = Object.entries(params)
        .map(([k, v]) => `${k}=${v}`)
        .join("&");
      apiStr = `url=${uri}?${qs}`;
    }

    const sign = signCreator(apiStr, null, this.cookies.a1);
    const fullUri = params
      ? `${uri}?${Object.entries(params).map(([k, v]) => `${k}=${v}`).join("&")}`
      : uri;

    const host = this.creatorHost(uri);
    const res = await fetch(`${host}${fullUri}`, {
      method: "GET",
      headers: {
        ...this.baseHeaders(),
        "x-s": sign["x-s"],
        "x-t": sign["x-t"],
        origin: this.platform.creatorHost,
        referer: `${this.platform.creatorHost}/`,
      },
    });

    return this.handleResponse(res);
  }

  private async creatorPost(
    uri: string,
    data: Record<string, unknown>
  ): Promise<unknown> {
    const sign = signCreator(`url=${uri}`, data, this.cookies.a1);

    const host = this.creatorHost(uri);
    const res = await fetch(`${host}${uri}`, {
      method: "POST",
      headers: {
        ...this.baseHeaders(),
        "x-s": sign["x-s"],
        "x-t": sign["x-t"],
        origin: this.platform.creatorHost,
        referer: `${this.platform.creatorHost}/`,
      },
      body: JSON.stringify(data),
    });

    return this.handleResponse(res);
  }

  private async handleResponse(res: Response): Promise<unknown> {
    if (res.status === 461 || res.status === 471) {
      throw new NeedVerifyError(
        res.headers.get("verifytype") ?? "unknown",
        res.headers.get("verifyuuid") ?? "unknown"
      );
    }

    const text = await res.text();
    if (!text) return null;

    let data: Record<string, unknown>;
    try {
      data = JSON.parse(text);
    } catch {
      throw new XhsApiError(
        `Non-JSON response: ${text.substring(0, 200)}`,
        res.status,
        text
      );
    }

    if (data.success) {
      return data.data ?? data.success;
    }

    const code = data.code as string | number | undefined;
    if (code === 300012) {
      throw new XhsApiError("IP blocked by XHS", code, data);
    }
    if (code === 300015) {
      throw new XhsApiError("Signature verification failed", code, data);
    }
    if (code === -100) {
      throw new XhsApiError("Session expired — please re-login", code, data);
    }
    if (code === -101) {
      const hint = process.platform === "win32"
        ? ' Use --cookie-string "a1=VALUE; web_session=VALUE" (from Chrome DevTools > Application > Cookies).'
        : " Try logging out and back in on xiaohongshu.com.";
      throw new XhsApiError(
        `Missing or incomplete login cookies — the 'web_session' cookie may not have been extracted.${hint}`,
        code,
        data
      );
    }

    throw new XhsApiError(
      `API error: ${JSON.stringify(data).substring(0, 300)}`,
      code,
      data
    );
  }

  // ─── Reading Endpoints ──────────────────────────────────────────────────

  async getSelfInfo(): Promise<unknown> {
    return this.mainApiGet("/api/sns/web/v2/user/me");
  }

  async getUserInfo(
    userId: string,
    options: UserPageRequestOptions = {}
  ): Promise<unknown> {
    return this.mainApiGet("/api/sns/web/v1/user/otherinfo", {
      target_user_id: userId,
      xsec_token: options.xsecToken ?? "",
      xsec_source: options.xsecSource ?? "",
    });
  }

  async getUserNotes(
    userId: string,
    cursor: string = "",
    options: UserPageRequestOptions = {}
  ): Promise<unknown> {
    const params = {
      num: 30,
      cursor,
      user_id: userId,
      image_formats: "jpg,webp,avif",
      xsec_token: options.xsecToken ?? "",
      xsec_source: options.xsecSource ?? "",
    };

    const endpoints = this.platform.id === "rednote"
      ? ["/api/sns/web/v1/user_posted"]
      : ["/api/sns/web/v2/user_posted", "/api/sns/web/v1/user_posted"];

    for (const [idx, endpoint] of endpoints.entries()) {
      try {
        return await this.mainApiGet(endpoint, params);
      } catch (err) {
        const canFallback =
          idx < endpoints.length - 1
          && err instanceof XhsApiError
          && (err.code === -1 || err.code === 404);
        if (!canFallback) throw err;
      }
    }

    throw new XhsApiError("No user-posted endpoint configured");
  }

  async searchNotes(
    keyword: string,
    page: number = 1,
    pageSize: number = 20,
    sort: "general" | "popularity_descending" | "time_descending" = "general",
    noteType: 0 | 1 | 2 = 0
  ): Promise<unknown> {
    const searchId = generateSearchId();
    return this.mainApiPost("/api/sns/web/v1/search/notes", {
      keyword,
      page,
      page_size: pageSize,
      search_id: searchId,
      sort,
      note_type: noteType,
    });
  }

  async getNoteById(
    noteId: string,
    xsecToken: string,
    xsecSource: string = "pc_feed"
  ): Promise<unknown> {
    return this.mainApiPost("/api/sns/web/v1/feed", {
      source_note_id: noteId,
      image_formats: ["jpg", "webp", "avif"],
      extra: { need_body_topic: 1 },
      xsec_source: xsecSource,
      xsec_token: xsecToken,
    });
  }

  async getHomeFeed(
    category: string = "homefeed_recommend"
  ): Promise<unknown> {
    return this.mainApiPost("/api/sns/web/v1/homefeed", {
      cursor_score: "",
      num: 40,
      refresh_type: 1,
      note_index: 0,
      unread_begin_note_id: "",
      unread_end_note_id: "",
      unread_note_count: 0,
      category,
      search_key: "",
      need_num: 40,
      image_scenes: ["FD_PRV_WEBP", "FD_WM_WEBP"],
    });
  }

  async getComments(
    noteId: string,
    cursor: string = "",
    xsecToken: string = ""
  ): Promise<unknown> {
    return this.mainApiGet("/api/sns/web/v2/comment/page", {
      note_id: noteId,
      cursor,
      image_formats: "jpg,webp,avif",
      xsec_token: xsecToken,
    });
  }

  // ─── Favorites / Collect Endpoints ────────────────────────────────────

  async getUserCollectedNotes(
    userId: string,
    num: number = 30,
    cursor: string = ""
  ): Promise<unknown> {
    return this.mainApiGet("/api/sns/web/v2/note/collect/page", {
      user_id: userId,
      num,
      cursor,
    });
  }

  async collectNote(noteId: string): Promise<unknown> {
    return this.mainApiPost("/api/sns/web/v1/note/collect", {
      note_id: noteId,
    });
  }

  async uncollectNote(noteId: string): Promise<unknown> {
    return this.mainApiPost("/api/sns/web/v1/note/uncollect", {
      note_ids: noteId,
    });
  }

  // ─── Like / Unlike Endpoints ─────────────────────────────────────────

  async likeNote(noteId: string): Promise<unknown> {
    return this.mainApiPost("/api/sns/web/v1/note/like", {
      note_oid: noteId,
    });
  }

  async unlikeNote(noteId: string): Promise<unknown> {
    return this.mainApiPost("/api/sns/web/v1/note/dislike", {
      note_oid: noteId,
    });
  }

  // ─── Follow Endpoints ────────────────────────────────────────────────

  async getUserFollowers(userId: string, cursor: string = ""): Promise<unknown> {
    return this.mainApiGet("/api/sns/web/v1/user/fans_page", {
      user_id: userId,
      cursor,
      num: 30,
    });
  }

  async getUserFollowing(userId: string, cursor: string = ""): Promise<unknown> {
    return this.mainApiGet("/api/sns/web/v1/user/following_page", {
      user_id: userId,
      cursor,
      num: 30,
    });
  }

  // ─── Delete Endpoint ─────────────────────────────────────────────────

  async deleteNote(noteId: string): Promise<unknown> {
    return this.creatorPost("/api/galaxy/creator/note/delete", {
      note_id: noteId,
    });
  }

  async getSubComments(
    noteId: string,
    rootCommentId: string,
    num: number = 30,
    cursor: string = ""
  ): Promise<unknown> {
    return this.mainApiGet("/api/sns/web/v2/comment/sub/page", {
      note_id: noteId,
      root_comment_id: rootCommentId,
      num,
      cursor,
    });
  }

  async postComment(
    noteId: string,
    content: string
  ): Promise<unknown> {
    return this.mainApiPost("/api/sns/web/v1/comment/post", {
      note_id: noteId,
      content,
      at_users: [],
    });
  }

  async replyComment(
    noteId: string,
    targetCommentId: string,
    content: string
  ): Promise<unknown> {
    return this.mainApiPost("/api/sns/web/v1/comment/post", {
      note_id: noteId,
      content,
      target_comment_id: targetCommentId,
      at_users: [],
    });
  }

  // ─── HTML Fallback ────────────────────────────────────────────────────

  async getNoteFromHtml(
    noteId: string,
    xsecToken: string
  ): Promise<unknown> {
    const url = `${this.platform.homeUrl}/explore/${noteId}?xsec_token=${xsecToken}&xsec_source=pc_feed`;
    const res = await fetch(url, {
      headers: {
        "user-agent": USER_AGENT,
        referer: `${this.platform.homeUrl}/`,
        cookie: cookiesToString(this.cookies),
      },
    });

    const html = await res.text();
    const match = html.match(
      /window\.__INITIAL_STATE__=({.*})<\/script>/
    );
    if (!match) {
      throw new XhsApiError("Could not parse __INITIAL_STATE__ from HTML");
    }

    // Replace bare `undefined` values (not inside strings) with ""
    const stateStr = match[1].replace(/:\s*undefined/g, ':""').replace(/,\s*undefined/g, ',""');
    const state = JSON.parse(stateStr);

    const detailMap = state.note?.noteDetailMap;
    if (detailMap) {
      // Try exact noteId first, then fall back to first entry
      const entry = detailMap[noteId] ?? Object.values(detailMap)[0];
      if (entry && (entry as Record<string, unknown>).note) {
        return (entry as Record<string, unknown>).note;
      }
    }

    throw new XhsApiError("Note not found in HTML state");
  }

  // ─── Board / Collection Album Endpoints ──────────────────────────────

  /** GET /api/sns/web/v1/board/note — list notes in a board */
  async getBoardNotes(
    boardId: string,
    num: number = 30,
    cursor: string = ""
  ): Promise<unknown> {
    return this.mainApiGet("/api/sns/web/v1/board/note", {
      board_id: boardId,
      num,
      cursor,
    });
  }

  /** GET /api/sns/web/v1/board/user — list user's boards */
  async getUserBoards(
    userId: string,
    num: number = 30,
    page: number = 1
  ): Promise<unknown> {
    return this.mainApiGet("/api/sns/web/v1/board/user", {
      user_id: userId,
      num,
      page,
    });
  }

  /** GET /api/sns/web/v1/board/{boardId} — get board info */
  async getBoardInfo(boardId: string): Promise<unknown> {
    return this.mainApiGet(`/api/sns/web/v1/board/${boardId}`);
  }

  // ─── Board HTML Fallback ────────────────────────────────────────────

  async getBoardFromHtml(
    boardId: string
  ): Promise<unknown> {
    const url = `${this.platform.homeUrl}/board/${boardId}`;
    const res = await fetch(url, {
      headers: {
        "user-agent": USER_AGENT,
        accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        referer: `${this.platform.homeUrl}/`,
        cookie: cookiesToString(this.cookies),
      },
    });

    const html = await res.text();

    // Board pages may use __INITIAL_SSR_STATE__ or __INITIAL_STATE__
    const ssrMatch = html.match(
      /window\.__INITIAL_SSR_STATE__\s*=\s*(\{[\s\S]*?\})\s*(?:;|<\/script>)/
    );
    if (ssrMatch) {
      const stateStr = ssrMatch[1].replace(/\bundefined\b/g, "null");
      const state = JSON.parse(stateStr);
      const main = state.Main;
      if (main) {
        return this.parseSsrBoard(boardId, main);
      }
    }

    // Fallback: try __INITIAL_STATE__ (older page versions)
    const stateMatch = html.match(
      /window\.__INITIAL_STATE__=({.*})<\/script>/
    );
    if (stateMatch) {
      const stateStr = stateMatch[1].replace(/:\s*undefined/g, ':""').replace(/,\s*undefined/g, ',""');
      const state = JSON.parse(stateStr);
      return this.parseLegacyBoard(boardId, state);
    }

    throw new XhsApiError("Could not parse board page — neither __INITIAL_SSR_STATE__ nor __INITIAL_STATE__ found");
  }

  private parseSsrBoard(boardId: string, main: Record<string, unknown>): unknown {
    const albumInfo = main.albumInfo as Record<string, unknown> | undefined;
    const notesDetail = main.notesDetail as Array<Record<string, unknown>> | undefined;

    const notes = Array.isArray(notesDetail) ? notesDetail : [];
    return {
      boardId,
      name: albumInfo?.name ?? albumInfo?.title ?? "",
      desc: albumInfo?.desc ?? "",
      noteCount: albumInfo?.noteCount ?? albumInfo?.note_count ?? notes.length,
      notes: notes.map((n) => ({
        note_id: n.id ?? n.noteId ?? n.note_id ?? "",
        xsec_token: n.xsecToken ?? n.xsec_token ?? "",
        title: n.title ?? n.displayTitle ?? "",
        type: n.type ?? "",
        author: (n.user as Record<string, unknown>)?.nickname ??
                (n.user as Record<string, unknown>)?.nickName ?? "",
        cover: ((n.cover as Record<string, unknown>)?.url as string ?? "").split("?")[0],
        url: `${this.platform.homeUrl}/explore/${n.id ?? n.noteId ?? n.note_id}`,
      })),
    };
  }

  private parseLegacyBoard(boardId: string, state: Record<string, unknown>): unknown {
    const board = state.board as Record<string, unknown> | undefined;
    const boardDetails = board?.boardDetails as Record<string, unknown> | undefined;
    const boardFeedsMap = board?.boardFeedsMap as Record<string, unknown> | undefined;

    let feedEntry = (boardFeedsMap?.[boardId] ?? (boardFeedsMap?._rawValue as Record<string, unknown>)?.[boardId]) as Record<string, unknown> | undefined;
    if (!feedEntry) {
      const entries = (boardFeedsMap?._rawValue ?? boardFeedsMap ?? {}) as Record<string, unknown>;
      const firstKey = Object.keys(entries).find(k => k !== "_rawValue");
      if (firstKey) feedEntry = entries[firstKey] as Record<string, unknown>;
    }

    const notes = (feedEntry?.notes ?? []) as Array<Record<string, unknown>>;
    const detail = ((boardDetails?.[boardId] ?? (boardDetails?._rawValue as Record<string, unknown>)?.[boardId]) ?? {}) as Record<string, unknown>;

    return {
      boardId,
      name: detail.name ?? detail.title ?? "",
      desc: detail.desc ?? "",
      noteCount: detail.noteCount ?? detail.note_count ?? notes.length,
      cursor: feedEntry?.cursor ?? "",
      hasMore: feedEntry?.hasMore ?? false,
      notes: notes.map((n) => ({
        note_id: n.noteId ?? n.note_id ?? "",
        xsec_token: n.xsecToken ?? n.xsec_token ?? "",
        title: n.displayTitle ?? n.display_title ?? n.title ?? "",
        type: n.type ?? "",
        author: (n.user as Record<string, unknown>)?.nickName ??
                (n.user as Record<string, unknown>)?.nickname ?? "",
        cover: ((n.cover as Record<string, unknown>)?.urlDefault ??
               (n.cover as Record<string, unknown>)?.url ?? "") as string,
        url: `${this.platform.homeUrl}/explore/${n.noteId ?? n.note_id}${n.xsecToken ? `?xsec_token=${n.xsecToken}&xsec_source=pc_share` : ""}`,
      })),
    };
  }

  // ─── Creator/Posting Endpoints ────────────────────────────────────────

  async getUploadPermit(
    fileType: "image" | "video",
    count: number = 1
  ): Promise<{ fileId: string; token: string }> {
    const data = (await this.creatorGet("/api/media/v1/upload/web/permit", {
      biz_name: "spectrum",
      scene: fileType,
      file_count: count,
      version: 1,
      source: "web",
    })) as { uploadTempPermits: Array<{ fileIds: string[]; token: string }> };

    const permit = data.uploadTempPermits[0];
    return { fileId: permit.fileIds[0], token: permit.token };
  }

  async uploadFile(
    fileId: string,
    token: string,
    filePath: string,
    contentType: string = "image/jpeg"
  ): Promise<void> {
    const fs = await import("node:fs");
    const fileData = fs.readFileSync(filePath);
    const url = `${this.platform.uploadHost}/${fileId}`;

    const res = await fetch(url, {
      method: "PUT",
      headers: {
        "X-Cos-Security-Token": token,
        "Content-Type": contentType,
      },
      body: fileData,
    });

    if (!res.ok) {
      throw new XhsApiError(`Upload failed: ${res.status} ${res.statusText}`);
    }
  }

  async createImageNote(
    title: string,
    desc: string,
    imageFileIds: string[],
    options: {
      topics?: Array<{ id: string; name: string; type: string }>;
      ats?: Array<{ userId: string; nickname: string }>;
      postTime?: string;
      isPrivate?: boolean;
    } = {}
  ): Promise<unknown> {
    const images = imageFileIds.map((fileId) => ({
      file_id: fileId,
      metadata: { source: -1 },
    }));

    const businessBinds = {
      version: 1,
      noteId: 0,
      noteOrderBind: {},
      notePostTiming: { postTime: options.postTime ? new Date(options.postTime).getTime() : null },
      noteCollectionBind: { id: "" },
    };

    const data = {
      common: {
        type: "normal",
        title,
        note_id: "",
        desc,
        source: '{"type":"web","ids":"","extraInfo":"{\\"subType\\":\\"official\\"}"}',
        business_binds: JSON.stringify(businessBinds),
        ats: options.ats ?? [],
        hash_tag: options.topics ?? [],
        post_loc: {},
        privacy_info: { op_type: 1, type: options.isPrivate ? 1 : 0 },
      },
      image_info: { images },
      video_info: null,
    };

    return this.creatorPost("/web_api/sns/v2/note", data);
  }

  async searchTopics(keyword: string): Promise<unknown> {
    return this.creatorPost("/web_api/sns/v1/search/topic", {
      keyword,
      suggest_topic_request: { title: "", desc: "" },
      page: { page_size: 20, page: 1 },
    });
  }

  async searchUsers(keyword: string): Promise<unknown> {
    return this.creatorPost("/web_api/sns/v1/search/user_info", {
      keyword,
      search_id: String(Date.now()),
      page: { page_size: 20, page: 1 },
    });
  }

  async getCreatorNoteList(
    tab: number = 0,
    page: number = 0
  ): Promise<unknown> {
    // v2 endpoint returns the hidden `level` field for note health checks
    return this.creatorGet("/api/galaxy/v2/creator/note/user/posted", {
      tab,
      page,
    });
  }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function generateSearchId(): string {
  const e = BigInt(Date.now()) << 64n;
  const t = BigInt(Math.floor(Math.random() * 2147483646));
  return base36Encode(e + t);
}

function base36Encode(num: bigint): string {
  const alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  if (num === 0n) return "0";
  let result = "";
  let n = num;
  while (n > 0n) {
    result = alphabet[Number(n % 36n)] + result;
    n = n / 36n;
  }
  return result;
}
