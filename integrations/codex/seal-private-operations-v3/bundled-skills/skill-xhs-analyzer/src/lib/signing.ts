/**
 * Main API signing (XYS_ prefix) for edith.xiaohongshu.com
 *
 * Generates x-s, x-s-common, x-t, x-b3-traceid, x-xray-traceid headers.
 *
 * Algorithm overview (v4.3.1, 144-byte payload):
 *   1. MD5 hash of content string (URI + params/body)
 *   2. Build 144-byte binary payload array (with a3 hash segment)
 *   3. XOR with static 144-byte hex key
 *   4. Custom Base64 encode (shuffled alphabet)
 *   5. Wrap in JSON envelope → another custom Base64 → XYS_ prefix
 *
 * Ported from: Cloxl/xhshow (MIT license)
 */

import crypto from "node:crypto";

// ─── Constants ──────────────────────────────────────────────────────────────

const STANDARD_BASE64 =
  "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
const CUSTOM_BASE64 =
  "ZmserbBoHQtNP+wOcza/LpngG8yJq42KWYj0DSfdikx3VT16IlUAFM97hECvuRX5";
const X3_BASE64 =
  "MfgqrsbcyzPQRStuvC7mn501HIJBo2DEFTKdeNOwxWXYZap89+/A4UVLhijkl63G";

const HEX_KEY =
  "71a302257793271ddd273bcee3e4b98d9d7935e1da33f5765e2ea8afb6dc77a51a499d23b67c20660025860cbf13d4540d92497f58686c574e508f46e1956344f39139bf4faf22a3eef120b79258145b2feb5193b6478669961298e79bedca646e1a693a926154a5a7a1bd1cf0dedb742f917a747a1e388b234f2277516db7116035439730fa61e9822a0eca7bff72d8";

const VERSION_BYTES = [121, 104, 96, 41];
const PAYLOAD_LENGTH = 144;

// Environment detection constants (part11)
const ENV_TABLE = [115, 248, 83, 102, 103, 201, 181, 131, 99, 94, 4, 68, 250, 132, 21];
const ENV_CHECKS_DEFAULT = [0, 1, 18, 1, 0, 0, 0, 0, 0, 0, 3, 0, 0, 0, 0];

// A3 hash segment constants
const A3_PREFIX = [2, 97, 51, 16];
const HASH_IV: [number, number, number, number] = [1831565813, 461845907, 2246822507, 3266489909];
const MAX_32BIT = 0xFFFFFFFF;

const SDK_VERSION = "4.2.6";
const APP_ID = "xhs-pc-web";
const PLATFORM = "Windows";
const X3_PREFIX = "mns0301_";
const XYS_PREFIX = "XYS_";

const B1_SECRET_KEY = "xhswebmplfbt";
const HEX_CHARS = "abcdef0123456789";

const XSCOMMON_TEMPLATE = {
  s0: 5,
  s1: "",
  x0: "1",
  x1: SDK_VERSION,
  x2: PLATFORM,
  x3: APP_ID,
  x4: "4.86.0",
  x5: "",
  x6: "",
  x7: "",
  x8: "",
  x9: -596800761,
  x10: 0,
  x11: "normal",
};

const SIGNATURE_DATA_TEMPLATE = {
  x0: SDK_VERSION,
  x1: APP_ID,
  x2: PLATFORM,
  x3: "",
  x4: "",
};

const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36 Edg/142.0.0.0";

// ─── Base64 Encoding ─────────────────────────────────────────────────────────

function makeTranslateTable(
  from: string,
  to: string
): Map<number, number> {
  const table = new Map<number, number>();
  for (let i = 0; i < from.length; i++) {
    table.set(from.charCodeAt(i), to.charCodeAt(i));
  }
  return table;
}

function translateString(s: string, table: Map<number, number>): string {
  const chars: string[] = [];
  for (let i = 0; i < s.length; i++) {
    const code = s.charCodeAt(i);
    const mapped = table.get(code);
    chars.push(String.fromCharCode(mapped ?? code));
  }
  return chars.join("");
}

const customEncodeTable = makeTranslateTable(STANDARD_BASE64, CUSTOM_BASE64);
const x3EncodeTable = makeTranslateTable(STANDARD_BASE64, X3_BASE64);

