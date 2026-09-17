#!/usr/bin/env python3
"""[scenes 规划 JSON] → [scenesData.ts] 生成器。

把分场规划（人工/脚本产出）编译成片子工程直接 import 的字幕数据模块。
输入 schema:
{
  "fps": 30, "duration": 110.443, "frames": 3313,
  "scenes": [
    {"id": 1, "start": 0.0, "end": 7.26, "text": "...", "state": "B",
     "kind": "hookyear", "accent": "#22d3ee", "material": null,
     "words": [{"w": "但是", "s": 0.0, "e": 0.54}]}
  ]
}
（words 来自 whisper 词级转录，经修正后落进来；修正做法见 PITFALLS.md「转录与字幕」。）

用法: python build_scenes_data.py --scenes scenes_v2.json --out src/damo/scenesData.ts
"""
import argparse
import json
import os

KEEP = ('id', 'start', 'end', 'text', 'state', 'kind', 'accent', 'material', 'words')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scenes', required=True, help='scenes 规划 JSON')
    ap.add_argument('--out', required=True, help='输出 .ts 路径')
    args = ap.parse_args()

    d = json.load(open(args.scenes, encoding='utf-8'))
    scenes = [{k: s.get(k) for k in KEEP} for s in d['scenes']]

    lines = [
        '// 自动生成：改 scenes 规划 JSON 后重跑 tools/build_scenes_data.py 再生成，请勿手改',
        'export type Word = { w: string; s: number; e: number };',
        "export type FilmScene = { id: number; start: number; end: number; text: string; state: 'A'|'B'; kind: string; accent: string; material: string|null; words: Word[] };",
        f"export const FILM_DURATION = {d['duration']};",
        f"export const FILM_FRAMES = {d['frames']};",
        'export const SCENES: FilmScene[] = ' + json.dumps(scenes, ensure_ascii=False) + ';',
    ]
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print(f'WROTE {args.out}: {len(scenes)} scenes')


if __name__ == '__main__':
    main()
