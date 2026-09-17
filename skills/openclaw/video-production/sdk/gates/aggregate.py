#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""七件门聚合 -> gate-report.md + gate-report.json（支持 verify / render 双相与报告合并）

配置：<run-dir>/gates.json
  {"gates": [
     {"id": "frames", "title": "帧检", "phase": "verify", "cmd": "..."},
     {"id": "audio",  "title": "响度门（成片）", "phase": "render", "cmd": "..."}
  ]}
phase 缺省 = verify。聚合结果按 id 合并进既有报告（verify 先跑，render 后跑，互不覆盖）。
退出码：0 本相全过 ｜ 2 本相有 FAIL ｜ 1 配置缺失
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SDK_ROOT = Path(__file__).resolve().parent.parent


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def write_reports(rd: Path, gates_entries: list, note: str = ""):
    total = len(gates_entries)
    npass = sum(1 for r in gates_entries if r["status"] == "PASS")
    nfail = sum(1 for r in gates_entries if r["status"] == "FAIL")
    rep = {"generated_at": now_iso(), "summary": {"total": total, "pass": npass, "fail": nfail, "note": note},
           "gates": gates_entries}
    (rd / "gate-report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 核验报告（gate-report）", "",
             f"> {now_iso()} ｜ 共 {total} 项：通过 {npass}，失败 {nfail}" + (f" ｜ {note}" if note else ""), ""]
    for r in gates_entries:
        lines.append(f"## [{'PASS' if r['status'] == 'PASS' else 'FAIL'}] {r['id']} · {r['title']}（{r.get('phase', 'verify')}）")
        lines.append("")
        lines.append(f"- cmd: `{r['cmd']}`")
        lines.append(f"- exit: {r['exit']} ｜ {r['seconds']:.1f}s")
        if r["status"] != "PASS":
            lines.append("- 输出尾部：")
            lines.append("```")
            lines.extend(r.get("tail") or [])
            lines.append("```")
        lines.append("")
    (rd / "gate-report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"报告：{rd / 'gate-report.md'}")
    print(f"现状：共 {total} 项，通过 {npass}，失败 {nfail}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--gates", default=None, help="gates 配置 JSON（默认 <run-dir>/gates.json）")
    ap.add_argument("--phase", default="verify", choices=["verify", "render", "all"])
    args = ap.parse_args()
    rd = Path(args.run_dir).resolve()
    cfg_path = Path(args.gates) if args.gates else rd / "gates.json"
    report = rd / "gate-report.json"
    merged = []
    if report.is_file():
        try:
            merged = json.loads(report.read_text(encoding="utf-8")).get("gates", [])
        except Exception:  # noqa: BLE001
            merged = []
    if not cfg_path.is_file():
        write_reports(rd, merged, note="未配置门（gates.json 缺失）——不算通过")
        sys.exit(1)
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        write_reports(rd, merged, note=f"gates.json 无法解析：{e}")
        print(f"gates.json 无法解析：{e}", file=sys.stderr)
        sys.exit(1)
    entries = [g for g in cfg.get("gates", [])
               if args.phase == "all" or g.get("phase", "verify") == args.phase]
    # {run_dir} / {out_dir} 占位符替换（手写 gates.json 也可直接用占位符）
    _outd = ""
    _stp = rd / "run-state.json"
    if _stp.is_file():
        try:
            _outd = json.loads(_stp.read_text(encoding="utf-8")).get("out_dir") or ""
        except Exception:  # noqa: BLE001
            _outd = ""
    for _g in entries:
        _cmd = _g.get("cmd")
        if isinstance(_cmd, str) and ("{run_dir}" in _cmd or "{out_dir}" in _cmd):
            _g["cmd"] = (_cmd.replace("{run_dir}", str(rd).replace("\\", "/"))
                             .replace("{out_dir}", str(_outd).replace("\\", "/")))
    results = []
    for g in entries:
        gid, title = g.get("id", "gate"), g.get("title", g.get("id", "gate"))
        cmd = g.get("cmd", "")
        cwd = g.get("cwd", str(SDK_ROOT))
        t0 = time.time()
        try:
            if os.name == "nt":
                comspec = os.environ.get("COMSPEC", "")
                if "cmd.exe" not in comspec.lower():
                    comspec = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cmd.exe")
                argv = [comspec, "/c", cmd]
            else:
                argv = ["/bin/sh", "-c", cmd]
            r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=g.get("timeout"))
            code, out = r.returncode, (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
        except subprocess.TimeoutExpired:
            code, out = 124, f"timeout {g.get('timeout')}s"
        tail = [ln for ln in out.strip().splitlines() if ln.strip()][-30:]
        results.append({"id": gid, "title": title, "phase": g.get("phase", "verify"), "cmd": cmd,
                        "exit": code, "status": "PASS" if code == 0 else "FAIL",
                        "seconds": time.time() - t0, "tail": tail})
        print(f"[{'PASS' if code == 0 else 'FAIL'}] {gid} · {title}")
    # 合并：新结果按 id 覆盖旧条目
    by_id = {r["id"]: r for r in merged}
    for r in results:
        by_id[r["id"]] = r
    write_reports(rd, list(by_id.values()))
    phase_fail = [r for r in results if r["status"] == "FAIL"]
    sys.exit(0 if not phase_fail else 2)


if __name__ == "__main__":
    main()
