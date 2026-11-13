# 定时任务模板：每半小时更新循环

> 用法：创建 cron 时把全文 `{{占位符}}` 换成新站的真实值（对照 BOOTSTRAP.md
> 第 0 节的表），正文作为任务 body。schedule：interval 每 30 分钟，
> timeout 3600 秒，归属新站的 goal。

---

{{SITE_NAME}} 每半小时更新循环（替代 GitHub Actions 的机器人更新；Actions 工作流已停用，避免两个写手打架）。仓库：{{REPO}}（公开，main 分支）。本地工作目录：{{WORK_DIR}}；另有个持久 git 检出 {{GIT_DIR}}（与仓库 main 同步，专门用来推）。循环持续跑，直到用户下令停止，绝不自己停。

本站是多页结构：首页/热点/日报/周报/月报/收藏/我的/关于/条款/隐私/更新日志/主题页 + 每条内容一个详情页 items/<id>.html + feed.xml/sitemap.xml/robots.txt。推送必须覆盖整个站，否则首页链到的详情页会 404。

数据结构：30 天库只存在本机 data/store.json（本地专用，不推送、不从头上同步）；给浏览器用的数据按天分块在 data/days/YYYY-MM-DD.json + data/days/index.json（每轮现算）；data/items.json 已废弃，主分支上不再有这个文件，不要再从头上拉它。首页首屏只渲染前 20 条时间线（其余由 JS 分页从分块里取），所以自查时 h3 是 20 条时间线 + 10 条精选，不是 110 条。

版权规则（全站铁律）：只放标题 + 一句自己表述的简介 + 跳转链接；不展示、不打包源站的正文、摘要、完整摘要原文（翻译件也不再展示）。data/days/*.json、data/hot.json、data/daily.json、data/weekly.json、data/monthly.json、feed.xml 等一切公开数据文件里也只放标题 + 一句话简介。旧条目的一句话简介由主代理批量补写，本轮只负责新到的条目。

每轮按顺序做：

1. 先同步：进 {{GIT_DIR}} 跑 `git pull --ff-only` 同步到最新头（如果 pull 失败或检出脏了/坏了，就删掉整个检出目录重 clone 一份再继续）。再把检出里的 data/hot.json、data/daily.json、data/weekly.json、data/monthly.json、data/changelog.json 拷回 {{WORK_DIR}}/data/ 覆盖本地同名文件（本地数据可能落后）。**data/zh_draft.json 不许直接覆盖**：按链接做键取头上和本地的并集（同一链接两边都有时保留本地的——本地可能有并行翻译刚写的新条目，直接覆盖会丢数据，2026-11-10 晚 228 条翻译就是这么丢的），合并后写回本地（indent=1，ensure_ascii=False）。tools/generate.py、config.json、sources.json 以本地为准，除非头上的提交信息表明它们在网页上改过，那也一并从检出拷回。data/store.json 是本机增量库，不从头上同步、不推送；data/days/ 每轮现算，不用同步；存档数据 data/daily/*.json、data/weekly/*.json、data/monthly/*.json 只增不改，本地留着即可。
2. 拉源：跑 `python3 tools/generate.py`（如果本轮是北京时间 {{DAILY_TIME}} 那一轮，加 `--daily` 参数，出当日日报；本轮时间看你收到的时间戳）。单个信源失败可以容忍（个别源常年 403/502 是已知现象），全部信源都失败就停下来并向主聊汇报。
3. 标题 + 一句话简介：找出本轮新到、还没有中文标题的条目（没有 zh_title 且链接不在 data/zh_draft.json 里），把标题翻成中文，写进 data/zh_draft.json（按链接做键，indent=1，ensure_ascii=False；专有名词和产品名保留英文）。再根据源站摘要（data/store.json 里的 summary，必要时参考 summary_full）用自己的话写一句中文简介，写进同一条目的 zh_oneliner（与 zh_title 同级，按链接做键）：一句话、完整、给{{AUDIENCE}}看、不照搬源站摘要的措辞、不复制原文句子、不用省略号结尾。通常一轮只有几条新到的。**不再翻译摘要和完整摘要**：不要再写 zh_summary / zh_summary_full；旧条目的这两个字段由主代理统一清理，本轮不要碰。写完重新生成一次。
4. 自查：生成的 index.html 里时间线（首屏 20 条）+精选（10 条）：标题应有中文翻译（zh_title；标题里夹着专有名词不算英文标题）；每条只显示标题 + 一句简介，不出现源站摘要或完整摘要的文字；页头更新时间是当前时间。发现没有一句话简介的新条目就补写再生成；发现页面上出现源站摘要文字，停下来向主聊汇报，不要推送。
5. 只在有实质变化时才推：新条目到了、翻译加了、代码或配置改了，才推送；只改了时间戳、内容一字未动，就跳过推送、保持安静。判断实质变化的代理指标：头上的 data/hot.json 或 index.html 与本地生成的不一致，或 tools/generate.py/config.json 改了——任一成立就推全站。**推送走 git + key（不再弹确认卡）**：用 rsync 把 {{WORK_DIR}} 下生成的全站文件同步进 {{GIT_DIR}}，命令：`rsync -a --delete --exclude='.git/' --exclude='.github/' --exclude='__pycache__/' --exclude='*.pyc' --exclude='data/store.json' {{WORK_DIR}}/ {{GIT_DIR}}/`。绝对不要带 .github/workflows/daily.yml（只在网页上管）。然后进检出目录 `git add -A`（本站文件全是 LF，add 不会改换行）、`git commit -m "{{SITE_NAME}} YYYY-MM-DD HH:MM 更新"`、`git push origin main`（走 ~/.git-credentials 里的 key 自动认证，不用点卡）。推完核对：新头 hash 与本地一致，再抽几个关键文件（index.html、data/hot.json、data/zh_draft.json）核对 blob SHA 与本地一致。一批失败（网络、冲突、被拒）就停下，剩下的留给下一轮补推，不要强行重试。
6. Cloudflare 镜像同步：站已在 Cloudflare Pages 上线（{{CF_URL}}，项目名 {{CF_PROJECT}}，GitHub Pages 仍是主站）。**只在第 5 步判断有实质变化时才部署**（只改了时间戳就跳过）。部署命令：`python3 ~/workspace/custom-connectors/custom.cloudflare/bin/cf.py deploy --project {{CF_PROJECT}} --dir {{WORK_DIR}}`（直接上传预构建文件，不消耗 Git 集成构建额度；只传 Cloudflare 还没有的文件；`_worker.js` 与 `_routes.json` 会随部署自动附上）。部署与第 5 步的 git 推送互相独立：推送失败不影响部署，部署失败也不影响推送。部署成功后抽查 {{CF_URL}}/ 返回 200 且页头更新时间是当前时间。部署失败记到 ~/memory/YYYY-MM-DD.md，下一轮再试，不要强行重试；连续两轮部署失败才向主聊汇报（与推送失败分开算）。
7. 失败不丢东西：推送失败、网络断了、冲突了，都记下来（~/memory/YYYY-MM-DD.md），下一轮重新推同样的内容。不用向主聊报每一次失败，只有连续两轮推不上去才汇报。

汇报：没事就别说话（不要每轮都在主聊报平安）。只有出问题或需要用户拍板才向主聊汇报（比如信源死了、翻译失败、连续两轮推不上去）。观察记到 ~/memory/YYYY-MM-DD.md，绝不要改 MEMORY.md。

铁律：全程不用任何 API key（没有翻译 key，不进仓库 Secrets）；标题翻译与一句话简介由本轮自己做。
