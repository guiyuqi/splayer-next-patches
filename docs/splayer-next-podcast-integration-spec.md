# SPlayer-Next 播客 / 电台（网易云 DJ radio）子系统集成规格

调研范围：`repo/`（只读，未修改任何仓库文件）。行号均以调研时工作区为准。

## 0. 结论先行：仓库已预留一半骨架

已存在的 radio 基础设施（**不需要新造**）：

| 已有物 | 位置 |
| --- | --- |
| `CollectionType` 含 `"radio"` | `src/types/collection.ts:7` |
| `PlaybackOriginType` 含 `"radio"` | `shared/types/player.ts:17` |
| `Collection.vue` 的 `typeLabel` / `playbackContext` / 图标已处理 radio | `src/pages/Collection.vue:97-104,135-144,289` |
| 详情页路由 `collection/:source/:type/:id` | `src/router/index.ts:61-64` |
| `SongList` 接受 `collectionType: CollectionType` | `src/components/list/SongList.vue:53,224` |
| radio 分享链接 | `src/utils/format/shareUrl.ts:43-49` |
| radio 更多菜单 i18n | `src/i18n/locales/zh-CN.json` → `collection.radio`、`collection.context.radio.*` |
| 播客打卡元数据（`resourceType: "dj"`、节目 id 用 `extId`、电台 id 用 `album.id`） | `shared/utils/neteaseScrobble.ts:54-84` |
| 打卡上报链路的 `djradio` 来源映射 | `electron/main/apis/netease/core/playLog.ts:59-62`、`modules/scrobble.ts:30-46` |
| `Track.extId` / `mediaId` 槽位 | `shared/types/player.ts:88-90` |

真正缺的四件事：① 主进程 `dj_*` 模块；② 渲染层 dj API + `loadNeteaseCollection` 的 radio 分支；③ 播客列表页 + 侧边栏一级入口；④ 「订阅电台」的 store / composable 分支。

---

## 1. 主进程网易云 API 模块的写法

### 1.1 标准结构（三个代表例）

eapi 代表 —— `electron/main/apis/netease/modules/playlist_detail.ts:1-26`：

```ts
/**
 * 歌单详情
 *
 * params:
 * - id  歌单 id
 * - s   收藏者数量，默认 8
 *
 * 响应：`{ code, playlist: { id, name, ..., tracks, trackIds }, privileges }`
 * 加密：默认 eapi（对齐 NCM 增强版 playlist_detail 行为）
 */
import { createOption } from "../core/option";
import type { NeteaseModule } from "../core/types";

const playlistDetail: NeteaseModule = (query, request) => {
  const data = { id: query.id, n: 100000, s: query.s ?? 8 };
  return request("/api/v6/playlist/detail", data, createOption(query));
};

export default playlistDetail;
```

weapi + 分页代表 —— `modules/artist_songs.ts:1-26`（`createOption(query, "weapi")`，`order ?? "hot"`、`offset ?? 0`、`limit ?? 50`）；
weapi 最简 —— `modules/album.ts:13-14`（路径内插值、空 data）；
写操作 + `t` 约定 —— `modules/playlist_subscribe.ts:14-18` / `album_sub.ts:14-18`。

- 文件头 JSDoc 固定三段：中文一句话说明 → `params:` 列表 → `响应:` 结构（可加「加密：」说明）。
- 类型：`NeteaseModule = (query, request) => Promise<RequestResponse>`（`core/types.ts:9-11`），只 `export default` 一个函数，无具名导出。

### 1.2 参数校验 / 默认值惯例

`core/option.ts:11-30` 的 `Query` **没有逐接口类型**，只有 `crypto/cookie/ua/realIP/ip/e_r/domain/checkToken` 加 `[key: string]: unknown`。惯例：

- 可选参数 `?? 默认值`：`limit: query.limit ?? 30`、`offset: query.offset ?? 0`（`modules/user_playlist.ts:11-12`）。
- 必填 id 直接透传，**不做校验、不抛错**（`modules/playlist_detail.ts:19`）。
- 逗号分隔 id 列表：`String(query.ids ?? "").split(",").map(s => s.trim()).filter(Boolean)`（`modules/song_detail.ts:14-17`）。
- 布尔动作统一用 `t`：`query.t === 2 ? "unsubscribe" : "subscribe"`（`modules/playlist_subscribe.ts:15`）。
- 条件字段用 `if (query.x) data.x = ...`（`modules/personal_fm.ts:13-15`）。

### 1.3 注册方式：**手工登记，无自动扫描**

`electron/main/apis/netease/modules/index.ts`：顶部按业务分组 `import`（`:11-107`），底部一张表：

```ts
// modules/index.ts:124
export const modules: Record<string, NeteaseModule> = {
  ...
  playlist_detail,
  ...
  song_url_v1: song_url,   // :160 同一函数可挂多个 key
};
```

路由守卫在 `electron/main/apis/netease/index.ts:212`：`Object.hasOwn(modules, name) ? modules[name] : undefined`，未注册即抛 `unknown netease api: ${name}`。
→ **新增 `dj_*` 必须同时在本文件加 `import` 与 `modules` 条目。**

### 1.4 `callNetease` 签名、返回值、cookie 来源

`electron/main/apis/netease/index.ts:207-266`：

```ts
export const callNetease = async (
  name: string,
  params: Record<string, unknown> = {},
): Promise<{ status: number; body: any }> => { ... }
```

