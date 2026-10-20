# 改动清单、证据等级与未验证点

基线：SPlayer-Next `dev` @ `4c60335`。本文件按补丁逐条说明**做了什么、我是怎么验证的、哪些没有验证**。

**证据等级定义**

| 等级 | 含义 |
|---|---|
| **A** | 在真实环境（Windows 真机 / 真实账号）复现过问题或验证过功能，有可复核的观测（日志、测得的数值、接口返回） |
| **B** | 在 WSL 开发实例上复现/验证，或有量化测量（DOM 尺寸、单测断言），但未在真机全量回归 |
| **C** | **推断**：没有复现原始问题，或结论来自接口语义/社区实现而未经实测；**不要当作已验证的修复** |
| **D** | 机械改动（类型、文案、默认值、文件搬移），无运行时行为，靠类型检查保证 |

> 这些改动是在个人使用场景下、借助 AI 辅助完成的。下面所有"未验证"都是我认为**不足以称为已修复**的部分。

---

## 0001 chore：共享类型 / 设置项定义 / 中英文案（D）

- **内容**：`shared/types/player.ts` 新增 `playList`/`setVolume`/队列 5 个外部控制事件类型；`shared/types/nowPlaying.ts` 新增队列窗口快照类型；`shared/types/settings.ts`、`shared/defaults/settings.ts`、`src/types/settings.ts` 新增 `lyric.alignCenter`、`lyric.horizontalOffset`、`player.playFromSourceList`、`mcp.bindMode` 等；`src/settings/categories/{lyric,player,aiIntegration}.ts`；中英 i18n（含播客全部文案）；`shared/utils/netease.ts` + `src/utils/format/netease.ts`（把网易云歌曲映射提到 `shared/`，供主进程复用）。
- **验证**：仅类型/文案/默认值，`tsc -p tsconfig.node.json` 与 `vue-tsc -p tsconfig.web.json` 通过。
- **注意**：**单独应用不产生任何功能**，它是 0002~0008 的公共前置。

## 0002 fix：整行单词时歌词罗马音重复且溢出（B）

- **现象**：某些歌词来源（主歌词 LRC + 行级音译 LRC）会把整行解析成"一个词"。渲染库 `lyric-dom` 为了断行会按空白把词拆成多段，但**每一段都拿到整词的 `romanWord`** → 罗马音被渲染两份，且逐词罗马音是 `nowrap`，实测两个 `.lp-word-roman` 合计 609px，溢出 547px 的歌词栏。
- **改法**：新增 `src/utils/lyric/wordRoman.ts` 的 `dropDuplicatedWordRoman()`，在 `src/stores/media.ts` 解析歌词后调用：判定「该行有行级 `romanLyric` + 词内含空白 + 所有词的 `romanWord` 都等于行级 `romanLyric`」时清掉词级 `romanWord`，让库回退到行级 `.lp-sub`（`white-space: normal`，可换行）。受影响行数 37 → 14。
- **验证**：`src/utils/lyric/wordRoman.spec.ts` 4 条单测；开发实例 DOM 矩形测量 + 截图对比。
- **未验证 / 取舍**：
  - 这些行的罗马音**不再参与逐字高亮遮罩**（行级元素在遮罩外）——是可接受的降级，但不是"完全等价"。
  - 只在手上的一首日文歌上量过，**没有全库回归**。
  - 逐词罗马音正常的来源（TTML/QRC）不受影响，因为判定条件会跳过。

## 0003 feat：歌词水平居中与水平偏移（B）

- **内容**：两个新设置项（`lyric.alignCenter` 默认 `false`、`lyric.horizontalOffset` 默认 `0`，单位是歌词区宽度百分比）；物理引擎补 `.lp-main > .lp-word-roman` 的对齐覆盖（库对每行首个词设了左对齐）；AMLL 引擎在「整曲每行词数 ≤1 → 走 non-dynamic 快路径」时回退到行级音译，避免音译整行消失。
- **验证**：开启居中后 48/48 行的原文/翻译/音译中心与原文一致；偏移在开发实例上逐档截图核对。
- **未验证**：只在默认引擎与 AMLL 两种引擎、默认字号下检查；RTL 文本、超长行与偏移组合没穷尽。

## 0004 feat：点单曲时把所在列表整体载入队列（B，⚠️ 默认行为变化）

- **内容**：新增 `player.playFromSourceList`，**默认 `true`**：在歌单/专辑/列表里双击或右键"播放"会把整张列表载入队列并从该曲开始；搜索页仍遵循原有 `searchPlayBehavior`；右键菜单新增 `onPlay` 回调以便与列表点播保持一致。
- **验证**：开发实例（点单曲 → 队列替换为整列表、从该曲起播）；真机上日常使用无异常。
- **⚠️ 风险**：**它改变了老用户的默认行为**。若打算向上游提 PR，建议把默认值改为 `false`（本补丁保留了我个人使用时的取值，请自行决定）。

