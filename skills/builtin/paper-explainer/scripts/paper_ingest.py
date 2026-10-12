#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""paper_ingest.py — 科研论文取原文 + 解析 + 结构化骨架（确定性部分）。

论文解读视频/图文的**确定性 IO** 在这里：拉 arxiv/PDF、解析出正文+图表、产出一份
「结构化 asset library」骨架 JSON（供 LLM 填提炼内容）。**通俗化提炼与分镜脚本由 LLM 完成**。

解析优先用 MinerU（含公式/图表结构化，需 MINERU_API_TOKEN）；无 token 退化到 pdfplumber（纯文本）。
联网遵循 Easel 代理约定：先读 http(s)_proxy，其次 EASEL_PROXY，都无则直连。

子命令：
    check      离线自检：依赖是否就位、MinerU token/代理是否配置
    fetch      arxiv id / url / 本地 PDF → 落地 PDF
    parse      PDF → 正文文本（+ 尽力抽图），dump 到目录
    skeleton   生成 asset-library.json 骨架（空模板，供 LLM 填提炼内容）
    selftest   自检（纯函数，不联网）

用法举例：
    paper_ingest.py check
    paper_ingest.py fetch --paper 2401.12345 -o outputs/paper/attn/paper.pdf
    paper_ingest.py fetch --paper https://arxiv.org/abs/2401.12345 -o .../paper.pdf
    paper_ingest.py parse -i outputs/paper/attn/paper.pdf -o outputs/paper/attn/parsed/
    paper_ingest.py skeleton -o outputs/paper/attn/asset-library.json
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

_ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")
MINERU_BASE = os.environ.get("MINERU_API_BASE", "https://mineru.net")


