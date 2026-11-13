# BOOTSTRAP.md — Agent 开新站 Playbook

> 读给 agent 的：用户一句话让你用这个模板开新站时，按本文件从头做到尾，
> 不要跳步。每步做完先自查再往下走。全文的 `{{占位符}}` 在动手前先定好。

## 0. 动手前先定好的事

用户一句话里通常只有站名和主题，缺的你自己定（定完在汇报里说明，不用逐项问）：

| 占位符 | 含义 | 例子 |
| --- | --- | --- |
| `{{SITE_NAME}}` | 站名 | 电商HOT |
| `{{SLUG}}` | 站点 slug（小写英文/拼音） | ecommerce-hot |
| `{{REPO}}` | GitHub 仓库 `owner/repo` | Staroltest/ecommerce-hot |
| `{{AUDIENCE}}` | 受众（一句话） | 电商从业者 |
| `{{TOPIC}}` | 主题范围（收什么、不收什么） | 电商平台、运营、营销、行业动态；不收纯促销信息 |
| `{{WORK_DIR}}` | 本机工作目录 | `~/workspace/ecommerce-hot` |
| `{{GIT_DIR}}` | 持久 git 检出（专门用来推） | `~/workspace/ecommerce-hot-git` |
| `{{CF_PROJECT}}` | Cloudflare Pages 项目名 | ecommerce-hot |
| `{{DAILY_TIME}}` | 日报出刊时间（北京时间） | 06:00 |
| `{{LAUNCH_DATE}}` | 上线日期 YYYY-MM-DD | 2026-11-14 |

命名规范：cron id 用 `{{SLUG}}-half-hourly-update` 与 `{{SLUG}}-daily-curation`；
goal（跟踪项）slug 用 `{{SLUG}}` 相关命名；MCP 服务名取 `{{SLUG}}`。

## 1. 拷贝模板

```bash
cp -r ~/workspace/hot-site-template {{WORK_DIR}}
cd {{WORK_DIR}} && rm -rf tools/__pycache__ data/store.json data/zh_draft.json
```

只留源文件：`tools/generate.py`、`config.json`、`sources.json`、`_worker.js`、
`_routes.json`、`favicon.svg`、`LICENSE`、`.nojekyll`、`.gitignore`、
`README.md`、`BOOTSTRAP.md`、`docs/`、`data/changelog.json`。
不要从旧站拷贝任何生成物（`index.html`、`items/`、`data/days/`、`feed.xml` 等）
和任何数据文件（`store.json`、`zh_draft.json`）。

## 2. 填 config.json

`config.json` 是唯一配置入口，生成器其余部分不许再写死站名。逐项填：

- `site.name` / `site.title` / `site.subtitle` / `site.tagline`：站名与一句话。
- `site.url`：`https://{{owner}}.github.io/{{repo}}`（GitHub Pages 地址）。
- `site.repo`：`https://github.com/{{REPO}}`。
- `site.slug`：`{{SLUG}}`（localStorage 键前缀，各站隔离）。
- `site.audience`：`{{AUDIENCE}}`（用于关于页、主题页、LLM 提示词）。
- `site.description`：一句话描述，含分类名。
- `site.crawler_name`：`{{SLUG}}Bot/1.0` 形。
- `site.launch_date`：`{{LAUNCH_DATE}}`（期号起算日）。
- `site.edition_time_cst`：`{{DAILY_TIME}}`。
- `site.mcp_url`：先留空，Cloudflare 部署成功后再填
  `https://{{CF_PROJECT}}.pages.dev/mcp`，填完重新生成一次。
- `site.footer_note`：页脚第二段（署名/出处链，纯文本）。
- `site.tips`：赞赏码列表，默认为空；用户给了码再加
  `[{"label": "USDT · TRC20", "image": "assets/tip-xxx.png", "address": "..."}]`，
  图片放 `assets/`。
- `site.about_blocks`：关于页各段 `[{"h": "标题", "paras": ["段落", ...]}]`，
  至少含定位、怎么做、制作人；段落里可用 `<code>`、`<a>`。
- `categories`：按 `{{TOPIC}}` 定 4–8 个分类，每类 `key`（英文）、`label`（中文）、
  `keywords`（中英关键词 15–25 个，分类器只靠它）。
- `scoring`：默认打分参数可直接用；`dev_keywords` / `noise_keywords` 按主题改词表，
  其余数值（门槛、衰减、tier 加成）先不动，等每日把关根据实测再调。

填完跑 `python3 -m json.tool config.json` 确认合法。

## 3. 找信源，逐个实测

目标 20–30 个 RSS/Atom 信源，覆盖 `{{TOPIC}}` 的官方博客、媒体、社区、博主。
每个源必须实测：HTTP 200 且能解析出条目（标题+链接+时间），否则不收。
常见死法记下来（403、机器人墙、无 RSS、停更、重复），不要反复试同一个死源。

- `tier`：T1 官方一手（博客/公告），T2 媒体/社区，T3 综合媒体（降权，进精选难）。
- `category_hint` 须是 `config.json` 里 `categories` 的 `key`。
- 写进 `sources.json`（保留 `comment` 字段，写清实测日期与淘汰原因）。
- 优先收中文源；英文源靠第 5 步的标题翻译 + 一句话简介解决。

## 4. 改 _worker.js 三个常量

文件头部的 `SITE_ORIGIN`（新站 GitHub Pages 地址）、`SERVER_NAME`（取 `{{SLUG}}`）。
工具描述里的“每天北京时间 06:00”若日报时间不同，一并改。
`_routes.json` 不用动。

