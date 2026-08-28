#!/usr/bin/env python3
"""report.py — CSV/Excel/JSON → 数据概览 / 整页可视化报告（pandas + matplotlib）。

把 data-report SKILL 里"读数据 → 算 KPI → 出图 → 拼 HTML"这条确定性流程
固化为脚本，避免 LLM 心算聚合、手拼 base64、现场调 matplotlib 出中文豆腐块。

两个子命令：
  analyze  读数据 → 输出数据概览 JSON（行列数/列类型/数值列统计/缺失/Top 类别），
           供 LLM 据此写洞察文字。
  report   读数据 → 计算 KPI + 自动选型出 2-4 张图（类别柱状/时间序列折线/占比饼）
           → 生成自包含 HTML（KPI 卡 + 内嵌 base64 图 + 数据表）写到 --output。

用法：
    report.py analyze data.csv
    report.py analyze data.csv -o overview.json
    report.py report data.csv -o outputs/report.html --title "7 月销售周报"
    report.py report data.xlsx -o report.html --kpi 销量 金额
    report.py --selftest

依赖：pandas、matplotlib（Agg 后端）、标准库。Excel 需 openpyxl（缺失则提示）。
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 无显示环境
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

# --------------------------------------------------------------------------- #
# 中文字体：找系统中文字体避免乱码/豆腐块
# --------------------------------------------------------------------------- #
_CJK_CANDIDATES = [
    "WenQuanYi Micro Hei", "WenQuanYi Zen Hei", "Noto Sans CJK SC",
    "Noto Sans CJK", "Source Han Sans SC", "Source Han Sans CN",
    "Microsoft YaHei", "SimHei", "PingFang SC", "Heiti SC", "Droid Sans Fallback",
]


def _setup_cjk_font() -> str | None:
    """把系统里能找到的中文字体设进 rcParams，返回选中的字体名。"""
    from matplotlib import font_manager

    available = {f.name for f in font_manager.fontManager.ttflist}
    chosen = next((c for c in _CJK_CANDIDATES if c in available), None)
    if chosen is None:
        # 兜底：扫常见路径手动注册
        for p in ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
                  "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
            if Path(p).is_file():
                font_manager.fontManager.addfont(p)
                chosen = font_manager.FontProperties(fname=p).get_name()
                break
    if chosen:
        plt.rcParams["font.sans-serif"] = [chosen] + _CJK_CANDIDATES
    plt.rcParams["axes.unicode_minus"] = False  # 负号正常显示
    return chosen


# 简洁配色
_PALETTE = ["#4C72B0", "#55A868", "#C44E52", "#8172B3", "#CCB974",
            "#64B5CD", "#E17C05", "#5D9C59"]


# --------------------------------------------------------------------------- #
# 读数据
# --------------------------------------------------------------------------- #
def load_data(path: str) -> pd.DataFrame:
    """按扩展名读 CSV/JSON/Excel。错误抛 ValueError（带中文说明）。"""
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"文件不存在: {path}")
    suf = p.suffix.lower()
    try:
        if suf == ".csv":
            df = pd.read_csv(p)
        elif suf in (".json",):
            df = pd.read_json(p)
        elif suf in (".xlsx", ".xls"):
            try:
                import openpyxl  # noqa: F401
            except ImportError:
                raise ValueError(
                    "读取 Excel 需要 openpyxl，请先 `pip install openpyxl`，"
                    "或把数据另存为 CSV 后重试。")
            df = pd.read_excel(p)
        else:
            raise ValueError(f"不支持的文件类型: {suf}（支持 .csv/.json/.xlsx）")
    except ValueError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"读取失败: {e}")
    if df.empty:
        raise ValueError("数据为空（0 行），无法分析")
    return df


def _col_kind(s: pd.Series) -> str:
    if pd.api.types.is_numeric_dtype(s):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "datetime"
    return "categorical"


def _detect_datetime_col(df: pd.DataFrame) -> str | None:
    """找一列能当时间轴的列：已是 datetime，或名字像日期且可解析。"""
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            return c
    hint = ("date", "time", "日期", "时间", "月", "年", "day", "month", "week", "周")
    for c in df.columns:
        if any(h in str(c).lower() for h in hint):
            try:
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    parsed = pd.to_datetime(df[c], errors="coerce")
                if parsed.notna().mean() > 0.7:
                    return c
            except Exception:  # noqa: BLE001
                continue
    return None


# --------------------------------------------------------------------------- #
# analyze
# --------------------------------------------------------------------------- #
def analyze(df: pd.DataFrame) -> dict:
    """产出数据概览 dict（可 json 序列化）。"""
    rows, cols = df.shape
    numeric_cols = [c for c in df.columns if _col_kind(df[c]) == "numeric"]
    cat_cols = [c for c in df.columns if _col_kind(df[c]) == "categorical"]
    dt_col = _detect_datetime_col(df)

    columns_info = []
    for c in df.columns:
        kind = _col_kind(df[c])
        info = {
            "name": str(c),
            "type": kind,
            "dtype": str(df[c].dtype),
            "missing": int(df[c].isna().sum()),
            "missing_pct": round(float(df[c].isna().mean()) * 100, 2),
            "unique": int(df[c].nunique(dropna=True)),
        }
        columns_info.append(info)

    numeric_stats = {}
    for c in numeric_cols:
        s = pd.to_numeric(df[c], errors="coerce").dropna()
        if s.empty:
            continue
        numeric_stats[str(c)] = {
            "min": round(float(s.min()), 4),
            "max": round(float(s.max()), 4),
            "mean": round(float(s.mean()), 4),
            "median": round(float(s.median()), 4),
            "sum": round(float(s.sum()), 4),
            "std": round(float(s.std()), 4) if len(s) > 1 else 0.0,
        }

    top_categories = {}
    for c in cat_cols:
        vc = df[c].astype(str).value_counts().head(5)
        top_categories[str(c)] = [
            {"value": str(k), "count": int(v)} for k, v in vc.items()
        ]

    return {
        "shape": {"rows": int(rows), "cols": int(cols)},
        "columns": columns_info,
        "numeric_columns": [str(c) for c in numeric_cols],
        "categorical_columns": [str(c) for c in cat_cols],
        "datetime_column": str(dt_col) if dt_col else None,
        "numeric_stats": numeric_stats,
        "top_categories": top_categories,
        "total_missing": int(df.isna().sum().sum()),
    }


# --------------------------------------------------------------------------- #
# 图表生成
# --------------------------------------------------------------------------- #
def _fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def _new_fig():
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    return fig, ax


def build_charts(df: pd.DataFrame, overview: dict) -> list[dict]:
    """自动选型生成 2-4 张图，返回 [{title, b64}]。"""
    charts: list[dict] = []
    numeric_cols = overview["numeric_columns"]
    cat_cols = overview["categorical_columns"]
    dt_col = overview["datetime_column"]

    if not numeric_cols:
        return charts

    main_num = numeric_cols[0]

    # 1) 时间序列 → 折线图
    if dt_col:
        try:
            tmp = df[[dt_col, main_num]].copy()
            tmp[dt_col] = pd.to_datetime(tmp[dt_col], errors="coerce")
            tmp = tmp.dropna(subset=[dt_col]).sort_values(dt_col)
            tmp[main_num] = pd.to_numeric(tmp[main_num], errors="coerce")
            if not tmp.empty:
                fig, ax = _new_fig()
                ax.plot(tmp[dt_col], tmp[main_num], marker="o",
                        color=_PALETTE[0], linewidth=2, markersize=4)
                ax.set_title(f"{main_num} 时间趋势")
                ax.set_xlabel(str(dt_col))
                ax.set_ylabel(str(main_num))
                ax.grid(True, alpha=0.3)
                fig.autofmt_xdate()
                charts.append({"title": f"{main_num} 时间趋势",
                               "b64": _fig_to_b64(fig)})
        except Exception:  # noqa: BLE001
            pass

    # 2) 类别 → 柱状图（按第一个类别列聚合 main_num 求和）
    cat_for_bar = next((c for c in cat_cols if c != dt_col), None)
    if cat_for_bar is not None:
        try:
            grp = (df.groupby(cat_for_bar)[main_num]
                   .apply(lambda s: pd.to_numeric(s, errors="coerce").sum())
                   .sort_values(ascending=False).head(10))
            if not grp.empty:
                fig, ax = _new_fig()
                ax.bar([str(x) for x in grp.index], grp.values,
                       color=_PALETTE[:len(grp)] if len(grp) <= len(_PALETTE)
                       else _PALETTE[0])
                ax.set_title(f"各{cat_for_bar}的{main_num}")
                ax.set_ylabel(str(main_num))
                plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
                ax.grid(True, axis="y", alpha=0.3)
                charts.append({"title": f"各{cat_for_bar}的{main_num}",
                               "b64": _fig_to_b64(fig)})

                # 3) 占比 → 饼图（类别数 <= 8 时才有意义）
                if 2 <= len(grp) <= 8 and (grp.values >= 0).all():
                    fig, ax = _new_fig()
                    ax.pie(grp.values, labels=[str(x) for x in grp.index],
                           autopct="%1.1f%%", colors=_PALETTE[:len(grp)],
                           startangle=90)
                    ax.set_title(f"{main_num}占比")
                    ax.axis("equal")
                    charts.append({"title": f"{main_num}占比",
                                   "b64": _fig_to_b64(fig)})
        except Exception:  # noqa: BLE001
            pass

    # 4) 若还没图（纯数值表）→ 数值列分布柱状
    if not charts and numeric_cols:
        try:
            fig, ax = _new_fig()
            sums = {c: pd.to_numeric(df[c], errors="coerce").sum()
                    for c in numeric_cols[:8]}
            ax.bar(list(sums.keys()), list(sums.values()),
                   color=_PALETTE[:len(sums)])
            ax.set_title("数值列汇总")
            plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
            ax.grid(True, axis="y", alpha=0.3)
            charts.append({"title": "数值列汇总", "b64": _fig_to_b64(fig)})
        except Exception:  # noqa: BLE001
            pass

    # 若只有一张图但有多个数值列，补一张多数值列对比
    if len(charts) < 2 and len(numeric_cols) >= 2:
        try:
            fig, ax = _new_fig()
            sums = {c: pd.to_numeric(df[c], errors="coerce").sum()
                    for c in numeric_cols[:8]}
            ax.bar(list(sums.keys()), list(sums.values()),
                   color=_PALETTE[:len(sums)])
            ax.set_title("数值列汇总对比")
            plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
            ax.grid(True, axis="y", alpha=0.3)
            charts.append({"title": "数值列汇总对比", "b64": _fig_to_b64(fig)})
        except Exception:  # noqa: BLE001
            pass

    return charts[:4]


# --------------------------------------------------------------------------- #
# KPI
# --------------------------------------------------------------------------- #
def _fmt_num(v: float) -> str:
    if v == int(v):
        return f"{int(v):,}"
    return f"{v:,.2f}"


def build_kpis(overview: dict, kpi_cols: list[str] | None) -> list[dict]:
    """从数值列统计里挑 KPI。缺省取前 4 个数值列的 sum。"""
    stats = overview["numeric_stats"]
    if kpi_cols:
        cols = [c for c in kpi_cols if c in stats]
    else:
        cols = list(stats.keys())[:4]
    kpis = []
    for c in cols:
        st = stats[c]
        kpis.append({
            "label": c,
            "value": _fmt_num(st["sum"]),
            "sub": f"均值 {_fmt_num(st['mean'])} · 峰值 {_fmt_num(st['max'])}",
        })
    return kpis


# --------------------------------------------------------------------------- #
# HTML 组装
# --------------------------------------------------------------------------- #
def _esc(x) -> str:
    from html import escape
    return escape(str(x))


def build_html(df: pd.DataFrame, overview: dict, charts: list[dict],
               kpis: list[dict], title: str) -> str:
    import datetime as _dt

    kpi_html = "".join(
        f'<div class="kpi"><div class="kpi-val">{_esc(k["value"])}</div>'
        f'<div class="kpi-label">{_esc(k["label"])}</div>'
        f'<div class="kpi-sub">{_esc(k["sub"])}</div></div>'
        for k in kpis
    ) or '<div class="kpi"><div class="kpi-val">—</div>' \
         '<div class="kpi-label">无数值列</div></div>'

    charts_html = "".join(
        f'<div class="chart"><h3>{_esc(c["title"])}</h3>'
        f'<img src="data:image/png;base64,{c["b64"]}" alt="{_esc(c["title"])}"/></div>'
        for c in charts
    ) or '<p class="empty">无可绘制的数值数据</p>'

    # 数据表（最多 20 行）
    head = df.head(20)
    thead = "".join(f"<th>{_esc(c)}</th>" for c in head.columns)
    trows = "".join(
        "<tr>" + "".join(f"<td>{_esc(v)}</td>" for v in row) + "</tr>"
        for row in head.itertuples(index=False, name=None)
    )
    more = (f'<p class="note">仅显示前 20 行，共 {overview["shape"]["rows"]} 行。</p>'
            if overview["shape"]["rows"] > 20 else "")

    ts = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>
  :root {{ --main:#4C72B0; --bg:#f6f7f9; --card:#fff; --ink:#1f2937; --muted:#6b7280; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font-family:"WenQuanYi Micro Hei","Noto Sans CJK SC","Microsoft YaHei",sans-serif; }}
  .wrap {{ max-width:1080px; margin:0 auto; padding:32px 20px 56px; }}
  header h1 {{ margin:0 0 6px; font-size:28px; }}
  header .meta {{ color:var(--muted); font-size:13px; }}
  .kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
    gap:14px; margin:24px 0; }}
  .kpi {{ background:var(--card); border-radius:14px; padding:18px 20px;
    box-shadow:0 1px 3px rgba(0,0,0,.06); border-top:3px solid var(--main); }}
  .kpi-val {{ font-size:26px; font-weight:700; }}
  .kpi-label {{ color:var(--muted); font-size:13px; margin-top:4px; }}
  .kpi-sub {{ color:#9aa3af; font-size:11px; margin-top:6px; }}
  .charts {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr));
    gap:18px; margin:8px 0 24px; }}
  .chart {{ background:var(--card); border-radius:14px; padding:16px;
    box-shadow:0 1px 3px rgba(0,0,0,.06); }}
  .chart h3 {{ margin:0 0 10px; font-size:15px; }}
  .chart img {{ width:100%; height:auto; display:block; }}
  section h2 {{ font-size:18px; margin:28px 0 12px; }}
  table {{ width:100%; border-collapse:collapse; background:var(--card);
    border-radius:12px; overflow:hidden; font-size:13px; box-shadow:0 1px 3px rgba(0,0,0,.06); }}
  thead th {{ position:sticky; top:0; background:var(--main); color:#fff;
    padding:10px 12px; text-align:left; font-weight:600; }}
  tbody td {{ padding:8px 12px; border-top:1px solid #eef0f3; }}
  tbody tr:nth-child(even) {{ background:#fafbfc; }}
  tbody tr:hover {{ background:#eef4fb; }}
  .table-wrap {{ max-height:520px; overflow:auto; border-radius:12px; }}
  .note, .empty {{ color:var(--muted); font-size:12px; }}
  footer {{ margin-top:36px; color:#9aa3af; font-size:12px; text-align:center; }}
</style></head>
<body><div class="wrap">
  <header>
    <h1>{_esc(title)}</h1>
    <div class="meta">生成于 {ts} · {overview["shape"]["rows"]} 行 × {overview["shape"]["cols"]} 列
      · 缺失值 {overview["total_missing"]} 个</div>
  </header>
  <div class="kpis">{kpi_html}</div>
  <section><h2>图表</h2><div class="charts">{charts_html}</div></section>
  <section><h2>数据明细</h2>
    <div class="table-wrap"><table><thead><tr>{thead}</tr></thead>
    <tbody>{trows}</tbody></table></div>{more}</section>
  <footer>Easel data-report · 由 report.py 自动生成</footer>
</div></body></html>"""


