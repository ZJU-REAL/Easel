#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""drama_ops.py — AI 短剧的确定性资产/编排管理（纯标准库）。

短剧的**创意**（剧集策划/剧本/分镜 prompt）交给 LLM；生成动作（生图/生视频/配音）
委派给 ai-image-gen / ai-video-gen / tts-voiceover 等已有 SKILL。本脚本只做**确定性 IO**：
搭剧集目录、维护角色/场景/道具参考图索引（跨镜跨集一致性的骨架）、校验分镜 JSON、
把逐镜生成的片段拼成 assemble.py 可吃的 storyboard、跟踪多集生成进度（控费）。

子命令：
    scaffold    搭一部剧的目录骨架 + series-bible 模板
    ref add     登记一张参考图到 ref_index.json（自动分配 C/S/P 编号）
    ref list    列出参考图索引
    ref review  记录对定妆图的肉眼视觉复核（看到的形象+是否符合设定；generate 前必做）
    shots validate  校验某集 shots.json 结构（镜头/引用/时长）
    generate    逐镜图生视频：脚本读每镜 generation_prompt 自己调 ai_video.py（强制喂台词、幂等控费）
    storyboard  把某集 shots.json（已填 clip 路径）转成 assemble.py 的 storyboard.json
    progress    登记/查看逐集生成进度（planned/done）
    selftest    自检

用法举例：
    drama_ops.py scaffold --series "逆袭甜妻"
    drama_ops.py ref add --series "逆袭甜妻" --kind character --name 林策 --image refs/lin.png --desc "男主，冷峻" --style "都市港风"
    drama_ops.py ref list --series "逆袭甜妻"
    drama_ops.py shots validate --series "逆袭甜妻" --episode 1
    drama_ops.py storyboard --series "逆袭甜妻" --episode 1 -o outputs/逆袭甜妻/episodes/ep01/storyboard.json
    drama_ops.py progress record --series "逆袭甜妻" --episode 1 --shot 3 --status done
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared" / "scripts"))
import ai_video  # noqa: E402

DEFAULT_ROOT = "outputs"
_KIND_PREFIX = {"character": "C", "scene": "S", "prop": "P"}

_SERIES_BIBLE = """# 剧集圣经（series bible）

> 据题材填满。**深度字段（行动模型/可跟随四问/反派阶梯…）不是可选项**——照 `series-bible-schema.md`
> 填，写完过 `drama-review-rubric.md` 的 A（故事引擎）+ B（人物可跟随）门。只写「年龄外貌性格」不合格。

## 1. 一句话卖点
> 谁 + 遇到什么 + 有多爽/多虐/多反转。先读 `genre-hooks-handbook.md` 定题材 + 核心爽点。

## 1.5 核心矛盾（一句话）
> 全剧单一主冲突：谁和谁、为了什么、对抗到底。

## 1.6 戏剧承诺（写角色/剧情前先过 A 门）
> 当【主角】用【惯常策略】追求【当前目标】时，【对抗机制】迫使其付出【核心代价】；
> 系列反复兑现【观众回报】，直到【终止性转变】发生。
> — 过 `story-engine.md` 承诺自检（swap-test / 阻力有筹码 / 主角能动性 / 中段有回报）。

## 2. 世界观 / 设定
> 时代/场景/规则/金手指。竖屏微短剧要极简。

## 3. 角色表（外貌一致性 + 人物深度，逐角色一节）

### C0X <姓名>
- **外貌关键词**（喂参考图 prompt）：年龄/发型/脸型/服装/气质，越具体越稳
- **行动模型（8 字段，治扁平）**：表层目标 / 保护对象 / 自我解释 / 惯常策略 / 筹码 / 盲区 / 底线与越线 / 可变事实
- **want / need / wound / flaw**：外在目标 vs 内在需要 + 创伤与错误信念 + 缺陷
- **弧光**：从头到尾变化了什么（主角必填）
- **可跟随四问**：ep1 内可见地答出其一（承受的具体不公 / 替谁扛 / 共同渴望 / 想借的本事）
- **关系（双向）**：A 需要 B 什么 / 怕 B 看见什么 / 用什么约束 B（反向亦然）
- **voice sheet**：词汇/口头禅/句长/语气/回避词（保台词过 swap-test）
- **音色档案**：性别 · 年龄段 · 气质 · 身份 · 语速（喂选角，具体到能选出唯一音色，别只写「男声」）

## 4. 剧情主线
> 起点 → 主要矛盾 → 高潮 → 结局。单线清晰，忌多线。

## 4.5 情绪曲线 & 爽点节奏表
> 情绪曲线：憋屈→释放→甜→揪心→大爽，别一路平/一路爽。

| 集 | 主爆点（爽/虐点）| 情绪 |
|---|---|---|
| 1 | | |

## 4.6 反派阶梯（治工具人 / 爽点通胀，见 `satisfaction-and-villain.md`）

| 层 | 角色 | 出场 | 筹码 / 威胁 | 三段式安排 |
|---|---|---|---|---|
| 小反派 | | 前15% | | 速败退场 |
| 中反派 | | 15–45% | | 小胜→受挫→翻盘 |
| 大反派 | | ~45%+ | | 高潮对决 |

## 5. 分集大纲（每集必有：一个反转点 + 一个集末钩子；集间因果咬合）
| 集 | 剧情（一句话）| 本集反转点 | 集末钩子 cliffhanger |
|---|---|---|---|
| 1 | 建立人物 + 抛核心冲突 | | 让人必须看下一集的悬念 |

## 6. 统一视觉风格前缀（一致性关键，抄进每个 shots.json 的 style_prefix）
> 风格 + 画幅(9:16竖屏) + 色调，如「都市港风，9:16竖屏，冷色调，电影质感，浅景深」。
"""


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _series_dir(root: str, series: str) -> Path:
    if not series.strip():
        _die("--series 剧名不能为空")
    return (Path(root).expanduser() / series).resolve()


