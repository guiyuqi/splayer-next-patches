# 上游 SPlayer（SPlayer-Dev/SPlayer @ dev）播客/电台子系统 移植规格

> 调研对象：上游仓库 `dev` 分支（`SPlayer-Dev/SPlayer`），本机解包于 `.probe/repo/`（只读）。
> 目的：为 SPlayer-Next 的 `dj_*` 移植提供「上游到底怎么用这些接口/字段/播放链路」的对照基准。
> 字段结论 = 上游代理（NeteaseCloudMusicApi 兼容后端，weapi）+ 真实网易云响应实测（见最后一节）。
> 与本工作区既有的 `PODCAST-RADIO-SPEC.md`（讲 Next 目标侧实现）互补，不重复其内容。

---

## 0. 一句话结论

上游播客是**「网易云 DJ 电台 + 节目单集」的薄封装**：接口层 13 个函数（其中 3 个死代码）、
节目被 `formatSongsList` 硬塞进 `SongType`（`type:"radio"`），播放层到处用 `song.dj.id`(=mainTrackId) 做特殊分支。
**没有任何播客专属能力**（无 RSS、无进度记忆、无已听标记、无跳过片头、无章节），
UI 全部由 Naive UI + 通用 `CoverList`/`SongList`/`ListDetail` 复用而来。

---

## 1. 数据流：页面 → 接口 → 参数 → 用到的返回字段

| 页面 | 接口 | 参数 | 用到的返回字段 |
| --- | --- | --- | --- |
| `Home/HomeOnline.vue`「推荐播客」区 | `/dj/recommend` | 无 | `djRadios[]` → `formatCoverList` |
| `Radio/hot.vue` 分类入口 | `/dj/catelist` | 无 | `categories[].id/name`（localStorage 永久缓存 `radioTypeData`） |
| `Radio/hot.vue` 热门推荐 | `/dj/toplist` | `type=hot,limit=20,offset=0` | `toplist[]` |
| `Radio/hot.vue` 分类推荐块 | `/dj/category/recommend` | 无 | `data[].categoryId/categoryName/radios[]` |
| `Radio/type.vue` tab「热门」 | `/dj/radio/hot` | `cateId,limit=50,offset=0` | `djRadios[]` |
| `Radio/type.vue` tab「推荐」 | `/dj/recommend/type` | `type=cateId` | `djRadios[]` |
| `List/radio.vue` 详情 | `/dj/detail` | `rid` | `data{}` → `formatCoverList(data)[0]` |
| `List/radio.vue` 节目列表 | `/dj/program` | `rid,limit=500,offset`（循环 +500 直到 `offset>=count`） | `{count,more,programs[]}` |
| `List/radio.vue` 订阅按钮 | `/dj/sub` | `rid,t,timestamp` | `code===200` |
| `List/radio.vue` 评论 tab | `/comment/new`、`/comment/hot` | `type=7`（电台） | 评论列表 |
| `Search/radios.vue` | `/cloudsearch` | `keywords,limit=50,offset,type=1009` | `result.djRadios[]`、`result.djRadiosCount`、`result.hasMore` |
| `Like/radios.vue` | **不发请求** | — | 直接读 `dataStore.userLikeData.djs` |
| 订阅状态刷新（登录后） | `/dj/sublist` | `limit=50,offset,timestamp` | `djRadios[]`，结果 `<limit` 即终止 |
| `CoverList.vue` 卡片「播放」（radio） | `/dj/program` | `rid,limit=100`（只取前 100） | `programs[]` |
| `Comment.vue` / `PlayerData.vue` 兼容旧数据 | `/dj/program/detail` | `id`（**节目 id，不是 rid**） | `program{id,mainSong,radio{id},coverUrl,duration}` |
| 播放取址（通用播放器） | `/song/url` | `id = dj.id(=mainTrackId)`、`level` | `data[0].url/br/size/fee/level` |
| 歌词 | `/lyric` | `id = dj.id(=mainTrackId)` | 上游 UI 对 radio 强制不显示歌词 |

**上游 `src/api/radio.ts` 里 3 个死代码**：`radioPersonalized`(`/dj/personalize/recommend`)、
`radioPersonalDj`(`/aidj/content/rcmd`)、`radioToplist("new")`（只调用过 `"hot"`）。移植时可省。

