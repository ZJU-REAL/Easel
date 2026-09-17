# 前置依赖清单（DEPS）

> 2026-09-16 · 本机已验证版本为准；Linux 分支待补（Easel 部署时再对）

## 运行时依赖

| 依赖 | 版本（已验） | 说明 |
|------|-------------|------|
| Node.js | 24.x | rm 运行时 |
| **Remotion（rm）** | **4.0.503（精确锁）** | 依赖蓝本在 `deps/remotion/`（package.json + package-lock.json）；`npm ci` 一条命令还原全部依赖（含 @remotion/transitions、light-leaks、remotion-bits、culori、three 等） |
| Chrome Headless Shell | 随 remotion 版本 | 首次运行自动下载；离线场景从已有工程 `node_modules/.remotion/` 拷贝 |
| ffmpeg | 8.1 full build | 必须含滤镜：`lut3d / curves / eq / colorbalance / hqdn3d / nlmeans / unsharp / volumedetect / loudnorm` |
| Python | 3.11 | 工具与门脚本 |
| faster-whisper + ctranslate2 | 已装 | GPU 转录（CUDA） |
| Whisper large-v3 模型 | 3.09GB | 模型目录自备（**不入包**；下载脚本 `tools/fetch_whisper_model.py`，hf-mirror 直拉） |
| CUDA GPU | RTX 3060（本机） | 转录/渲染加速；无 GPU 时转录退 CPU（慢） |

## 包内自带

- Remotion 依赖蓝本（精确锁）、效果件源码、卡片系统、字体（3）、胶片 LUT（4）、现成音效（10 枚）、素材台账

## 安装

```powershell
# Windows（本机）
powershell -ExecutionPolicy Bypass -File deps/bootstrap.ps1
```

## 待办

- [ ] Linux 分支脚本（Easel 部署用）：apt 装 nodejs/ffmpeg/python3；`--gl=angle` 视环境切换
- [ ] chrome-headless-shell 离线携带策略
- [x] whisper 模型下载脚本入 tools（`tools/fetch_whisper_model.py`，hf-mirror 直拉）