- 成功返回 `{ status, body }`（`body` 是已解密的网易云业务体）；非 200 抛 `NeteaseRequestError`（`core/request.ts:54-64`），IPC 层转 `{ ok:false, error, status, body }`（`electron/main/ipc/apis.ts:52-59`）。
- **cookie 自动注入**，调用方无需传：`getSessionCookies("netease")`（SQLite，`@main/database/sessions`）→ 进程内 `sessionCache`（`index.ts:120-132`）；传了 `params.cookie` 则覆盖（`:233-239`）。
- 未登录时先 `ensureNeteaseAnonymousSession()`（`:220-222`）→ 走 `register_anonimous`（xeapi）拿 `MUSIC_A` 落库（`:175-200`）。`params.cookie === undefined` 才会触发。
- 响应缓存默认 2 分钟、LRU 200 条（`core/cache.ts:12-15`）。**写操作必须登进 `NON_CACHEABLE`**（`index.ts:40-82`），否则 2 分钟内读到旧响应（现有 `playlist_subscribe` 在 `:62`、`album_sub` 在 `:77`）。
- 仅 `SESSION_MUTATING`（登录类）才把 set-cookie 写回 SQLite（`:30-37,249-260`）。

### 1.5 加密模式与 `/dj/*` 的门槛

- `createOption(query)` 不传 crypto → `crypto: ""` → `createRequest` 回落 **`"eapi"`**（`core/option.ts:44` + `core/request.ts:166-167`）。`playlist_detail`、`cloudsearch`、`lyric_new` 都是这个默认。
- 显式 `"weapi"`：`user_playlist`、`artist_songs`、`album`、`album_sub`、`artist_sub`、`comment_music`、`artist_sublist` 等。
- `"xeapi"`：`song_url`（`modules/song_url.ts:29`）、`like_v1`（`modules/like_v1.ts:20`，唯一带 `checkToken` 的）、`register_anonimous`（`:31`）。xeapi 需 `ensureXeapiKey` 协商会话密钥（`core/request.ts:211-249`）。
- **不存在「只有 eapi 能用」的硬门槛**：任何接口都能拿到匿名 `MUSIC_A` 或登录 cookie。`/dj/*` 用 `weapi` 或默认 eapi 都能带 cookie；**但服务端是否接受该加密模式属于风控问题，本仓库无法静态判定**（见第 9 节）。
- `X-antiCheatToken`（易盾）只在模块显式传第三参时请求（`createOption(query, "eapi", "v3")`，`core/checktoken.ts:16-30`）。`/dj/*` 目前无证据需要它。

---

## 2. 渲染层怎么调网易云

**核心：`src/apis/netease.ts` 是 Proxy，无需为每个接口改任何管道。**

```ts
// src/apis/netease.ts:81-86
export const netease: NeteaseProxy = new Proxy({} as NeteaseProxy, {
  get: (_t, name: string) => <T = any>(params?: Record<string, unknown>) =>
    neteaseCall<T>(name, params),
});
```

- 调用链：`netease.dj_detail({...})` → `neteaseCall` → `neteaseRaw` → `window.api.apis.call("netease", name, params)`（`src/apis/netease.ts:41-74`）。
- **IPC 通道名只有 4 个且固定**：`apis:call` / `apis:clearSession` / `apis:openLoginWeb` / `apis:setCookie`（`electron/main/ipc/apis.ts:43-116`），类型 `ApisApi` 在 `shared/types/apis.ts:14-46`。**新增 `dj/*` 不用动 IPC / preload / platform 枚举**（`ApiPlatform` 保持 `netease|qqmusic|kugou`）。
- 需要改的渲染层文件（薄封装，仿 `src/apis/album/netease.ts:9-29`）：
  - 新增 `src/apis/radio/netease.ts`：`fetchRadio` / `fetchRadioPrograms` / `subscribeRadio`；
  - 新增映射 `toDjRadio` / `programToTrack`（放 `src/utils/format/radio.ts`）；
  - 失败处理沿用 `ensureOk`（`src/utils/format/netease.ts:18-24`）。

---

## 3. 页面 / 路由 / 导航落点

### 3.1 路由

`src/router/index.ts` 单文件、`createWebHashHistory`、全部懒加载。列表页挂在 `/` 的 `MainLayout` children 下（`:17-122`）；详情页统一 `collection/:source/:type/:id` → `Collection.vue`（`:61-64`）。

### 3.2 keep-alive / 缓存策略

```ts
// src/layouts/MainLayout.vue:34-48
const cachedViews = ["Home","Library","Liked","History","Download","Daily",
  "Favorites","Cloud","LocalList","Folders","SearchPage","Stats","StreamingIndex"];
// :139  <KeepAlive :max="10" :include="cachedViews">
```

按**组件 `name`** 匹配 → 新页面要缓存必须 `defineOptions({ name: "Podcast" })`（仿 `src/pages/Favorites.vue:2`）并加进 `cachedViews`。`Collection.vue` 不在白名单（详情页不缓存），**建议播客详情也复用 `Collection.vue` 而非新页面**。
另外 `routeKey`（`:28-31`）对含 `:` 的路由按 `route.path` 区分 key。

### 3.3 侧边栏「播客」一级入口

两处必须同步改：

```ts
// src/components/layout/sidebarNav.ts:26-44
const SIDEBAR_NAV_ENTRIES: SidebarNavEntry[] = [
  { key: "/", labelKey: "nav.home", icon: IconLucideHome, hideable: false },
  ...
  { key: "/streaming", labelKey: "nav.streaming", icon: IconLucideLibrary, hideable: true },
];
```