def _load_env() -> None:
    """向上查找项目 .env 并注入 os.environ（仅当变量未设时），与其它脚本一致。"""
    for directory in (Path.cwd(), *Path.cwd().parents):
        env_file = directory / ".env"
        if not env_file.is_file():
            continue
        try:
            lines = env_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
        return


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _prep_out(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ── 代理（遵循 Easel 约定）──────────────────────────────────────────
def _proxies() -> dict:
    for k in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY"):
        v = os.environ.get(k)
        if v:
            return {"http": v, "https": v}
    v = os.environ.get("EASEL_PROXY")
    if v:
        return {"http": v, "https": v}
    return {}  # 直连


def _opener():
    proxies = _proxies()
    handlers = [urllib.request.ProxyHandler(proxies)] if proxies else [
        urllib.request.ProxyHandler({})]
    return urllib.request.build_opener(*handlers)


# ── arxiv 解析 ────────────────────────────────────────────────────────
def parse_arxiv(paper: str) -> dict:
    """把 arxiv id / abs url / pdf url / 本地路径 归一化。纯函数。

    返回 {kind: 'arxiv'|'url'|'local', id, pdf_url, path}。
    """
    p = paper.strip()
    if p.lower().endswith(".pdf") and ("://" not in p):
        return {"kind": "local", "path": p}
    m = _ARXIV_ID_RE.search(p)
    if "arxiv.org" in p and m:
        aid = m.group(1) + (m.group(2) or "")
        return {"kind": "arxiv", "id": aid,
                "pdf_url": f"https://arxiv.org/pdf/{aid}"}
    if m and "://" not in p:  # 裸 arxiv id
        aid = m.group(1) + (m.group(2) or "")
        return {"kind": "arxiv", "id": aid,
                "pdf_url": f"https://arxiv.org/pdf/{aid}"}
    if p.startswith("http"):
        return {"kind": "url", "pdf_url": p}
    _die(f"无法识别的论文来源：{paper}（给 arxiv id、arxiv 链接或本地 .pdf 路径）")


def fetch(paper: str, out: str) -> str:
    info = parse_arxiv(paper)
    if info["kind"] == "local":
        src = Path(info["path"]).expanduser().resolve()
        if not src.is_file():
            _die(f"本地 PDF 不存在：{src}")
        dst = _prep_out(out)
        if src != dst:
            shutil.copy2(src, dst)
        return str(dst)
    url = info["pdf_url"]
    dst = _prep_out(out)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Easel"})
    try:
        with _opener().open(req, timeout=60) as r:
            data = r.read()
    except Exception as e:
        _die(f"下载失败：{url}\n  {e}\n  （需外网？检查 http(s)_proxy / EASEL_PROXY）")
    if not data[:5] == b"%PDF-":
        _die(f"下载内容不是 PDF（可能是页面/重定向）：{url}")
    dst.write_bytes(data)
    return str(dst)


# ── 解析 PDF ──────────────────────────────────────────────────────────
def _oss_put(url: str, pdf: Path, proxies) -> None:
    """PUT 上传到 OSS 预签名 URL：先直连(忽略环境代理)，失败再走代理。

    很多内网代理放行 mineru.net 却挡 aliyuncs OSS；而 OSS 常可直连，故直连优先。
    """
    import requests
    errs = []
    for tag, trust_env, use_proxy, tmo in (("直连", False, False, 180),
                                           ("代理", True, True, 600)):
        if use_proxy and not proxies:
            continue
        try:
            s = requests.Session()
            s.trust_env = trust_env
            with open(pdf, "rb") as f:
                r = s.put(url, data=f, timeout=tmo,
                          proxies=(proxies if use_proxy else None))
            if r.status_code == 200:
                return
            errs.append(f"{tag} HTTP {r.status_code}")
        except Exception as e:
            errs.append(f"{tag} {e}")
    raise RuntimeError("OSS 上传失败（直连+代理均不通）：" + "; ".join(errs))


def _oss_get(url: str, proxies) -> bytes:
    """GET 下载 OSS 资源（结果 zip）：先直连，失败走代理。返回 bytes。"""
    import requests
    errs = []
    for tag, trust_env, use_proxy, tmo in (("直连", False, False, 180),
                                           ("代理", True, True, 600)):
        if use_proxy and not proxies:
            continue
        try:
            s = requests.Session()
            s.trust_env = trust_env
            r = s.get(url, timeout=tmo, proxies=(proxies if use_proxy else None))
            if r.status_code == 200:
                return r.content
            errs.append(f"{tag} HTTP {r.status_code}")
        except Exception as e:
            errs.append(f"{tag} {e}")
    raise RuntimeError("OSS 下载失败（直连+代理均不通）：" + "; ".join(errs))


def _mineru_rest(pdf: Path, out_dir: Path, token: str) -> dict:
    """MinerU v4 本地文件解析：申请上传链接 → PUT 上传 → 轮询 → 下载解压。

    依据 https://mineru.net/apiManage/docs 的 v4「文件上传批量解析」流程实现。
    可用 env 调：MINERU_MODEL(pipeline|vlm|MinerU-HTML,默认 pipeline)、MINERU_LANG、
    MINERU_TIMEOUT(轮询秒,默认 900)、MINERU_API_BASE。
    """
    import requests  # 仅 MinerU 路径需要；未装由上层降级 pdfplumber

    proxies = _proxies() or None
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {token}", "Accept": "*/*"}
    model = os.environ.get("MINERU_MODEL", "pipeline")
    entry = {"name": pdf.name, "is_ocr": False,
             "data_id": "easel_" + re.sub(r"[^0-9A-Za-z_.-]", "_", pdf.stem)[:64]}
    payload = {"enable_formula": True, "enable_table": True,
               "model_version": model, "files": [entry]}
    lang = os.environ.get("MINERU_LANG")
    if lang:
        payload["language"] = lang

    # 1) 申请上传链接
    r = requests.post(f"{MINERU_BASE}/api/v4/file-urls/batch",
                      headers=headers, json=payload, proxies=proxies, timeout=60)
    j = r.json()
    if j.get("code") != 0:
        raise RuntimeError(f"申请上传链接失败 code={j.get('code')} msg={j.get('msg')}")
    batch_id = j["data"]["batch_id"]
    up_url = j["data"]["file_urls"][0]

    # 2) PUT 上传（OSS 预签名：直连优先、代理兜底；不带 Content-Type/Authorization）
    _oss_put(up_url, pdf, proxies)

    # 3) 轮询结果
    result_url = f"{MINERU_BASE}/api/v4/extract-results/batch/{batch_id}"
    deadline = time.time() + int(os.environ.get("MINERU_TIMEOUT", "900"))
    zip_url, last = None, ""
    while time.time() < deadline:
        rr = requests.get(result_url, headers=headers, proxies=proxies, timeout=60).json()
        items = (rr.get("data") or {}).get("extract_result") or []
        if not items:
            time.sleep(5)
            continue
        it = items[0]
        st = it.get("state")
        if st != last:
            prog = it.get("extract_progress") or {}
            extra = (f" {prog.get('extracted_pages','')}/{prog.get('total_pages','')}页"
                     if prog else "")
            print(f"  MinerU: {st}{extra}", file=sys.stderr)
            last = st
        if st == "done":
            zip_url = it.get("full_zip_url")
            break
        if st == "failed":
            raise RuntimeError(f"MinerU 解析失败：{it.get('err_msg')}")
        time.sleep(5)
    if not zip_url:
        raise RuntimeError("MinerU 轮询超时（可调大 MINERU_TIMEOUT）")

    # 下载并解压结果 zip（含 full.md + images + layout.json 等）
    mineru_dir = out_dir / "mineru"
    mineru_dir.mkdir(parents=True, exist_ok=True)
    zip_bytes = _oss_get(zip_url, proxies)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        z.extractall(mineru_dir)

    mds = sorted(mineru_dir.rglob("*.md"), key=lambda p: -p.stat().st_size)
    if not mds:
        raise RuntimeError("MinerU 结果 zip 内未找到 markdown")
    content = out_dir / "content.md"
    text = mds[0].read_text(encoding="utf-8", errors="replace")
    content.write_text(text, encoding="utf-8")
    figs = [str(p) for p in sorted(mineru_dir.rglob("*"))
            if p.suffix.lower() in {".png", ".jpg", ".jpeg"}]
    return {"engine": f"mineru:{model}", "text_file": str(content),
            "chars": len(text), "figures": figs, "batch_id": batch_id}


def _parse_mineru(pdf: Path, out_dir: Path) -> dict | None:
    """MinerU 云解析（含公式/图表结构化）。需 MINERU_API_TOKEN；失败返回 None 由上层降级。"""
    token = os.environ.get("MINERU_API_TOKEN")
    if not token:
        return None
    try:
        return _mineru_rest(pdf, out_dir, token)
    except Exception as e:
        print(f"  (MinerU 解析不可用，降级 pdfplumber：{e})", file=sys.stderr)
        return None


def _parse_pdfplumber(pdf: Path, out_dir: Path) -> dict:
    try:
        import pdfplumber
    except Exception:
        _die("未安装 pdfplumber，且 MinerU 不可用。请 `pip install pdfplumber` "
             "或配置 MINERU_API_TOKEN。")
    texts = []
    with pdfplumber.open(str(pdf)) as doc:
        for i, page in enumerate(doc.pages):
            texts.append(f"\n\n===== PAGE {i + 1} =====\n" + (page.extract_text() or ""))
    full = "".join(texts)
    tf = out_dir / "content.txt"
    tf.write_text(full, encoding="utf-8")
    figs = _extract_figures(pdf, out_dir)
    return {"engine": "pdfplumber", "text_file": str(tf),
            "chars": len(full), "figures": figs}


def _extract_figures(pdf: Path, out_dir: Path) -> list[str]:
    """尽力抽图（PyMuPDF 有则用，无则跳过）。返回图片路径列表。"""
    try:
        import fitz  # PyMuPDF
    except Exception:
        return []
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    try:
        doc = fitz.open(str(pdf))
        for pno in range(len(doc)):
            for j, img in enumerate(doc.get_page_images(pno)):
                xref = img[0]
                pix = fitz.Pixmap(doc, xref)
                if pix.n - pix.alpha >= 4:  # CMYK → RGB
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                fp = fig_dir / f"p{pno + 1}_img{j + 1}.png"
                pix.save(str(fp))
                saved.append(str(fp))
    except Exception as e:
        print(f"  (抽图失败，跳过：{e})", file=sys.stderr)
    return saved


def parse(pdf_path: str, out_dir: str) -> dict:
    pdf = Path(pdf_path).expanduser()
    if not pdf.is_file():
        _die(f"PDF 不存在：{pdf}")
    od = Path(out_dir).expanduser()
    od.mkdir(parents=True, exist_ok=True)
    result = _parse_mineru(pdf, od) or _parse_pdfplumber(pdf, od)
    (od / "parse-meta.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


# ── asset library 骨架 ────────────────────────────────────────────────
def skeleton() -> dict:
    """结构化 asset library 骨架（视频与图文两条产线共用同一次提炼）。"""
    return {
        "meta": {"title": "", "authors": [], "venue": "", "arxiv_id": "", "url": ""},
        "one_liner": "",              # 一句话讲清这篇干了啥（大白话）
        "hook": "",                   # 视频/图文开头钩子
        "problem": "",                # 解决什么问题、为什么重要
        "prior_gap": "",              # 已有方法的不足
        "contributions": [],          # 核心贡献点（3 条以内）
        "method": {"idea": "", "how": "", "analogy": ""},  # 方法 + 通俗类比
        "key_figures": [              # 关键图表（引用 parse 抽出的图）
            {"id": "", "path": "", "caption": "",
             "why_matters": "", "plain": ""}  # plain = 大白话解释这张图
        ],
        "results": "",                # 主要结果（含关键数字）
        "limitations": "",            # 局限
        "takeaway": "",               # 对观众意味着什么
        "terms": []                   # 需要通俗解释的术语表 [{term, plain}]
    }


# ── check / selftest ──────────────────────────────────────────────────
def check() -> int:
    print("paper_ingest 环境自检：")
    ok = True
    try:
        import pdfplumber  # noqa
        print("  [✓] pdfplumber 已安装（PDF 文本解析兜底可用）")
    except Exception:
        print("  [✗] pdfplumber 未安装（pip install pdfplumber）")
        ok = False
    try:
        import fitz  # noqa
        print("  [✓] PyMuPDF(fitz) 已安装（可抽图）")
    except Exception:
        print("  [ ] PyMuPDF 未安装（可选，装了能抽论文原图：pip install pymupdf）")
    if os.environ.get("MINERU_API_TOKEN"):
        print("  [✓] MINERU_API_TOKEN 已配置（走 MinerU v4 云解析，含公式/图表结构化）")
        try:
            import requests  # noqa
            print("  [✓] requests 已安装（MinerU REST 调用可用）")
        except Exception:
            print("  [✗] requests 未装（MinerU 需要：pip install requests），当前会降级 pdfplumber")
            ok = False
    else:
        print("  [ ] MINERU_API_TOKEN 未配置（用 pdfplumber 兜底，无公式结构化）")
    px = _proxies()
    print(f"  [i] 联网代理：{px.get('https') if px else '直连（未设代理）'}")
    return 0 if ok else 1


def _selftest() -> int:
    ok = True

    def chk(name, cond):
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {name}")
        ok = ok and cond

    a = parse_arxiv("2401.12345")
    chk("arxiv 裸 id", a["kind"] == "arxiv" and a["pdf_url"].endswith("2401.12345"))
    a = parse_arxiv("https://arxiv.org/abs/2401.12345v2")
    chk("arxiv abs url + 版本", a["id"] == "2401.12345v2")
    a = parse_arxiv("https://arxiv.org/pdf/2401.12345")
    chk("arxiv pdf url", a["kind"] == "arxiv" and a["id"] == "2401.12345")
    a = parse_arxiv("/tmp/some/paper.pdf")
    chk("本地 pdf", a["kind"] == "local" and a["path"].endswith("paper.pdf"))
    a = parse_arxiv("https://example.com/foo.pdf")
    chk("通用 url", a["kind"] == "url")

    sk = skeleton()
    chk("skeleton 结构完整",
        set(sk) >= {"meta", "one_liner", "hook", "problem", "contributions",
                    "method", "key_figures", "results", "takeaway", "terms"}
        and set(sk["method"]) == {"idea", "how", "analogy"})

    # 代理解析
    os.environ.pop("https_proxy", None)
    os.environ.pop("HTTPS_PROXY", None)
    os.environ.pop("http_proxy", None)
    os.environ.pop("HTTP_PROXY", None)
    os.environ.pop("EASEL_PROXY", None)
    chk("无代理时直连", _proxies() == {})
    os.environ["EASEL_PROXY"] = "http://x:3128"
    chk("EASEL_PROXY 生效", _proxies().get("https") == "http://x:3128")
    os.environ.pop("EASEL_PROXY", None)

    print("✅ selftest 通过" if ok else "❌ selftest 失败")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="论文取原文 + 解析 + 结构化骨架（确定性部分）",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="环境自检")

    pf = sub.add_parser("fetch", help="拉论文 PDF")
    pf.add_argument("--paper", required=True, help="arxiv id / 链接 / 本地 .pdf")
    pf.add_argument("-o", "--output", required=True)

    pp = sub.add_parser("parse", help="解析 PDF → 文本(+图)")
    pp.add_argument("-i", "--input", required=True, help="PDF 路径")
    pp.add_argument("-o", "--output", required=True, help="输出目录")

    psk = sub.add_parser("skeleton", help="生成 asset-library 骨架")
    psk.add_argument("-o", "--output", required=True)

    sub.add_parser("selftest", help="自检（纯函数）")

    a = ap.parse_args()
    _load_env()  # 注入项目 .env（MINERU_API_TOKEN 等），仅当未在环境时
    if a.cmd == "check":
        return check()
    if a.cmd == "selftest":
        return _selftest()
    if a.cmd == "fetch":
        print(f"✅ {fetch(a.paper, a.output)}")
        return 0
    if a.cmd == "parse":
        r = parse(a.input, a.output)
        print(f"✅ 解析完成（{r['engine']}）→ {a.output}")
        if r.get("figures"):
            print(f"   抽出 {len(r['figures'])} 张图")
        return 0
    if a.cmd == "skeleton":
        out = _prep_out(a.output)
        out.write_text(json.dumps(skeleton(), ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"✅ {out}（asset library 骨架，供填提炼内容）")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