function customBase64Encode(data: Buffer | Uint8Array | string): string {
  const buf =
    typeof data === "string" ? Buffer.from(data, "utf-8") : Buffer.from(data);
  const standard = buf.toString("base64");
  return translateString(standard, customEncodeTable);
}

function x3Base64Encode(data: Buffer | Uint8Array): string {
  const standard = Buffer.from(data).toString("base64");
  return translateString(standard, x3EncodeTable);
}

// ─── Utility Functions ───────────────────────────────────────────────────────

function randomInt(min: number, max: number): number {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function randomUint32(): number {
  return crypto.randomBytes(4).readUInt32LE(0);
}

function intToLeBytes(val: number, length: number = 4): number[] {
  if (length <= 4) {
    const arr: number[] = [];
    for (let i = 0; i < length; i++) {
      arr.push(val & 0xff);
      val = val >>> 8;
    }
    return arr;
  }
  // For 8-byte values, use BigInt to avoid JS number precision issues
  const buf = Buffer.alloc(length);
  buf.writeBigUInt64LE(BigInt(val));
  return Array.from(buf);
}

function hexToBytes(hex: string): Uint8Array {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < hex.length; i += 2) {
    bytes[i / 2] = parseInt(hex.substring(i, i + 2), 16);
  }
  return bytes;
}

// ─── A3 Hash Functions ──────────────────────────────────────────────────────

function rotateLeft(val: number, n: number): number {
  return ((val << n) | (val >>> (32 - n))) >>> 0;
}

function customHashV2(inputBytes: number[]): number[] {
  let [s0, s1, s2, s3] = HASH_IV;
  const length = inputBytes.length;

  s0 = (s0 ^ length) >>> 0;
  s1 = (s1 ^ ((length << 8) & MAX_32BIT)) >>> 0;
  s2 = (s2 ^ ((length << 16) & MAX_32BIT)) >>> 0;
  s3 = (s3 ^ ((length << 24) & MAX_32BIT)) >>> 0;

  const buf = Buffer.from(inputBytes);
  for (let i = 0; i < Math.floor(length / 8); i++) {
    const v0 = buf.readUInt32LE(i * 8);
    const v1 = buf.readUInt32LE(i * 8 + 4);

    s0 = rotateLeft(((s0 + v0) & MAX_32BIT) ^ s2, 7);
    s1 = rotateLeft(((v0 ^ s1) + s3) & MAX_32BIT, 11);
    s2 = rotateLeft(((s2 + v1) & MAX_32BIT) ^ s0, 13);
    s3 = rotateLeft(((s3 ^ v1) + s1) & MAX_32BIT, 17);
  }

  const t0 = (s0 ^ length) >>> 0;
  const t1 = (s1 ^ t0) >>> 0;
  const t2 = ((s2 + t1) & MAX_32BIT) >>> 0;
  const t3 = (s3 ^ t2) >>> 0;

  const rot_t0 = rotateLeft(t0, 9);
  const rot_t1 = rotateLeft(t1, 13);
  const rot_t2 = rotateLeft(t2, 17);
  const rot_t3 = rotateLeft(t3, 19);

  s0 = ((rot_t0 + rot_t2) & MAX_32BIT) >>> 0;
  s1 = (rot_t1 ^ rot_t3) >>> 0;
  s2 = ((rot_t2 + s0) & MAX_32BIT) >>> 0;
  s3 = (rot_t3 ^ s1) >>> 0;

  const result: number[] = [];
  for (const s of [s0, s1, s2, s3]) {
    result.push(...intToLeBytes(s, 4));
  }
  return result;
}

function extractApiPath(uriWithData: string): string {
  const bracePos = uriWithData.indexOf("{");
  const questionPos = uriWithData.indexOf("?");

  if (bracePos !== -1 && questionPos !== -1) {
    return uriWithData.substring(0, Math.min(bracePos, questionPos));
  } else if (bracePos !== -1) {
    return uriWithData.substring(0, bracePos);
  } else if (questionPos !== -1) {
    return uriWithData.substring(0, questionPos);
  }
  return uriWithData;
}

// ─── Payload Builder ────────────────────────────────────────────────────────

