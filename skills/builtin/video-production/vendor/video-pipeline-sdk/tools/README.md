# 工具脚本（tools/）

> 配方参考型工具：路径/参数按本机工程调整（脚本内为 Windows 显式盘符写法）。
> 单入口通用化（run.py）在 roadmap 上。

## 音画同步（交付门）

| 脚本 | 用途 | 速记 |
|------|------|------|
| `check_sync.py` | 互相关测音频偏移（ms 级） | `python check_sync.py --ref ref.wav --test out.mp4 --windows 8-14,30-36` |

## 转录与字幕数据

| 脚本 | 用途 | 速记 |
|------|------|------|
| `transcribe.py` | faster-whisper 词级转录 → JSON | `python transcribe.py --src proxy.mp4 --out transcript.json` |
| `build_scenes_data.py` | scenes 规划 JSON → scenesData.ts | `python build_scenes_data.py --scenes scenes_v2.json --out src/damo/scenesData.ts` |
| `fetch_whisper_model.py` | large-v3 模型下载（hf-mirror） | `python fetch_whisper_model.py` |

## 素材

| 脚本 | 用途 | 速记 |
|------|------|------|
| `transcode_material.py` | 素材批量转码 1080p30（`-g 30`） | `python transcode_material.py --src-dir raw --out-dir pub/mat a.mp4=mat_a` |
| `transcode_stock.py` | （早期版）素材统一转码配方 | 同上 |
| `fetch_mixkit*.py` / `parse_mixkit*.py` | Mixkit 视频抓取/解析链（迭代三版） | 改 slug 后按序跑 |
| `fetch_stock*.py` | 按 id 下载 + 降级链 + 校验 | — |
| `fetch_sfx.py` | Mixkit 音效抓取（10 枚起点） | `python fetch_sfx.py` |
| `fx5_frames.py` | 素材抽帧核验表（台词列对照） | 改 items 后运行 |

## 调色

| 脚本 | 用途 | 速记 |
|------|------|------|
| `grade_demo.py` | 降噪 → LUT → blend 控强度 → 对比表 | LUT 放 `../assets/luts/` |

## 运维

| 脚本 | 用途 | 速记 |
|------|------|------|
| `clean_remotion_temp.ps1` | 清 Remotion 在系统 Temp 的残留拷贝 | `powershell -File clean_remotion_temp.ps1` |
