"""Permission choices supported by each Easel execution path."""
from __future__ import annotations

TARGETS = {"easel": "画板自身", "api": "仅聊天模式", "codex": "Codex", "openclaw": "OpenClaw",
           "opencode": "OpenCode", "hermes": "Hermes", "acp": "通用 ACP"}
ACP = {"opencode", "hermes", "acp"}
ASK = ("ask", "按需询问", "收到额外权限请求时，由你决定。")
AUTO = ("auto", "自动审批", "自动处理可识别的常规操作，其余请求交给你。")
ALLOW = ("allow", "全部允许", "在所选范围内直接执行。")
NATIVE = ("native", "引擎管理", "沿用引擎自身的权限配置。")


def choices(target):
    if target == "easel":
        return ([("native", "启用工具", "可安装依赖、渲染、运行技能、生成画像、登录账号及发布内容。"),
                 ("read-only", "停用执行工具", "阻止画板启动这些操作，仍可查看账号和已有内容。")],
                [("ask", "每次询问", "执行前显示操作名称和对象。"),
                 ("auto", "自动审批", "渲染测试直接运行，其他执行工具先确认。"), ALLOW])
    if target == "api":
        return ([("chat", "仅对话", "模型可以分析你发来的文字和附件。")],
                [("none", "无工具调用", "此模式没有本地执行接口。")])
    if target == "openclaw":
        return ([NATIVE, ("read-only", "只读", "使用网关的只读会话模式。"),
                 ("guarded", "按需询问", "由网关处理需要人工审批的操作。"),
                 ("workspace-write", "自动审批", "使用网关的工作区自动审查模式。"),
                 ("full", "全部允许", "请求网关的完整访问模式，受原生工具策略约束。")],
                [("native", "网关管理", "审批与访问范围由 OpenClaw 会话模式共同决定。")])
    if target in ACP:
        return ([NATIVE, ("read-only", "项目内读取", "仅放行带有项目内路径的读取和搜索请求。"),
                 ("workspace-write", "项目内读写", "另可放行标明项目内路径的文件编辑。")],
                [ASK, ("auto", "自动审批", "仅自动通过带有项目内路径的读取或搜索。"), ALLOW])
    return ([("read-only", "只读", "查看文件与资料，限制写入和联网。"),
             ("workspace-write", "项目内读写", "可编辑画板工作区，额外访问按审批方式处理。"),
             ("full", "本机完整访问", "以当前系统用户的权限操作文件与网络。")], [ASK, AUTO, ("allow", "全部允许", "在所选范围内自动运行；超出沙箱的操作由 Codex 拒绝。")])


def valid(target, scope, approval):
    if target not in TARGETS or not isinstance(scope, str) or not isinstance(approval, str):
        return False
    scopes, approvals = choices(target)
    return scope in {option[0] for option in scopes} and approval in {option[0] for option in approvals}


def policy(config, target):
    if target == "codex":
        return ("full" if config.get("codex_full_access") else config.get("sandbox", "workspace-write"),
                "allow" if config.get("codex_never_ask") else "auto" if config.get("codex_auto_approve") else "ask")
    saved = config.get("agent_access", {}).get(target)
    if saved:
        return saved["scope"], saved["approval"]
    return {"easel": ("native", "allow"), "api": ("chat", "none"),
            "openclaw": ("native", "native")}.get(target, ("native", "ask"))