function buildPayloadArray(
  hexParameter: string,
  a1Value: string,
  contentString: string,
  timestamp?: number
): number[] {
  const payload: number[] = [];

  // Version bytes [0-3]
  payload.push(...VERSION_BYTES);

  // Random seed [4-7]
  const seed = randomUint32();
  const seedBytes = intToLeBytes(seed, 4);
  payload.push(...seedBytes);
  const seedByte0 = seedBytes[0];

  // Timestamp
  const ts = timestamp ?? Date.now() / 1000;
  const tsMs = Math.floor(ts * 1000);

  // Timestamp bytes [8-15] — raw LE int64 (no XOR in v4.3.1)
  const tsBytes = intToLeBytes(tsMs, 8);
  payload.push(...tsBytes);

  // Page load timestamp [16-23]
  const timeOffset = randomInt(10, 50);
  const pageLoadTs = Math.floor((ts - timeOffset) * 1000);
  payload.push(...intToLeBytes(pageLoadTs, 8));

  // Sequence counter [24-27]
  const sequenceValue = randomInt(15, 50);
  payload.push(...intToLeBytes(sequenceValue, 4));

  // Window props length [28-31]
  const windowPropsLength = randomInt(1000, 1200);
  payload.push(...intToLeBytes(windowPropsLength, 4));

  // URI content length [32-35] — UTF-8 byte length (not char count)
  payload.push(...intToLeBytes(Buffer.byteLength(contentString, "utf-8"), 4));

  // MD5 XOR segment [36-43]
  const md5Bytes = hexToBytes(hexParameter);
  for (let i = 0; i < 8; i++) {
    payload.push(md5Bytes[i] ^ seedByte0);
  }

  // A1 length marker [44]
  payload.push(52);

  // A1 content [45-96] (52 bytes, padded/truncated)
  const a1Bytes = Buffer.from(a1Value, "utf-8");
  for (let i = 0; i < 52; i++) {
    payload.push(i < a1Bytes.length ? a1Bytes[i] : 0);
  }

  // Source length marker [97]
  payload.push(10);

  // Source content [98-107] ("xhs-pc-web", 10 bytes)
  const sourceBytes = Buffer.from(APP_ID, "utf-8");
  for (let i = 0; i < 10; i++) {
    payload.push(i < sourceBytes.length ? sourceBytes[i] : 0);
  }

  // Part 11: Environment detection [108-123] (16 bytes)
  payload.push(1); // env marker
  payload.push(seedByte0 ^ ENV_TABLE[0]); // seed ^ ENV_TABLE[0]
  for (let i = 1; i < 15; i++) {
    payload.push(ENV_TABLE[i] ^ ENV_CHECKS_DEFAULT[i]);
  }

  // A3 segment [124-143] (20 bytes) — new in v4.3.1
  const apiPath = extractApiPath(contentString);
  const apiPathMd5 = crypto.createHash("md5").update(apiPath, "utf-8").digest("hex");
  const md5PathBytes: number[] = [];
  for (let i = 0; i < 32; i += 2) {
    md5PathBytes.push(parseInt(apiPathMd5.substring(i, i + 2), 16));
  }
  const hashInput = [...tsBytes, ...md5PathBytes]; // 8 + 16 = 24 bytes
  const hashOutput = customHashV2(hashInput);
  payload.push(...A3_PREFIX);
  for (const b of hashOutput) {
    payload.push(b ^ seedByte0);
  }

  return payload;
}

// ─── XOR Transform ──────────────────────────────────────────────────────────

function xorTransform(source: number[]): Uint8Array {
  const keyBytes = hexToBytes(HEX_KEY);
  const result = new Uint8Array(source.length);
  for (let i = 0; i < source.length; i++) {
    if (i < keyBytes.length) {
      result[i] = (source[i] ^ keyBytes[i]) & 0xff;
    } else {
      result[i] = source[i] & 0xff;
    }
  }
  return result;
}

// ─── CRC32 (JS-compatible variant) ──────────────────────────────────────────

const CRC32_POLY = 0xedb88320;
let crc32Table: Uint32Array | null = null;

function ensureCrc32Table(): Uint32Array {
  if (crc32Table) return crc32Table;
  const table = new Uint32Array(256);
  for (let d = 0; d < 256; d++) {
    let r = d;
    for (let j = 0; j < 8; j++) {
      r = r & 1 ? (r >>> 1) ^ CRC32_POLY : r >>> 1;
    }
    table[d] = r;
  }
  crc32Table = table;
  return table;
}

