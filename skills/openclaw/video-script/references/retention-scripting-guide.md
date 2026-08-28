# Retention & Scripting Guide

> 本文档来源于跨平台留存率研究数据。原始数据主要基于英语视频平台分析，但 Hook 框架、节奏中断策略、能量模式和 CTA 放置原则具有普遍适用性。各平台的具体指标阈值（如推荐触发门槛、完播率基准）因平台算法差异而有所不同——使用时需结合目标平台的实际数据校准。

## Table of Contents

- [Hook Framework](#hook-framework)
- [Hook Benchmarks](#hook-benchmarks)
- [Pattern Interrupts](#pattern-interrupts)
- [Energy Patterns](#energy-patterns)
- [Optimal Video Length by Format](#optimal-video-length-by-format)
- [Retention Graph Diagnosis](#retention-graph-diagnosis)
- [Algorithmic Promotion Thresholds](#algorithmic-promotion-thresholds)
- [CTA Placement & Conversion](#cta-placement--conversion)
- [Key Constraints & Gotchas](#key-constraints--gotchas)

---

## Hook Framework

### Viewer Loss Data

- **55%** of viewers lost in the first 60 seconds
- **20%** lost in the first 10 seconds
- Videos with a **value proposition in the first 15 seconds** = 18% higher retention at the 1-minute mark

### Hook Structure (First 30 Seconds)

| Timestamp | Purpose | Action |
|-----------|---------|--------|
| 0:00-0:05 | Attention grab | Visual/verbal pattern break, bold claim, or unexpected moment |
| 0:05-0:15 | Clarify promise | State exactly what the viewer will get |
| 0:15-0:30 | Stakes/context | Why this matters, what they'll miss |

---

## Hook Benchmarks

| Metric | Threshold | Assessment |
|--------|-----------|------------|
| Retention at 10-15s | Below 50% | Hook is failing |
| Retention at 30s | 70%+ | Solid |
| Retention at 30s | 80%+ | Exceptional |

- **Never open with** generic greetings or channel intros -- causes instant, measurable drop-off

### 平台差异备注

- **B站**：3 秒完播率是核心指标，前 3 秒决定是否进入推荐池
- **抖音**：5 秒完播率决定推荐量级，Hook 需在 5 秒内完成核心承诺
- **视频号**：完播率权重高于互动率，Hook 需快速建立信任感

---

## Pattern Interrupts

### Impact Data

- Pattern interrupt in **first 5 seconds** = **23% higher retention**
- Strategic breaks at drop-off points = **15-22% re-engagement** (Wistia)
- Adobe tutorials using pattern interrupts = **43% higher completion**

### Recommended Frequency

| Format | Interrupt Frequency |
|--------|-------------------|
| Pre-recorded (long-form) | Every 30-90 seconds |
| Live | Every 2-3 minutes |
| Shorts / 短视频 | Every 2-3 seconds |

### Interrupt Types

- Camera angle change
- Sound effects / music shift
- Text pop-ups / lower thirds
- Unexpected facts or stats
- Format shifts (talking head to B-roll, screen share to whiteboard)

---

## Energy Patterns

Source: AIR Media-Tech, 5 documented patterns

| Pattern | Description | Best For |
|---------|-------------|----------|
| **Gradual Slowdown** | High energy open, gradually decreasing | Short content, impact pieces |
| **Calm-Burst Oscillation** | 15-25s calm, then energy burst every 2-3 min | Educational, tutorials |
| **Anchor Pattern** | Return to core thesis every 2-3 min | Long-form essays, explainers |
| **Strategic Pauses** | Deliberate silence/slowdown before key points | Storytelling, dramatic content |
| **Progressive Energy** | High first 3 min, stabilize, mix variety after min 8 | Vlogs, entertainment |

---

## Optimal Video Length by Format

| Format | Optimal Length | Notes |
|--------|---------------|-------|
| Tutorials | 7-15 min | Step-by-step pacing |
| Entertainment / Vlogs | 8-12 min | Energy management critical |
| Educational | 15-25 min | Anchor pattern recommended |
| Gaming (edited) | 10-20 min | Pattern interrupts essential |
| Product reviews | 8-15 min | Front-load verdict for retention |
| Podcasts | 30-90 min | Calm-Burst Oscillation works well |
| Shorts / 短视频 | 15-60s | Peak completion rate range |

### Length vs Performance

- **5-10 min** = peak retention at **31.5%**
- Short-form accounts for the majority of views across platforms
- Videos **20+ min** capture **57% of total watch time**

---

## Retention Graph Diagnosis

| Pattern | Visual Shape | Diagnosis | Fix |
|---------|-------------|-----------|-----|
| **Sharp cliff** | 20%+ lost in first 15s | Hook failure | Rebuild 0:00-0:15 |
| **Steady decline** | Gradual downward slope | Normal/expected | Optimize pacing |
| **Mid-video valley** | Dip at 40-60% mark | Pacing issue | Add pattern interrupt or reorder content |
| **Spikes/bumps** | Upward blips | Rewatch moments | Create more of these intentionally |
| **Suspension bridge** | High retention through open loops | Excellent scripting | **68% higher completion** |
| **Sawtooth** | Zigzag from pattern interrupts | Active re-engagement | **43% higher completion** |

---

## Algorithmic Promotion Thresholds

- Videos outperforming channel average retention by **15%+** receive significantly more algorithmic promotion
- A **10 percentage point retention improvement** = **25%+ impression increase**
- **AI narration** = **70% lower retention** vs human-fronted content

> Note: Exact promotion multipliers vary by platform. The directional relationship (higher retention = more distribution) is universal.

---

## CTA Placement & Conversion

### Viewer Reach Data

- Only **16%** of viewers reach the final 10% of a video
- At **~1 min mark**: ~60% of viewers still watching
- At **~4 min mark**: ~35% of viewers still watching

### Best Practices

| Strategy | Impact |
|----------|--------|
| Place CTA after first value delivery (1-3 min) | Catches majority of viewers |
| Embedded CTAs (visual + verbal) | **380% conversion increase** over verbal-only |
| With CTA: 1 sub per 33 views | **2.5x better** than without CTA (1 per 83 views) |
| Personalized CTA language | **150% growth boost** |

### Dual CTA Strategy

- **First CTA** at ~1 min = reaches ~60% of viewers
- **Second CTA** at ~4 min = reaches ~35% of viewers
- Never save the only CTA for the end (only 16% see it)

---

## Pacing Principles (Validated at Scale)

### Deliver on the Promise Immediately
The title and thumbnail set a promise. In the first 5-10 seconds, **instantly assure
the viewer you are delivering on that promise**. No intros, no greetings,
no talking about your day. Deliver what they clicked for, then promise even more
to exceed expectations.

### Ruthless Pacing & Final Payoff
- Remove every dull moment. Have critical friends review your video to find dead spots.
- Use different camera angles and fast cuts to maintain visual stimulation.
- Ensure a **strong payoff at the end** (reveal, result, conclusion) so viewers have a
  compelling reason to stay until the last second -- this directly boosts average view duration.

### The Suspension Bridge Technique
Open loops throughout the script create a "suspension bridge" retention curve.
This delivers the highest completion rate improvement (**68%**) -- prioritize
open-loop scripting over other techniques.

---

## Key Constraints & Gotchas

- **55% of viewers leave in the first 60 seconds** -- the hook is the single highest-leverage optimization
- **Generic greetings** are a measurable retention killer -- avoid channel-first openings entirely
- **AI narration drops retention by 70%** -- always prefer human-fronted content unless the channel is explicitly AI-themed
- **Only 16% reach the final 10%** of a video -- any CTA placed only at the end is seen by a fraction of viewers
- **Pattern interrupt frequency differs by format** -- every 30s for pre-recorded is aggressive but data-supported; live content needs longer intervals (2-3 min)
- **15%+ above channel average retention** is the threshold for algorithmic boost -- optimize your best-performing content types, not underperformers
- **Short-form optimal length is 15-60s** for completion rate
- **The suspension bridge pattern (open loops)** delivers the highest completion rate improvement (68%) -- prioritize open-loop scripting over other techniques