---

## 2. `userLikeData.djs`（我订阅的播客）来源

**不在 pinia store 里请求，而是在 `src/utils/auth.ts` 的登录初始化链路里拉。**

```ts
// src/api/user.ts
export const userDj = (limit = 50, offset = 0) =>
  request({ url: "/dj/sublist", params: { limit, offset, timestamp: Date.now() } });

// src/utils/auth.ts:324
export const updateUserLikeDjs = async () => {
  await setUserLikeDataLoop(userDj, formatCoverList, "djs");
};
// auth.ts:450 —— 关键：从 result.djRadios 取，每页 50，data.length < limit 即结束
if (key === "djs") data = result.djRadios || [];
```

- **发起时机**：`updateUserData()`（auth.ts:207）内 `Promise.allSettled([... updateUserLikeDjs(), ...])`；
  调用者只有 `Modal/Login/Login.vue:81`（登录成功）与 `Layout/User.vue:176/225`（启动检查登录、添加账号）。
  ⇒ 即 `User.vue onMounted → checkLoginStatus() → refreshLoginData() → updateUserData()`，**每次启动都会全量重拉**。
- **登录态依赖**：`isLogin()` 必须为 1（`userLoginStatus && MUSIC_U`）。UID 登录（`loginType==="uid"`）走
  `updateSpecialUserData()`，**只拉歌单、不拉 djs** ⇒ UID 登录下订阅列表为空，且 `toSubRadio` 会提示「该登录模式暂不支持该操作」。
- **合并方式**：不是增量合并，而是 `dataStore.setUserLikeData("djs", 全量数组)`（先清空语义 = 覆盖写）。

---

## 3. 路由与导航

| path | name | component | meta / 守卫 |
| --- | --- | --- | --- |
| `/radio?id=` | `radio` | `views/List/radio.vue` | 无 meta；`beforeEnter` 缺 `id` → `/403` |
| `/radio-hot` | `radio-hot` | `views/Radio/hot.vue` | 无 meta |
| `/radio-type?id=&name=` | `radio-type` | `views/Radio/type.vue` | 无 meta；`beforeEnter` 缺 `id` 或 `name` → `/403` |
| `/search/radios` | `search-radios` | `views/Search/radios.vue` | 父路由 `/search` 要求 `query.keyword` |
| `/like/radios` | `like-radios` | `views/Like/radios.vue` | 父路由 `/like` 有 `meta:{needLogin:true}` |

**侧边栏入口**：`src/components/Layout/Menu.vue:122-132`，在 `useOnlineService` 分支的**平铺一级菜单**里（不是「发现」子项），
位于「私人漫游」之后、「我喜欢的音乐」之前：

```ts
{ key: "radio-hot", link: "radio-hot", label: "播客电台",
  show: !settingStore.sidebarHide.hideRadioHot, icon: renderIcon("Record") }
```

- 图标用的是 **`Record`**（不是 `Podcast.svg`/`Radio.svg`）。`hideRadioHot` 由
  `components/Modal/Setting/SidebarHideManager.vue:46` 管理。
- 上游「发现」(`/discover`) 只有歌单/榜单/歌手/新歌，**不含播客**。
- 移动端底部导航（`components/Layout/Nav.vue`）**没有**播客入口。

---

## 4. 搜索集成

`src/api/search.ts` 用枚举集中定义，`/search/*.vue` 每个 tab 固定传一个数字：

```ts
export enum SearchTypes {
  Single = 1, Album = 10, Artist = 100, Playlist = 1000, User = 1002,
  Mv = 1004, Lyrics = 1006, Radio = 1009, Video = 1014, All = 1018, Audio = 2000,
}
```

各 tab 实际传值：songs=1、albums=10、artists=100、playlists=1000、**radios=1009**、videos=**1004**（注意不是枚举里的 1014）。

- **tab 注册点**：`views/Search/layout.vue`（`<n-tab name="search-radios">播客</n-tab>`）+ `router/routes.ts:51-55` 子路由；
  tab 切换 = `router.push({name})`，关键词走 `query.keyword`。
