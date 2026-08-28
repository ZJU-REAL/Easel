---
name: skill-cross-platform-publish
description: >-
  跨平台一键发布：一份内容适配并发布到多个平台（小红书/抖音/B站/公众号/快手/视频号/知乎）。
  按各平台格式约束（字数/比例/标签/内容类型）适配内容，再逐个委派对应平台发布 SKILL。
  当用户说"一键发布""同时发到多个平台""多平台发布""一稿多发""全平台发""发到抖音+小红书+B站"
  "分发到各平台"时使用。适配由 LLM 做，路由与约束检查由 scripts/publish_dispatch.py。
layer: publish
---

# 跨平台一键发布

> 一稿多发：按各平台规范适配同一份内容，再逐平台委派发布 SKILL。走
> `scripts/publish_dispatch.py`（约束检查 + 平台→publisher 路由 + 派发计划）。
> **内容适配由你（LLM）完成，实际发布委派各平台 publisher SKILL。**

## 支持平台 → 发布 SKILL

| 平台 | publisher SKILL |
|------|-----------------|
| xiaohongshu | skill-xhs-publisher ✅ |
| douyin | skill-douyin-upload ✅ |
| wechat（公众号）| skill-wechat-publisher ✅ |
| bilibili | skill-bilibili-upload ✅ |
| kuaishou | skill-kuaishou-upload ✅ |
| weixin-channels（视频号）| skill-channels-upload ✅ |
| zhihu | skill-zhihu-publisher ✅ |

`python <skill>/scripts/publish_dispatch.py platforms` 看全部平台及约束。

## 输入

内容清单 manifest（JSON）：
```json
{
  "content": {"title": "...", "body": "...", "tags": ["...", "..."], "media_type": "video"},
  "platforms": ["xiaohongshu", "douyin", "bilibili"]
}
```

## 执行流程

脚本路径：`skills/openclaw/skill-cross-platform-publish/scripts/publish_dispatch.py`。

```bash
# 1) 生成派发计划（校验各平台越限 + 路由到 publisher）
python skills/openclaw/skill-cross-platform-publish/scripts/publish_dispatch.py plan --manifest content.json
```
2. **按计划为每个平台适配内容**（你来做）：
   - 依 `constraints_note` 与 `warnings` 精简标题/正文、删减标签、调整话题格式。
   - 依 `recommend_aspect` 决定是否用 **video-reframe** 转比例（如竖版转横版发 B站）。
   - 语气/话题按平台生态本地化（小红书亲和+emoji、B站梗、知乎专业、抖音短平快）。
3. **发布前人设检查**（有 Profile 时，见 AGENTS.md「发布前人设一致性检查」）：
   对适配后的各平台内容跑 skill-persona-check，评分喂
   `python skills/shared/scripts/persona_gate.py check --score 85`——
   低于 80 分时告知分数、偏离点和修改建议，但不阻断发布；用户已明确要发布就继续执行。
4. **逐平台发布**：调用 `dispatch[i].publisher` 对应的发布 SKILL 执行。
5. 发布后：**skill-publish-notify** 推送结果；**skill-short-link** 生成带 UTM 追踪短链；
   并把本次发布登记进 manifest 供归因层消费：
   ```
   python skills/shared/scripts/manifest.py record --topic 露营攻略 \
     --layer publish --skill skill-cross-platform-publish --profile 户外达人 \
     --upstream outputs/露营攻略/article.md --summary "已发 小红书/抖音/B站"
   ```
   > 发布记录已由 publisher 脚本在 `--exec` 成功时**自动**落「内容日历（`_schedule.json`）+ skill-publish-log」，无需手动补记（重复会双记）。仅当要补 `--persona-score/--persona-verdict` 等元数据时，再单独调 **skill-publish-log** 追加。

## Profile 感知

- 有 Profile：默认目标平台取 `platforms.md` 已开通的账号；各平台语气/话题贴合 `style.md`；
  合规底线遵守 `preferences.md`。
- 无 Profile：询问目标平台，用平台通用规范适配。

## 规则

1. **不要一稿原样多发**——每个平台按其约束与生态适配（这是本 SKILL 的核心价值）。
2. 发布前用 `plan` 检查越限，逐条消除 warnings 再发。
3. 视频跨横竖平台先用 video-reframe 转比例，别直接发导致黑边/裁切。
4. 每个平台的实际发布委派其 publisher SKILL；未部署 publisher 的平台先提示用户。
5. 批量按时间发布见 **skill-publish-scheduler**。

## 参考来源

一稿多发的关键不是"复制粘贴"而是"按平台重适配"。本 SKILL 用约束注册表把各平台的字数/比例/
标签/类型规则固化，路由到对应 publisher，适配交给 LLM，发布交给平台 SKILL。