def _ep_dir(base: Path, episode: int) -> Path:
    return base / "episodes" / f"ep{episode:02d}"


def _load_json(p: Path, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def _write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


# ── scaffold ──────────────────────────────────────────────────────────
def scaffold(root: str, series: str) -> dict:
    base = _series_dir(root, series)
    for sub in ("refs", "episodes"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    created = []
    bible = base / "series-bible.md"
    if not bible.exists():
        bible.write_text(_SERIES_BIBLE, encoding="utf-8")
        created.append("series-bible.md")
    ri = base / "ref_index.json"
    if not ri.exists():
        _write_json(ri, {"series": series, "refs": []})
        created.append("ref_index.json")
    return {"base": str(base), "created": created}


# ── ref index ─────────────────────────────────────────────────────────
def ref_add(root: str, series: str, kind: str, name: str,
            image: str, desc: str, style: str) -> dict:
    base = _series_dir(root, series)
    if not base.exists():
        _die(f"剧目录不存在，请先 scaffold：{base}")
    if kind not in _KIND_PREFIX:
        _die(f"--kind 只能是 {list(_KIND_PREFIX)}")
    ri = base / "ref_index.json"
    data = _load_json(ri, {"series": series, "refs": []})
    prefix = _KIND_PREFIX[kind]
    existing = [r for r in data["refs"] if r["code"].startswith(prefix)]
    code = f"{prefix}{len(existing) + 1:02d}"
    entry = {"code": code, "kind": kind, "name": name,
             "desc": desc, "image": image, "style": style}
    data["refs"].append(entry)
    _write_json(ri, data)
    return entry


def ref_list(root: str, series: str) -> list:
    base = _series_dir(root, series)
    return _load_json(base / "ref_index.json", {"refs": []}).get("refs", [])


def ref_review(root: str, series: str, code: str, observation: str,
               matches: bool = True) -> dict:
    """记录对某参考图的**肉眼视觉复核**：你实际看到的形象 + 是否符合设定。
    观察写不出=没真看图。generate 会拦「角色定妆图未复核」，逼先看再往下。"""
    obs = (observation or "").strip()
    if len(obs) < 6:
        _die("--observation 太短：请写你**实际看到**的形象（发型/年龄/服装/气质…）并判断是否符合设定，"
             "别敷衍——这是防止不看图就往下走。")
    base = _series_dir(root, series)
    ri = base / "ref_index.json"
    data = _load_json(ri, {"series": series, "refs": []})
    hit = next((r for r in data["refs"] if r.get("code") == code), None)
    if not hit:
        _die(f"参考图 {code} 不在索引里（先 ref add 登记）。已登记：{[r.get('code') for r in data['refs']]}")
    hit["reviewed"] = True
    hit["review_observation"] = obs
    hit["review_matches"] = bool(matches)
    _write_json(ri, data)
    return hit


def _unreviewed_character_refs(root: str, series: str, shots: list) -> list[str]:
    """本集 shots 引用到的**角色定妆图**里，还没肉眼复核（或复核判不符）的 code。"""
    refs = {r.get("code"): r for r in ref_list(root, series)}
    used = {c for sh in shots for c in (sh.get("refs") or [])}
    bad = []
    for code in sorted(used):
        r = refs.get(code)
        if r and r.get("kind") == "character" and not (r.get("reviewed") and r.get("review_matches")):
            bad.append(code)
    return bad


# ── shots 校验 ────────────────────────────────────────────────────────
def _norm_line(s: str) -> str:
    """粗归一（去标点/空格、繁→简、小写）用于判断 generation_prompt 是否已含台词。"""
    s = s or ""
    try:
        import zhconv
        s = zhconv.convert(s, "zh-cn")
    except Exception:  # noqa: BLE001
        pass
    return "".join(ch for ch in s.lower() if ch.isalnum())


def validate_shots(shots: dict, known_codes: set[str] | None = None,
                   dialogue_texts: dict | None = None) -> list[str]:
    """校验某集 shots 结构，返回问题清单（空=通过）。纯函数，供测试。
    dialogue_texts（{idx: 台词}）非空时启用**生视频前硬门**：有台词的镜必须已由 `prepare`
    写入 generation_prompt 且其中含该台词——否则生视频时模型不知道要说什么、台词全对不上。"""
    problems: list[str] = []
    if "episode" not in shots:
        problems.append("缺 episode 字段")
    lst = shots.get("shots")
    if not isinstance(lst, list) or not lst:
        problems.append("shots 为空或非列表")
        return problems
    if not shots.get("style_prefix"):
        problems.append("缺 style_prefix（统一风格前缀，保画面一致）")
    idxs = []
    for i, sh in enumerate(lst):
        tag = f"镜头[{i}]"
        if "idx" not in sh:
            problems.append(f"{tag} 缺 idx")
        else:
            idxs.append(sh["idx"])
        if not sh.get("prompt") and not sh.get("desc"):
            problems.append(f"{tag} 缺 prompt/desc")
        refs = sh.get("refs", [])
        if not refs:
            problems.append(f"{tag} 未引用任何参考图（refs 空，角色/场景一致性无保障）")
        elif known_codes is not None:
            for c in refs:
                if c not in known_codes:
                    problems.append(f"{tag} 引用了未登记的参考 {c}")
    if idxs and sorted(idxs) != list(range(min(idxs), max(idxs) + 1)):
        problems.append(f"镜头 idx 不连续：{sorted(idxs)}")
    if dialogue_texts:
        by_idx = {sh.get("idx"): sh for sh in lst}
        for idx, texts in dialogue_texts.items():
            sh = by_idx.get(idx)
            if sh is None:
                continue
            # 一镜可多句：texts 为该镜逐句列表（兼容旧的单串）。逐句校验，别拼接后当整串找子串——
            # native-first 的 gp 里各句之间夹着「角色X逐字说」等文本，拼接串不是连续子串会误判。
            texts = [texts] if isinstance(texts, str) else list(texts)
            gp = sh.get("generation_prompt") or ""
            if not gp:
                problems.append(f"镜{idx} 有台词但没 generation_prompt——**没跑 dubbing.py prepare**；"
                                "直接拿 prompt(只有画面、没台词)生视频，模型不会说台词、台词必对不上。先跑 prepare。")
                continue
            # native-first 契约会把每句台词逐字写进 gp；dub-reserve 契约不含台词（合法）。
            if "逐字" in gp or "native-first" in gp or "逐字说" in gp:
                gpn = _norm_line(gp)
                for text in texts:
                    if _norm_line(text) and _norm_line(text) not in gpn:
                        problems.append(f"镜{idx} 的 generation_prompt 声称逐字却未含台词「{text}」——可能改了 lines 没重跑 prepare。")
    return problems


def cmd_shots_validate(root: str, series: str, episode: int, pre_video: bool = False) -> int:
    base = _series_dir(root, series)
    sp = _ep_dir(base, episode) / "shots.json"
    if not sp.exists():
        _die(f"未找到 {sp}（先写好本集分镜 shots.json）")
    shots = _load_json(sp, {})
    known = {r["code"] for r in ref_list(root, series)}
    dialogue_texts = None
    if pre_video:
        # 生视频前硬门：核对有台词的镜是否已由 prepare 写好含台词的 generation_prompt
        lines = _load_json(_ep_dir(base, episode) / "lines.json", {}).get("lines", [])
        dialogue_texts = {}
        for ln in lines:
            idx = ln.get("shot")
            if idx is not None and ln.get("speaker") and ln.get("speaker") != "旁白":
                dialogue_texts.setdefault(idx, []).append(str(ln.get("text") or ""))
    problems = validate_shots(shots, known, dialogue_texts)
    if problems:
        print(f"⚠️ 第 {episode} 集分镜有 {len(problems)} 个问题：")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"✅ 第 {episode} 集分镜校验通过（{len(shots['shots'])} 个镜头）")
    return 0


# ── 脚本驱动逐镜生视频（把 generation_prompt 强制喂给视频模型）────────────
def _resolve_media(rel: str | None, ep: Path, base: Path) -> Path | None:
    """按 原样(CWD)→ episode 目录 → series 目录 找文件；找不到返回 None。"""
    if not rel:
        return None
    for cand in (Path(rel), ep / rel, base / rel):
        if cand.is_file():
            return cand
    return None


def cmd_generate(root: str, series: str, episode: int, only: list[int] | None,
                 force: bool, provider: str | None, model: str | None,
                 ratio: str, dry_run: bool) -> int:
    """逐镜图生视频——**脚本读每镜 generation_prompt 自己调 ai_video.py**，把台词契约强制
    喂给视频模型，agent 无从传成「只有画面的 prompt」（治反复出现的「没喂台词→全 dub→直接 TTS」）。

    先过生视频前硬门（有台词的镜必须已由 dubbing.py prepare 写好含台词的 generation_prompt），
    再逐镜生成；已有 clip 的镜跳过（幂等控费），失败镜记 progress=failed 不影响其它镜。"""
    base = _series_dir(root, series)
    ep = _ep_dir(base, episode)
    sp = ep / "shots.json"
    if not sp.exists():
        _die(f"未找到 {sp}（先写好本集分镜 shots.json）")
    shots_data = _load_json(sp, {})
    shots = shots_data.get("shots", [])
    if not shots:
        _die("shots 为空")
    locked = shots_data.get("video_generation") or {}
    locked_provider = str(locked.get("provider") or "").strip() or None
    locked_model = str(locked.get("model") or "").strip() or None
    if provider and locked_provider and provider != locked_provider:
        _die(f"视频 provider 与 prepare 锁定值冲突：prepare={locked_provider}，generate={provider}。"
             "请使用同一 provider，或带新 provider 重新跑 dubbing.py prepare。")
    provider = provider or locked_provider
    try:
        provider = ai_video.resolve_provider(provider)
        resolved_model = ai_video.resolve_model(provider, model or locked_model, image=True)
    except SystemExit:
        _die("未指定视频 provider。请在 Web 配置 VIDEO_PROVIDER，或 prepare/generate 都传 --provider。")
    if model and locked_model and model != locked_model:
        _die(f"视频 model 与 prepare 锁定值冲突：prepare={locked_model}，generate={model}。"
             "请使用同一模型，或带新模型重新跑 dubbing.py prepare。")
    if locked_provider and (provider != locked_provider or resolved_model != (locked_model or resolved_model)):
        _die("当前视频 provider/model 与 prepare 阶段不一致，请重新跑 dubbing.py prepare 后再生成。")
    model = resolved_model
    # 硬门：生视频前必须先 prepare（有台词的镜要有含台词的 generation_prompt）。复用 validate_shots。
    lines = _load_json(ep / "lines.json", {}).get("lines", [])
    dialogue_texts: dict = {}
    for ln in lines:
        idx = ln.get("shot")
        if idx is not None and ln.get("speaker") and ln.get("speaker") != "旁白":
            dialogue_texts.setdefault(idx, []).append(str(ln.get("text") or ""))
    known = {r["code"] for r in ref_list(root, series)}
    problems = validate_shots(shots_data, known, dialogue_texts or None)
    if problems:
        _die("生视频前硬门未过——先跑 `dubbing.py prepare`（把台词写进 generation_prompt）"
             "或修分镜，再来 generate：\n  - " + "\n  - ".join(problems))
    # 硬门：生视频前必须**肉眼复核角色定妆图**（做完图别跳过看视觉形象就往下）。
    # 每个被引用的角色定妆图要用 `ref review` 记录「实际看到的形象 + 是否符合设定」，写不出=没真看。
    unreviewed = _unreviewed_character_refs(root, series, shots)
    if unreviewed:
        _die(f"这些角色定妆图还没肉眼复核（或复核判不符）：{unreviewed}。\n"
             f"做完定妆图必须**看图确认形象符合设定**再生视频——别跳过视觉验证。逐个记录：\n"
             f"  drama_ops.py ref review --series \"{series}\" --code C0X --observation \"看到的：<发型/年龄/服装/气质>，符合<角色>设定\"\n"
             f"（形象不符就重生成定妆图再复核，别拿跑偏的形象往下生视频。）")
    only_set = set(only) if only else None
    ai_video_script = Path(__file__).resolve().parents[3] / "shared" / "scripts" / "ai_video.py"
    if not ai_video_script.is_file():
        _die(f"找不到 ai_video.py：{ai_video_script}")
    # 组装计划（跳过已有 clip 的镜，除非 --force / --only 指定）
    plan: list[tuple] = []
    for s in shots:
        idx = s.get("idx")
        if only_set is not None and idx not in only_set:
            continue
        if s.get("clip") and _resolve_media(s.get("clip"), ep, base) and not force:
            continue
        frame = _resolve_media(s.get("frame"), ep, base)
        if not frame:
            _die(f"镜{idx} 没有可用首帧图(frame)——先按步骤15用 ai-image-gen 生成首帧、写回 shots.json 的 frame。")
        prompt = (s.get("generation_prompt") or s.get("prompt") or s.get("desc") or "").strip()
        if not prompt:
            _die(f"镜{idx} 没有 generation_prompt/prompt——无法生视频。")
        plan.append((idx, s, frame, prompt))
    if not plan:
        print("✅ 无需生成（目标镜都已有片段；--force 可强制重生成）")
        return 0
    # 控费：先报计划（多镜 × 生视频按量计费）
    print(f"# 第{episode}集 生视频计划：{len(plan)} 镜 → {provider}:{model or '默认'}（按量计费）")
    for idx, s, frame, _ in plan:
        d = s.get("gen_duration") or s.get("target_duration")
        tag = "含台词契约" if s.get("generation_prompt") else "⚠️仅画面(未 prepare?)"
        print(f"  镜{idx}: 首帧={frame.name} 档={d or '默认'}s prompt={tag}")
    if dry_run:
        print("（--dry-run：仅列计划，未生成）")
        return 0
    failed: list = []
    for idx, s, frame, prompt in plan:
        clip_out = ep / "shots" / f"clip_{idx:02d}.mp4"
        clip_out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, str(ai_video_script), "image2video", "--image", str(frame),
               "--prompt", prompt, "--audio", "auto", "--ratio", ratio, "-o", str(clip_out)]
        d = s.get("gen_duration") or s.get("target_duration")
        if d:
            cmd += ["--duration", str(int(float(d)))]
        if provider:
            cmd += ["--provider", provider]
        if model:
            cmd += ["--model", model]
        print(f"▶ 镜{idx} 生视频…")
        r = subprocess.run(cmd)
        if r.returncode == 0 and clip_out.is_file() and clip_out.stat().st_size > 0:
            s["clip"] = str(clip_out.resolve())   # 绝对路径：align/storyboard/assemble 各 CWD 都能解析
            _write_json(sp, shots_data)            # 每镜写回，断点续跑
            progress_record(root, series, episode, idx, "done")
            print(f"✅ 镜{idx} → {clip_out}")
        else:
            failed.append(idx)
            progress_record(root, series, episode, idx, "failed")
            print(f"❌ 镜{idx} 生视频失败（见上）", file=sys.stderr)
    if failed:
        _die(f"以下镜生视频失败：{failed}。修复后重跑（已成功的镜会自动跳过）。")
    print(f"✅ 第{episode}集 {len(plan)} 镜生视频完成，clip 已写回 shots.json；"
          f"下一步 dubbing.py audit → align。")
    return 0