- **共用组件**：`views/Search/radios.vue`、`playlists.vue`、`albums.vue`、`videos.vue` **全部复用同一个
  `components/List/CoverList.vue`**，靠 `type: "playlist" | "album" | "video" | "radio"` 分支：
  - 点击进详情：`router.push({ name: props.type, query: { id } })`（radio → `/radio`）
  - 卡片播放：`getListData()` 的 `case "radio"` → `/dj/program?rid&limit=100`
  - 样式差异：`type === 'radio'` 走 `item.creator.id` 显示主播、`updateTip`、`count`；`album` 隐藏遮罩与播放量。
- `CoverMenu.vue`（右键）对 radio 只给「查看详情/播放/暂停/复制名称/复制ID/分享链接」，**没有「订阅」**。

---

## 5. 播放集成（重点）

### 5.1 节目 → 可播放对象

节目 **不转成独立模型**，直接喂给 `formatSongsList`（`utils/format.ts:49`）：

```ts
dj: item.dj ? {
  id: item.mainTrackId || item.id,      // ← 真正用于取播放地址的 id
  radioId: item.radio?.id,
  name: item.dj?.brand,                 // 电台名（播放器里当"专辑"显示）
  creator: item.dj?.nickname,           // 主播名（当"歌手"显示）
} : undefined,
duration: Number(item.duration || item.dt || 0),
type: item?.dj ? "radio" : "song",      // ← 判型靠"有没有 dj 字段"
```

其余字段：`id = program.id`（节目 id）、`name = program.name`、`cover/coverSize ← program.coverUrl`、
`playCount = program.playCount || program.listenerCount`、`createTime = program.createTime`、
`updateTime = program.lastProgramCreateTime || program.scheduledPublishTime`、
`artists = ""`（空串，节目对象没有 artist/artists/ar ⇒ 列表里显示「电台节目」）、
`album = {id:undefined,name:undefined,cover:undefined}`（**不会回落到 mainSong.al**）。

实测样本（电台 972022490）：
`id=3081834575, mainTrackId=2730355242, coverUrl=…, duration=1114226, listenerCount=483053, createTime=1753706790896, scheduledPublishTime=1753706790896, dj.brand=清音悦耳, dj.nickname=清尘伊笑, existLyric=false`。

### 5.2 判型分支（凡是播客就必须特判的地方）

| 位置 | 逻辑 |
| --- | --- |
| `core/player/SongManager.ts:514`（取址）、`:429`（预加载下一首） | `const songId = song.type === "radio" ? song.dj?.id : song.id;` |
| `SongManager.ts:533/432` | `canUnlock = … && song.type !== "radio"` ⇒ **播客不走"解灰"** |
| `core/player/LyricManager.ts:233` | `id = song.type === "radio" ? song.dj?.id : song.id` → `/lyric?id=mainTrackId` |
| `stores/music.ts:60` | `isHasLrc = lrcData.length > 0 && playSong.type !== "radio"` ⇒ **radio 恒定显示 NO-LRC** |
| `PlayerController.ts:587` | `if (song.type !== "radio") dataStore.setHistory(song);` ⇒ **节目不进播放历史** |
| `MediaSessionManager.ts:232-243` | `artist = dj.creator`、`album = dj.name` |
| `utils/format.ts:362-370`（`getPlayerInfoObj`） | 同上，供 Last.fm 上报用 |
| `PlayerMeta/PlayerData.vue:136-139` | radio 时用 `Podcast.svg` 渲染一行主播行，点击 `jumpToRadio()` |
| `SongCard.vue` / `SongList.vue` | radio 时隐藏专辑列、操作列、喜欢按钮；新增「更新日期(`updateTime`)」「播放量(`playCount`)」两列；歌手列显示「电台节目」 |
| `SongPlayList.vue:92` | 队列里 radio 显示「播客电台」占位 |

### 5.3 替换队列 vs 插入队列

- **播放全部**（`ListDetail` 播放按钮 → `radio.vue@play-all` → `useListActions.playAllSongs(songs, radioId)`）
  → `player.updatePlayList(songs, undefined, radioId)`，**整队替换**，并 `musicStore.playPlaylistId = radioId`。
- **双击单集**（`SongList.handleSongPlay` → `player.updatePlayList(listData, song, props.playListId)`）
  **也是整队替换**；但 `radio.vue` 传的是 `:radioId="radioId"`，而 `SongList` **没有声明 `radioId` prop**
  （只有 `playListId`）⇒ 该属性落到 attrs 被忽略，**双击后 `playPlaylistId` 变成 0**（上游 bug，移植时要么补 prop 要么改名）。
