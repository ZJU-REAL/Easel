/**
 * Creator platform signing (XYW_ prefix)
 * Used for creator.xiaohongshu.com endpoints (posting, analytics)
 *
 * Algorithm: MD5(api + JSON(data)) → AES-128-CBC encrypt → XYW_ prefix
 * Much simpler than main API signing.
 *
 * Ported from: Spider_XHS/static/xhs_creator_xs.js + ReaJason/xhs help.py
 */

import crypto from "node:crypto";

const AES_KEY = Buffer.from("7cc4adla5ay0701v");
const AES_IV = Buffer.from("4uzjr7mbsibcaldp");

function aesEncrypt(data: string): string {
  const cipher = crypto.createCipheriv("aes-128-cbc", AES_KEY, AES_IV);
  let encrypted = cipher.update(data, "utf8", "hex");
  encrypted += cipher.final("hex");
  return encrypted;
}

export interface CreatorSignResult {
  "x-s": string;
  "x-t": string;
}

/**
 * Generate creator platform signature headers.
 *
 * @param api - The API path, prefixed with "url=" (e.g., "url=/web_api/sns/v2/note")
 * @param data - Request body data (null for GET requests)
 * @param a1 - The a1 cookie value
 * @returns Object with x-s and x-t headers
 */
export function signCreator(
  api: string,
  data: Record<string, unknown> | null,
  a1: string
): CreatorSignResult {
  let content = api;
  if (data) {
    content += JSON.stringify(data);
  }

  const md5 = crypto.createHash("md5");
  const x1 = md5.update(content).digest("hex");
  const x2 = "0|0|0|1|0|0|1|0|0|0|1|0|0|0|0|1|0|0|0";
  const x3 = a1;
  const x4 = Date.now();

  const plaintext = `x1=${x1};x2=${x2};x3=${x3};x4=${x4};`;
  const payload = aesEncrypt(Buffer.from(plaintext).toString("base64"));

  const envelope = {
    signSvn: "56",
    signType: "x2",
    appId: "ugc",
    signVersion: "1",
    payload,
  };

  const xs = "XYW_" + Buffer.from(JSON.stringify(envelope)).toString("base64");

  return {
    "x-s": xs,
    "x-t": String(x4),
  };
}