```ts
// src/types/settings.ts:103-114
export const DEFAULT_SIDEBAR_NAV_GROUPS: SidebarNavGroup[] = [
  { name: "", showName: false,
    keys: ["/", "/library", "/artists/local", "/albums/local", "/folders", "/stats"] },
  { name: "", showName: false,
    keys: ["/liked", "/favorites", "/cloud", "/download", "/streaming", "/history"] },
];
```

- 渲染顺序取自 `appearance.sidebarNavGroups`（`src/components/layout/SideBar.vue:177-215`），`hideable: true` 才进右键隐藏菜单（`:251`）。
- 老存档对账：`reconcileNavGroups` / `reconcileHiddenKeys`（`src/stores/settings.ts:52-90`）会把新 key 自动补进末组，**用户无需重置设置**。
- 可选的功能闸门写法（若要「设置里开关播客入口」）：`SideBar.vue:186-187` 的 `if (key === "/streaming" && !systemSettings.streaming.enabled) continue;`，配套 `shared/defaults/settings.ts:129-131` 的 `streaming: { enabled: true }` 与 `shared/types/settings.ts`。

### 3.4 可复用组件清单

| 组件 | props | 需要的数据结构 |
| --- | --- | --- |
| `src/components/list/SongList.vue` | `items: Track[]`、`searchQuery`、`showIndex/showAlbum/showDuration/showSize/enableSort`、`source: TrackSource`、`collectionType: CollectionType`、`collectionId`、`playbackContext: PlaybackContext`、`canRemove`、`hasMore`、`loadingMore`；emit `scroll`/`change` | `Track[]`（`shared/types/player.ts:84`）；**已支持 `collectionType:"radio"`** |
| `src/components/list/CoverList.vue` | `items: CoverItem[]`、`type:"default"\|"artist"`、`virtual`、`minSize`、`gap`、`rounded`、`paddingX/Top/Bottom`、`hasMore`、`loadingMore`；emit `click(item)`/`reachBottom` | `CoverItem[]`（`src/types/artist.ts:4-15`：`{id,title,cover?,subtitle?,trackCount}`） |
| `src/components/list/CoverCard.vue` | `item: CoverItem`、`type`、`rounded`、`fallback` | 同上 |
| `src/components/ui/SVirtualList.vue` | 虚拟滚动底座，`CoverList.vue:3` 引用 | — |
| `src/components/ui/STabs.vue` | 页签（范例 `src/pages/Favorites.vue:38-42,110`） | `{key,label}[]` |
| 空态/加载/错误三段式 | 无组件，直接照抄 `src/pages/Collection.vue:431-455`（`SLoading`/`SButton`） | — |

- 无限滚动契约：`hasMore` + `@reachBottom`（`CoverList.vue:27-30,58`），分页范例 `src/pages/Search.vue:79-105,174-176`。
- 封面图一律走 `withPicSize`（`shared/utils/netease.ts:44-48`）。
- **页面目录规范**：`src/pages/*.vue` 扁平；唯一子目录 `src/pages/Streaming/` 用嵌套路由 + `Index.vue` 做壳（`router/index.ts:96-121`）。布局只有 `src/layouts/MainLayout.vue`（`/onboarding`、`/agreement-update` 在布局外）。列表页最佳范例：`src/pages/Daily.vue`（顶栏 + `SongList`）、`src/pages/Favorites.vue`（`STabs` + `CoverList`）。

### 3.5 `Collection.vue` 对 radio 的兼容性（已核对，无需改）

- 编辑/删除按钮由 `manage.canManage` 控制，`canManage` 硬性要求 `current.type === "playlist"`（`src/composables/collection/usePlaylistManage.ts:30-39`）→ **radio 不会误显示编辑/删除**。
- `copyUrl` 走 `getCollectionShareUrl`，radio 分支已存在（`src/utils/format/shareUrl.ts:43-49`）。
- `playbackContext` 直接 `originType: current.type`（`Collection.vue:135-144`）→ radio 就绪后自动是 `"radio"`。

---

## 4. 状态管理：订阅 / 收藏抽象

- 通用 composable：`src/composables/collection/useCollectionSubscribe.ts`，**只认 netease 的 playlist / album**：

```ts
// useCollectionSubscribe.ts:6-11
/**
 * 通用收藏 / 取消收藏
 * 当前支持：netease playlist / album
 * 待接入：netease radio
 */
```

`isSubscribed` 读 `userStore.subscribedPlaylists` / `userStore.albums`（`:18-28`）；`available` 排除自建歌单（`:31-39`）；`toggle` 分发到 `togglePlaylistSubscribe` / `toggleAlbumSubscribe`（`:48-52`）。

- 动作实现在 `src/stores/user.ts`：`togglePlaylistSubscribe:588`、`toggleAlbumSubscribe:597`、`toggleArtistSubscribe:603`；`loadContent` 用 `Promise.allSettled` 并发拉歌单/红心/专辑/歌手/等级（`:424-451`）；列表来源 `src/apis/user/netease.ts:52-63`（`fetchAllPages` 通用分页器）。
- **不存在「任意实体类型」的统一枚举**：类型判断分散在 `CollectionType`（`src/types/collection.ts:7`）与 user store 的三个扁平数组 `playlists/albums/artists`。
- → **两个枚举都不用扩展**（`"radio"` 已在 `CollectionType` 与 `PlaybackOriginType` 里）。新增「订阅电台」只需：`user.ts` 加 `radios` + `toggleRadioSubscribe` + `loadContent` 加一项；`src/apis/user/netease.ts` 加 `fetchUserRadios`；`useCollectionSubscribe.ts` 各加一个 radio 分支。
- 电台领域模型**建议复用 `Playlist`**（`shared/types/player.ts:55-63`，id/name/cover/description/trackCount/owner 完全够用），避免新增 `DjRadio` 类型扩散。