- 页面内模糊搜索命中时 `doubleClickAction="add"` → `player.addNextSong(song, true)`，**插入当前播放之后**。
- `CoverList` 卡片播放 → 同样替换队列，`pid = item.id`。

### 5.4 播客专属能力：**一个都没有**（明确结论）

| 能力 | 上游现状 |
| --- | --- |
| 收听进度记忆 | ❌ 无 per-节目记忆。只有全局「上次播放的一集」：`musicStore`（localStorage 全量 persist）+ `statusStore.currentTime`，配合设置项 `memoryLastSeek`（默认 true）在启动时 seek 回原位置；任意往期节目无法续播 |
| 已听标记 / 未听过滤 | ❌ 无。`historyList` 明确排除 radio（`afterPlaySetup`），也没有 played 状态字段 |
| 跳过片头/片尾 | ❌ 无。只有全局 `disableDjMode`（按曲名关键词 `shouldSkipSong` 跳过 DJ 版歌曲），不是播客功能 |
| 倍速 | ⚠️ 只有全局 `statusStore.playRate`（0.2–2.0，localStorage 持久化），**不按播客/节目记忆** |
| 章节 / 时间戳 / 字幕 | ❌ 响应里有 `songTimeStamps`、`existLyric`，上游代码从未读取 |
| 节目搜索（服务端） | ❌ 详情页的模糊搜索是纯前端过滤已加载的 `listData`（`useListSearch`） |
| 按电台订阅推送/更新提醒 | ❌ 无 |

### 5.5 订阅按钮链路

```ts
// src/api/radio.ts:97
export const radioSub = (rid: number, t: number = 1) =>
  request({ url: "/dj/sub", params: { rid, t, timestamp: Date.now() } });
// src/utils/auth.ts:429 —— 取消订阅传的是 2（不是 0）；后端 dj_sub 逻辑为 t==1?sub:unsub，故可用
export const toSubRadio = toLikeSomething("订阅", "播客", () => radioSub, updateUserLikeDjs);
```

- 按钮状态是**前端推导**的：`isLikeRadio = dataStore.userLikeData.djs.some(r => r.id === detailData.id)`，
  **完全忽略 `/dj/detail` 返回的 `subed` 字段**。
- 订阅成功后 `await updateUserLikeDjs()`（重新全量分页拉 `/dj/sublist`），非乐观更新。
- `getComment`/`getHotComment` 的 type：**7 = 电台**（`List/radio.vue` 传 7），4 = 电台节目（`Comment.vue` 走 `radioProgramDetail`）。

---

## 6. 类型定义（`src/types/main.ts`）

上游**没有独立的 radio 类型**，全部塞进通用类型：

```ts
export type DjData = { id: number; radioId?: number; name: string; creator?: string; };

export type SongType = {                     // 节选
  id: number; name: string; artists: MetaData[] | string; album: MetaData | string;
  dj?: DjData;                               // ← 有 dj 就是 radio（判型依据）
  cover: string; coverSize?: CoverSize; duration: number; free: 0|1|4|8;
  mv: number | null; path?: string; pc?: boolean; size?: number; quality?: QualityType;
  createTime?: number; updateTime?: number; playCount?: number;
  type: "song" | "radio" | "streaming";
};

export type CoverType = {                    // 电台/歌单/专辑/视频/MV 共用（节选）
  id: number | string; name: string; cover: string; coverSize?: CoverSize;
  description?: string; creator?: UserType; artists?: MetaData[] | string;
  count?: number; tags?: string[]; playCount?: number; commentCount?: number;
  shareCount?: number; subCount?: number; createTime?: number; updateTime?: number;
  updateTip?: string; tracks?: { first: string; second: string }[];
};

export interface UserLikeDataType { songs: number[]; playlists: CoverType[]; artists: ArtistType[];
  albums: CoverType[]; mvs: CoverType[]; djs: CoverType[]; }   // ← djs
```