function crc32JsInt(data: string): number {
  const table = ensureCrc32Table();
  let c = 0xffffffff;

  // JS mode: charCodeAt & 0xFF for each char
  for (let i = 0; i < data.length; i++) {
    const b = data.charCodeAt(i) & 0xff;
    c = (table[(c & 0xff) ^ b] ^ (c >>> 8)) >>> 0;
  }

  // JS-compatible final XOR: (-1 ^ c ^ 0xEDB88320) >>> 0, then signed
  const u = ((0xffffffff ^ c) ^ CRC32_POLY) >>> 0;
  return u > 0x7fffffff ? u - 0x100000000 : u;
}

// ─── RC4 Encryption ─────────────────────────────────────────────────────────

function rc4Encrypt(key: string, data: string): Buffer {
  const keyBuf = Buffer.from(key, "utf-8");
  const dataBuf = Buffer.from(data, "utf-8");

  // KSA
  const S = new Uint8Array(256);
  for (let i = 0; i < 256; i++) S[i] = i;
  let j = 0;
  for (let i = 0; i < 256; i++) {
    j = (j + S[i] + keyBuf[i % keyBuf.length]) & 0xff;
    [S[i], S[j]] = [S[j], S[i]];
  }

  // PRGA
  const result = Buffer.alloc(dataBuf.length);
  let i2 = 0;
  let j2 = 0;
  for (let k = 0; k < dataBuf.length; k++) {
    i2 = (i2 + 1) & 0xff;
    j2 = (j2 + S[i2]) & 0xff;
    [S[i2], S[j2]] = [S[j2], S[i2]];
    result[k] = dataBuf[k] ^ S[(S[i2] + S[j2]) & 0xff];
  }

  return result;
}

// ─── Fingerprint Generation ─────────────────────────────────────────────────

import { GPU_VENDORS, SCREEN_RESOLUTIONS, FINGERPRINT_DEFAULTS } from "./fingerprint-data.js";

function weightedChoice<T>(options: T[], weights: number[]): T {
  const total = weights.reduce((a, b) => a + b, 0);
  let r = Math.random() * total;
  for (let i = 0; i < options.length; i++) {
    r -= weights[i];
    if (r <= 0) return options[i];
  }
  return options[options.length - 1];
}