---

## 5. 播放集成

### 5.1 入队 / 播放入口

`src/core/player/index.ts`：

| 函数 | 行 | 用途 |
| --- | --- | --- |
| `playFrom(items, startIndex=0, context?)` | `:760` | 整批替换队列并播放（会清 `heartMode`/`fmMode`） |
| `playNow(item, context?)` | `:1236` | 单曲插入当前位置之后并立即播放 |
| `insertToQueue(item, afterIndex?, context?)` | `:1180` | 单曲插入，已存在则更新+移动 |
| `insertManyToQueue(items, position="next"\|"end", context?)` | `:1212` | 批量插入（按 id 去重） |

context 落到每个队列项 `{track, context}`（`src/stores/queue.ts:24,65`），当前项经 `status.currentPlaybackContext`（`src/stores/status.ts:112`）→ `media.setPlaybackContext`（`player/index.ts:358`）→ 主进程打卡（`electron/main/services/neteaseScrobble.ts:80-90`）。

### 5.2 `PlaybackContext` 与来源标记

```ts
// shared/types/player.ts:17-29
export type PlaybackOriginType = "track" | "playlist" | "album" | "artist" | "radio" | "page";
export interface PlaybackContext {
  provider?: TrackSource;  // "local" | "streaming" | Platform
  originId: string;
  originType: PlaybackOriginType;
  originName?: string;
}
```

**已有 `"radio"`，没有 `"podcast"`。** `PlayerData.vue:108-122` 把 `context.originType` 原样当 `ResourceNavigationTarget.type` 传给 `navigateToResource` → 落到 `collection` 路由（`src/utils/navigate.ts:75-79`）。因此 **`PlayerData.vue` 与 `navigate.ts` 都不用改**，只要 `loadNeteaseCollection` 支持 radio，全屏播放器的「播放来源」徽标点击即可跳转。

### 5.3 让播客单集可播放 / 入队的最少步骤

`dj/program/detail` 返回 `program { id, mainSong, radio, coverUrl, duration }`。映射成 `Track` 的关键约定（**已被现有打卡逻辑反向确定**，见 `shared/utils/neteaseScrobble.ts:60-76` 与 `electron/main/services/neteaseScrobbleMeta.test.ts:67-93`）：

1. `Track.id = String(program.mainSong.id)` —— 播放解析只认 `track.id`（`src/apis/song/netease.ts:73-77`）。
2. `Track.extId = String(program.id)` —— 节目 id；scrobble 靠 `asNumericId(track.extId)` 判定 `resourceType: "dj"`（`shared/utils/neteaseScrobble.ts:62,76`）。
3. `Track.album = { id: String(program.radio.id), name: program.radio.name, cover }` —— 电台 id 作为打卡 `sourceId`（同文件 `:67,70`；测试用例断言 `extId:"3081133072"` / `album.id:"9988"` → `sourceId:"9988"`、`resourceType:"dj"`）。
4. `duration = program.duration`、`fee = program.mainSong.fee`、`cover = withPicSize(program.coverUrl)`、`comment = program.description?`、`artists = [{ name: program.radio.name }]`。
5. 播放：`player.playFrom(tracks, 0, { provider: "netease", originId: String(radio.id), originType: "radio", originName: radio.name })`。

→ **不能直接用 `songToTrack`**：`shared/utils/netease.ts:88-112` 不产出 `extId`，且专辑字段取的是 `mainSong.al`（会丢掉电台 id）。需要新纯函数 `programToTrack(program)`。

---

## 6. i18n 与设置

### 6.1 i18n 键组织

`src/i18n/locales/{zh-CN,en-US}.json`，`src/i18n/index.ts:1-13` 静态 import（无懒加载，`fallbackLocale: "en-US"`）。zh-CN 顶层命名空间（共 36 个）：
`update / onboarding / agreementUpdate / common / comments / equalizer / speed / autoClose / abLoop / uiZoom / nav / recognition / home / login / search / streaming / player / songList / quality / playlist / liked / cloud / history / download / daily / favorites / library / settings / collection / artist / album / folder / stats / errors / tagEditor`

新增播客文案的落点：

- 一级入口 → `nav.podcast`（SideBar 用 `t(entry.labelKey)`，`SideBar.vue:188`）。同层已有 `nav.home/nav.cloud/nav.streaming/nav.stats`。
- 详情页 → **复用 `collection.*`**：`collection.radio`（"电台"/"Radio"）、`collection.context.radio.{copyTitle,copyId,copyUrl}` 均已存在。
- 列表页/页签 → 建议新开 `podcast.*`（`podcast.title` / `podcast.empty` / `podcast.notLogin` / `podcast.tabs.*`）；若要挂进「我的收藏」页则加 `favorites.tabs.radio`（现有 `favorites.tabs` 只有 playlist/album/artist，`src/pages/Favorites.vue:22-42` 的 `FavTab` 联合类型需同步扩）。
- **zh-CN 与 en-US 必须成对新增。**

### 6.2 settings schema 写法

`src/settings/schema.ts:15-34` 只是类目数组；类目文件在 `src/settings/categories/*.ts`：

```ts
// src/settings/categories/services.ts:8-25
const servicesCategory: SettingCategory = {
  id: "services",
  icon: IconLucideGlobe,
  sections: [
    { id: "network", items: [
      { key: "networkProxyProtocol", type: "select",
        binding: { store: "settings", path: "system.system.networkProxy.protocol" },
        options: [{ value: "off", labelKey: "settings.networkProxyProtocol.off" }],
        defaultValue: "off" },
    ]},
  ],
};
```