## 0005 fix：外部修改音量后界面与持久化不同步（音量 A / 外部控制 C）

- **音量（A）**：外部（MCP / 插件 / 外部 API）改音量原先只改引擎，渲染层随后用持久化的旧值反推覆盖，导致滑块、`localStorage` 与引擎三层不一致。改法：`playerControl.setVolume` 先在引擎落地，**同时**发 `setVolume` 事件让渲染层走同一条 IPC 路径。
  **验证**：真机上三层一致（多次实测：引擎 0.42 / 渲染层 0.65 / localStorage 0.66 / 1.0）；MCP 改音量后界面同步、重启后不回退。
- **外部控制事件通道（C）**：渲染层新增 `playList` / `removeFromQueue` / `moveInQueue` / `clearQueue` / `jumpToIndex` / `toggleLike` 的处理，全部复用界面同一条路径（队列下标自动跟随播放项）。
  **⚠️ 未验证**：`playList` 是为了修「`play_playlist` 给了 index 却点到别的歌」的报告而加的，但**我没能复现那份报告**。三条解释（歌单里有同名曲目 / 随机播放会把下标洗牌重置 / 音源受限导致自动下移）都是推断，其中"加载失败自动下移"还是在**不存在的假文件**上观察到的。**请把它当"语义澄清 + 加固"，而不是已验证的修复。**

## 0006 feat：内置 MCP 控制面（A，⚠️ 新增本地监听面）

- **内容**：主进程内置 Streamable HTTP MCP 服务（Hono + `@hono/node-server`）、`X-MCP-Key` 恒定时间比较 + Origin 校验、**客户端会话失效时透明重建**（治「播放器重启后官方客户端遇 404 不重连、工具永久失效」）、会话有界回收（最多 8 个 / 空闲 30 分钟）、监听范围三档（仅本机 / 本机+WSL 网卡 / 局域网）、DSH 等 Agent 配置一键写入（标记块、幂等、只认自己写的内容）、队列窗口推送到主进程供 `get_queue` 读取；工具面覆盖状态读取、播放控制、队列精修、歌单读写（写操作返回 `beforeOrder`/`afterOrder` 供对账）、喜欢的音乐、歌词偏移、曲库/在线搜索、播客（见 0008）。
- **验证（真机 + 开发实例）**：43 个工具可列出；真实账号读取正常（26 个歌单、订阅播客 2 个）；`play_podcast` 真机播放进度递增；系统媒体控件元数据正确；主进程日志 0 错误。歌单写操作在**本机歌单**上做过 create / add / remove / reorder / move / rename / desc / delete 全流程并逐次对账。
- **⚠️ 未验证 / 需要重点 review**：
  - 新开了一个本地 HTTP 监听面（默认只绑 `127.0.0.1` 与 WSL 虚拟网卡）；**鉴权只有一个静态密钥**，没有速率限制、没有审计日志；请重点看 `electron/main/services/mcp/http.ts` 的绑定与来源校验。
  - 云端歌单的**写**操作只在真实账号上验证过"订阅/取消订阅"；重排/增删是在本机歌单与开发实例上验证的。
  - `server.ts` 里同时包含 0008 的 4 个播客工具注册：两个补丁一起应用才完整。

## 0007 fix：账号会话加密存储并迁移历史明文（B）

- **内容**：网易云账号会话改为 `enc:`（Electron safeStorage / Windows DPAPI）优先，安全存储不可用时 `b64:` 兜底并告警；首次读到历史明文时自动迁移。
- **验证**：`electron/main/database/sessions.spec.ts` 5 条单测（编解码 / 迁移 / 兜底 / 异常值）；Windows 真机上写入后库里为 `enc:` 前缀，WSL 开发实例（无 safeStorage）为 `b64:`。
- **未验证**：`enc:` 会话是 DPAPI 绑定用户与机器的，**跨机器拷贝必然解密失败**；这符合设计预期，但目前没有面向用户的提示文案。

## 0008 feat：播客 / 电台子系统（A，⚠️ 依赖未公开接口）

