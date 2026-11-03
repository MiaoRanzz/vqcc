# VQCC 私有控制台

FastAPI 提供同源 API 与静态文件，React + TypeScript 提供八个页面（含任务介绍）。计算仍由
`automation/runner.py` 执行，共用原来的 `agent.lock`。Web 退出不结束计算任务。
页面刷新、筛选和报告读取不调用模型。项目继续使用 Python 3.13 Conda `vqcc`。

## 安装与构建

先用 `conda env list` 确定环境路径，并确认解释器：

```bash
conda run -n vqcc /root/miniconda3/envs/vqcc/bin/python -c \
  'import sys; print(sys.executable); print(sys.prefix)'
conda run -n vqcc /root/miniconda3/envs/vqcc/bin/python -m pip install \
  --target web/.python -r web/requirements.lock
cd web/frontend
npm ci
npm run build
```

`web/.python` 只供 Web 进程使用，保持原科学环境的包版本。不要在调用 Conda 前
把此目录加入 `PYTHONPATH`，Conda 自身使用另一版本的 Python。`web/run.py`
在启动 vqcc 解释器后加载这些依赖，`web/serve.sh` 已处理此步骤。

## 启动和 SSH 访问

第一次启用控制功能时执行：

```bash
./web/serve.sh init
./web/serve.sh serve
```

`init` 创建数据盘 `console/state.json`，导入已知的历史模型启动次数，并使后续
runner tick 使用统一队列。它不创建新 daemon。已有 daemon 的下次 tick 会读取
新代码；运行中的旧任务继续使用原快照。首次切换应在执行器空闲时进行，便于
核对历史任务身份。页面上的调度器启动操作也使用同一个 daemon 锁。

在服务器通过 SSH 读取 `artifacts/console/session-key`，在登录页输入；密钥
不放进 URL。另开本机终端：

```bash
ssh -N -L 8766:127.0.0.1:8766 USER@SERVER
```

访问 `http://127.0.0.1:8766`。服务只绑定服务器回环地址。当前主机的 8765
由另一个实验控制台占用，因此 VQCC 默认使用 8766；可用 `--port` 改端口。
首次登录密钥由 Web 进程创建，文件权限为 0600。会话过期或 Web 重启后重新登录。
只运行一个 Web 写实例和一个调度执行实例；服务通过文件锁约束单实例。

独立只读验收可使用：

```bash
./web/serve.sh serve --read-only --key-path /tmp/vqcc-console-review-key --port 8766
```

只读模式可以浏览、预检，但不会接受作业、配置或调度写操作；不会初始化队列。
测试服务器退出使用该终端的 Ctrl-C。正式运行可在已有终端会话管理工具中保持
前台进程；本容器没有 init，本项目不安装系统服务。

## 控制语义

若 Kaggle OAuth 返回 callback URL 不在允许列表中，先检查 Codex 配置的
`oauth.client_id` 与该客户端注册的回调地址是否匹配。本部署曾把 Codex 的
`/callback/...` 地址配给 `kagglesdk` 客户端；2026-10-30 已恢复为匹配的已注册
客户端并完成浏览器登录。旧会话需重新连接 MCP 才能加载新配置，不要重复使用旧授权链接。

提交和对账也支持官方 API Token：在 `https://www.kaggle.com/settings/api`
生成 API Token，然后在服务器执行
`bash /root/project/vqcc/automation/set_kaggle_token.sh`，按提示粘贴（不回显）。
令牌保存至运行用户的 `~/.kaggle/access_token`，不进入仓库。runner 在每次启动
模型任务时读取，通过 `KAGGLE_API_TOKEN` 提供给官方 SDK，不覆盖 Codex 的 MCP
OAuth 凭据；正在运行的任务仍沿用启动时的环境。认证恢复仍需实际查询团队
提交历史确认；本地保存成功不代表平台接受，提交预算和检查门槛继续生效。
本部署已验证 API Token 和新 OAuth 凭据都能通过官方 `kagglesdk` 读取同一账户的
提交记录，但两者访问 MCP 私有接口仍返回 `Unauthenticated`。提交/对账任务遇到
该错误时按流程使用官方 SDK，不重复浏览器 OAuth。查询成功不等于已上传，
最终结果仍以提交回执为准。