`CoverType` 字段来源（`formatCoverList`，`utils/format.ts:117`）：
`id=item.id||item.vid`、`cover=getCoverUrl`、`description=item.description||item.desc`、
`updateTip=item.updateFrequency`、`creator={dj.userId, dj.nickname, dj.avatarUrl}`、
`count=item.trackCount ?? item.size ?? item.programCount`、`tags=item.tags||algTags||videoGroup||[category]`、
`duration=msToTime(item.duration||item.dt||item.playTime)`。
⚠️ **电台详情没有 `updateTime`**（实测 `lastProgramCreateTime` 存在但不在 `formatCoverList` 的取值白名单里）
⇒ `detail.updateTime` 为 undefined，列表缓存失效判定（`useListDataCache.checkNeedsUpdate`）实际只能比 `count`。

---

## 7. 订阅状态的本地存储

- **服务端为唯一真相**：`/dj/sublist` 全量分页 → `dataStore.setUserLikeData("djs", ...)`。
- **落盘位置：IndexedDB（localforage），不是 localStorage**：

```ts
// stores/data.ts
const userDB = localforage.createInstance({ name: "user-data", storeName: "user" });
async setUserLikeData(name, data) { await userDB.setItem(name, toRaw(data)); this.userLikeData[name] = data; }
persist: { key: "data-store", storage: localStorage,
           pick: ["userLoginStatus","loginType","userData","userList","searchHistory","catData"] } // 不含 userLikeData
```

- 启动时 `dataStore.loadData()`（`composables/useInit.ts` onMounted）把 `userDB` 里所有 key 灌回 `userLikeData`（离线可见最后一次结果）。
- **没有 per-账号隔离**：`user-data` 库只有一份 `djs` key，切号靠 `updateUserData()` 覆盖；登出 `clearUserData()` 全部置空。
- **无本地订阅队列/离线改写**：订阅是「请求成功 → 重拉列表」，失败则本地不变。

---

## 8. RSS：**确认没有实现**（明确结论）

证据（全仓 grep + 依赖 + 文件树）：

| 检查 | 结果 |
| --- | --- |
| 文件名含 rss/feed/podcast/xml | 只有 `src/assets/icons/{RssFeed,Podcast,Radio}.svg` 三个图标，**无任何 rss/feed/xml 模块** |
| `src`/`electron`/`web` 内容 grep `rss\|podcast\|feed` | 仅 3 个命中：`Setting/AboutSetting.vue:332`（**RssFeed.svg 用于"官方博客"外链图标**）、`PlayerMeta/PlayerData.vue:138`（Podcast.svg 用于播放器主播行）、`electron/main/update/index.ts`（自动更新 feed 无关文案） |
| `package.json` 依赖 | 无 `rss-parser` / `fast-xml-parser` / `xml2js` / `feed` 等任何解析库 |
| 路由 / 设置项 | 无 RSS 订阅页、无 RSS 源管理设置 |
| `src/api/radio.ts` | 全部是网易云 `/dj/*`，无 RSS/Atom 抓取 |

⇒ **上游的"播客"就是网易云 DJ 电台，`RssFeed.svg` 只是博客链接图标，移植时不要误当成 RSS 功能。**
若 Next 要真 RSS，属于**全新子系统**（抓取 + 解析 + 本地订阅存储 + 本地/远程音频直链播放），上游没有任何可抄的代码。

---

## 9. 移植到 SPlayer-Next 时必须注意的差异/坑