# --------------------------------------------------------------------------- #
# 子命令入口
# --------------------------------------------------------------------------- #
def cmd_analyze(args) -> int:
    try:
        df = load_data(args.input)
        overview = analyze(df)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    out = json.dumps(overview, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        print(f"✅ 数据概览已写入 {args.output}")
    else:
        print(out)
    return 0


def cmd_report(args) -> int:
    try:
        df = load_data(args.input)
        overview = analyze(df)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if not overview["numeric_columns"]:
        print("WARN: 数据中没有数值列，报告将只含数据表（无 KPI/图表）",
              file=sys.stderr)
    _setup_cjk_font()
    charts = build_charts(df, overview)
    kpis = build_kpis(overview, args.kpi)
    html = build_html(df, overview, charts, kpis, args.title)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"✅ 报告已生成: {out}")
    print(f"   KPI {len(kpis)} 个 · 图表 {len(charts)} 张 · "
          f"数据 {overview['shape']['rows']}×{overview['shape']['cols']}")
    return 0


# --------------------------------------------------------------------------- #
# selftest
# --------------------------------------------------------------------------- #
def _selftest() -> int:
    import tempfile

    rows = []
    cats = ["华东", "华北", "华南"]
    for i in range(12):
        rows.append({
            "日期": f"2026-07-{i + 1:02d}",
            "销量": 100 + i * 7 + (i % 3) * 15,
            "金额": 2000 + i * 130,
            "区域": cats[i % 3],
        })
    df = pd.DataFrame(rows)

    with tempfile.TemporaryDirectory() as d:
        csv_p = Path(d) / "sales.csv"
        df.to_csv(csv_p, index=False, encoding="utf-8")

        # analyze
        loaded = load_data(str(csv_p))
        ov = analyze(loaded)
        assert ov["shape"] == {"rows": 12, "cols": 4}, ov["shape"]
        assert "销量" in ov["numeric_columns"] and "金额" in ov["numeric_columns"]
        assert ov["datetime_column"] == "日期", ov["datetime_column"]
        assert "区域" in ov["categorical_columns"]
        assert ov["numeric_stats"]["销量"]["sum"] > 0
        assert ov["top_categories"]["区域"], "应有 Top 类别"
        print("[analyze] OK:", ov["shape"], "数值列", ov["numeric_columns"])

        # report
        _setup_cjk_font()
        charts = build_charts(loaded, ov)
        kpis = build_kpis(ov, None)
        assert len(charts) >= 1, "至少 1 张图表"
        assert len(kpis) >= 1, "至少 1 个 KPI"
        html = build_html(loaded, ov, charts, kpis, "自检报告")
        html_p = Path(d) / "report.html"
        html_p.write_text(html, encoding="utf-8")
        assert html_p.is_file() and html_p.stat().st_size > 1000
        assert "kpi-val" in html, "HTML 应含 KPI 卡片"
        assert "data:image/png;base64," in html, "HTML 应含内嵌图表"
        assert "销量" in html
        print(f"[report] OK: {len(kpis)} KPI, {len(charts)} 图表, "
              f"HTML {html_p.stat().st_size} 字节")

        # 错误处理
        try:
            load_data(str(Path(d) / "nope.csv"))
            print("[FAIL] 缺文件未报错"); return 1
        except ValueError:
            pass
        empty_p = Path(d) / "empty.csv"
        empty_p.write_text("a,b\n", encoding="utf-8")
        try:
            load_data(str(empty_p))
            print("[FAIL] 空数据未报错"); return 1
        except ValueError:
            pass

    font = _setup_cjk_font()
    print(f"[font] 中文字体: {font or '未找到（可能乱码）'}")
    print("[PASS] data-report/report.py 全部自检通过")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="CSV/Excel/JSON → 数据概览 / 可视化报告")
    ap.add_argument("--selftest", action="store_true", help="运行自检")
    sub = ap.add_subparsers(dest="cmd")

    pa = sub.add_parser("analyze", help="输出数据概览 JSON")
    pa.add_argument("input", help="数据文件 .csv/.json/.xlsx")
    pa.add_argument("-o", "--output", help="写入 JSON 文件（缺省打印 stdout）")

    pr = sub.add_parser("report", help="生成整页 HTML 报告")
    pr.add_argument("input", help="数据文件 .csv/.json/.xlsx")
    pr.add_argument("-o", "--output", required=True, help="输出 HTML 路径")
    pr.add_argument("--title", default="数据可视化报告", help="报告标题")
    pr.add_argument("--kpi", nargs="*", help="指定 KPI 数值列名（缺省自动挑）")

    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if args.cmd == "analyze":
        return cmd_analyze(args)
    if args.cmd == "report":
        return cmd_report(args)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
