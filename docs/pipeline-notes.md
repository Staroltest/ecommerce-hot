# 流水线笔记：踩过的坑与铁律

IndieHOT（第一个站，2026-11-09 上线）跑下来沉淀的经验。开新站与日常运行
都要遵守；新发现的坑往这里追加。

## 版权规则（铁律）

- 全站只放原标题 + 一句自己表述的简介 + 原文跳转链接。源站正文、摘要、
  完整摘要及翻译件不展示、不打包进任何公开数据文件（包括 `data/days/*.json`、
  `data/hot.json`、日报/周报/月报 JSON、`feed.xml`）。
- 标题照常显示原文标题（中文标题沿用 `zh_title`）；简介一律自己写，进新字段
  `zh_oneliner`，与 `zh_title` 同级、按链接做键。
- 生成器内部仍可用标题+摘要做分类与打分（本地行为，不发布）；`parse_feed`
  提取的摘要只进本地 `store.json`。
- 日报导读是自写概括，不受此限。
- 自查探针：取旧摘要中间 40 字切片（避开标题/链接子串），扫全部公开文件，
  0 命中才算干净。

## zh_draft.json 合并规则（铁律）

- 每轮同步时，`zh_draft.json` 按链接取头上与本地的并集，冲突保留本地。
  **绝不直接覆盖**。2026-11-10 晚直接覆盖丢过 228 条翻译。
- 写回格式：`indent=1`，`ensure_ascii=False`。

## 推送铁律

- 绝不推送 `.github/workflows/*`：Muse GitHub App 没有 workflows 权限，
  带工作流文件的推送会 403。Actions 工作流只在网页上管理，且保持停用。
- 细粒度 PAT 没有 Administration 权限：改仓库简介/网站/话题、读 Traffic API
  都会 403，这些事走浏览器用用户账号改。
- 细粒度 PAT 按仓库授权：新仓库需先加进 key 的授权范围，否则推送 403。
- 本站文件全是 LF，`git add -A` 安全（与 CRLF 项目不同，不要混用那套流程）。
- 推完必核：新头 hash + 关键文件 blob SHA 与本地一致。

## 数据结构

- `data/store.json`：30 天库，只存本机，**不推送、不从头上同步**，
  `.gitignore` 里有它。丢了它等于丢历史，换机器时要先备份。
- `data/days/*.json` + `index.json`：给浏览器用的按天分块，每轮现算。
- `data/items.json` 已废弃，不要再生成、同步或引用它。
- `data/changelog.json`、`data/hot.json`、日报/周报/月报 JSON 从头上同步回本地。
- `data/daily/*.json` 等存档只增不改。

## 生成器约定

- 纯 Python 标准库，零依赖；CSS 与 JS 以字符串形式存在 `generate.py` 里，
  生成时写出 `assets/site.css` / `assets/site.js`。改样式只改 `generate.py`。
- 品牌、分类、文案、链接一律走 `config.json`，代码里不许写死站名。
  （例外：注释与 docstring 里的 AIHOT 出处链，那是设计 lineage。）
- 分类只靠 `config.json` 的关键词；分类器没命中时看 `sources.json` 的
  `category_hint`，都没有就落默认分类。

## Cloudflare 直传与 MCP

- 部署走 REST API 直接上传预构建文件（`cf.py deploy`），不接 Git，
  不消耗每月 500 次构建额度；静态访问与流量不限量。
- `_worker.js`（单文件、无 import）随部署以表单字段上传，跑 Pages Advanced Mode；
  `_routes.json` 只把 `/mcp` 交给它。`functions/` 目录走不了这条路（需 wrangler 编译）。
- MCP 端点读 GitHub Pages 源站的公开 JSON，无状态、无需密钥；
  调用额度走 Workers 免费额度（每天 10 万次）。
- Pages 干净 URL：`/all.html` 会 308 到 `/all`，正常现象。
- canonical 永远指回 GitHub Pages 主站，避免双站 SEO 惩罚。
- 部署与 git 推送互相独立，失败分开算；连续两轮部署失败才汇报。

## 失败与汇报

- 推送/部署失败：记下来，下一轮补推同样内容，不强行重试，不报平安。
- 只有连续两轮推不上去、信源死了、翻译失败、需要拍板时才向主聊汇报。
- 观察记 `~/memory/YYYY-MM-DD.md`，绝不改 `MEMORY.md`。

## 权重与选题

- 三档信源：T1 官方一手 +10，T2 平权，T3 综合媒体 −15。
  综合媒体的玩家向/促销新闻靠打分压出精选与热点，压不住就降档。
- 精选门槛默认 65 分、48 小时窗口；热点榜 20 条、7 天窗口、每日衰减。
- 权重调整先本地 `--daily` 验证，再推送；调完看一轮精选是否干净。

## 其它

- 搜索引擎索引靠时间：新站上线几天内搜不到是正常的；SEO 基础
  （robots.txt、sitemap.xml、标题/meta/OG、canonical）生成器已带。
- 移动端视觉检查在云端浏览器做不了（窗口尺寸固定），需用户真机看。
- 统计：GitHub Pages 没有访问统计；Cloudflare Web Analytics 免费，
  在后台 Workers & Pages → 项目 → Metrics 里开，下次部署自动注入。
  开启需登录 Cloudflare 后台（GitHub SSO 账号可能要过 2FA）。