1. **后端契约**：上游全部走 NeteaseCloudMusicApi 兼容代理（`baseURL = isDev ? "/api/netease" : VITE_API_URL`，
   axios 拦截器注入 `cookie=MUSIC_U=…;os=pc;`、可选 `realIP/randomCNIP/proxy`、3 次重试）。
   Next 是在主进程自实现 `dj_*` 模块（weapi），必须对齐这些路径与参数名（已实测，来自 NeteaseCloudMusicApi 4.32.0 源码）：

   | Next 模块 | 上游路径 | 参数 | 加密 |
   | --- | --- | --- | --- |
   | `dj_detail` | `/api/djradio/v2/get` | **`id`（不是 rid！）** | weapi |
   | `dj_program` | `/api/dj/program/byradio` | `radioId`、`limit ?? 30`、`offset ?? 0`、`asc` | weapi |
   | `dj_program_detail` | `/api/dj/program/detail` | `id`（节目 id） | weapi |
   | `dj_sublist` | `/api/djradio/get/subed` | `limit ?? 30`、`offset ?? 0`、`total: true` | weapi |
   | `dj_sub` | `/api/djradio/sub` / `/unsub` | `id=rid`、`t`（**1 订阅 / 其它=取消**） | weapi |
   | `dj_catelist` | `/api/djradio/category/get` | 无 | weapi |
   | `dj_recommend_type` | `/api/djradio/recommend` | `cateId = query.type`（分类 id 即此处 type） | weapi |
   | `dj_toplist` | `/api/djradio/toplist` | `type`（**0=新晋 / 1=热门**，不是字符串）、limit/offset | weapi |
   | `dj_hot`（类别热门） | `/api/djradio/hot` | `cateId`、limit/offset | weapi |
   | `dj_category_recommend` | `/api/djradio/home/category/recommend` | 无 | weapi |
   | `dj_recommend` | `/api/djradio/recommend/v1` | 无 | weapi |
   | `dj_personalize_recommend`（下游可省） | `/api/djradio/personalize/rcmd` | `limit ?? 6` | weapi |

   响应 key：`catelist → {categories[]}`、`detail → {data{}}`、`program → {code,count,more,programs[]}`、
   `sublist/recommend/hot/radio-hot → {djRadios[]}`、`toplist → {toplist[]}`、`recommend/type → {djRadios,hasMore}`、
   `category/recommend → {data[{categoryId,categoryName,radios[]}]}`、
   `cloudsearch(type=1009) → {result:{djRadios[],djRadiosCount,hasMore}}`。

2. **id 语义是最大的坑**：上游 `SongType.id = program.id`（节目 id），**真正取地址用的是 `dj.id = mainTrackId`**，
   播放器/歌词/预加载三处都 `song.type === "radio" ? dj.id : id`。
   而 Next 的既有约定相反：`Track.id = mainSong.id`、`Track.extId = program.id`（打卡依赖 extId）。
   ⇒ 移植时**不要照抄上游的 SongType 形状**，只照抄「取址用 mainTrackId」这一事实。
3. **`/song/url` 对节目有效**：实测 `mainTrackId=2730355242` → 返回 320kbps 直链、`fee=0`。
   但节目**不能走"解灰"(unlock)**（上游显式禁用），Next 的 track resolver 也要为 radio 屏蔽 unlock 分支。
4. **分页 500 条 + 循环**：上游详情页一次要 `limit=500` 并循环到 `detail.count`。实测网易云接口在连续大 limit 请求后
   返回 `code 406`（风控），且 `byradio.count`(664) 与 `detail.programCount`(787) 不一致，会出现"多请求一页空数据"。
   Next 侧建议改成 `limit<=200` + 以 `more`/返回条数收敛，而不是以 programCount 为循环条件。
5. **`radioId` prop 缺失 bug**：上游 `List/radio.vue` 给 `SongList` 传 `:radioId`（不存在的 prop）导致双击播放后
   `playPlaylistId=0`。Next 移植时用 `collectionId` 正确传。
6. **`program` 上没有音质信息**：`handleSongQuality(program,"online")` 读不到 `level/privilege/br` ⇒ 基本返回 undefined；
   封面/时长/主播全部来自 program 顶层与 `dj.*`，**不要指望 mainSong.al / mainSong.artists**（上游也没用）。
7. **详情页没有 `updateTime`**：Next 的列表缓存失效不要比 `updateTime`，改用 `lastProgramCreateTime`（detail 顶层有，实测存在）。
8. **订阅态只认本地列表**：忽略 `/dj/detail` 的 `subed` / program 的 `subscribed`；UID 登录不支持订阅；
   登出会清空 `djs`；Next 若用 per-account key 存订阅（现有 store 已是 per-user）需自行决定与服务端的合并策略。
9. **组件/依赖不可直接搬**：Naive UI（`n-card/n-grid/n-tabs/n-empty`）、`window.$message`、pinia `persist` 插件、
   `localforage`、`@/utils/request`(axios-retry)、`composables/List/{useListDetail,useListSearch,useListScroll,useListActions,useListDataCache}`、
   `ListDetail`/`CoverList`/`SongList`/`CoverMenu` 都是 SPlayer 专有，Next 需按自己的 `Collection.vue`/`SongList.vue`/i18n 重写；
   `useListDataCache` 还**只在 Electron 下生效**（`if (!isElectron) return null`，走 `CacheManager` 磁盘缓存）。