# ── storyboard（转 assemble.py 输入）──────────────────────────────────
def build_storyboard(shots: dict, size: str = "1080x1920",
                     narration: str | None = None, bgm: str | None = None,
                     subtitle: str | None = None, pad_mode: str = "trim",
                     audit: dict | None = None) -> dict:
    """把某集 shots（已填 clip/frame 路径）转成 assemble.py 的 storyboard。纯函数。

    pad_mode 默认 "trim"（自然）：片段够长裁到需要、短则只冻结尾巴，**绝不慢放/循环**——
    每镜画面 = 完整片段（align 已把片段实测时长写回 duration），台词只占其中一段，自然播放。

    另外汇总每镜的定时音效 `sh["sfx"]`=[{file, at(镜内秒), volume}]，按镜头累计起点换算成
    **全局 at** 收进 board["sfx"]，供 assemble 在成片音轨上定点叠入（枪声/椅子/脚步等占非台词时间）。
    """
    out_shots = []
    audit_by_shot = {x.get("shot"): x for x in (audit or {}).get("shots", [])}
    sfx_global: list[dict] = []
    cum_start = 0.0   # 已累计到当前镜的全局起点（= 前面各镜 duration 之和）
    for sh in shots.get("shots", []):
        item = {"caption": sh.get("caption", "")}
        if sh.get("clip"):
            item["video"] = sh["clip"]
            verdict = audit_by_shot.get(sh.get("idx"), {})
            # native = 整轨原音（模型原声+环境音）直通、优先用模型原声；dub = 换独立 TTS 配音，
            # **该镜原生轨在 assemble 里整轨丢弃**（无人声分离时保留会与配音双重人声）。
            # regenerate 镜应先重生成拿好原声再来；万一漏到此处按 dub 处理。
            item["audio_mode"] = "native" if verdict.get("decision") == "native" else "dub"
            # 逐镜对齐：dubbing align 已把每镜时长写回 shots.json 的 duration；
            # 带上它，assemble 才能把片段精确做到该时长，与配音/字幕对齐。
            if sh.get("duration"):
                item["duration"] = sh["duration"]
        elif sh.get("frame"):
            item["image"] = sh["frame"]
            if sh.get("duration"):
                item["duration"] = sh["duration"]
        else:
            continue  # 该镜头还没生成素材，跳过
        dur = float(sh.get("duration") or 0.0)
        for fx in (sh.get("sfx") or []):
            if not fx.get("file"):
                continue   # 只汇总已有音效文件的（纯描述留给 ai-music 生成后再填 file）
            sfx_global.append({"file": fx["file"],
                               "at": round(cum_start + float(fx.get("at") or 0.0), 3),
                               "volume": fx.get("volume", 0.9)})
        cum_start += dur
        out_shots.append(item)
    board = {"size": size, "shots": out_shots, "pad_mode": pad_mode,
             "audio_policy": "native-first"}
    if narration:
        board["narration"] = narration
    if bgm:
        board["bgm"] = bgm
    if subtitle:
        board["subtitle"] = subtitle
    if sfx_global:
        board["sfx"] = sfx_global
    return board


