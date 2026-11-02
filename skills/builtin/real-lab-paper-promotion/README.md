# REAL Lab Paper Promotion

可复用的 Agent Skill：提供论文即可生成一篇小红书中文文案和原始 PDF 截图。

## 安装

已接入 Easel 的 `skills/builtin/real-lab-paper-promotion/`。在技能面板选择，或在对话中用 `/real-lab-paper-promotion` 调用。依赖使用项目虚拟环境安装：

```bash
.venv/bin/python -m pip install -r skills/builtin/real-lab-paper-promotion/requirements.txt
```

## 使用

直接发送任意一种：

- `用 /real-lab-paper-promotion 处理 https://arxiv.org/abs/论文编号`
- `用 /real-lab-paper-promotion 处理 https://论文网站/paper.pdf`
- `用 /real-lab-paper-promotion 处理 /本地路径/paper.pdf`

也接受裸 arXiv 编号及指定版本的链接。下载链接需可访问；无需填写图号、裁剪框或提纲。Agent 负责阅读、写作、选择截图并检查；脚本负责获取 PDF、渲染及硬性校验，不是无模型自动写作程序。

Easel 项目目录包含：

```text
outputs/<论文简称>/
  .easel.json
  assets/paper-promotion/  # 内部工作资料
  post.md
  images/
    01-first-page.png
    02-method.png
    ...
```

标题不超过20字符、正文不超过1000字符，严格禁止真实链接，只保留已核实的 arXiv 编号或仓库简称。第1张完整截首页；其余只截正文讨论的图表与原 caption，顺序与正文一致，不重绘。图片数量由内容决定。

内部证据与审核报告放在工作目录，不作为待发布成品。六篇历史案例是风格参考，不是新稿事实来源。Skill 不自动发布。

开发验证：安装依赖后运行 `python skills/builtin/real-lab-paper-promotion/scripts/test_promotion.py`。测试 PDF 为临时合成材料，不是待宣传论文，也不会生成虚构宣传成果。