10. **详情页缓存三件套**：`loadCache("radio", id)` 先出缓存 → 后台 `radioDetail` 比对 → 变了才全量重拉；
    `moreOptions` 提供「刷新缓存 / 刷新播客 / 复制分享链接(`djradio` 类型) / 打开源页面(music.163.com/#/djradio?id=)」。
    若 Next 不做缓存，可先忽略但需保留"刷新"语义。
11. **`getCoverUrl` 回退链**是 `cover → picUrl → coverUrl → coverImgUrl → imgurl → img1v1Url → album/al.picUrl`，
    电台用 `picUrl`、节目用 `coverUrl`；`getCoverSizeUrl` 拼 `?param=NxN`，缺图回退 `/images/song.jpg?asset`。
12. **图标**：`Podcast.svg`（播放器主播行）、`Radio.svg`（菜单"私人漫游"）、`RssFeed.svg`（关于页博客链接）；
    侧边栏播客入口用的是 `Record` 图标。Next 加图标时别语义错位。

---

## 10. 证据文件（实际读过/实测的）

**上游源码（`SPlayer-Dev/SPlayer@dev`，本地 `.probe/repo/`）**
`src/api/radio.ts`、`src/api/user.ts`、`src/api/search.ts`、`src/api/song.ts`、`src/api/comment.ts`、`src/api/video.ts`、
`src/views/Radio/hot.vue`、`src/views/Radio/type.vue`、`src/views/List/radio.vue`、
`src/views/Search/{layout,radios,videos}.vue`、`src/views/Like/{layout,radios}.vue`、`src/views/Home/HomeOnline.vue`、`src/views/Comment.vue`、
`src/components/List/{CoverList,SongList,ListDetail,ListComment,SongPlayList}.vue`、`src/components/Card/SongCard.vue`、
`src/components/Menu/CoverMenu.vue`、`src/components/Layout/{Menu,User}.vue`、`src/components/Player/PlayerMeta/PlayerData.vue`、
`src/components/Global/SvgIcon.vue`、`src/components/Modal/Setting/SidebarHideManager.vue`、
`src/router/{routes,index}.ts`、`src/stores/{data,music,status,setting}.ts`、
`src/composables/useInit.ts`、`src/composables/List/{useListActions,useListDataCache}.ts`、
`src/utils/{format,auth,request,cache,helper}.ts`、
`src/core/player/{SongManager,LyricManager,MediaSessionManager,PlayerController}.ts`、`src/utils/lastfmScrobbler.ts`、
`src/components/Setting/AboutSetting.vue`、`electron/main/update/index.ts`、`package.json`、`.env.example`、`electron.vite.config.ts`

**后端契约（NeteaseCloudMusicApi 4.32.0，本机 tarball `.ncmapi/package/module/`）**
`dj_detail.js`、`dj_program.js`、`dj_program_detail.js`、`dj_sub.js`、`dj_sublist.js`、`dj_catelist.js`、
`dj_category_recommend.js`、`dj_recommend_type.js`、`dj_toplist.js`、`dj_hot.js`、`dj_radio_hot.js`、`dj_recommend.js`、
`dj_personalize_recommend.js`、`djRadio_top.js`、`aidj_content_rcmd.js`

**真实接口实测（2026-10-04，无登录 `os=pc` cookie，python urllib）**
`GET music.163.com/api/djradio/v2/get?id=972022490`（detail 全字段、无 updateTime）、
`GET …/api/dj/program/byradio?radioId=972022490&limit=N&asc=`（程序字段、排序、`count=664` vs `programCount=787`、连续大 limit 触发 `code 406`）、
`GET …/api/djradio/{category/get,recommend?cateId=3,hot/v1,home/category/recommend,recommend/v1,toplist,get/subed,personalize/rcmd}`、
`GET …/api/cloudsearch/pc?s=故事&type=1009`（`result.djRadios/djRadiosCount`）、
`GET …/api/song/enhance/player/url?ids=[2730355242]&br=320000`（节目 mainTrackId 可直链、fee=0）。