类型定义 `src/types/settings-schema.ts`（`SettingCategory → SettingSection → SettingItem`，`SettingItem.binding = { store: "settings"|"theme", path }`）。i18n 约定 `settings.section.{id}` / `settings.{itemKey}.{label,description}`（AGENTS.md:99）。`system.*` 路径经 IPC 落主进程 config。
主进程开关需三处同步：`shared/defaults/settings.ts`（默认值，参照 `streaming: { enabled: true }` 在 `:129-131`）、`shared/types/settings.ts`（类型，`SystemConfig` 在 `:480` 附近）、消费处（如 `SideBar.vue:187`）。

---

## 7. 类型位置约定

- **跨进程类型 → `shared/types/`**：现有 `player.ts / lyrics.ts / platform.ts / streaming.ts / settings.ts / apis.ts / library.ts / comment.ts / errors.ts ...`。`Track.extId`、`mediaId` 已在 `shared/types/player.ts:88-90`。（AGENTS.md:206-209 明确要求）
- **纯映射/派生工具 → `shared/utils/`**：`netease.ts`、`neteaseScrobble.ts`、`track.ts`、`path.ts`；渲染层薄封装留在 `src/utils/format/netease.ts` 并 re-export（`:5-6`：`export { pickQuality, songToTrack, songsToTracks, withPicSize }`）。
- **渲染层专用类型 → `src/types/`**：`collection.ts`（`Collection`/`CollectionType`）、`artist.ts`（`CoverItem`/`ArtistProfile`）、`netease.ts`、`settings.ts`、`list.ts`、`user.ts`。
- **网易云原始响应类型现在有两套并存**：
  - `shared/utils/netease.ts:17-41` `NeteaseRawSong` —— **映射用的最小字段集**，跨进程共用，`songToTrack` 的入参；
  - `src/types/netease.ts:89-137` `NeteaseSong` —— 渲染层较完整字段（含 `privilege`/`pc`/`mv`）。
  → 新增 `NeteaseDjRadio` / `NeteaseDjProgram` 建议照 `NeteaseSong` 的粒度放 `src/types/netease.ts`；若 `programToTrack` 要放 `shared/utils/` 跨进程共用，则原始类型也要放 `shared/utils/radio.ts`（或复用 `shared/utils/netease.ts` 的最小字段风格）。

---

## 8. 测试与门禁

两个 runner（`package.json` scripts）：

```
"test":      "pnpm test:node && pnpm test:web"
"test:node": "tsx --test \"electron/**/*.test.ts\" \"src/**/*.test.ts\""   // node:test + node:assert
"test:web":  "vitest run --config vitest.config.ts"
```

```ts
// vitest.config.ts:35-40
include: ["electron/**/*.spec.ts", "src/**/*.spec.ts",
          "windows/**/*.spec.ts", "docs/**/*.spec.ts"],
```

- ⚠️ **`shared/` 不在任何 include 里**，且当前 `shared/` 下 0 个 `*.spec.ts` / `*.test.ts`。
- vitest 别名：`@` `@main` `@shared` `@windows` `@root`（`vitest.config.ts:17-25`）。
- 现有 `electron/main/apis/**/*.test.ts`（`playLog.test.ts`、`scrobble.test.ts`、`utils.test.ts`）走的是 `tsx --test`，**不会被 vitest 收集**，两者不要混。

**新增纯函数（`programToTrack` / `toDjRadio`）的推荐落位与测试位置：**

| 纯函数位置 | 测试位置 | 依据范例 |
| --- | --- | --- |
| `src/utils/format/radio.ts` | `src/utils/format/radio.spec.ts`（vitest） | `src/utils/format/netease.ts` + `src/utils/format/netease.spec.ts:1-31` |
| `shared/utils/radio.ts` | `src/utils/format/radio.spec.ts` 或 `electron/main/services/radio.test.ts`（**import `@shared/utils/radio`**） | `shared/utils/neteaseScrobble.ts` + `electron/main/services/neteaseScrobbleMeta.test.ts:1-7`（node:test 测 shared 工具） |

→ **推荐第一种**（放 `src/`，vitest 风格，不改任何配置），且 `programToTrack` 只被渲染层用，不需要跨进程。

门禁：`pnpm test`（CI `test.yml:35-36`）、`pnpm typecheck`（tsc node + vue-tsc web）、`pnpm lint`、Prettier（双引号 / 分号 / 100 列 / 尾逗号；AGENTS.md:198-204）。中文注释 + JSDoc `@param`/`@returns`（AGENTS.md:146-157），禁止 `// ───` 分隔线注释。

---

## 9. 最小改动清单

### 新增文件