# ── progress ──────────────────────────────────────────────────────────
def progress_record(root: str, series: str, episode: int, shot: int | None,
                    status: str) -> dict:
    base = _series_dir(root, series)
    if not base.exists():
        _die(f"剧目录不存在：{base}")
    pf = base / "progress.json"
    data = _load_json(pf, {"series": series, "episodes": {}})
    ep_key = str(episode)
    ep = data["episodes"].setdefault(ep_key, {"status": "planned", "shots": {}})
    if shot is None:
        ep["status"] = status
    else:
        ep["shots"][str(shot)] = status
    _write_json(pf, data)
    return {"episode": episode, "shot": shot, "status": status}


def progress_show(root: str, series: str) -> str:
    base = _series_dir(root, series)
    data = _load_json(base / "progress.json", {"series": series, "episodes": {}})
    lines = [f"# {data.get('series','')} 生成进度", ""]
    for ep in sorted(data["episodes"], key=lambda x: int(x)):
        info = data["episodes"][ep]
        done = sum(1 for s in info.get("shots", {}).values() if s == "done")
        total = len(info.get("shots", {}))
        lines.append(f"- 第 {ep} 集 [{info.get('status','?')}] 镜头 {done}/{total} done")
    return "\n".join(lines) if len(lines) > 2 else "（暂无进度）"


