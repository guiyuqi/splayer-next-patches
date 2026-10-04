#!/usr/bin/env python3
"""把 SPlayer-Next 工作区里未提交的改动按主题切成一组可独立应用的提交，并导出补丁系列。

这是本补丁集的生成脚本（需要 Node/pnpm 之外的纯 Python 3）。
用法：在 SPlayer-Next 仓库的**父目录**放好 `.changed-files.txt`（`git status --short -uall` 的路径列），
      `git worktree add --detach .patchbuild <基线提交>`，然后执行本脚本；
      成功后用 `git format-patch -8 4c60335..HEAD` 导出补丁（见 README）。
注意：脚本里写死了本机的绝对路径，移植时请改 W / REPO / WT 三个常量。

做法：在一个 4c60335 的临时 git worktree 里按主题逐个落文件、逐个提交，
最后 git format-patch 导出。全程不改动原始工作区（只读它的文件内容）。
"""
import pathlib
import subprocess
import sys

W = pathlib.Path("/home/fragranstea/dsh-workspace/SPlayer-next")
REPO = W / "repo"
WT = W / ".patchbuild"
BASE = "4c60335"

DJ = "electron/main/apis/netease/modules"

TOPICS: list[tuple[str, list[str]]] = [
    (
        "chore: 补齐共享类型、设置项定义与中英文案",
        [
            "shared/types/player.ts",
            "shared/types/nowPlaying.ts",
            "shared/types/settings.ts",
            "shared/defaults/settings.ts",
            "shared/utils/netease.ts",
            "src/types/settings.ts",
            "src/i18n/locales/zh-CN.json",
            "src/i18n/locales/en-US.json",
            "src/settings/categories/lyric.ts",
            "src/settings/categories/player.ts",
            "src/settings/categories/aiIntegration.ts",
            "src/utils/format/netease.ts",
        ],
    ),
    (
        "fix: 修复整行单词时歌词罗马音重复且溢出的问题",
        [
            "src/utils/lyric/wordRoman.ts",
            "src/utils/lyric/wordRoman.spec.ts",
            "src/stores/media.ts",
        ],
    ),
    (
        "feat: 歌词支持水平居中与水平偏移设置",
        [
            "src/stores/settings.ts",  # 只取歌词相关默认值
            "src/components/player/Lyrics/index.vue",
            "src/components/player/Lyrics/DefaultLyrics.vue",
            "src/components/player/Lyrics/AMLLLyrics.vue",
        ],
    ),
    (
        "feat: 点单曲时可把所在列表整体载入播放队列",
        [
            "src/stores/settings.ts",  # 只取 playFromSourceList 默认值
            "src/composables/useTrackMenu.ts",
            "src/components/list/SongList.vue",  # 只取该主题的 hunk
        ],
    ),
    (
        "fix: 外部修改音量后界面与持久化不同步（顺带补外部控制事件通道）",
        [
            "electron/main/services/playerControl.ts",
            "src/core/player/events.ts",
        ],
    ),
    (
        "feat: 内置 MCP 控制面（工具面 + 一键配置 + 会话透明重建）",
        [
            "electron/main/services/mcp/endpoint.ts",
            "electron/main/services/mcp/http.ts",
            "electron/main/services/mcp/injector.ts",
            "electron/main/services/mcp/server.ts",
            "electron/main/services/mcp/dshConfig.ts",
            "electron/main/services/mcp/dshConfig.spec.ts",
            "electron/main/services/mcp/playlists.ts",
            "electron/main/services/mcp/playlists.spec.ts",
            "electron/main/services/mcp/likes.ts",
            "electron/main/services/mcp/podcasts.ts",
            "electron/main/utils/lan.ts",
            "electron/main/utils/lan.spec.ts",
            "electron/main/services/nowPlaying.ts",
            "electron/main/ipc/nowPlaying.ts",
            "electron/main/store/migrations.ts",
            "electron/main/database/playlists.ts",
            "electron/preload/index.ts",
            "electron/main/server/index.ts",
            "src/main.ts",
            "src/services/queueSync.ts",
            "src/components/settings/custom/McpConfigDialog.vue",
            "src/components/settings/custom/McpStatusCard.vue",
        ],
    ),
    (
        "fix: 账号会话加密存储并迁移历史明文",
        [
            "electron/main/database/sessions.ts",
            "electron/main/database/sessions.spec.ts",
        ],
    ),
    (
        "feat: 播客/电台子系统（发现、分类、详情、订阅、搜索、播放）",
        [
            *[f"{DJ}/{name}.ts" for name in (
                "dj_catelist", "dj_recommend", "dj_personalize_recommend", "dj_toplist", "dj_hot",
                "dj_category_recommend", "dj_radio_hot", "dj_recommend_type", "dj_detail",
                "dj_program", "dj_program_detail", "dj_sub", "dj_sublist",
            )],
            f"{DJ}/index.ts",
            "electron/main/apis/netease/index.ts",
            "shared/types/radio.ts",
            "shared/utils/radio.ts",
            "src/utils/format/radio.ts",
            "src/utils/format/radio.spec.ts",
            "src/apis/radio/netease.ts",
            "src/apis/radio/netease.spec.ts",
            "src/services/collection/netease.ts",
            "src/stores/user.ts",
            "src/composables/collection/useCollectionSubscribe.ts",
            "src/pages/Podcast.vue",
            "src/pages/PodcastCategory.vue",
            "src/pages/Favorites.vue",
            "src/pages/Search.vue",
            "src/pages/Collection.vue",
            "src/components/list/SongList.vue",
            "src/router/index.ts",
            "src/components/layout/sidebarNav.ts",
            "src/layouts/MainLayout.vue",
            "src/apis/search/index.ts",
            "src/apis/search/netease.ts",
        ],
    ),
]

