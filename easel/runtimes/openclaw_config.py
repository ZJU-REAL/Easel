"""OpenClaw 配置读写：openclaw.json 的供应商/主模型 + 认证判定。

从 runtimes/openclaw.py 拆出：适配器负责跑 agent、探测环境与诊断，这里只回答
「配置是什么、怎么写」。web 设置面板与 doctor 都从这里取 OpenClaw 的配置真值，
路径统一经 openclaw_workspace 解析（支持 EASEL_OPENCLAW_STATE_DIR 覆盖）。
"""

from __future__ import annotations

import json
import shutil

from easel.openclaw_workspace import config_path
from .common import runtime_env

# 内置槽位名：设置面板的自定义供应商不许占用，同步时也不删这三家。
RESERVED_PROVIDER_KEYS = {"openai", "anthropic", "relay"}

_AUTH_CHANNELS = (
    ("ANTHROPIC_API_KEY",),
    ("EASEL_LLM_API_KEY", "EASEL_LLM_BASE_URL"),
    ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"),
    ("OPENAI_API_KEY",),
    ("OPENAI_MAAS_API_KEY", "OPENAI_MAAS_ENDPOINT"),
)


def auth_configured() -> bool:
    """配置里是否有一套可用的认证（静态存在性；连通性以 `easel ping` 为准）。

    默认 .env 带的 `sk-ant-REPLACE_ME` 这类占位符不算配置 —— 否则 setup 会被骗过、
    doctor 报绿而对话直接报 "No route-compatible authentication source is configured"。
    """
    env = runtime_env()

    def _set(name: str) -> bool:
        value = (env.get(name) or "").strip()
        return bool(value) and "REPLACE_ME" not in value

    return any(all(_set(name) for name in names) for names in _AUTH_CHANNELS)


def primary_model_routable() -> tuple[bool, str]:
    """检查 agents.defaults.model.primary 指向的 provider 在 openclaw 里真的配了认证。

    `.env (API Key)` 只查配置里静态有没有填值，查不出 setup 有没有真把 provider 写进
    openclaw.json。两边脱节时（例如认证判定被占位符卡住、provider 一个字没写却照样设了
    primary），doctor 会全绿而对话直接报
    "No route-compatible authentication source is configured for <provider>"。

    返回 (是否可路由, 失败提示)。拿不准的情况一律放行，不制造假告警。
    """
    path = config_path()
    if not path.is_file():
        return False, f"{path} 不存在 — 先跑 bash setup.sh（Windows: setup.ps1）"
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, f"{path} 读不出来（{exc}）"

    primary = (((cfg.get("agents") or {}).get("defaults") or {})
               .get("model") or {}).get("primary") or ""
    if not primary:
        return False, "未设置 agents.defaults.model.primary — 重新跑 setup 脚本"
    if "/" not in primary:
        # 不是 provider/model 形式，解析不出 provider，交给 `easel ping` 去判，不在这里猜。
        return True, ""

    provider = primary.split("/", 1)[0]
    providers = (cfg.get("models") or {}).get("providers") or {}
    entry = providers.get(provider)
    if not isinstance(entry, dict):
        return False, (f"primary 是 {primary}，但 models.providers.{provider} 不存在 —— "
                       "在 .env 填好真实 key 后重新跑 setup 脚本")
    # apiKey / 本地适配器 / OAuth 任一即可。字段名随 OpenClaw 版本变过，这里从宽认。
    has_auth = bool(str(entry.get("apiKey") or "").strip()) or bool(entry.get("localService")) \
        or any(k for k, v in entry.items() if "oauth" in k.lower() and v)
    if not has_auth:
        return False, (f"models.providers.{provider} 没有 apiKey —— "
                       "在 .env 填好真实 key 后重新跑 setup 脚本")
    return True, ""


def is_local_gateway_base(url: str) -> bool:
    """这个供应商当前是不是挂在本地模型网关上。

    网关模式下 openclaw.json 里存的 baseUrl 是 127.0.0.1:8890，真实上游在 easel-models.yaml，
    面板显示/回传的是上游地址 —— 两边天生不相等。凡是拿「baseUrl 变了」当判据的逻辑都得先问过
    这里，否则网关用户每次保存都被判成「换了地址」。
    """
    return str(url or "").startswith("http://127.0.0.1:8890")


def provider_creds() -> dict[str, tuple[str, str]]:
    """读 openclaw.json 里每个 chat 供应商现存的 (baseUrl, apiKey)。读不到就当空表（不阻断保存）。"""
    try:
        provs = (json.loads(config_path().read_text(encoding="utf-8"))
                 .get("models") or {}).get("providers") or {}
        return {k: (str(v.get("baseUrl") or ""), str(v.get("apiKey") or ""))
                for k, v in provs.items() if isinstance(v, dict)}
    except Exception:  # noqa: BLE001
        return {}


def config_snapshot() -> dict:
    """设置面板展示用：主模型引用 + 全部供应商原始 dict。读不到就返回空快照。"""
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"primary": "", "providers": {}}
    primary = ((((data.get("agents") or {}).get("defaults") or {})
                .get("model") or {}).get("primary")) or ""
    providers = (data.get("models") or {}).get("providers") or {}
    return {"primary": str(primary), "providers": providers if isinstance(providers, dict) else {}}


def sync_chat_providers(provider_updates: dict[str, dict], keep_custom: set[str],
                        primary_ref: str) -> str:
    """同步 chat 供应商到 openclaw.json：更新/新增 + 删除多余自定义 + 主模型。

    provider_updates: {pkey: {"model","base","key"}}；keep_custom: 保留的自定义键；
    primary_ref: 目标主模型（空=不改）。只有确有差异才落盘（改前备份 .bak-web）。
    """
    try:
        path = config_path()
        if not path.is_file():
            return ''
        data = json.loads(path.read_text(encoding='utf-8'))
        providers = data.setdefault('models', {}).setdefault('providers', {})
        changed = False
        for pkey in [k for k in list(providers.keys())
                     if k not in RESERVED_PROVIDER_KEYS and k not in keep_custom]:
            providers.pop(pkey, None)
            changed = True
        for pkey, vals in provider_updates.items():
            prov = providers.setdefault(pkey, {})
            base, key, model = vals.get('base', ''), vals.get('key', ''), vals.get('model', '')
            if base and prov.get('baseUrl') != base:
                if is_local_gateway_base(prov.get('baseUrl')):
                    pass  # 本地模型网关模式：保留网关地址（真实上游在 easel-models.yaml），勿改回直连
                else:
                    prov['baseUrl'] = base
                    changed = True
            if key and prov.get('apiKey') != key:
                prov['apiKey'] = key
                changed = True
            if model:
                models = prov.get('models') if isinstance(prov.get('models'), list) and prov.get('models') else [{}]
                if not isinstance(models[0], dict):
                    models = [{}]
                if models[0].get('id') != model:
                    models[0]['id'] = model
                    changed = True
                prov['models'] = models
        if primary_ref:
            ref = data.setdefault('agents', {}).setdefault('defaults', {}).setdefault('model', {})
            if ref.get('primary') != primary_ref:
                ref['primary'] = primary_ref
                changed = True
        if not changed:
            return ''
        shutil.copy2(path, path.parent / (path.name + '.bak-web'))
        tmp = path.parent / (path.name + '.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(path)
        return 'openclaw 已同步（下一条消息生效）'
    except Exception as e:  # noqa: BLE001
        return f'openclaw 同步失败：{e}'
