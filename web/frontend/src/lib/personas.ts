import type { PersonaItem } from './api';

/** A failed or malformed response must never be mistaken for an empty catalog. */
export function parsePersonas(value: unknown): PersonaItem[] {
  if (!Array.isArray(value) || value.some((item) => !item || typeof item !== 'object'
    || typeof item.name !== 'string' || !item.name.trim() || item.name.startsWith('.')
    || item.name.startsWith('_') || /[/\\:]/.test(item.name)
    || Array.from(item.name as string).some((character) => character.charCodeAt(0) < 32)
    || typeof item.description !== 'string')
    || new Set(value.map((item) => item.name)).size !== value.length) {
    throw new Error('画像列表响应格式无效，请重试。');
  }
  return value;
}

/** Resolve the current identity without rewriting historical session metadata. */
export function availablePersona(name: string | undefined, catalog: PersonaItem[] | null): string {
  if (!name) return '';
  return catalog === null || catalog.some((item) => item.name === name) ? name : '';
}
