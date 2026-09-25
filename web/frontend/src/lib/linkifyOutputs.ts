import { mediaUrl } from './api';

/**
 * 对话正文里的「产物路径」→ 前端可用链接（渲染前纯文本变换，不改存储的消息）。
 *
 * 背景：agent 回复里习惯写 `outputs/<项目>/...` 的后端相对路径，偶尔还带
 * `D:\...\outputs\...` 这类绝对路径，纯文本透传给用户 —— 不能点、图不内联，
 * 也暴露了后端存储布局。
 *
 * 规则：
 * - 图片          → markdown 内联图（/api/media 直出，卡图直接显示在对话里）
 * - 其他文件      → 可点击链接（/api/media 直开/下载，新标签页）
 * - 目录          → `#/outputs/<路径>` 锚点，由 App 监听 hashchange 跳内容库对应层级
 * - 绝对路径      → 先归一成 outputs/ 相对路径再分类（盘符 / ~ / POSIX 前缀都收敛掉）
 * - 围栏代码块 / 已有 markdown 链接 → 一律不动（防破坏命令示例，保证幂等）
 * - 行内代码      → agent 习惯把路径包在反引号里；仅当整个 code span 就是一个
 *                   产物路径时转为链接，路径嵌在命令中（如 `py x.py --output outputs/`）则不动
 */

const IMG_RE = /\.(png|jpe?g|gif|webp|svg|avif|bmp|ico)$/i;

/** 路径尾随的标点（顿号/句号等）不属于路径本身，匹配后剥掉 */
const TRAILING = /[.,;:!~～、，。；：！？]+$/;

/** 绝对路径前缀：盘符 / ~ / POSIX 路径，后面任意层级接到 outputs 分隔符为止。
 *  lookbehind 排除字母数字:.\/ —— 防 `https://host/outputs/` 这类 URL 被误伤。 */
const ABS_PREFIX = /(?<![A-Za-z0-9:.\/])(?:[A-Za-z]:[\\/]|~|\/)(?:[^\s`|~～<>"'“”‘’，。；：！？、（）【】《》「」]*?[\\/])?outputs[\\/]/g;

/** outputs/ 之后允许出现在路径里的字符：排除空白、反引号、ASCII 竖线/波浪/括号引号、
 *  常见中西文标点（它们常紧跟路径出现，如「outputs/a.png，共 7 张」里的逗号）。
 *  注意必须放行全角竖线 ｜ 和反斜杠 —— 项目目录名与 Windows 相对路径会用到。 */
const REST = '[^\\s`|~～<>"\'“”‘’()\\[\\]{}:,;，。；：！？、（）【】《》「」]';
const OUT_RE = new RegExp(`outputs\\/(?:${REST})+`, 'g');

/** 受保护区：围栏代码块、行内代码、已有的 markdown 链接 —— 原样保留 */
const PROTECT = /(```[\s\S]*?```|`[^`\n]*`|\[[^\]]*\]\([^)\n]*\))/g;

function toMediaUrl(outputsPath: string): string {
  const rel = outputsPath.replace(/^outputs\//, '');
  return mediaUrl(rel);
}

function toJumpUrl(outputsPath: string): string {
  const rel = outputsPath.replace(/^outputs\//, '').replace(/\/+$/, '');
  return `#/outputs/${rel.split('/').map(encodeURIComponent).join('/')}`;
}

/** 单个 outputs 路径 token → markdown 链接 / 内联图。
 *  面向用户的文案用产品词汇：目录是「内容库 › 相对位置」，文件只显示文件名，
 *  `outputs/` 这类后端存储术语不再出现在界面上。 */
function renderPath(token: string): string {
  const t = token.replace(/\\/g, '/').replace(TRAILING, '');
  if (t === 'outputs/' || t === 'outputs') return token;
  // 目录：显式尾斜杠，或末段没有「.扩展名」
  const isDir = t.endsWith('/') || !/\/[^/]+\.[A-Za-z0-9]{1,8}$/.test(t);
  if (isDir) {
    const rel = t.replace(/^outputs\//, '').replace(/\/+$/, '');
    if (!rel) return token;
    return `[内容库 › ${rel}](${toJumpUrl(t)})`;
  }
  const name = t.slice(t.lastIndexOf('/') + 1);
  if (IMG_RE.test(t)) return `![${name}](${toMediaUrl(t)})`;
  return `[${name}](${toMediaUrl(t)})`;
}

function transformSegment(seg: string): string {
  if (!seg.includes('outputs')) return seg;   // 快速路径
  let s = seg.replace(ABS_PREFIX, 'outputs/');
  s = s.replace(/outputs[\\/]/g, 'outputs/'); // 相对路径里的反斜杠分隔符
  return s.replace(OUT_RE, renderPath);
}

/** 整体恰好是一个产物路径（用于判定行内代码能否安全转链） */
const WHOLE_PATH_RE = new RegExp(`^outputs\\/(?:${REST})+$`);
function asWholePath(codeSpan: string): string | null {
  const inner = codeSpan.slice(1, -1).trim();
  if (!inner.includes('outputs')) return null;
  let t = inner.replace(ABS_PREFIX, 'outputs/');
  t = t.replace(/outputs[\\/]/, 'outputs/');
  return WHOLE_PATH_RE.test(t) ? t : null;
}

/** 入口：整段 markdown 先按受保护区切开；普通文本段做变换，
 *  行内代码仅在「整体就是产物路径」时整体替换为链接。 */
export function linkifyOutputs(md: string): string {
  if (!md || !md.includes('outputs')) return md;
  return md
    .split(PROTECT)
    .map((seg, i) => {
      if (i % 2 === 0) return transformSegment(seg);
      if (seg.length > 2 && seg.startsWith('`') && !seg.startsWith('```')) {
        const whole = asWholePath(seg);
        if (whole) return renderPath(whole);
      }
      return seg;
    })
    .join('');
}

/** 渲染后的 HTML 里，把指向 /api/media 的链接改为新标签打开（点文件不离开工作台）。 */
export function externalizeMediaLinks(html: string): string {
  return html.replace(
    /<a href="([^"]*\/api\/media\/[^"]*)"/g,
    '<a href="$1" target="_blank" rel="noreferrer"',
  );
}