| # | 文件 | 职责 |
| --- | --- | --- |
| N1 | `electron/main/apis/netease/modules/dj_detail.ts` | 电台详情（元数据 + 节目数） |
| N2 | `electron/main/apis/netease/modules/dj_program.ts` | 电台节目列表（`limit`/`offset` 分页） |
| N3 | `electron/main/apis/netease/modules/dj_program_detail.ts` | 单集详情（拿 `mainSong`） |
| N4 | `electron/main/apis/netease/modules/dj_sublist.ts` | 我的订阅电台（分页） |
| N5 | `electron/main/apis/netease/modules/dj_sub.ts` | 订阅 / 取消订阅（`t` 或 sub/unsub） |
| N6 | `electron/main/apis/netease/modules/dj_hot.ts`（可选） | 热门电台，用于播客首页发现区 |
| N7 | `src/types/radio.ts` | `NeteaseDjRadio` / `NeteaseDjProgram` 原始响应类型（或并入 `src/types/netease.ts`） |
| N8 | `src/utils/format/radio.ts` | 纯映射：`toDjRadio`、`programToTrack`（产出 `extId` + `album.id`） |
| N9 | `src/apis/radio/netease.ts` | `fetchRadio` / `fetchRadioPrograms` / `subscribeRadio`（仿 `src/apis/album/netease.ts`） |
| N10 | `src/pages/Podcast.vue` | 播客首页：订阅电台 + 热门电台 `CoverList`；`defineOptions({name:"Podcast"})` |
| N11 | `src/utils/format/radio.spec.ts` | `programToTrack` / `toDjRadio` 单测（vitest；重点断言 `id`/`extId`/`album.id`） |

### 修改文件

| # | 文件 | 改什么 |
| --- | --- | --- |
| M1 | `electron/main/apis/netease/modules/index.ts` | `import` + `modules` 表加 6 个 `dj_*` key（`:11-107` / `:124-199`） |
| M2 | `electron/main/apis/netease/index.ts` | 把 `dj_sub`（及任何写接口）加进 `NON_CACHEABLE`（`:40-82`）——**漏了会 2 分钟内收藏状态不刷新** |
| M3 | `src/services/collection/netease.ts` | 加 `type === "radio"` 分支：拉元数据 + 全量节目 → `options.onUpdate(collection)`（现在 `:32-35` 直接返回 `null`） |
| M4 | `src/stores/user.ts` | 加 `radios = shallowRef<Playlist[]>([])`、`toggleRadioSubscribe`、`loadContent` 的 allSettled 里加 `fetchUserRadios()`（`:428-441`）、return 导出 |
| M5 | `src/apis/user/netease.ts` | 加 `fetchUserRadios()`（走 `dj_sublist` + `fetchAllPages`，`toDjRadio`） |
| M6 | `src/composables/collection/useCollectionSubscribe.ts` | `isSubscribed` / `available` / `toggle` 各加 `current.type === "radio"` 分支，删掉「待接入」注释 |
| M7 | `src/router/index.ts` | 加 `{ path: "podcast", name: "podcast", component: () => import("@/pages/Podcast.vue") }` |
| M8 | `src/components/layout/sidebarNav.ts` | `SIDEBAR_NAV_ENTRIES` 加 `{ key: "/podcast", labelKey: "nav.podcast", icon: IconLucideRadio, hideable: true }` |
| M9 | `src/types/settings.ts` | `DEFAULT_SIDEBAR_NAV_GROUPS` 的某个 `keys` 里加 `"/podcast"`（老存档由 `reconcileNavGroups` 自动补） |
| M10 | `src/layouts/MainLayout.vue` | 若要让播客首页保持缓存：`cachedViews`（`:34-48`）加 `"Podcast"` |
| M11 | `src/i18n/locales/zh-CN.json` **和** `en-US.json` | `nav.podcast` + `podcast.*`（详情页复用已有 `collection.radio`） |
| — | 可选 | 若加功能开关：`shared/defaults/settings.ts` + `shared/types/settings.ts` + `src/settings/categories/*.ts` + `SideBar.vue:186-187` 闸门 |
| — | 可选 | 若挂进「我的收藏」：`src/pages/Favorites.vue`（`FavTab` 联合类型 + `tabs` + `currentItems` + 跳转分支）+ `favorites.tabs.radio` |

### 明确**不需要改**的文件（已核对）

`src/apis/netease.ts`（Proxy 通吃）、`electron/main/ipc/apis.ts`、`electron/preload/index.ts`、`shared/types/apis.ts`、`shared/types/player.ts`（`radio` 已存在）、`src/types/collection.ts`（`radio` 已存在）、`src/pages/Collection.vue`（radio 分支/图标/i18n 已就绪）、`src/utils/format/shareUrl.ts`、`shared/utils/neteaseScrobble.ts`、`src/components/player/FullPlayer/PlayerData.vue`、`src/utils/navigate.ts`、`vitest.config.ts`。

---

## 10. 风险与未知