function generateFingerprint(cookies: Record<string, string>, userAgent: string, signLocation: string = "https://www.xiaohongshu.com/explore"): Record<string, unknown> {
  const cookieString = Object.entries(cookies)
    .map(([k, v]) => `${k}=${v}`)
    .join("; ");

  const gpuEntry = GPU_VENDORS[Math.floor(Math.random() * GPU_VENDORS.length)];
  const [vendor, renderer] = gpuEntry.split("|");

  const screenRes = weightedChoice(
    SCREEN_RESOLUTIONS.resolutions,
    SCREEN_RESOLUTIONS.weights
  );
  const [widthStr, heightStr] = screenRes.split(";");
  const width = parseInt(widthStr);
  const height = parseInt(heightStr);

  const availWidth = Math.random() > 0.5 ? width - weightedChoice([0, 30, 60, 80], [0.1, 0.4, 0.3, 0.2]) : width;
  const availHeight = Math.random() > 0.5 ? height : height - weightedChoice([30, 60, 80, 100], [0.2, 0.5, 0.2, 0.1]);

  const colorDepth = weightedChoice([16, 24, 30, 32], [0.05, 0.6, 0.05, 0.3]);
  const deviceMemory = weightedChoice([1, 2, 4, 8, 12, 16], [0.1, 0.25, 0.4, 0.2, 0.03, 0.01]);
  const cores = weightedChoice([2, 4, 6, 8, 12, 16, 24, 32], [0.1, 0.4, 0.2, 0.15, 0.08, 0.04, 0.02, 0.01]);

  const webglHash = crypto.createHash("md5").update(crypto.randomBytes(32)).digest("hex");
  const canvasHash = "742cc32c";

  const isIncognito = Math.random() > 0.95 ? "true" : "false";

  const x78y = randomInt(2350, 2450);

  return {
    x1: userAgent,
    x2: "false",
    x3: "zh-CN",
    x4: String(colorDepth),
    x5: String(deviceMemory),
    x6: "24",
    x7: `${vendor},${renderer}`,
    x8: String(cores),
    x9: `${width};${height}`,
    x10: `${availWidth};${availHeight}`,
    x11: "-480",
    x12: "Asia/Shanghai",
    x13: isIncognito,
    x14: isIncognito,
    x15: isIncognito,
    x16: "false",
    x17: "false",
    x18: "un",
    x19: "Win32",
    x20: "",
    x21: FINGERPRINT_DEFAULTS.browserPlugins,
    x22: webglHash,
    x23: "false",
    x24: "false",
    x25: "false",
    x26: "false",
    x27: "false",
    x28: "0,false,false",
    x29: "4,7,8",
    x30: "swf object not loaded",
    x33: "0",
    x34: "0",
    x35: "0",
    x36: String(randomInt(1, 20)),
    x37: "0|0|0|0|0|0|0|0|0|1|0|0|0|0|0|0|0|0|1|0|0|0|0|0",
    x38: "0|0|1|0|1|0|0|0|0|0|1|0|1|0|1|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0",
    x39: 0,
    x40: "0",
    x41: "0",
    x42: "3.4.4",
    x43: canvasHash,
    x44: String(Date.now()),
    x45: "__SEC_CAV__1-1-1-1-1|__SEC_WSA__|",
    x46: "false",
    x47: "1|0|0|0|0|0",
    x48: "",
    x49: "{list:[],type:}",
    x50: "",
    x51: "",
    x52: "",
    x55: "380,380,360,400,380,400,420,380,400,400,360,360,440,420",
    x56: `${vendor}|${renderer}|${webglHash}|35`,
    x57: cookieString,
    x58: "180",
    x59: "2",
    x60: "63",
    x61: "1291",
    x62: "2047",
    x63: "0",
    x64: "0",
    x65: "0",
    x66: {
      referer: "",
      location: signLocation,
      frame: 0,
    },
    x67: "1|0",
    x68: "0",
    x69: "326|1292|30",
    x70: ["location"],
    x71: "true",
    x72: "complete",
    x73: "1191",
    x74: "0|0|0",
    x75: "Google Inc.",
    x76: "true",
    x77: "1|1|1|1|1|1|1|1|1|1",
    x78: {
      x: 0,
      y: x78y,
      left: 0,
      right: 290.828125,
      bottom: x78y + 18,
      height: 18,
      top: x78y,
      width: 290.828125,
      font: FINGERPRINT_DEFAULTS.fonts,
    },
    x82: "_0x17a2|_0x1954",
    x31: "124.04347527516074",
    x79: "144|599565058866",
    x53: crypto.createHash("md5").update(crypto.randomBytes(32)).digest("hex"),
    x54: "10311144241322244122",
    x80: "1|[object FileSystemDirectoryHandle]",
  };
}

