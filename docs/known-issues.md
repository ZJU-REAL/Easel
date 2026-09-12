# 已知问题

本页记录目前已知、且与 Easel 使用相关的问题，以及推荐的规避方式。遇到未列出的问题，欢迎提交 [Issue](https://github.com/ZJU-REAL/Easel/issues)。

---

## CLI 终端对话中「问答题」后回复重复显示

- **影响范围**：仅 `easel chat`（终端对话）。**Web 工作台不受影响**。
- **表现**：当 Agent 触发一次 `ask_user` 问答题、用户回答之后，Agent 的下一条回复在终端里可能被重复渲染一次（内容正确，只是显示了两遍）。
- **性质**：这是**纯显示层**问题，不影响实际对话内容、产物生成或发布结果。

### 根因

问题位于上游 [OpenClaw](https://www.npmjs.com/package/openclaw) 本体的**会话投影（session projection）**逻辑，不在 Easel 仓库内。

`easel chat` 底层调用 `openclaw tui`，由 OpenClaw 的 gateway-client 负责在终端重建对话记录。当一条实时回复与另一行（例如 `ask_user` 的问答行）发生错误匹配、且两者不共享 transcript identity 时，投影逻辑会把该回复重新插入一次，导致重复渲染。

我们已核实该根因，并在上游的回归测试中复现（修复前 3 条相关用例失败，修复后全部通过）。

### 上游修复进展

修复已提交至 OpenClaw，跟踪 PR：

- openclaw#144730
- openclaw#144892

修复采用四层策略：全内容唯一匹配、要求终端证据、暂定恢复记录、以及在暂定恢复无法表示时保留后续独立 final 可见。

### 规避与升级

- **推荐**：使用 **Web 工作台**（`easel web`，默认 `http://localhost:7860`）。Web 后端从原始事件流自行渲染，不经过上述会话投影逻辑，因此**不受此问题影响**，并且提供比 CLI 更完整的会话、素材、账号、画像、内容库与发布管理能力。
- 若坚持使用 `easel chat`：待上游发布含修复的版本后，升级 OpenClaw 即可解决：

  ```bash
  npm i -g openclaw@latest
  ```

- Easel 安装的是 OpenClaw 全局 CLI（预构建产物），因此我们**不在 Easel 仓库内内置该补丁**，而是跟随上游最新版本；后续会在 `easel doctor` 中加入 OpenClaw 最低版本检查。