1. **`/dj/*` 接口路径与加密模式未经验证（最高风险）。** 仓库内**没有任何** `/dj/` 端点的代码或文档证据（我 grep 过 `electron/ src/ shared/ windows/ docs/`，只有 scrobble/shareUrl 的 `djradio` 字样）。`NeteaseCloudMusicApi` 社区惯例的候选路径为：电台详情 `/api/djradio/v2/get`、节目列表 `/api/dj/program/byradio`、单集详情 `/api/dj/program/detail`、订阅列表 `/api/djradio/get/subed`、订阅/取消 `/api/djradio/sub` 与 `/api/djradio/unsub`、热门 `/api/djradio/hot` —— **以上全部属于待实测确认的假设，不是本仓库或官方文档的事实**。实现前请先用 `window.api.apis.call("netease", name, params)` 或直接 `callNetease` 在真机验证路径、`weapi` vs `eapi`、以及返回体字段名（`djRadios` / `programs` / `data` 等）。
2. **`song_url` 对节目 `mainSong.id` 是否可用未验证。** 本仓库现有解析链只认 `track.id` 且固定走 `song_url` 的 **xeapi**（`src/apis/song/netease.ts:73-77` + `modules/song_url.ts:29`）。若服务端对主歌曲 id 返回 `url: null`，就得新增 dj 专用取址模块并改 `src/services/audioSource.ts` 的解析分发——**这会明显扩大改动面**。第 5.3 节的 `Track.id = mainSong.id` 约定是从 `shared/utils/neteaseScrobble.ts` 反推的，属于强假设。
3. **匿名态（MUSIC_A）能否访问 dj 只读接口未知。** `callNetease` 会自动注册匿名态（`index.ts:220-222`），但会被风控拒绝或返回空列表的可能性无法静态排除。订阅类接口必然要求登录（可照 `useFavorite.ts:81-83` 的 `user.isLoggedIn` 前置提示模式）。
4. **节目评论不支持。** `comment_music` 把资源前缀硬编码成 `R_SO_4_`（`electron/main/apis/netease/modules/comment_music.ts:21`，常量 `NETEASE_RESOURCE_TYPE` 在 `electron/main/services/comments/index.ts:24`），且 `findNeteaseId` 对 netease 直接用 song id。播客评论需要 `R_VI_62_` 之类的新前缀 + 按 `track.extId` 分支——**本轮范围内建议不做**，做的话要单独评估。
5. **节目歌词未知。** `lyric` / `lyric_new`（`modules/lyric_new.ts:10-23`）只接受 song id；播客是否/如何返回歌词（含时间轴的 shownotes）本仓库无证据。若不支持，`media.activeLyric` 为空属可接受降级。
6. **`dj_info` 的字段名差异。** 电台详情与订阅列表的嵌套结构（是否包一层 `data`、封面字段叫 `picUrl` 还是 `interPicUrl`）只能实测确认；`toDjRadio` 必须写得对两种命名都容忍（仿 `toAlbum` 的 `raw.picUrl` 兜底风格，`src/utils/format/netease.ts:40-47`）。
7. **`CollectionType` 复用「radio」的语义边界。** 现有 `radio` 同时表示「网易云电台」和 `PlaybackOriginType` 里泛指 radio，`src/utils/format/shareUrl.ts:43-49` 还给 qqmusic/kugou 也填了 radio 链接（实际不可用）。若未来要接 QQ 音乐/酷狗的播客，需要重新审视这个共用枚举，本轮不必处理。
8. **`Playlist` 复用 vs 新增 `DjRadio` 类型**：复用 `Playlist` 改动最小，但 `trackCount` 在电台语境下应填「节目数」、`owner` 填「主播昵称」——语义会轻微漂移。若在意语义纯度可新增 `DjRadio` 并让 `Collection` 的 `creator` 承载主播名。
9. **`Collection.vue` 的「播放全部」无分页。** 现有 loader 契约是一次性 `onUpdate(完整 Collection)`（`src/services/collection/types.ts:3-7`）；大电台（上千集）全量拉取会一次性展开目录。若节目数很大，需要评估是否引入 `hasMore`/`loadingMore`（`SongList` 已支持这两个 prop，但 `Collection.vue` 没接）。此点同时影响 `setQueue` 的内存占用（AGENTS.md 的 Memory Discipline）。
10. **`extId` 语义冲突。** `Track.extId` 在 qqmusic 表示 songmid、kugou 表示 `albumAudioId`（`shared/types/player.ts:86-88`）；netease 侧此前从未赋值。给它赋予「节目 id」是本仓库首例，需确认不会与 `src/services/lyric/request.ts:17`、`src/components/modals/TagEditorDialog.vue:147`、`electron/main/ipc/lyrics.ts:104` 等按 `extId` 取平台的逻辑打架——目前已核对：这些点都对 netease 走 `track.id`，**未见冲突**，但新增功能时不要再往 `extId` 塞别的东西。

---

## 11. 证据文件（实际读过）

**主进程网易云 API**
`electron/main/apis/netease/index.ts`、`core/types.ts`、`core/option.ts`、`core/request.ts`、`core/config.ts`、`core/cache.ts`、`core/device.ts`、`core/checktoken.ts`、`modules/index.ts`、`modules/playlist_detail.ts`、`modules/song_detail.ts`、`modules/user_playlist.ts`、`modules/artist_songs.ts`、`modules/album.ts`、`modules/album_sub.ts`、`modules/artist_sub.ts`、`modules/artist_sublist.ts`、`modules/user_subcount.ts`、`modules/personal_fm.ts`、`modules/register_anonimous.ts`、`modules/playlist_subscribe.ts`、`modules/cloudsearch.ts`、`modules/song_url.ts`、`modules/lyric_new.ts`、`modules/comment_music.ts`、`modules/like_v1.ts`（grep）、`core/playLog.ts` + `.test.ts`（grep）、`modules/scrobble.ts`（grep）、`modules/search.ts`（grep）

**IPC / preload / 共享类型**
`electron/main/ipc/apis.ts`、`shared/types/apis.ts`、`shared/types/player.ts`、`shared/types/platform.ts`、`shared/types/settings.ts`（grep）、`shared/utils/netease.ts`、`shared/utils/neteaseScrobble.ts`、`shared/defaults/settings.ts`

**渲染层 API / 服务**
`src/apis/netease.ts`、`src/apis/album/netease.ts`、`src/apis/playlist/netease.ts`、`src/apis/song/netease.ts`、`src/apis/user/netease.ts`、`src/apis/recommend/netease.ts`、`src/apis/search/netease.ts`、`src/apis/search/index.ts`、`src/services/collection/index.ts`、`types.ts`、`netease.ts`、`src/services/audioSource.ts`、`src/utils/format/netease.ts` + `.spec.ts`、`src/utils/format/coverItem.ts`、`src/utils/format/shareUrl.ts`、`src/utils/navigate.ts`、`src/types/collection.ts`、`src/types/artist.ts`、`src/types/netease.ts`

