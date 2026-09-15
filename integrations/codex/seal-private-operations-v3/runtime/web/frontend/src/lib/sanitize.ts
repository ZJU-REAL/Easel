import { marked } from 'marked';
import DOMPurify from 'dompurify';

marked.setOptions({ breaks: true, gfm: true });

/** 把 markdown 渲染成【已消毒】的 HTML。所有 dangerouslySetInnerHTML 都应走这里，防 XSS。 */
export function renderMarkdown(md: string): string {
  if (!md) return '';
  const raw = marked.parse(md) as string;
  return DOMPurify.sanitize(raw);
}