# ── selftest ──────────────────────────────────────────────────────────
def _selftest() -> int:
    import tempfile
    ok = True

    def chk(name, cond):
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {name}")
        ok = ok and cond

    with tempfile.TemporaryDirectory() as td:
        r = scaffold(td, "测试剧")
        base = Path(r["base"])
        chk("scaffold", (base / "series-bible.md").is_file()
            and (base / "ref_index.json").is_file())
        c1 = ref_add(td, "测试剧", "character", "林策", "refs/a.png", "男主", "港风")
        c2 = ref_add(td, "测试剧", "character", "苏晚", "refs/b.png", "女主", "港风")
        s1 = ref_add(td, "测试剧", "scene", "天台", "refs/s.png", "夜景天台", "港风")
        chk("ref 自动编号 C01/C02/S01",
            c1["code"] == "C01" and c2["code"] == "C02" and s1["code"] == "S01")
        chk("ref list", len(ref_list(td, "测试剧")) == 3)

        # shots 校验：坏的
        bad = {"episode": 1, "shots": [{"idx": 1, "desc": "x"}]}
        probs = validate_shots(bad, {"C01"})
        chk("validate 抓 无风格前缀+无refs", any("style_prefix" in p for p in probs)
            and any("参考图" in p for p in probs))
        # 好的
        good = {"episode": 1, "style_prefix": "港风9:16", "shots": [
            {"idx": 1, "prompt": "a", "refs": ["C01"]},
            {"idx": 2, "prompt": "b", "refs": ["C01", "S01"]}]}
        chk("validate 通过", validate_shots(good, {"C01", "S01"}) == [])
        chk("validate 抓未登记ref", any("未登记" in p for p in
            validate_shots({"episode": 1, "style_prefix": "x",
                            "shots": [{"idx": 1, "prompt": "a", "refs": ["C99"]}]},
                           {"C01"})))
        # 生视频前硬门：有台词的镜没 generation_prompt（没跑 prepare）→ 拦
        dlg = {1: "你终于来了"}
        chk("pre-video 抓 没跑prepare(缺generation_prompt)",
            any("没跑" in p and "prepare" in p for p in
                validate_shots(good, {"C01", "S01"}, dlg)))
        okgood = {"episode": 1, "style_prefix": "港风", "shots": [
            {"idx": 1, "prompt": "a", "refs": ["C01"],
             "generation_prompt": "画面…必须逐字说：「你终于来了」…"},
            {"idx": 2, "prompt": "b", "refs": ["C01", "S01"]}]}
        chk("pre-video 通过(gen_prompt 含台词)", validate_shots(okgood, {"C01", "S01"}, dlg) == [])

        # generate：脚本驱动生视频——门必须拦「有台词却没跑 prepare」
        epg = _ep_dir(base, 1)
        epg.mkdir(parents=True, exist_ok=True)
        _write_json(epg / "lines.json", {"lines": [{"speaker": "林策", "text": "你终于来了", "shot": 1}]})
        _write_json(epg / "shots.json", {"episode": 1, "style_prefix": "港风",
                    "shots": [{"idx": 1, "prompt": "画面", "refs": ["C01"], "frame": "shots/f1.png"}]})
        try:
            cmd_generate(td, "测试剧", 1, None, False, "xhs-maas", "happyhorse-1.0-i2v",
                         "9:16", dry_run=True)
            gate_fired = False
        except SystemExit:
            gate_fired = True
        chk("generate 拦 没跑prepare(缺generation_prompt)", gate_fired)
        # 补上 generation_prompt + 首帧 → dry-run 只列计划、返回 0，不真发
        (epg / "shots").mkdir(parents=True, exist_ok=True)
        (epg / "shots" / "f1.png").write_text("x", encoding="utf-8")
        _write_json(epg / "shots.json", {"episode": 1, "style_prefix": "港风",
                    "video_generation": {"provider": "xhs-maas", "model": "happyhorse-1.0-i2v"},
                    "shots": [{"idx": 1, "prompt": "画面", "refs": ["C01"], "frame": "shots/f1.png",
                               "generation_prompt": "画面…必须逐字说：「你终于来了」…", "gen_duration": 5}]})
        # 定妆图未复核 → generate 拦（做完图别跳过看视觉形象）
        try:
            cmd_generate(td, "测试剧", 1, None, False, "xhs-maas", "happyhorse-1.0-i2v",
                         "9:16", dry_run=True)
            vgate = False
        except SystemExit:
            vgate = True
        chk("generate 拦 定妆图未肉眼复核", vgate)
        # 复核 C01 后 → dry-run 通过
        ref_review(td, "测试剧", "C01", "看到：冷峻短发西装男，符合男主设定")
        try:
            rc = cmd_generate(td, "测试剧", 1, None, False, "xhs-maas", "happyhorse-1.0-i2v",
                              "9:16", dry_run=True)
        except SystemExit:
            rc = 99
        chk("generate dry-run 通过(prepare+首帧+定妆复核齐)", rc == 0)
        try:
            cmd_generate(td, "测试剧", 1, None, False, "agnes", "agnes-video-2.5-flash",
                         "9:16", dry_run=True)
            model_gate = False
        except SystemExit:
            model_gate = True
        chk("generate 拦 provider/model 与 prepare 锁定值冲突", model_gate)
        try:
            ref_review(td, "测试剧", "C01", "ok")   # 太短
            short_rejected = False
        except SystemExit:
            short_rejected = True
        chk("ref_review 敷衍观察(太短)被拒", short_rejected)

        # storyboard
        shots = {"episode": 1, "shots": [
            {"idx": 1, "clip": "ep01/s1.mp4", "duration": 3.2, "caption": "开场"},
            {"idx": 2, "frame": "ep01/s2.png", "duration": 3, "caption": "转折"},
            {"idx": 3, "caption": "还没生成"},
            {"idx": 4, "clip": "ep01/s4.mp4", "duration": 4.0, "caption": "换配音镜"}]}
        # native → 整轨原音直通（用模型原声）；dub（人声坏了换配音）→ audio_mode=dub，原生轨在 assemble 里丢弃、纯 TTS
        audit = {"shots": [{"shot": 1, "decision": "native"},
                            {"shot": 4, "decision": "dub"}]}
        board = build_storyboard(shots, narration="v.mp3", bgm="b.mp3", audit=audit)
        chk("storyboard 映射 video/image + 跳过未生成 + video 带 duration + 默认 trim + native/dub 音频模式",
            len(board["shots"]) == 3 and board["shots"][0]["video"] == "ep01/s1.mp4"
            and board["shots"][0]["duration"] == 3.2
            and board["shots"][1]["image"] == "ep01/s2.png"
            and board["narration"] == "v.mp3"
            and board["pad_mode"] == "trim"
            and board["shots"][0]["audio_mode"] == "native"
            and board["shots"][2]["audio_mode"] == "dub")

        # progress
        progress_record(td, "测试剧", 1, 1, "done")
        progress_record(td, "测试剧", 1, 2, "done")
        progress_record(td, "测试剧", 1, None, "done")
        chk("progress", "第 1 集" in progress_show(td, "测试剧"))

    print("✅ selftest 通过" if ok else "❌ selftest 失败")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="AI 短剧确定性资产/编排管理",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("scaffold", help="搭剧集骨架")
    ps.add_argument("--series", required=True)
    ps.add_argument("--root", default=DEFAULT_ROOT)

    pr = sub.add_parser("ref", help="参考图索引")
    rsub = pr.add_subparsers(dest="refcmd", required=True)
    ra = rsub.add_parser("add", help="登记参考图")
    ra.add_argument("--series", required=True)
    ra.add_argument("--root", default=DEFAULT_ROOT)
    ra.add_argument("--kind", required=True, choices=list(_KIND_PREFIX))
    ra.add_argument("--name", required=True)
    ra.add_argument("--image", required=True)
    ra.add_argument("--desc", default="")
    ra.add_argument("--style", default="")
    rl = rsub.add_parser("list", help="列参考图")
    rl.add_argument("--series", required=True)
    rl.add_argument("--root", default=DEFAULT_ROOT)
    rv = rsub.add_parser("review", help="记录对定妆图的肉眼视觉复核（generate 前必做）")
    rv.add_argument("--series", required=True)
    rv.add_argument("--root", default=DEFAULT_ROOT)
    rv.add_argument("--code", required=True, help="参考图编号（如 C01）")
    rv.add_argument("--observation", required=True,
                    help="你**实际看到**的形象（发型/年龄/服装/气质…）+ 是否符合设定；写不出=没真看图")
    rv.add_argument("--mismatch", action="store_true",
                    help="形象与设定不符（标记后 generate 仍会拦，应重生成定妆图再复核）")

    psh = sub.add_parser("shots", help="分镜")
    ssub = psh.add_subparsers(dest="shotcmd", required=True)
    sv = ssub.add_parser("validate", help="校验某集分镜")
    sv.add_argument("--series", required=True)
    sv.add_argument("--root", default=DEFAULT_ROOT)
    sv.add_argument("--episode", type=int, required=True)
    sv.add_argument("--pre-video", dest="pre_video", action="store_true",
                    help="生视频前硬门：额外校验有台词的镜已由 prepare 写好含台词的 generation_prompt"
                         "（防止拿只有画面的 prompt 生视频导致台词全对不上）")

    pg = sub.add_parser("generate", help="逐镜图生视频（脚本读 generation_prompt 自己调 ai_video.py，强制喂台词）")
    pg.add_argument("--series", required=True)
    pg.add_argument("--root", default=DEFAULT_ROOT)
    pg.add_argument("--episode", type=int, required=True)
    pg.add_argument("--only", help="只生成这些镜（逗号分隔 idx，如 1,3,5）")
    pg.add_argument("--force", action="store_true", help="已有 clip 也重生成（默认跳过控费）")
    pg.add_argument("--provider", help="视频 provider（默认 env VIDEO_PROVIDER）")
    pg.add_argument("--model", help="视频模型（覆盖默认）")
    pg.add_argument("--ratio", default="9:16", help="画幅（默认 9:16 竖屏）")
    pg.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="只列生成计划、不真发（控费预检）")

    pb = sub.add_parser("storyboard", help="转 assemble.py storyboard")
    pb.add_argument("--series", required=True)
    pb.add_argument("--root", default=DEFAULT_ROOT)
    pb.add_argument("--episode", type=int, required=True)
    pb.add_argument("-o", "--output", required=True)
    pb.add_argument("--size", default="1080x1920")
    pb.add_argument("--narration")
    pb.add_argument("--bgm")
    pb.add_argument("--subtitle")
    pb.add_argument("--pad-mode", dest="pad_mode", default="trim",
                    choices=["trim", "auto", "stretch", "loop", "freeze"],
                    help="片段短于台词时长时的补足方式（默认 trim=自然，不慢放不循环）")
    pb.add_argument("--allow-static", dest="allow_static", action="store_true",
                    help="放行「只有关键帧图、没生成视频片段」的镜头（会是静态图，很垃圾）——"
                         "默认硬拦，逼你先对每镜跑 ai-video-gen 图生视频")

    pp = sub.add_parser("progress", help="生成进度")
    psub = pp.add_subparsers(dest="pcmd", required=True)
    pre = psub.add_parser("record")
    pre.add_argument("--series", required=True)
    pre.add_argument("--root", default=DEFAULT_ROOT)
    pre.add_argument("--episode", type=int, required=True)
    pre.add_argument("--shot", type=int)
    pre.add_argument("--status", default="done",
                     choices=["planned", "done", "failed"])
    psw = psub.add_parser("show")
    psw.add_argument("--series", required=True)
    psw.add_argument("--root", default=DEFAULT_ROOT)

    sub.add_parser("selftest", help="自检")

    a = ap.parse_args()
    if a.cmd == "selftest":
        return _selftest()
    if a.cmd == "scaffold":
        r = scaffold(a.root, a.series)
        print(f"✅ {r['base']}（新建 {len(r['created'])} 个）")
        return 0
    if a.cmd == "ref":
        if a.refcmd == "add":
            e = ref_add(a.root, a.series, a.kind, a.name, a.image, a.desc, a.style)
            print(f"✅ {e['code']} {e['name']} → {e['image']}")
        elif a.refcmd == "review":
            e = ref_review(a.root, a.series, a.code, a.observation, matches=not a.mismatch)
            flag = "✅ 符合" if e["review_matches"] else "⚠️ 不符（应重生成定妆图）"
            print(f"{flag} {e['code']} {e['name']} 复核记录：{e['review_observation']}")
        else:
            for r in ref_list(a.root, a.series):
                rv = "✓看过" if r.get("reviewed") else "·未复核"
                print(f"  {r['code']} [{r['kind']}] {r['name']} {rv} — {r.get('desc','')} → {r['image']}")
        return 0
    if a.cmd == "shots" and a.shotcmd == "validate":
        return cmd_shots_validate(a.root, a.series, a.episode, getattr(a, "pre_video", False))
    if a.cmd == "generate":
        only = [int(x) for x in a.only.replace("，", ",").split(",") if x.strip()] if a.only else None
        return cmd_generate(a.root, a.series, a.episode, only, a.force,
                            a.provider, a.model, a.ratio, a.dry_run)
    if a.cmd == "storyboard":
        base = _series_dir(a.root, a.series)
        sp = _ep_dir(base, a.episode) / "shots.json"
        if not sp.exists():
            _die(f"未找到 {sp}")
        shots_data = _load_json(sp, {})
        # 静态图硬闸门：有关键帧图(frame)却没生成视频片段(clip)的镜头 = 会是静态图冒充视频（很垃圾）
        static = [s.get("idx") for s in shots_data.get("shots", [])
                  if s.get("frame") and not s.get("clip")]
        if static and not a.allow_static:
            _die(f"镜 {static} 只有关键帧图、没有视频片段(clip)——成片会是**静态图**，不是短剧！\n"
                 f"请先对每镜用 ai-video-gen 图生视频（image2video）把首帧驱动成动态片段，"
                 f"把 clip 路径写回 shots.json 再合成。\n"
                 f"（确实要做静态图片短剧才加 --allow-static。）")
        audit = _load_json(_ep_dir(base, a.episode) / "clip-audit.json", {})
        board = build_storyboard(shots_data, a.size,
                                 a.narration, a.bgm, a.subtitle, a.pad_mode, audit)
        _write_json(Path(a.output).expanduser(), board)
        vids = sum(1 for s in board["shots"] if s.get("video"))
        print(f"✅ {a.output}（{len(board['shots'])} 个镜头，{vids} 个动态片段）")
        return 0
    if a.cmd == "progress":
        if a.pcmd == "record":
            r = progress_record(a.root, a.series, a.episode, a.shot, a.status)
            print(f"✅ 第 {r['episode']} 集"
                  + (f" 镜头 {r['shot']}" if r['shot'] is not None else "")
                  + f" [{r['status']}]")
        else:
            print(progress_show(a.root, a.series))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
