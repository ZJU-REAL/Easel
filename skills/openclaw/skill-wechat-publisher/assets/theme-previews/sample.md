# Claude 的付费用户,正在变成另一个物种

> Max 计划最早是为"重度聊天"设计的,不是为 Claude Code 设计的。Claude Code 是后来才加进去的,而且是在 Opus 4 之后才真正爆发。Cowork 落地后,长时间运行的异步 agent 已经成为日常工作流。**用户使用 Claude 订阅的方式已经发生了根本变化。**

## 一段话总结

这段话的信息密度很高,我给翻一下重点:

1. Max 计划最早是为"重度聊天"设计的,不是为 Claude Code 设计的
2. 早期用户画像是 ChatGPT 重度用户的平替,不是写代码的开发者
3. Claude Code 是后来才加进去的,而且是在 Opus 4 之后才真正爆发
4. 爆发点是代码能力质变 + CLI 体验对 power user 的吸引力
5. Cowork(多人协作)和长时间运行的异步 Agent 现在已经成了日常工作流
6. 这直接把使用时长从小时级拉到全天候级
7. **用户的使用方式已经发生根本变化**——从短暂的对话变成了近乎全天候的多代理工作流

## 三个关键信号

这不是简单的"使用时长变长了",而是使用方式的 ==质变==。具体表现在:

- **使用形态**:从 chat-based 到 agent-based
- **时间分布**:从 session-based 到 always-on
- **价值主张**:从辅助工具变成 ++协作基础设施++

想象一下:你不再只是"跟 AI 聊天",而是 %%派出一群 Agent 去替你工作%%,它们在后台跑,你只是偶尔 check 一下进度。这就是 &&Cowork 带来的范式转移&&。

### 对订阅模型的影响

原来 Max 计划的定价假设是:用户偶尔来问几个问题。现在的假设变成了:!!用户 24 小时都在烧 token!!。这对 Anthropic 的经济模型是 @@巨大的压力测试@@,也是 ^^下一代订阅产品的设计起点^^。

## 一个代码示例

下面是一个典型的 agent 工作流:

```python
from anthropic import Anthropic

client = Anthropic()

def run_agent(task: str) -> str:
    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=8192,
        messages=[{"role": "user", "content": task}],
    )
    return response.content[0].text
```

行内代码示例:`claude-opus-4-7` 是最新的 Opus 模型,支持 `1M context`。

## 对照一下数据

| 指标 | 一年前 | 今天 |
|---|---|---|
| 日均使用时长 | 40 分钟 | 近全天候 |
| 主要使用场景 | 对话问答 | Agent 工作流 |
| 每日 Token 消耗 | 数万 | 数百万 |
| 主要用户画像 | ChatGPT 用户 | 开发者 / 专业人士 |

===

## 结论

说实话,这种范式转移背后,[官方博客](https://www.anthropic.com)其实早就埋过伏笔。Claude 付费用户,**正在变成另一个物种**。
