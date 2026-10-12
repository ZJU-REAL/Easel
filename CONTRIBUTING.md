# 贡献指南

感谢参与 Easel。项目以 Apache-2.0 开源，欢迎 Issue 和 PR。

## 反馈 Issue

- **环境问题**：附上 OS、Python、Node.js、`openclaw --version` 版本、`easel doctor` 输出和 `easel gateway logs` 相关片段。先查 [已知问题](docs/known-issues.md)。
- **功能建议 / 新技能**：先开 Issue 说明场景与预期产物，确认方向后再动手，避免大改撞车。

## 提交前必跑

```bash
python scripts/validate_skills.py            # SKILL frontmatter、目录结构、发布契约
python scripts/validate_skill_commands.py    # 文档中的 python 命令与脚本真实 argparse 对齐
python scripts/validate_document_paths.py
python -m pytest tests/                      # 核心单测（不会调用真实模型或平台）
```

路径校验覆盖根文档、`docs/`、`agents/` 和 `skills/` 下的 Markdown，以及画像模板和前端说明，包括深层参考文档和 Agent 提示材料。命令里的 `skills/...` 相对项目根，技能资源名相对技能目录，Markdown 链接与显式 `../` 相对当前文档；占位符和运行时生成的产物不要求预先存在。

仅更新 OpenClaw 已同步的提示文档时可运行 `bash agents/sync.sh --docs-only`：更新内置技能与共享 Markdown、身份文档和运行时路径说明，不清空 `MEMORY.md`、不删除 `USER.md` 或自定义技能、不修改脚本和产物链接。其它原生执行引擎直接读取 `agents/workspace/`，不需要这一步。

## Skill 约定

- 遵循 [SKILL 接口规范](docs/SKILL-SPEC.md)：frontmatter 含 `name / description / layer`，SKILL.md 精简（< 200 行），领域知识进 `references/`，可执行脚本进 `scripts/`。
- 产物统一写入 `outputs/<项目>/`，路径经 `skills/shared/scripts/output_paths.py` 校验；不要在技能里散落写其他目录。
- 发布类技能保持门禁语义：先预览与发布前检查，真实发布由用户确认后执行。
- 技能内的账号画像只从 `profiles/<画像>/` 读取，不写全局 `MEMORY.md`（见 [提示词分层](docs/prompt-stack.md)）。

## 代码约定

- Python ≥ 3.10；Web 为 FastAPI + React（`web/`），CLI 入口在 `easel/`。
- 超时只改 [`easel/timeouts.py`](easel/timeouts.py) 单一真相源，不要在调用处各写各的。
- OpenClaw 的缺陷跟随上游修复，不在本仓库内置补丁；环境问题沉淀到 `easel doctor` 或 [known-issues](docs/known-issues.md)。
- 凭证不进仓库：`.env` 不入库；测试不得调用真实模型、真实平台或外部消息渠道。

## PR 约定

- 一个 PR 只做一件事；标题用 `feat: / fix: / docs: / chore: / polish:` 前缀。
- 描述里写清动机与验证方式；涉及技能行为改动时附上触发示例。
- 第三方素材或技能引入需在 [ACKNOWLEDGMENTS](docs/ACKNOWLEDGMENTS.md) 登记来源与许可。
