#!/usr/bin/env bash
# cleanup_outputs.sh — 删除 outputs/ 里的测试残渣。
#
# ⚠️ 本脚本会 **删除文件**，请先审阅再运行；每条都有注释说明为何删。
#    不想删某项就把那一行注释掉。删除不可恢复。
#
# 为什么固化成脚本让你手动跑：仓库安全策略会拦截 AI 直接 rm outputs/ 下的东西，
# 所以清理动作固化成本脚本，由你审阅后执行。
#
# 说明：系统状态文件（publish-log.json / follower-log.json / analytics/ 等）不在这里动，
# 它们由归因层脚本按固定路径读写；前端「内容库」已改为只展示项目目录、
# 自动忽略这些根目录散文件与系统目录（见 web/app.py get_output_tree）。
#
# 用法：
#   bash scripts/cleanup_outputs.sh            # 预览（dry-run，只打印不动手）
#   bash scripts/cleanup_outputs.sh --apply    # 真正执行
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/outputs"
APPLY=0
[[ "${1:-}" == "--apply" ]] && APPLY=1

run() {   # run <描述> <命令...>
  local desc="$1"; shift
  if [[ $APPLY -eq 1 ]]; then
    echo "执行: $desc"
    "$@"
  else
    echo "计划: $desc  ->  $*"
  fi
}

echo "=== cleanup_outputs $([ $APPLY -eq 1 ] && echo APPLY || echo DRY-RUN) ==="

# 1) 卡片设计预览测试图（card-design 验证残渣，非产物）
for f in "$OUT"/card_preview_*.png; do
  [[ -e "$f" ]] || continue
  run "删测试图 $(basename "$f")" rm -f "$f"
done

# 2) 空的 analytics/（skill-data-tracker 的快照目录，当前为空壳；用到时会自动重建）
#    只剩 .easel.json（迁移脚本误建的）也算空
if [[ -d "$OUT/analytics" && -z "$(find "$OUT/analytics" -type f ! -name .easel.json)" ]]; then
  run "删空目录 analytics/" rm -rf "$OUT/analytics"
fi

# ---------------------------------------------------------------------------
# 以下为「疑似测试残渣」候选，默认注释掉，请你确认后再取消注释：
#
# ai-init-note/：只含 comments.json + replied.json，像是 xhs 评论脚本的测试产物，非内容产物
# run "删测试残渣 ai-init-note/" rm -rf "$OUT/ai-init-note"
#
# 注：outputs/xhs/ 名字泛但内含真实小红书图文（cards+md），不删；建议手动重命名为具体主题。
# ---------------------------------------------------------------------------

echo ""
[[ $APPLY -eq 0 ]] && echo "以上为计划。确认后加 --apply 执行。" || echo "清理完成。"