function generateB1(fp: Record<string, unknown>): string {
  const b1Fields: Record<string, unknown> = {};
  for (const key of [
    "x33", "x34", "x35", "x36", "x37", "x38", "x39",
    "x42", "x43", "x44", "x45", "x46", "x48", "x49",
    "x50", "x51", "x52", "x82",
  ]) {
    b1Fields[key] = fp[key];
  }

  const b1Json = JSON.stringify(b1Fields);
  const ciphertext = rc4Encrypt(B1_SECRET_KEY, b1Json);

  // URL-encode the ciphertext (latin1), then parse byte values
  const latin1 = ciphertext.toString("latin1");
  const encoded = encodeURIComponent(latin1).replace(
    /[!'()*~._-]/g,
    (c) => c  // keep these chars unencoded like Python's safe param
  );

  // Parse URL-encoded bytes
  const bytes: number[] = [];
  const parts = encoded.split("%").slice(1);
  for (const part of parts) {
    bytes.push(parseInt(part.substring(0, 2), 16));
    for (let i = 2; i < part.length; i++) {
      bytes.push(part.charCodeAt(i));
    }
  }

  return customBase64Encode(Buffer.from(bytes));
}

// ─── Trace ID Generation ────────────────────────────────────────────────────

function generateB3TraceId(): string {
  let id = "";
  for (let i = 0; i < 16; i++) {
    id += HEX_CHARS[Math.floor(Math.random() * 16)];
  }
  return id;
}

function generateXrayTraceId(timestamp?: number): string {
  const ts = timestamp ?? Date.now();
  const seq = Math.floor(Math.random() * 8388607); // 2^23-1
  const part1 = ((BigInt(ts) << 23n) | BigInt(seq))
    .toString(16)
    .padStart(16, "0");
  let part2 = "";
  for (let i = 0; i < 16; i++) {
    part2 += HEX_CHARS[Math.floor(Math.random() * 16)];
  }
  return part1 + part2;
}

// ─── Content String Builder ─────────────────────────────────────────────────

function buildContentString(
  method: "GET" | "POST",
  uri: string,
  payload?: Record<string, unknown>
): string {
  if (method === "POST") {
    if (!payload) return uri;
    return uri + JSON.stringify(payload);
  }
  // GET: URI is already the full path with query params
  return uri;
}

function extractUri(url: string): string {
  try {
    const parsed = new URL(url);
    return parsed.pathname;
  } catch {
    // Already a URI path
    return url.split("?")[0];
  }
}

function buildGetUri(
  uri: string,
  params?: Record<string, string | number | string[]>
): string {
  if (!params || Object.keys(params).length === 0) return uri;
  const parts: string[] = [];
  for (const [key, value] of Object.entries(params)) {
    const strVal = Array.isArray(value) ? value.join(",") : String(value);
    const encoded = strVal.replace(/=/g, "%3D");
    parts.push(`${key}=${encoded}`);
  }
  return `${uri}?${parts.join("&")}`;
}

// ─── Public API ─────────────────────────────────────────────────────────────

export interface SignHeaders {
  "x-s": string;
  "x-s-common": string;
  "x-t": string;
  "x-b3-traceid": string;
  "x-xray-traceid": string;
}

/**
 * Generate all signing headers for a main API (edith.xiaohongshu.com) request.
 */
export function signMainApi(
  method: "GET" | "POST",
  uri: string,
  cookies: Record<string, string>,
  params?: Record<string, string | number | string[]>,
  payload?: Record<string, unknown>,
  timestamp?: number,
  signLocation?: string
): SignHeaders {
  const a1 = cookies.a1;
  if (!a1) throw new Error("Missing 'a1' in cookies");

  const ts = timestamp ?? Date.now() / 1000;
  const tsMs = Math.floor(ts * 1000);

  // Build URI with query params for GET
  const uriPath = extractUri(uri);
  const fullUri = method === "GET" ? buildGetUri(uriPath, params) : uriPath;

  // Build content string for signature
  const contentString = buildContentString(method, fullUri, payload);

  // MD5 hash
  const dValue = crypto
    .createHash("md5")
    .update(contentString, "utf-8")
    .digest("hex");

  // Build payload array and sign
  const payloadArray = buildPayloadArray(dValue, a1, contentString, ts);
  const xorResult = xorTransform(payloadArray);
  const x3Signature = x3Base64Encode(xorResult.slice(0, PAYLOAD_LENGTH));

  // Build x-s
  const signatureData = { ...SIGNATURE_DATA_TEMPLATE };
  signatureData.x3 = X3_PREFIX + x3Signature;
  const signatureJson = JSON.stringify(signatureData);
  const xs = XYS_PREFIX + customBase64Encode(signatureJson);

  // Build x-s-common
  const fingerprint = generateFingerprint(cookies, USER_AGENT, signLocation);
  const b1 = generateB1(fingerprint);
  const x9 = crc32JsInt(b1);
  const xsCommonStruct = { ...XSCOMMON_TEMPLATE, x5: a1, x8: b1, x9 };
  const xsCommonJson = JSON.stringify(xsCommonStruct);
  const xsCommon = customBase64Encode(xsCommonJson);

  return {
    "x-s": xs,
    "x-s-common": xsCommon,
    "x-t": String(tsMs),
    "x-b3-traceid": generateB3TraceId(),
    "x-xray-traceid": generateXrayTraceId(tsMs),
  };
}

export { USER_AGENT, extractUri, buildGetUri };