EXCLUDED = {"components.d.ts"}  # 自动生成，见 CHANGES.md

# 跨主题共享的文件：(主题序号, 文件) → 该主题保留的 hunk 标记
PARTIAL = {
    (3, "src/stores/settings.ts"): ("alignCenter", "horizontalOffset"),
    (4, "src/stores/settings.ts"): ("playFromSourceList",),
}


def run(cmd, cwd=WT, check=True):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print("命令失败:", " ".join(map(str, cmd)), file=sys.stderr)
        print(result.stdout[-2000:], result.stderr[-2000:], file=sys.stderr)
        raise SystemExit(1)
    return result.stdout


def split_hunks(diff: str) -> tuple[list[str], list[list[str]]]:
    """把 unified diff 拆成 header 与 hunks"""
    header, hunks, cur = [], [], None
    for line in diff.splitlines(keepends=True):
        if line.startswith("@@"):
            if cur:
                hunks.append(cur)
            cur = [line]
        elif cur is None:
            header.append(line)
        else:
            cur.append(line)
    if cur:
        hunks.append(cur)
    return header, hunks


def filter_file(rel: str, keep: tuple[str, ...]) -> str:
    """只保留正文里出现 keep 中任一标记的 hunk（用于跨主题的共享文件）"""
    diff = run(["git", "diff", "-U3", BASE, "--", rel], cwd=REPO)
    header, hunks = split_hunks(diff)
    kept = [h for h in hunks if any(mark in "".join(h) for mark in keep)]
    print(f"  {rel}: 保留 {len(kept)}/{len(hunks)} 个 hunk（匹配 {keep}）")
    assert kept, f"{rel} 没有匹配到任何 hunk"
    return "".join(header + [l for h in kept for l in h])


def songlist_only_play_from_source_list() -> str:
    """从完整 diff 里挑出「点单曲载入列表」相关的 hunk（排除播客的 hideActions）"""
    diff = run(["git", "diff", "-U3", BASE, "--", "src/components/list/SongList.vue"], cwd=REPO)
    lines = diff.splitlines(keepends=True)
    header, hunks = split_hunks("".join(lines))
    kept = [h for h in hunks if "hideActions" not in "".join(h)]
    dropped = len(hunks) - len(kept)
    print(f"  SongList.vue: 保留 {len(kept)} 个 hunk，排除 {dropped} 个（播客 hideActions）")
    return "".join(header + [l for h in kept for l in h])


def main() -> None:
    assert WT.exists(), "临时 worktree 不存在，请先 git worktree add"
    assert run(["git", "rev-parse", "--short", "HEAD"], cwd=WT).strip() == BASE
    changed = set((W / ".changed-files.txt").read_text().split())
    assigned: set[str] = set()

    for index, (subject, files) in enumerate(TOPICS, start=1):
        for rel in files:
            src = REPO / rel
            dst = WT / rel
            assert src.exists(), f"缺少文件 {rel}"
            dst.parent.mkdir(parents=True, exist_ok=True)
            partial = PARTIAL.get((index, rel))
            if partial:
                patch = filter_file(rel, partial)
                p = W / ".partial.patch"
                p.write_text(patch)
                run(["git", "apply", "--index", str(p)], cwd=WT)
                p.unlink()
            elif rel == "src/components/list/SongList.vue" and index == 4:
                patch = songlist_only_play_from_source_list()
                p = W / ".songlist-partial.patch"
                p.write_text(patch)
                run(["git", "apply", "--index", str(p)], cwd=WT)
                p.unlink()
            else:
                dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
                run(["git", "add", "--", rel])
        assigned.update(files)
        run(["git", "-c", "user.name=guiyuqi", "-c", "user.email=210155735+guiyuqi@users.noreply.github.com",
             "commit", "-q", "-m", subject])
        print(f"  {index:02d} {subject}（{len(files)} 个文件）")

    # 覆盖性检查
    missing = sorted(changed - assigned - EXCLUDED)
    if missing:
        print("以下改动没有被任何主题覆盖：", missing, file=sys.stderr)
        raise SystemExit(1)
    print(f"  覆盖检查通过：{len(changed) - len(EXCLUDED)} 个文件全部归类（显式排除 {sorted(EXCLUDED)}）")

    # 与工作区最终状态对账（排除自动生成文件）
    diff = run(["git", "diff", "--stat", BASE], cwd=WT)
    print(diff.strip().splitlines()[-1])


if __name__ == "__main__":
    main()
