#!/usr/bin/env bash
# 发布前扫一遍敏感信息：MCP 访问密钥、网易云 cookie、绝对路径、账号名等。
#
# 用法：
#   ./scripts/scrub-secrets.sh <目录|文件>...        # 只报告（默认）
#   ./scripts/scrub-secrets.sh --fix <目录|文件>...  # 就地替换成占位符
#
# 说明：默认只扫描、不改动；--fix 会把命中的「32 位十六进制密钥」替换为 <MCP_ACCESS_KEY>。
#       密钥一旦进过版本库就应当视为已泄露，请到播放器「AI 集成」里重新生成，而不是只改文本。
set -uo pipefail

FIX=0
[ "${1:-}" = "--fix" ] && { FIX=1; shift; }
[ "$#" -ge 1 ] || { echo "用法: $0 [--fix] <目录|文件>..."; exit 2; }

# 需要留意的模式（用 grep -P，避免把 40 位提交哈希里的 32 位片段当成密钥）
PATTERNS=(
  '(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])'          # MCP accessKey 形态（32 位 hex）
  'devtestkey[0-9a-f]+'                             # 开发实例专用 key
  'MUSIC_U=[A-Za-z0-9%._-]{20,}'                     # 网易云登录 cookie（真实值）
  'MUSIC_A=(?!dev-placeholder)[A-Za-z0-9%._-]{20,}'  # 网易云匿名 cookie（占位值除外）
  '__csrf=[A-Za-z0-9%._-]{16,}'
  'fragranstea'                                     # 开发机用户名/绝对路径
  'C:\\\\Users\\\\[A-Za-z]+'
  'X-MCP-Key:[[:space:]]*(?!<|\$|test-key)[A-Za-z0-9]{16,}'
)
files() { find "$@" -type f \( -name '*.md' -o -name '*.sh' -o -name '*.ps1' -o -name '*.yml' -o -name '*.yaml' -o -name '*.json' -o -name '*.ts' -o -name '*.py' -o -name '*.patch' \) -not -path '*/.git/*' -not -path '*/node_modules/*' -not -name 'scrub-secrets.sh'; }

hit=0
while IFS= read -r f; do
  for pat in "${PATTERNS[@]}"; do
    if grep -Pq "$pat" "$f" 2>/dev/null; then
      hit=1
      echo "⚠ 命中 [$pat] → $f"
      grep -Pn "$pat" "$f" | head -3 | sed 's/^/    /'
      if [ "$FIX" = "1" ] && [ "$pat" = '(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])' ]; then
        perl -pi -e 's/(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])/<MCP_ACCESS_KEY>/g' "$f"
        echo "    已替换为 <MCP_ACCESS_KEY>"
      fi
    fi
  done
done < <(files "$@")

if [ "$hit" = "0" ]; then
  echo "✓ 未发现明显敏感信息"
else
  echo
  echo "提醒：命中的密钥即使已删除也必须视为泄露 —— 请到播放器「AI 集成」重新生成密钥，"
  echo "      并同步更新 ~/.dsh/profiles/web/cordis.patch.yml 等 Agent 侧配置。"
  [ "$FIX" = "0" ] && echo "（加 --fix 可就地替换 32 位 hex 密钥）"
fi