- 本地生成、验证、晋级与打包不调用模型；Codex 优化、提交和对账计入顶层次数。
- Codex 优化默认覆盖全部三个任务，最长运行时间默认 3600 秒；与本地实验分别保留表单选择。
- 作业入队冻结配置和生成器指纹；dispatch 按当前预算、平台配额和授权上限重新检查。
- 暂停只影响未来自动任务；暂停期间不会自动提交。手动作业仍受统一门槛约束。
- 取消排队仅处理 queued/blocked；停止针对具体 run ID，由监督器确认后更新状态。
- 配置保存产生新版本，激活后用于新任务；旧任务保留快照。回滚复制历史配置为新版本。
- 未完成验证不算 PASS；运行 completed 也不等于候选通过验证。
- 提交预览只供查看，正式提交重新准备；reserve 后保留尝试记录，结果不明只能先对账。
- 每次上传失败或结果未确认且缺少提交 ID 时，自动为该上传尝试安排一次只读对账。
  每笔尝试单独记录并跨重启去重；预算不足或暂停时等待恢复。对账仍未查清时保留
  未确认状态，不自动重复对账或重传；每日例行对账仍保留为后续检查。
- 若已结束的上传记录证明正式创建提交接口尚未调用，且完整平台历史也没有匹配项，
  由流水线核验哈希绑定的证据后记为“已确认未创建提交”。该次尝试不占每日成功额度，
  原组合仍去重；其他已验证的新改进可以继续提交。存储端是否收到 ZIP 单独保留为未知。
- 未提交的最佳改进保留到下一个 UTC 23:40（北京时间 07:40）上传窗口，跨日也不丢失。
  现有队列在窗口内优先检查，无需等待新优化；执行时采用当前最佳已验证组合。
  每天最多一次尝试、一次成功提交，暂停、模型预算、截止时间、验证和
  提交去重规则继续生效。
- 资源页分别展示整机与当前任务。整机 CPU、内存、磁盘和配置 GPU 每 5 秒采样；GPU 为设备级指标，可能包含其他项目。任务空闲明确显示空闲，不把整机用量算到本项目；RSS 为进程树求和，可能重复计入共享页。

## 阅读控制台

- “任务介绍”解释 DQI、InvSqrt、DFTHC-SOS 的背景、成本公式和优化方向。
- 每题的官方成本趋势只纳入证据仍完整的正式 PASS；普通点表示全部有效分数，晋级点来自实际 `promoted_at` 记录。纵轴使用对数刻度，精确成本和相对改进可在明细表核对。
- 总览的三个大数字是已记录官方验证成本，越低越好；各题数值不能直接比较。成本降低比例相对初始基线，本地组合改善相对上次已提交组合，平台分数单独展示。
- 提交中心的 Kaggle 分数历史只展示平台已经返回的公开分数。评分未知和结果待确认的提交仍在每日台账中；总览显示最近一次已知平台分数，不会被更新但尚未评分的提交清空。
- “当前提交进展”区分条件满足、已排队、执行中和实际上传。任务结束不等于上传成功；最近运行结论、时间和原始报告可直接查看。
- 每个优化时段只创建一轮任务。队列为空时显示下一次计划检查时刻、调度状态及扣除预留后的模型次数；计划时间并非保证启动时间。
- 点击任务进入独立详情页，可返回列表；读取中、读取失败和重试都有明确提示。
- 提交模型预留与对账模型预留分别是总模型预算内保留的任务次数，不是“已用/总额”，也不是平台提交上限。平台提交配额仍在独立区域展示。

## 测试与 API 契约

```bash
conda run -n vqcc /root/miniconda3/envs/vqcc/bin/python web/run.py \
  unittest discover -s tests -v
conda run -n vqcc /root/miniconda3/envs/vqcc/bin/python web/run.py \
  unittest discover -s automation -p 'test_console_jobs.py' -v
conda run -n vqcc /root/miniconda3/envs/vqcc/bin/python web/run.py \
  unittest discover -s automation -p 'test_runner*.py' -v
conda run -n vqcc /root/miniconda3/envs/vqcc/bin/python web/run.py \
  unittest discover -s automation -p 'test_pipeline.py' -v
```

自动化测试使用临时数据、假进程和本地 HTTP 客户端，不上传比赛文件，不调用真实
Codex，不重复跑完整科学验证。前端构建通过 `npm run build` 同时检查 TypeScript。
API schema 保存于 `web/openapi.json`；服务登录后可读取 `/api/v1/openapi.json`。

读取响应包含 `data/observed_at/source_updated_at/revision/freshness/consistency`。
写请求使用 `Idempotency-Key` 和 `X-CSRF-Token`。预检无副作用；修改状态的操作
持久保存请求指纹与结果。生成器参数范围来自 `/parameter-schemas`。