## 5. 首次生成 + 中文 + 自查

```bash
cd {{WORK_DIR}} && python3 tools/generate.py
```

- 第一轮 `data/store.json` 从空开始，只有当天条目，正常；历史随时间累积。
- 找出没有中文标题的条目（链接不在 `data/zh_draft.json` 里）：写 `zh_title`
  （专有名词保留英文）与 `zh_oneliner`（一句自己表述的简介，给 `{{AUDIENCE}}` 看，
  不照搬源站摘要措辞，不用省略号结尾）。**绝不写 `zh_summary` / `zh_summary_full`**。
- 写完重新生成一次。自查：首页首屏时间线 + 精选标题全中文、每条只有标题 +
  一句话简介、页头时间是当前时间、页面上无源站摘要文字、页脚品牌与链接正确。
- 再跑一次 `python3 tools/generate.py --daily`，确认日报能出（`data/daily.json`、
  `daily.html`），期号为 1。

## 6. 建 GitHub 仓库并推送

- 建公开仓库 `{{REPO}}`（main 分支）。**不要**在仓库里启用 GitHub Actions：
  更新只走定时任务，两边写会打架；也**不要**推送任何 `.github/workflows/*` 文件
  （App 没有 workflows 权限，推送会 403）。
- 推送走 git + key：`{{GIT_DIR}}` 持久检出 → `git pull --ff-only` →
  rsync 工作目录（排除 `.git/`、`.github/`、`__pycache__/`、`*.pyc`、
  `data/store.json`）→ `git add -A` → commit → `git push`。
  本站文件全是 LF，`add` 不会改换行。推完核对新头 hash 与关键文件 blob SHA。
- ⚠️ **PAT 作用域**：细粒度 PAT 是按仓库授权的，新仓库不在旧 key 的作用域里
  时推送会 403。处理办法（二选一）：用户在 GitHub 设置里把新仓库加进 key 的
  授权仓库；或改用 GitHub App 快照推送。先试推，403 再按此处理，不要反复重试。
- 开 GitHub Pages：仓库 Settings → Pages → Deploy from branch → main / root。
  等几分钟验证首页 200。仓库 About（简介 + 网站链接 + 话题）走浏览器用用户账号改
  （PAT 没有 Administration 权限，调 API 会 403）。

## 7. Cloudflare 镜像部署

用现成的 `custom.cloudflare` 连接器助手（`cf.py`，deploy 命令直接上传预构建文件，
不消耗每月 500 次 Git 集成构建额度）：

```bash
python3 ~/workspace/custom-connectors/custom.cloudflare/bin/cf.py deploy \
  --project {{CF_PROJECT}} --dir {{WORK_DIR}}
```

- 项目不存在时先 `create-project`（生产分支 main）。`_worker.js` 会随部署自动
  作为 worker 附加上（助手已支持），`_routes.json` 同理。
- 部署成功后抽查：`https://{{CF_PROJECT}}.pages.dev/` 200 且页头时间当前；
  填好 `site.mcp_url` 重新生成并重新部署一次，让关于页与页脚出现 MCP 入口。
- 然后实测 MCP：POST `/mcp` 做 initialize、tools/list、三次 tools/call
  （get_hot / get_daily / search_items）全部成功，且首页与 `/data/hot.json` 仍 200。

## 8. 建两个定时任务

用 `docs/cron-half-hourly-update.md` 与 `docs/cron-daily-curation.md` 里的模板，
把 `{{占位符}}` 全部换成新站的真实值后创建：

- 半小时任务：interval 每 30 分钟，`{{DAILY_TIME}}` 那轮加 `--daily` 出日报；
  含第 6 步 Cloudflare 同步；失败处理与汇报规则见模板正文。
- 每日把关：daily，`{{DAILY_TIME}}` 之后约 1.5 小时（例如 07:42），只管精选质量、
  权重、信源，不管翻译。
- 两个任务都归属新站的 goal；汇报规则：**没事别说话**，只有问题或需拍板才汇报。

## 9. 验收清单（全部通过才算完）

- [ ] GitHub Pages 首页 200，内容最新，详情页能打开（无 404）。
- [ ] Cloudflare 镜像首页 200，页头时间当前。
- [ ] `feed.xml`、`sitemap.xml`、`robots.txt` 均 200。
- [ ] MCP：initialize / tools/list / 三个工具调用均成功；GET `/mcp` 返回 405。
- [ ] 版权自查：公开文件里只有标题 + 一句话简介 + 链接，0 源站摘要残留。
- [ ] 两个定时任务已建，下一轮能正常跑（看一次运行记录）。
- [ ] 汇报给用户：站名、两个站的地址、MCP 端点、信源数量、分类、待她拍板的事
      （如 PAT 作用域、About/话题是否已设）。

## 铁律（开新站与日常运行通用）

1. **版权**：全站只放原标题 + 一句自己表述的简介 + 跳转链接；源站正文、摘要、
   完整摘要及翻译件不展示、不打包进任何公开数据文件。日报导读是自写概括，不动。
2. **`zh_draft.json` 永不直接覆盖**：按链接取头上与本地的并集，冲突保留本地。
   直接覆盖曾丢过 228 条翻译。
3. **绝不推送 `.github/workflows/*`**，绝不启用 Actions。
4. **推送/部署失败不强行重试**：记下来下一轮补推；连续两轮失败才汇报。
5. **没事别说话**：例行运行成功不汇报。
6. **全程不用 API key** 做翻译与简介；LLM 打分是可选项，缺 key 自动跳过。
7. 详情见 [docs/pipeline-notes.md](docs/pipeline-notes.md)。