- **内容**：13 个网易云 `dj_*` 接口模块（全部 weapi）；`shared/utils/radio.ts` 一份跨进程映射（`Track.id = mainSong.id`、`extId = 节目 id`、`album.id = 电台 id`，打卡据此判定 `resourceType: "dj"`）；渲染层电台 API（节目 200 条/页 + 页间 400ms + 命中风控重试一次、尾页失败只截断）；UI：播客发现页（19 个分类 + 热门榜 + 分类推荐 + 我的订阅）、分类详情页（热门/推荐）、电台详情复用 `collection/netease/radio/:id`（节目流式分页、播放全部、隐藏"专辑/操作"列）、搜索页"播客"tab、收藏页"播客"页签、侧边栏一级入口、路由、中英 i18n；MCP 侧 4 个工具（`list_podcasts` / `search_podcasts` / `get_podcast_tracks` / `play_podcast`）。
- **验证（真机真实账号）**：订阅列表读取 = 2 个真实电台；**订阅写入**（在 UI 点收藏）后数量 2→3 且立即可见（`dj_sub`/`dj_sublist` 已加入免缓存名单，否则会被 2 分钟响应缓存挡住）；`get_podcast_tracks` 拉到 664 集 / 39 集电台的完整分页；UI「播放全部」产生的队列 = 39 集且每集 `extId`/`album.id` 正确；`play_podcast` 播放进度正常推进；期间日志 0 错误。
- **⚠️ 未验证 / 风险**：
  - `/dj/*` 是**未公开接口**：路径与参数取自社区实现（NeteaseCloudMusicApi 4.32.0）并在本机联调确认，服务端变更即可能失效。
  - 大电台分页实测会命中风控（HTTP 405/406 "操作频繁"）；补丁做了退避 + 重试 + 截断，但**只测过 664 集与 39 集两个电台**，没有更广泛的回归。
  - 单集**歌词与评论不支持**（评论资源前缀固定为 `R_SO_4_`，播客需要别的类型），本补丁不含。
  - 播客**没有**单集进度记忆、已听标记、跳过片头片尾（前身 SPlayer 也没有）。
  - 分类详情页只取首批 30 条，没有触底分页。

## 0009 feat：宏音量对齐 + 窗口唤醒后的播放/歌词恢复（A，⚠️ 仅 JS 层）

这一批与 0001~0008 无重叠：那批是播客/MCP/歌词显示，这批是**音量一致性与"回到前台后播放状态恢复"**。

### 新增：宏音量对齐（整曲恒定增益）

- **问题**：不同歌曲母带响度差异极大（实测同一歌单里 `-5.2 LUFS` 与 `-17.5 LUFS` 共存，差 12 dB），调一次音量没法同时听。原有「音量均衡」是**实时 AGC**，会随内容不断改增益，反而造成段内忽大忽小（见 `AUDIO-NORMALIZATION-ANALYSIS.md` 那类问题）。
- **做法**：
  - 测量在**渲染端**：`cache://` 协议带 `supportFetchAPI`，直接 `fetch` 已缓存的音频 → Web Audio `decodeAudioData` → 按 **ITU-R BS.1770-4 / EBU R128** 做 K 加权、400ms 分块 75% 重叠、绝对门限 −70 LUFS + 相对门限 −10 LU 的积分，外加样本峰值。纯 TS，`src/services/loudness/{measure,gain,index}.ts`。
  - 增益：`clamp(min(目标响度 − 实测, -1 dBTP − 峰值), ±12 dB)`，目标默认 **−18 LUFS**（设置里可调 −23…−14），有单测覆盖"抬升被峰值余量压住"和"钳制在前级范围"。
  - 施加：引擎没有独立增益入口，用**均衡器前级** —— `dsp/equalizer.rs` 里 `gain_db = 0` 时滤波器系数退化为逐采样直通，所以「开均衡器 + 全频段 0dB + 只改前级」等价于整曲乘一个常数；且 `eq_enabled=true` 会启用 `dsp/limiter.rs` 的限幅器（ceiling 0.98），顺带做削波保护。组合规则（用户前级 + 宏增益、均衡器开关）只在主进程算，避免设置页与宏音量互相覆盖。
  - 校准结果存渲染端 IndexedDB（`splayer/loudness`，键 `{source}:{id}`，带算法版本号），下次播放直接读。
  - 首次播放：没缓存就拿不到整首音频，先按 0dB 播；`cacheScheduler.triggerNow()` 立刻催缓存，`watchCalibration()` 每 2s 试一次，测到就**中途生效**；并对**队列下一首**做延迟预校准，使第二首起从头就准。
  - 场景门控：`playbackContext.originType` 为 `album` / `radio` 时不参与对齐（保留专辑与播客自身的动态）。
  - 与旧「音量均衡」三层互斥：设置页互相确认并关闭、主进程 `applyConfigChange` 双向清除、运行时 `ensureNormalizationOff()` 兜底。旧开关标注为「已由宏音量对齐取代，建议关闭」。
