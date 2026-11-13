# 定时任务模板：每日精选把关

> 用法：创建 cron 时把全文 `{{占位符}}` 换成新站的真实值（对照 BOOTSTRAP.md
> 第 0 节的表），正文作为任务 body。schedule：daily，{{DAILY_TIME}} 之后
> 约 1.5 小时（例如日报 06:00 则把关 07:42），归属新站的 goal。

---

{{SITE_NAME}} 每日精选把关（{{TOPIC}}，循环持续跑、没用户命令不许停；绝不要自己停掉或删除这个任务）。

站点：{{SITE_URL}}；仓库 {{REPO}}（main 分支）；本地工作目录 {{WORK_DIR}}；另有个持久 git 检出 {{GIT_DIR}}（与仓库 main 同步，专门用来推）。更新主力是每半小时跑一次的 {{SLUG}}-half-hourly-update 任务（拉源、翻译、上传全包，北京时间 {{DAILY_TIME}} 那轮出日报）；GitHub Actions 已停用。你的工作是每天一次精选把关，不是 24 小时在线。翻译不再是你的活——新条目翻译由半小时任务负责；你只管精选质量、权重、信源。

每轮做：
1. 看今天的精选质量：读线上 data/hot.json（今日精选 10 条、热点 20 条）与 data/daily.json（当日日报），以及仓库里的 config.json（打分权重、精选门槛）与 sources.json（信源列表）。判断精选是不是真对{{AUDIENCE}}有用（分类：{{CATEGORIES}}）；跑题内容、促销、纯资讯进了精选就是问题。
2. 查信源健康：有没有源连续多天 0 条、403/超时、重复。已知：{{KNOWN_SOURCE_ISSUES}}。
3. 需要调权重、改门槛、修信源时：在 {{WORK_DIR}} 里改 config.json / sources.json，本地跑 python3 tools/generate.py --daily 验证生成正常，再把改动推到仓库。**推送走 git + key（不再弹确认卡）**：先 `cd {{GIT_DIR}} && git pull --ff-only` 同步到最新头（pull 失败或检出坏了就重 clone），再用 rsync 把工作目录的改动同步进检出（`rsync -a --delete --exclude='.git/' --exclude='.github/' --exclude='__pycache__/' --exclude='*.pyc' --exclude='data/store.json' {{WORK_DIR}}/ {{GIT_DIR}}/`），然后 `git add -A`、`git commit -m "{{SITE_NAME}} 把关：<改了什么>"`、`git push origin main`（走 ~/.git-credentials 里的 key 自动认证）。推送铁律：绝对不要把 .github/workflows/daily.yml 放进推送——工作流文件本身只能走浏览器改，不要碰。推完核对新头 hash 与本地一致。推送失败就记下来下一轮再推，不要强行重试。
4. 只在有事时向用户汇报（主聊天）：改了权重/信源、某源死了、精选质量明显变差、或需要她拍板。什么都没变就保持沉默，不要发“一切正常”的消息。不要改 MEMORY.md；观察记到 ~/memory/YYYY-MM-DD.md。
