# 验证用小工具（可选，不参与构建）

这些脚本是我在开发/验证过程中用的，放在这里是为了让别人能复核 CHANGES.md 里的结论。

| 脚本 | 用途 |
|---|---|
| `native-api-check.py` | 把 `native/*/index.d.ts` 里的导出名逐个到 Windows `.node` 的字符串表里找，用于确认「复用的官方原生模块是否与当前源码 API 对齐」（Windows 打包前的门禁）。用法：`python3 tools/native-api-check.py <含 .node 的目录> --repo=<仓库路径>` |
| `smtc-read.ps1` | 用 WinRT 读 Windows 系统媒体控件（SMTC）当前会话的标题/歌手/专辑/是否有封面，用来验证播放器是否真的把元数据写进了系统媒体控件。用法：`powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/smtc-read.ps1` |
| `mcp-call.py` | 通用 MCP 调用器：`tools` 列出工具、`call <工具> '<json>'` 调用。默认连 `http://127.0.0.1:14559/mcp`，可用环境变量 `MCP_URL` / `MCP_KEY` 指向别处（播放器「AI 集成」里能看到 key）。 |

注意：`native-api-check.py` 依赖 `strings`（binutils）；三个脚本都不需要安装额外 Python 包。