**播放 / 状态**
`src/core/player/index.ts`（分段读）、`src/stores/queue.ts`（grep）、`src/stores/status.ts`（grep）、`src/stores/media.ts`（grep）、`src/stores/user.ts`、`src/components/player/FullPlayer/PlayerData.vue`、`electron/main/services/neteaseScrobble.ts`、`electron/main/services/neteaseScrobbleMeta.test.ts`、`electron/main/services/comments/index.ts`

**页面 / 路由 / 导航 / 设置 / i18n**
`src/router/index.ts`、`src/layouts/MainLayout.vue`、`src/components/layout/SideBar.vue`、`src/components/layout/sidebarNav.ts`、`src/types/settings.ts`、`src/stores/settings.ts`、`src/settings/schema.ts`、`src/settings/categories/services.ts`、`src/types/settings-schema.ts`、`src/pages/Collection.vue`、`src/pages/Favorites.vue`、`src/pages/Daily.vue`、`src/pages/Search.vue`（grep）、`src/pages/Home.vue`（grep）、`src/components/list/SongList.vue`、`CoverList.vue`、`CoverCard.vue`、`src/composables/collection/useCollectionSubscribe.ts`、`src/composables/collection/usePlaylistManage.ts`、`src/composables/useFavorite.ts`、`src/composables/useFmMode.ts`、`src/i18n/index.ts`、`src/i18n/locales/zh-CN.json`、`src/i18n/locales/en-US.json`

**工程配置**
`AGENTS.md`、`CLAUDE.md`、`package.json`、`vitest.config.ts`、`.github/workflows/test.yml`、`docs/`（目录列举）

---

## 12. 附：调研期间观测到的并行实现现状（重要）

调研末尾发现**有并行 agent 正在同一个工作区实现本子系统**。截至 2026-10-04 15:53，主进程第一层已落地，本规格第 9 节的部分条目已不再是 todo：

**已存在（未跟踪的新文件，13 个）**
`electron/main/apis/netease/modules/` 下的 `dj_detail.ts`、`dj_program.ts`、`dj_program_detail.ts`、`dj_sublist.ts`、`dj_sub.ts`、`dj_hot.ts`、`dj_catelist.ts`、`dj_category_recommend.ts`、`dj_personalize_recommend.ts`、`dj_radio_hot.ts`、`dj_recommend.ts`、`dj_recommend_type.ts`、`dj_toplist.ts`

**已修改**：`electron/main/apis/netease/modules/index.ts`（+29 行：`:110-122` 加 import 分组「电台（播客）」，`:215+` 加 `modules` key）→ **第 1.3 节的原始行号（`11-107` / `124-199`）已因这次改动漂移，以当前文件为准。**

**已实测到的真实契约（对第 10.1 节不确定性的部分收敛，仍非真机验证）**

| 模块 | 路径 | 参数 | crypto |
| --- | --- | --- | --- |
| `dj_detail` | `/api/djradio/v2/get` | `id: query.rid`（**电台 id 参数名叫 `rid`**） | weapi |
| `dj_program` | `/api/dj/program/byradio` | `radioId: query.rid`、`limit ?? 30`、`offset ?? 0`、`asc` | weapi |
| `dj_program_detail` | `/api/dj/program/detail` | `id: query.id`（**节目 id 用 `id`，与 `rid` 不同**） | weapi |
| `dj_sublist` | `/api/djradio/get/subed` | `limit ?? 30`、`offset ?? 0` | weapi |
| `dj_sub` | `/api/djradio/sub` / `/unsub` | `id: query.rid`、`t`（**1 订阅 / 0 取消**） | weapi |
| `dj_hot` | `/api/djradio/hot/v1` | `limit`、`offset` | weapi |

**仍需处理 / 值得复核的三点**

1. **M2 未做，是当前最实际的缺陷**：`electron/main/apis/netease/index.ts` 的 `NON_CACHEABLE`（`:40-82`）**没有加入任何 `dj_*`**。`dj_sub` 是写操作，会被 2 分钟响应缓存挡住（`core/cache.ts:12-15`），表现为「收藏后立刻回看仍是旧状态」。必须补 `"dj_sub"`。
2. **`dj_sub` 的 `t` 约定与仓库既有惯例不一致**：`dj_sub.ts:15` 用 `t === 0 → unsub`，而仓库其它三个 `_sub` 模块统一是 `t === 2 → 取消`（`playlist_subscribe.ts:15`、`album_sub.ts:15`、`artist_sub.ts:15`）。若网易云该接口本身用 1/0 就得保留（并建议在文件头 JSDoc 写明与其它 `_sub` 的差异），否则建议对齐为 1/2，以免后续渲染层接线时按习惯传错值。**这是一个需要决策的点，不能靠猜。**
3. **第 2~9 节的渲染层（`src/`）改动目前全部未开始**：`src/apis/radio/`、`programToTrack`、`loadNeteaseCollection` 的 radio 分支、`useCollectionSubscribe` 的 radio 分支、`Podcast.vue`、路由/侧边栏/i18n 均无改动（`git status` 只显示主进程与既有的 MCP/nowPlaying 相关改动）。第 5.3 节「`Track.id = mainSong.id` + `extId = program.id` + `album.id = radio.id`」的映射约定仍是后续实现的关键接口，必须在渲染层落地时严格对齐，否则打卡（`shared/utils/neteaseScrobble.ts`）会静默降级为 `resourceType: "song"`。
