#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lunar.py — 农历 ↔ 公历换算（纯标准库，覆盖 1900-2100）。

skill-event-calendar 承诺"日期不出错"，但农历→公历换算靠 LLM 估算易错。
本脚本用标准 lunar_info 十六进制年表算法离线换算，权威可靠。

用法：
    # 农历 → 公历（2025 农历正月初一 = 春节）
    python3 lunar.py l2s 2025 1 1
    python3 lunar.py l2s 2023 2 1 --leap        # 闰二月初一
    # 公历 → 农历
    python3 lunar.py s2l 2025-10-06
    # 某农历节日在指定公历年的日期
    python3 lunar.py festival 中秋 2025
    python3 lunar.py festival --list            # 列出支持的节日
    # 自测锚点
    python3 lunar.py selftest

数据来源：1900-2100 lunarInfo 十六进制年表，见本目录同级 SKILL 的
EASEL-META.md 血缘记录。JSON 输出加 --json。
"""

import argparse
import json
import sys
from datetime import date, timedelta

# 1900-2100 农历年信息表：每年 20bit。
#  bit16      : 闰月是 30 天(1) 还是 29 天(0)
#  bit15..4   : 12 个月的大小(1=30天,0=29天)，从正月到腊月
#  bit3..0    : 闰月月份(0=当年无闰月)
_LUNAR_INFO = [
    0x04bd8, 0x04ae0, 0x0a570, 0x054d5, 0x0d260, 0x0d950, 0x16554, 0x056a0, 0x09ad0, 0x055d2,  # 1900-1909
    0x04ae0, 0x0a5b6, 0x0a4d0, 0x0d250, 0x1d255, 0x0b540, 0x0d6a0, 0x0ada2, 0x095b0, 0x14977,  # 1910-1919
    0x04970, 0x0a4b0, 0x0b4b5, 0x06a50, 0x06d40, 0x1ab54, 0x02b60, 0x09570, 0x052f2, 0x04970,  # 1920-1929
    0x06566, 0x0d4a0, 0x0ea50, 0x06e95, 0x05ad0, 0x02b60, 0x186e3, 0x092e0, 0x1c8d7, 0x0c950,  # 1930-1939
    0x0d4a0, 0x1d8a6, 0x0b550, 0x056a0, 0x1a5b4, 0x025d0, 0x092d0, 0x0d2b2, 0x0a950, 0x0b557,  # 1940-1949
    0x06ca0, 0x0b550, 0x15355, 0x04da0, 0x0a5b0, 0x14573, 0x052b0, 0x0a9a8, 0x0e950, 0x06aa0,  # 1950-1959
    0x0aea6, 0x0ab50, 0x04b60, 0x0aae4, 0x0a570, 0x05260, 0x0f263, 0x0d950, 0x05b57, 0x056a0,  # 1960-1969
    0x096d0, 0x04dd5, 0x04ad0, 0x0a4d0, 0x0d4d4, 0x0d250, 0x0d558, 0x0b540, 0x0b6a0, 0x195a6,  # 1970-1979
    0x095b0, 0x049b0, 0x0a974, 0x0a4b0, 0x0b27a, 0x06a50, 0x06d40, 0x0af46, 0x0ab60, 0x09570,  # 1980-1989
    0x04af5, 0x04970, 0x064b0, 0x074a3, 0x0ea50, 0x06b58, 0x055c0, 0x0ab60, 0x096d5, 0x092e0,  # 1990-1999
    0x0c960, 0x0d954, 0x0d4a0, 0x0da50, 0x07552, 0x056a0, 0x0abb7, 0x025d0, 0x092d0, 0x0cab5,  # 2000-2009
    0x0a950, 0x0b4a0, 0x0baa4, 0x0ad50, 0x055d9, 0x04ba0, 0x0a5b0, 0x15176, 0x052b0, 0x0a930,  # 2010-2019
    0x07954, 0x06aa0, 0x0ad50, 0x05b52, 0x04b60, 0x0a6e6, 0x0a4e0, 0x0d260, 0x0ea65, 0x0d530,  # 2020-2029
    0x05aa0, 0x076a3, 0x096d0, 0x04afb, 0x04ad0, 0x0a4d0, 0x1d0b6, 0x0d250, 0x0d520, 0x0dd45,  # 2030-2039
    0x0b5a0, 0x056d0, 0x055b2, 0x049b0, 0x0a577, 0x0a4b0, 0x0aa50, 0x1b255, 0x06d20, 0x0ada0,  # 2040-2049
    0x14b63, 0x09370, 0x049f8, 0x04970, 0x064b0, 0x168a6, 0x0ea50, 0x06b20, 0x1a6c4, 0x0aae0,  # 2050-2059
    0x0a2e0, 0x0d2e3, 0x0c960, 0x0d557, 0x0d4a0, 0x0da50, 0x05d55, 0x056a0, 0x0a6d0, 0x055d4,  # 2060-2069
    0x052d0, 0x0a9b8, 0x0a950, 0x0b4a0, 0x0b6a6, 0x0ad50, 0x055a0, 0x0aba4, 0x0a5b0, 0x052b0,  # 2070-2079
    0x0b273, 0x06930, 0x07337, 0x06aa0, 0x0ad50, 0x14b55, 0x04b60, 0x0a570, 0x054e4, 0x0d160,  # 2080-2089
    0x0e968, 0x0d520, 0x0daa0, 0x16aa6, 0x056d0, 0x04ae0, 0x0a9d4, 0x0a2d0, 0x0d150, 0x0f252,  # 2090-2099
    0x0d520,  # 2100
]

_BASE_YEAR = 1900
_MAX_YEAR = 2100
# 农历 1900 年正月初一 == 公历 1900-01-31
_BASE_DATE = date(1900, 1, 31)


def _info(y: int) -> int:
    if y < _BASE_YEAR or y > _MAX_YEAR:
        raise ValueError(f"年份 {y} 超出支持范围 {_BASE_YEAR}-{_MAX_YEAR}")
    return _LUNAR_INFO[y - _BASE_YEAR]


def leap_month(y: int) -> int:
    """返回农历 y 年的闰月月份（1-12），无闰月返回 0。"""
    return _info(y) & 0xf


def leap_days(y: int) -> int:
    """闰月天数（无闰月为 0）。"""
    if leap_month(y):
        return 30 if _info(y) & 0x10000 else 29
    return 0


def month_days(y: int, m: int) -> int:
    """农历 y 年第 m 个普通月（1-12）的天数。"""
    return 30 if _info(y) & (0x10000 >> m) else 29


def year_days(y: int) -> int:
    """农历 y 年总天数。"""
    total = 0
    for m in range(1, 13):
        total += month_days(y, m)
    return total + leap_days(y)


def _months_of(y: int):
    """按时间顺序返回 (月份, 是否闰月, 天数) 序列。"""
    leap = leap_month(y)
    seq = []
    for m in range(1, 13):
        seq.append((m, False, month_days(y, m)))
        if m == leap:
            seq.append((m, True, leap_days(y)))
    return seq


def l2s(year: int, month: int, day: int, is_leap: bool = False) -> date:
    """农历 → 公历。"""
    if not 1 <= month <= 12:
        raise ValueError(f"农历月份须在 1-12，收到 {month}")
    if is_leap and leap_month(year) != month:
        raise ValueError(f"{year} 年闰月是 {leap_month(year) or '无'}，不是闰{month}月")
    offset = 0
    for y in range(_BASE_YEAR, year):
        offset += year_days(y)
    for m, lp, dm in _months_of(year):
        if m == month and lp == is_leap:
            if not 1 <= day <= dm:
                raise ValueError(f"{year} 年{'闰' if lp else ''}{m}月只有 {dm} 天，收到 {day}")
            return _BASE_DATE + timedelta(days=offset + day - 1)
        offset += dm
    raise ValueError(f"{year} 年没有闰{month}月")


def s2l(d: date):
    """公历 → 农历，返回 (年, 月, 日, 是否闰月)。"""
    if d < _BASE_DATE or d > date(_MAX_YEAR, 12, 31):
        raise ValueError(f"日期 {d} 超出支持范围（{_BASE_DATE} 起）")
    offset = (d - _BASE_DATE).days
    y = _BASE_YEAR
    while y <= _MAX_YEAR:
        yd = year_days(y)
        if offset < yd:
            break
        offset -= yd
        y += 1
    for m, lp, dm in _months_of(y):
        if offset < dm:
            return (y, m, offset + 1, lp)
        offset -= dm
    raise ValueError("换算失败（数据表异常）")


# 常用农历营销节点：名称 -> (农历月, 农历日, 公历年偏移)
#  偏移 -1 表示该节日虽在下一个农历年，却落在指定公历年（如腊八/小年）
#  除夕单独处理（农历腊月最后一天，= 次年春节前一天）
FESTIVALS = {
    "春节": (1, 1, 0),
    "元宵": (1, 15, 0),
    "龙抬头": (2, 2, 0),
    "端午": (5, 5, 0),
    "七夕": (7, 7, 0),
    "中元": (7, 15, 0),
    "中秋": (8, 15, 0),
    "重阳": (9, 9, 0),
    "腊八": (12, 8, -1),
    "小年": (12, 23, -1),
    "除夕": None,  # 特殊：春节前一天
}


def festival(name: str, solar_year: int) -> date:
    """某农历节日在指定公历年的公历日期。"""
    if name not in FESTIVALS:
        raise ValueError(f"未知节日：{name}。支持：{'、'.join(FESTIVALS)}")
    if name == "除夕":
        return l2s(solar_year, 1, 1) - timedelta(days=1)
    month, day, off = FESTIVALS[name]
    return l2s(solar_year + off, month, day)


def _cn(year, month, day, is_leap):
    return f"农历{year}年{'闰' if is_leap else ''}{month}月{day}日"


def _selftest() -> int:
    cases = [
        # 春节锚点
        ("2025 春节", l2s(2025, 1, 1), date(2025, 1, 29)),
        ("2024 春节", l2s(2024, 1, 1), date(2024, 2, 10)),
        ("2023 春节", l2s(2023, 1, 1), date(2023, 1, 22)),
        # 中秋锚点
        ("2025 中秋", l2s(2025, 8, 15), date(2025, 10, 6)),
        ("2024 中秋", l2s(2024, 8, 15), date(2024, 9, 17)),
        # 端午
        ("2025 端午", l2s(2025, 5, 5), date(2025, 5, 31)),
        # 闰月：2023 闰二月
        ("2023 闰二月初一", l2s(2023, 2, 1, True), date(2023, 3, 22)),
        # festival helper
        ("festival 春节 2025", festival("春节", 2025), date(2025, 1, 29)),
        ("festival 中秋 2025", festival("中秋", 2025), date(2025, 10, 6)),
        ("festival 除夕 2025", festival("除夕", 2025), date(2025, 1, 28)),
        ("festival 腊八 2025", festival("腊八", 2025), date(2025, 1, 7)),
        # 往返一致性
        ("s2l(2025-01-29)", s2l(date(2025, 1, 29)), (2025, 1, 1, False)),
        ("s2l(2025-10-06)", s2l(date(2025, 10, 6)), (2025, 8, 15, False)),
        ("s2l(2023-03-22)", s2l(date(2023, 3, 22)), (2023, 2, 1, True)),
    ]
    ok = True
    for name, got, exp in cases:
        passed = got == exp
        ok = ok and passed
        print(f"[{'PASS' if passed else 'FAIL'}] {name}: got={got} exp={exp}")
    # 全域往返自测：2000-2050 每一天 s2l→l2s 复原
    d = date(2000, 1, 1)
    end = date(2050, 12, 31)
    rt_ok = True
    while d <= end:
        y, m, dd, lp = s2l(d)
        if l2s(y, m, dd, lp) != d:
            rt_ok = False
            print(f"[FAIL] roundtrip {d} -> {_cn(y, m, dd, lp)}")
            break
        d += timedelta(days=1)
    print(f"[{'PASS' if rt_ok else 'FAIL'}] 2000-2050 每日往返一致")
    ok = ok and rt_ok
    return 0 if ok else 1


def _out(obj, as_json):
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, default=str))
    else:
        print(obj)


def main():
    p = argparse.ArgumentParser(
        description="农历 ↔ 公历换算（纯标准库，1900-2100）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("l2s", help="农历 → 公历")
    pl.add_argument("year", type=int)
    pl.add_argument("month", type=int)
    pl.add_argument("day", type=int)
    pl.add_argument("--leap", action="store_true", help="该月为闰月")
    pl.add_argument("--json", action="store_true")

    ps = sub.add_parser("s2l", help="公历 → 农历（YYYY-MM-DD）")
    ps.add_argument("date")
    ps.add_argument("--json", action="store_true")

    pf = sub.add_parser("festival", help="农历节日在指定公历年的日期")
    pf.add_argument("name", nargs="?", help="节日名，如 中秋")
    pf.add_argument("year", type=int, nargs="?", help="公历年")
    pf.add_argument("--list", action="store_true", help="列出支持的节日")
    pf.add_argument("--json", action="store_true")

    sub.add_parser("selftest", help="运行自测锚点")

    args = p.parse_args()

    try:
        if args.cmd == "selftest":
            sys.exit(_selftest())
        elif args.cmd == "l2s":
            d = l2s(args.year, args.month, args.day, args.leap)
            _out({"lunar": _cn(args.year, args.month, args.day, args.leap),
                  "solar": str(d), "weekday": d.isoweekday()}, args.json)
        elif args.cmd == "s2l":
            d = date.fromisoformat(args.date)
            y, m, dd, lp = s2l(d)
            _out({"solar": str(d), "lunar": _cn(y, m, dd, lp),
                  "year": y, "month": m, "day": dd, "is_leap": lp}, args.json)
        elif args.cmd == "festival":
            if args.list:
                _out({"festivals": list(FESTIVALS)}, args.json)
            elif args.name and args.year:
                d = festival(args.name, args.year)
                _out({"festival": args.name, "solar_year": args.year,
                      "solar": str(d), "weekday": d.isoweekday()}, args.json)
            else:
                sys.exit("用法：festival <节日名> <公历年>，或 festival --list")
    except ValueError as e:
        sys.exit(f"错误：{e}")


if __name__ == "__main__":
    main()
