#!/usr/bin/env python3
"""校验 Windows .node 的原生 API 是否与仓库源码（generated index.d.ts）一致。

背景：WSL 打包复用官方 exe 里的 Windows .node，如果那个 exe 比仓库源码旧，
`#[napi(object)]` 的字段名一旦改过就会在运行时抛 `Missing field ...`（DEV-NOTES §3.24）。

用法：
    python3 native-api-check.py <含 .node 的目录> [--repo=<仓库路径>]
"""
import re
import subprocess
import sys
from pathlib import Path

MODULES = ["audio-engine", "audio-capture", "media-ctrl", "taskbar-lyric", "taskbar-thumbnail", "opencc"]

# napi 生成的名字里，这些是通用词，出现在二进制里不代表 API 对得上
IGNORED = {"type", "value", "data", "name"}


def dts_names(dts: Path) -> set[str]:
    text = dts.read_text(encoding="utf-8", errors="ignore")
    names = set(re.findall(r"export declare function (\w+)", text))
    names |= set(re.findall(r"^\s{2}(\w+)\??:", text, flags=re.M))
    names |= set(re.findall(r"^\s{2}(\w+)\(", text, flags=re.M))
    return {n for n in names if len(n) > 3 and n not in IGNORED}


def binary_strings(node: Path) -> str:
    out = subprocess.run(["strings", "-n", "4", str(node)], capture_output=True, text=True).stdout
    return out


usage_text = ("用法：python3 native-api-check.py <目录>   # 目录下可为 <m>.node 或 <m>/<m>.node")


def find_node(native_dir: Path, module: str) -> Path | None:
    for candidate in (native_dir / f"{module}.node", native_dir / module / f"{module}.node"):
        if candidate.exists():
            return candidate
    return None


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--repo")]
    native_dir = Path(args[0])
    repo = Path("repo")
    for arg in sys.argv[1:]:
        if arg.startswith("--repo="):
            repo = Path(arg.split("=", 1)[1])
    failures = 0
    for module in MODULES:
        node = find_node(native_dir, module)
        dts = repo / "native" / module / "index.d.ts"
        if node is None or not dts.exists():
            print(f"{module:18s} 跳过（缺 {module}.node 或 index.d.ts）")
            continue
        expected = dts_names(dts)
        text = binary_strings(node)
        missing = sorted(n for n in expected if n not in text)
        status = "OK" if not missing else f"缺失 {len(missing)}"
        print(f"{module:18s} d.ts 名字 {len(expected):3d} 个 → {status}")
        if missing:
            failures += 1
            print(f"    {missing[:12]}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