- **验证（真机）**：日志可见 `校准完成 とある一家の御茶会議 -5.2LUFS peak=2.1dB` → `宏音量增益已应用: -12.00dB`（撞到 ±12 上限）与 `ツギハギスタッカート -9.5LUFS` → `-8.54dB`；用户主观确认"两首音量相差很大的歌"对齐后听感一致。缓存目录与校准库均在本机生成。
- **⚠️ 未验证 / 限制**：
  - **本地文件**（`track.source === "local"`）不参与（渲染端拿不到可 fetch 的 `file://`）。
  - 峰值用的是**样本峰值**，不是 4× 过采样的真峰值；已用 −1 dBTP 上限留余量，但对强限幅母带可能仍有极少量瞬态被限幅器吃掉。
  - LUFS 是**长时平均**：压得很猛的歌对齐后短时仍显得更响，这是标准本身的局限，本补丁不引入 LUFS-S 之类的短时约束。
  - 首次播放某首未缓存的歌，会有约 5~20 秒的"未对齐"窗口（等缓存 + 解码测量）。
  - 只在网易云在线流媒体 + 一首歌单的样本上量过，没有全库回归。

### 修复：最小化/隐藏后回来，进度条不动、歌词冻结在最开始

- **根因（真机日志定位，非猜测）**：渲染端 `seekTarget` 是一道**没有超时的永久屏蔽** —— `hasReachedSeekTarget()` 只在后端推送位置落在目标 ±1s 内才清除；一次"跳到 0"的 seek 若引擎实际在 84 秒处继续播放，就永远到不了目标，之后**每条 `position` 推送都被丢弃**，于是进度条停在 0:00、歌词停在第一行。实测日志：`[player] 解除卡住的 seek 屏蔽 target=0` + `播放状态已对账(seek-stall) state=playing pos=84462`。
- **改法**：
  - `seekTarget` 加 3s 超时自动解除；`resyncFromEngine()` 以引擎快照为权威，卡住的屏蔽一并解除并重新锚定。
  - 新增 3s 位置停滞看门狗（2s 巡检，`document.hidden` 时跳过），用 `player:getStatus` 对账。
  - 主进程 `pushPlaybackSnapshot()`：窗口 `focus` / `show` / `restore` / 系统唤醒后补发快照（隐藏期间高频推送按约定跳过，恢复时补一次），**不触发播放**。
- **验证（真机）**：用户实测"冻结现在被正常唤醒了"；日志有 `主窗口恢复可见，已补发播放快照（focus）`、`[lyric] 窗口恢复…`。

### 修复：歌词页唤醒后仍然冻结

- **根因**：`lyric-dom` 的 `freeze()` 会 `cancelAnimationFrame` 并把 `animationFrameId` 置 0，只有 `resume()` 能救；而 `resume()` 只挂在展开过渡的 `after-enter` 上——窗口在后台时过渡整段跑在无帧环境里，`after-enter` 可能不触发。另外引擎内部缓存 `isPageVisible`，只由它自己的 `visibilitychange` 监听更新。
- **改法**：唤醒时 `resume()`（库自带 `animationFrameId !== 0` 幂等保护）+ 补发一次合成的 `visibilitychange`（防重入）+ 重锚时钟；展开/收起改由 `watch(isPlayerExpanded)` 驱动 `resume + startTick` / `freeze + stopTick`，不再依赖过渡钩子；推进时钟**不再被加载标记门卡死**；`usePlaybackTime` 先续帧再回调 + try/catch，异常不会断掉帧链。
- **验证（真机）**：用户实测通过。

### 其它

- 渲染端 console 转发进主进程日志（`(renderer)` 前缀），生产包没有 devtools 时也能回溯；位置推送被丢弃时按 5s 节流记录拦截原因（`位置推送被丢弃(trackLoading|seekTarget)`）。
- 新增单测 `src/services/loudness/gain.spec.ts`；`vitest` 249 / `tsx --test` 35 全绿，`prettier` / `eslint` / `tsc` / `vue-tsc` 通过。

---

## 有意排除的内容

- `components.d.ts`：由 unplugin 自动生成，未包含在补丁中，首次 `pnpm dev` / 构建会自动补齐（因此补丁不会覆盖它，也不会与你的本地生成结果冲突）。
- 个人环境相关脚本与配置（DSH / MCP 联通探测、打包脚本、日志、截图）**不在本仓库**，避免夹带环境细节与凭据。

## 我认为自己可能搞错的地方（如果要向上游提 PR，请先自查）

1. **0005 的 `playList` 归因**：见上，C 级——原报告未能复现。
2. **"网易云歌单重排会刷新全部加入时间"**：来自接口语义与社区实现，**没有在真实账号上做 before/after 时间戳对比**。
3. **0002 的影响面**：只在一首日文歌上量化过。
4. **更早的一些结论**（分片缓存、更新器行为、DPAPI 迁移细节）只有当时环境下的观察记录，**无法仅凭本补丁复现**。
