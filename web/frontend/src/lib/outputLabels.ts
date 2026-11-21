import type { OutputNode } from './api';

export function fileLabel(file: OutputNode) {
  if (file.kind === 'text') return /\.html?$/i.test(file.name) ? '网页' : '文档';
  return ({ image: '图片', video: '视频', audio: '音频', binary: '文件' } as const)[file.kind || 'binary'];
}

export function sizeLabel(bytes?: number) {
  if (bytes === undefined) return '';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return Math.round(bytes / 102.4) / 10 + ' KB';
  return Math.round(bytes / 1024 / 102.4) / 10 + ' MB';
}