源码分工：`web/backend/read_model.py` 适配历史数据；`automation/jobs.py` 管理
队列、配置与预算；`automation/local_job.py` 复用 pipeline 的科学门槛；
`automation/runner.py` 监督进程；前端页面和公共组件分开，便于后续视觉和交互优化。

## 数据、恢复和回退

原始 experiments、runs、state 保持既有格式；新控制状态位于数据盘 console。
研究排序和备注存于 console/research.json，不改历史假设文件。停止 Web 后备份
console 和原始证据；若需要一致的整体备份，应先暂停自动调度、等当前任务结束，
再停空闲调度器。不要清空预算、提交台账或幂等记录。

重新启动 Web 不启动计算；重新启动 runner 先核对遗留任务的进程身份与 result。
无法确认的 starting/running 记录保留 unknown，阻止新 dispatch，不盲目重复执行。
这种情况需要通过运维检查进程、结果文件及提交台账；首版不提供“清空未知状态”按钮。

回退前先排空或取消新队列、处理所有 unknown 与未确定上传，再停空闲调度器。
保存完整 console 备份后回退源码。旧 runner 不认识 console 预算，不应在控制状态
仍有待处理作业时启用。迁移时同时复制 console、runs、experiments、state，更新部署
路径，确认只保留一个执行宿主；不要复制他人账号的认证文件。

当前交付验证和仍未覆盖的环境验收见 `docs/web-console-read-validation.md`。

## 浏览器回归与截图

先创建新的隔离 fixture（仅复制小型元数据，不复制电路）：

```bash
conda run -n vqcc /root/miniconda3/envs/vqcc/bin/python \
  tests/create_console_fixture.py /tmp/vqcc-browser-fixture
./web/serve.sh serve --config /tmp/vqcc-browser-fixture/config.json \
  --key-path /tmp/vqcc-browser-fixture/session-key --port 8766
```

另一个终端运行：

```bash
cd web/frontend
VQCC_TEST_URL=http://127.0.0.1:8766 \
VQCC_TEST_KEY_FILE=/tmp/vqcc-browser-fixture/session-key npm test
```

测试会操作该 fixture 的队列、暂停状态、配置与研究记录，不能指向正式控制服务。
不会启动调度器、模型或科学验证。可用 `CHROMIUM_PATH` 指定已有 Chromium；无
中文字体的验收环境可用 `VQCC_TEST_FONT_FILE` 指定本地字体文件，仅测试截图注入。
结束后用 Ctrl-C 停止测试 Web；fixture 可保留用于调试。

截图见 `docs/screenshots/`。这些截图来自隔离的浏览器 fixture，其中队列、预算和
磁盘信息属于测试环境；候选成本从已有真实报告复制，不能把截图当实时平台状态。

## 2026-11-03 提交与优化调度调整

提交改为每天一次：UTC 23:40（北京时间 07:40）开始，窗口 20 分钟，在 UTC 额度重置前
结束；`daily_submission_times: ["23:40"]`、`submission_timezone: UTC`、
`max_daily_submissions: 1`。对账移到北京时间 09:00。优化改为全天按小时接力
（`optimize_windows: [["00:00","23:59"]]`、`optimize_slot_minutes: 60`），避开提交前
35 分钟保护和对账；`daily_model_limit` 为 30。控制台若已保存过旧配置版本，需在
“配置与额度”中把每日总次数改为 30。以下为此前策略记录。

## 2026-10-30 提交策略调整

用户已将每轮优化完成后提交调整为每天北京时间 08:00、20:00 各检查一次。
`automation/config.json` 使用 `submission_policy: daily_windows`；每个窗口 45 分钟，
最多一次上传尝试。2026-11-03 用户将本地每日上限改为三次成功提交，
`submission_quota_basis: successful_submissions`（每 UTC 日，北京时间 08:00 重置）。未提交的已验证
改进保留到下一窗口，执行时选择当前最佳，无需再完成优化；没有改进就跳过。
官方每日上限仍为 5 次，真实上传前还要查询平台团队记录。两项限制分别检查。
总览与提交中心展示成功提交/本地当日上限，并单独注明尝试记录数和剩余成功额度。
成功提交指平台已接收并取得提交 ID 的记录；评分状态另计，缺少 ID 的未确认上传不计入。
每日额度只计算不同的有效提交 ID；失败上传保留尝试记录，不占成功额度。
未指定新计数口径的历史配置仍按尝试计算。候选相同或无改进不会重复提交；
缺提交 ID 的不确定上传先对账。有 ID 但分数未知不阻止下一份合格改进。
模型任务预算仍独立生效，本次没有提高其次数或资源上限。
