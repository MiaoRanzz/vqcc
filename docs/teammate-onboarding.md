# VQCC 自动化流程：导出与独立接入教程

这份教程用于让另一位参赛者在自己的服务器上，用自己的 Codex 和 Kaggle 账号，独立研究、优化、验证和提交。双方各有自己的实验和提交记录。

**当前流程还不是换账号就能启动的通用版本。** 初始化程序绑定了原账号的历史提交。第4节列出了发布前必须完成的修改；完成并验证后，接收方才能启用自动提交。本次交付是教程，没有修改运行中的程序，也没有发布或发送代码。

源码核对基准为 `5fe2986`；后续提交 `07880c1` 仍有相同的初始化绑定。未提交的 Web 开发不属于这份教程假定已经可用的能力。

## 1. 独立参赛，怎样共享代码

“同事”或“小伙伴”不等于同一个 Kaggle 队伍。比赛规则 C(5)(d) 和 C(6)(a) 禁止不同队伍私下共享比赛相关代码或数据，允许通过比赛论坛让所有参赛者获取共享代码。[比赛规则](https://www.kaggle.com/competitions/google-verifiable-quantum-circuit-compilation/rules)

因此，接入顺序是：

1. 导出方在本地整理准备公开的源码，检查许可、隐私和账号绑定。
2. 作者审阅具体内容并决定是否公开；决定公开后，通过比赛论坛提供所有参赛者都能获取的版本。
3. 队友从公开版本接入，用自己的账号下载官方数据，建立自己的基线和台账。
4. 双方各自优化和提交，不私下交换未公开的比赛代码、候选或实验数据。

仅把仓库设成公开，不等于已经完成比赛要求的分享方式。是否公开仍由作者决定，这份教程没有代替作者发布代码。若暂时不公开，就保留本地草稿，不把它当成跨队私下交接包。

## 2. 导出哪些内容

| 内容 | 处理方式 |
|---|---|
| `automation/`、项目 skill、必要的生成器和说明 | 挑选准备公开的版本，保留来源与许可 |
| 第三方代码 | 保留 LICENSE 和来源提交，确认可以这样分发 |
| 官方样例、验证器、`kickmix`、化学数据 | 接收方接受比赛规则后自行下载 |
| 原账号实验、研究队列、提交文件和回执 | 不作为独立接入包的一部分 |
| 原账号 `state/`、`runtime/`、运行槽位 | 不复制；接收方建立自己的状态 |
| 私有 Git 历史 | 不整个打包；历史中可能仍有未准备公开的内容 |
| Codex/Kaggle 登录、`.env`、SSH密钥、代理和Web会话 | 不导出，双方各自配置 |

不要把原提交 `57763974` 换成队友的 ID，就继续用原报告。科学基线、账号提交记录和平台成绩必须分别建立。

## 3. 导出方：制作本地待发布副本

下面只制作本地草稿，不上传，也不停止原自动化。命令读取指定 Git 提交，不带未提交的 Web 开发。按顺序在同一个 Bash 终端执行；命令失败就先处理，不继续覆盖或解包。

~~~bash
set -euo pipefail
cd /root/project/vqcc
export VQCC_EXPORT_REV="$(git rev-parse '5fe2986^{commit}')"
export VQCC_EXPORT_DIR="$(mktemp -d /mnt/data2/vqcc-release-draft.XXXXXX)"
mkdir "$VQCC_EXPORT_DIR/source"
git archive --format=tar \
  --output="$VQCC_EXPORT_DIR/source-draft.tar" \
  "$VQCC_EXPORT_REV" \
  AGENTS.md README.md .gitignore .agents/skills/vqcc-optimize \
  automation generators submission/2026-10-29/source
tar --extract --no-same-owner \
  --file="$VQCC_EXPORT_DIR/source-draft.tar" \
  -C "$VQCC_EXPORT_DIR/source"
printf '%s\n' "$VQCC_EXPORT_REV" > "$VQCC_EXPORT_DIR/SOURCE_COMMIT.txt"
~~~

要使用更新的提交，先检查新增内容和接口，再替换版本号。这份草稿还不能交付运行：它保留了待移植的初始化逻辑，以及需要作者审阅的生成器。`submission/2026-10-29/source` 是现有 DQI 生成器的代码依赖，不包含原账号的提交产物和验证回执。

在副本中建立新的 Git 仓库，设置作者自己的提交身份，完成第4节改造并记录版本。不要直接在原自动化正在使用的目录里改造。

发布版 README 换成新账号说明，并补齐实际引用的文件。skill 对 `docs/research.md` 的引用应改为公开研究入口；不要为了补链接，把私有假设队列和报告一起加进去。

## 4. 发布前必须改好的地方

这些是现有实现中的实际绑定，不是可选增强。

| 位置 | 当前行为 | 独立版本需要的行为 |
|---|---|---|
| `Pipeline.init()` | 要求原回执ID为 `57763974`，写入固定日期和已提交成本 | 支持新账号初始化，将本地基线与已提交记录分开 |
| `baseline_submission_id`、`baseline_path` | 初始化没有按这两个配置完成通用导入 | 实际实现并校验，或删掉无效字段，不能让用户误以为改值就生效 |
| `skip_reason()`、`prepare()`、`record()` | 假设已有已提交成本，空账号不能正常首提 | 支持首提，取得真实ID后再建立该账号的已提交成本 |
| `prompts/smoke.md` | 固定查询原提交ID | 查询接收方自己的记录；没有提交时如实显示尚无提交 |
| `AGENTS.md`、runner附加提示、提交说明 | 带有原部署的授权和历史声明 | 记录新部署自己的资源和提交授权 |
| 生成器和源码快照 | 部分依赖历史源码目录 | 保留合法公开的代码依赖或整理为模块，不能删掉目录却保留引用 |

不要全局替换所有 `2026-10-29`：科研档案日期、来源路径和测试种子可能是真实历史。需要改的是“当前账号已经提交过什么”的逻辑。

新账号没有提交过时，初始化应建立经过完整验证的三题本地候选、成本和当前最佳；提交列表为空，已提交成本为空。首次提交满足验证、窗口、次数和身份检查后，可以预留并上传；相对改善标为“首次提交”或空值，不虚构上次成绩。拿到真实提交ID后，才建立已提交组合。以后继续执行“有改进才提交、无改进就跳过”。

接收方已经提交过时，依据其账号能核实的真实回执、提交时间和匹配产物导入。只有一个ID不够。当天已手动提交，默认等下一天再自动提交；结果不明的上传先对账。

可以把下面这段交给负责发布版本的 Codex：

~~~text
在这个独立发布副本中，让VQCC流程支持新的独立参赛账号。
保留完整验证、资源监督、版本记录、北京时间20:00窗口、每日最多一次、
先预留后上传和未知结果阻塞规则。

分开本地科学基线与账号已提交基线。支持尚无提交的新账号初始化，
以及导入该账号真实提交和匹配产物。不得导入原账号57763974，
不得复制原state、实验或登录。不得把本地PASS写成平台成功。

修正init、skip_reason、prepare、record、smoke和指令中的账号绑定，
检查生成器路径，保留必要的第三方来源和许可证。
用临时目录和假MCP回执测试首提、历史导入、当天去重、未知上传、
首次回执落盘和重启恢复。测试不真实上传比赛文件。

完成后在README写出实际存在且测试过的初始化命令及通过条件，
补齐依赖文件和启动说明。不要发布代码、修改原服务器或启动调度。
~~~

**目前仓库没有上述新账号初始化命令。** 旧 `pipeline.py init` 不适用；删除 `state/` 再运行旧初始化也不适用。完成改造前，不进入本教程的日常启动步骤。

发布前还要验证：导入别人的提交被拒绝；当地当天的手动提交不会被自动流程绕过；候选或报告改动后无法晋级或提交。这里的“当天”按部署明确配置的时区计算。

## 5. 审阅并交付公开版本

作者检查准备公开的生成器、说明和第三方代码。比赛数据的 Apache 2.0 许可不等于替所有第三方代码完成授权。

发布版应有自己的依赖文件，例如 `requirements.txt`。本机核对过的参考环境是 Linux、Python 3.13.18、NumPy 2.5.4、SciPy 1.18.1、pypdf 6.21.4；这不是完整 Conda 锁，也不保证任意系统都能加载当前 `kickmix`。

记录源码、依赖、官方数据获取方式和改造测试结果。以下命令要求副本已经成为 Git 仓库，改造和说明已全部提交：

~~~bash
set -euo pipefail
cd "$VQCC_EXPORT_DIR/source"
test -z "$(git status --porcelain)"
git rev-parse HEAD > "$VQCC_EXPORT_DIR/RELEASE_COMMIT.txt"
git archive --format=tar.gz \
  --output="$VQCC_EXPORT_DIR/vqcc-workflow.tar.gz" HEAD
(
  cd "$VQCC_EXPORT_DIR"
  sha256sum vqcc-workflow.tar.gz RELEASE_COMMIT.txt > SHA256SUMS
)
~~~

最终文件是源码包、`RELEASE_COMMIT.txt`、`SHA256SUMS`，以及包内完整的部署说明。不要把早期的 `source-draft.tar` 当成成品。

作者决定公开后，再通过比赛论坛提供统一下载地址和版本。队友与其他参赛者取得同一版本。本文编写时尚未执行发布。

## 6. 接收方：准备自己的目录和官方文件

先加入比赛、接受规则，再自行下载官方数据。官方包中的样例、验证器、`kickmix` 和化学数据一起保留，记录来源和哈希，不改官方验证器。

在新 Bash 终端中，把下载目录改成实际路径。项目和数据目录都须新建；校验失败或目录已存在时，整段停止，不会继续解包到旧部署。

~~~bash
set -euo pipefail
export VQCC_PACKAGE_DIR="/实际下载目录"
export VQCC_PROJECT_DIR="$HOME/projects/vqcc"
export VQCC_DATA_DIR="/mnt/data2/vqcc-independent"
(
  cd "$VQCC_PACKAGE_DIR"
  sha256sum --check SHA256SUMS
)
test ! -e "$VQCC_PROJECT_DIR"
test ! -L "$VQCC_PROJECT_DIR"
test ! -e "$VQCC_DATA_DIR"
test ! -L "$VQCC_DATA_DIR"
mkdir -p "$(dirname "$VQCC_PROJECT_DIR")"
mkdir "$VQCC_PROJECT_DIR"
mkdir "$VQCC_DATA_DIR"
tar --extract --no-same-owner \
  --file="$VQCC_PACKAGE_DIR/vqcc-workflow.tar.gz" -C "$VQCC_PROJECT_DIR"
cd "$VQCC_PROJECT_DIR"
git init
cp "$VQCC_PACKAGE_DIR/RELEASE_COMMIT.txt" UPSTREAM_RELEASE.txt
ln -s "$VQCC_DATA_DIR" artifacts
mkdir -p artifacts/runtime
touch artifacts/runtime/PAUSED
~~~

先核对来源和包内路径；校验和能发现传输损坏，不能证明陌生来源可信。没有 `/mnt/data2` 时改用自己的数据盘。除数据和实验空间外，还应保留配置要求的20 GiB空闲空间。

按发布说明放置官方文件，通常需要项目根下的 `sample_submission/`、`verifiers/`、`kickmix/kickmix.so`。设置自己的 Git 身份，记录初始版本；凭证、数据和生成的大文件不进入 Git。

## 7. 配置环境、模型和 Kaggle MCP

先看 `conda env list`。有匹配的 `vqcc` 就复用；没有时，由队友确认创建，不能默默使用 `base`。

~~~bash
conda env list
# 仅在没有匹配环境且同意创建时执行；版本以发布说明为准
conda create -n vqcc python=3.13.18 pip
~~~

环境就绪后，解析实际解释器。以下假设发布版已经提供 `requirements.txt`：

~~~bash
set -euo pipefail
export VQCC_ENV_PREFIX="$(conda env list | awk '$1 == "vqcc" {print $NF; exit}')"
test -n "$VQCC_ENV_PREFIX"
test -x "$VQCC_ENV_PREFIX/bin/python"
conda run -n vqcc "$VQCC_ENV_PREFIX/bin/python" -c \
  'import os,sys; assert sys.prefix == os.environ["VQCC_ENV_PREFIX"]; assert sys.executable.startswith(sys.prefix + "/"); print(sys.executable); print(sys.version)'
conda run -n vqcc "$VQCC_ENV_PREFIX/bin/python" -m pip install -r requirements.txt
conda run -n vqcc "$VQCC_ENV_PREFIX/bin/python" -c \
  'import sys; from pathlib import Path; sys.path.insert(0,str(Path("kickmix").resolve())); import kickmix,numpy,scipy; print(kickmix.__file__); print(numpy.__version__,scipy.__version__)'
~~~

依赖已齐全就跳过安装。加载失败先解决 Python、系统或二进制兼容性。导入成功只是环境检查，不是科学验证通过。

按 [OpenAI 官方说明](https://learn.chatgpt.com/docs/codex/cli)安装 Codex。源环境核对到 `codex-cli 0.153.0`，发布版应记录它实际测试的 CLI 版本。

~~~bash
codex --version
codex exec --help
codex login
codex login status
~~~

远程服务器可以用 `codex login --device-auth`，在自己的浏览器完成登录；是否可用取决于账号设置。不要复制原作者的登录缓存。[官方登录说明](https://learn.chatgpt.com/docs/auth)

当前 runner 需要 `--approve-for-me`、`--ephemeral`、`--add-dir`、`-C`、`--json` 和 `--output-last-message`。不支持时先处理版本兼容性，不用关闭全部审批和沙箱来替代。

在自己的 Codex 配置里选择账号支持的模型和推理强度，用 `/status` 核对。稳定版 runner 继承 Codex 的有效配置，没有独立模型字段。[配置说明](https://learn.chatgpt.com/docs/config-file/config-basic)

优化、smoke、提交和对账都会调用 Codex，使用当前登录账号或工作区的额度。API key 登录采用 API 计费，本教程不要求切换到额外付费方式。[认证说明](https://learn.chatgpt.com/docs/auth)

Kaggle MCP 使用 `https://www.kaggle.com/mcp`。先检查配置，缺少时添加，再登录自己的 Kaggle 账号：

~~~bash
codex mcp list
# 缺少kaggle服务时添加
codex mcp add kaggle --url https://www.kaggle.com/mcp
codex mcp login kaggle
~~~

配置方法见[官方MCP说明](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)。确认比赛和账号归属。新账号尚无提交是正常状态，改造后的 smoke 应显示尚无提交，不再查询原账号的ID。

## 8. 初始化自己的基线

在发布版 `automation/config.json` 填写自己的数据路径、Conda解释器、Codex路径，以及获准使用的CPU、内存、GPU和时长。`artifacts` 与配置的数据目录要一致。

原部署的上限是20 CPU、180 GiB内存和GPU 0、1，现有代码也会拒绝更大的值。这不是对队友机器的授权；机器较小就调低预算，扩展上限另行明确。沿用北京时间20:00、每天最多一次，是本工作流的选择。截止时间在接入当天核对比赛页面。

稳定版尚无每日模型任务次数上限。单次时长限制不保证全天额度够用，也不能把 Web 设计文档中的次数控制当成已经部署。

先做不调用模型的检查：

~~~bash
./automation/launch.sh --config automation/config.json dry-run
~~~

再执行发布版 README 中**实际存在且测试过的新账号初始化命令**。这里不编一个尚未实现的命令名；当前旧 `pipeline.py init` 不适用。

初始化后检查：

~~~bash
conda run -n vqcc "$VQCC_ENV_PREFIX/bin/python" \
  automation/pipeline.py --config automation/config.json status
./automation/launch.sh --config automation/config.json smoke --seconds 300
~~~

新账号应看到三题自己的本地起点、空提交列表和尚无已提交成本。已有提交的账号应看到自己的真实记录。不能出现原账号导入记录或凭空产生的平台成绩。

smoke 会消耗模型额度。看报告中的实际检查项，不只看退出码；只读检查也不等于测试过真实上传。自定义配置时，每个 `pipeline.py` 命令都显式写 `--config`，当前稳定版不会自动读取 `VQCC_CONFIG`。

## 9. 先跑一轮，再开每日调度

**以下以第4节改造和验证已完成为前提。** 接收方先确认自己的资源、额度、时长和自动提交授权，再跑30分钟：

~~~bash
./automation/launch.sh --config automation/config.json optimize --seconds 1800
~~~

这轮会自行研究、改代码、做预算内的实验并写报告。没有改进也要保留结果。命令在前台执行；需要断开SSH时，可以在已有 `tmux` 会话里运行，计算仍须在 runner 监督范围内。

返回的 `run_dir` 中，`report.md` 说明做了什么，`result.json` 记录结束原因，`events.jsonl` 记录过程。候选在 `artifacts/experiments/`，代码历史用 `git log` 查看。

首轮正常后，启动自己的唯一调度器：

~~~bash
set -euo pipefail
rm -- artifacts/runtime/PAUSED
conda run -n vqcc "$VQCC_ENV_PREFIX/bin/python" \
  automation/install_schedule.py --config automation/config.json --install --start
./automation/launch.sh --config automation/config.json status
~~~

调度器按配置窗口优化，20:00检查可提交组合，20:55开始查询结果。首次提交走已经验证的首提分支；以后没有合格改进就跳过。平台评分未知就保留未知。

独立参赛的双方可以各运行一套；每个账号或 Kaggle 队伍只保留一个负责提交的执行宿主。自己的手动提交也要计入自己的台账。

关闭聊天或SSH不会停止独立调度器，但服务器必须持续在线。当前启动器不安装系统开机服务；重启后先确认挂载和登录，再重新启动。

## 10. 日常查看、暂停和停止

下面是分别使用的命令，不要整块顺序执行：

~~~bash
# 查看状态，不调用模型
./automation/launch.sh status

# 暂停后续自动任务，当前任务继续
touch artifacts/runtime/PAUSED

# 确定要恢复时执行
rm -- artifacts/runtime/PAUSED

# 停止调度器及它当前的调度任务
conda run -n vqcc "$VQCC_ENV_PREFIX/bin/python" \
  automation/install_schedule.py --config automation/config.json --remove
~~~

`PAUSED` 只拦自动调度，不拦手动命令。前台单次优化可按 `Ctrl+C`，等 runner 清理并退出。

| 问题 | 先检查什么 |
|---|---|
| 缺少 `vqcc` | `conda env list`，不要改用base |
| 解释器不符 | 配置、绝对解释器和 `sys.prefix` |
| `kickmix` 不能加载 | Python、CPU架构、系统库和文件是否匹配 |
| Codex不认识参数 | CLI与发布版runner是否兼容 |
| 查询出现原账号ID | 历史绑定未移植完成，停用自动提交 |
| 空账号一直显示无改进 | 首提分支未实现，不能填假已提交成本绕过 |
| `busy` | 已有任务持锁；稳定版没有手动任务队列 |
| 没有自动运行 | 是否暂停、是否在窗口内、是否已过截止 |

## 11. 怎样算接入完成

接收方能用自己的账号跑完一轮优化，找到源码提交、候选和报告；台账只包含自己的记录；调度、暂停和停止符合说明；首提和后续提交通过本地故障测试。这不代表已经取得新的平台成绩。

本文已核对项目接口、初始化绑定、CLI参数、解释器和参考依赖，并查阅比赛共享规则。公开发布、新账号初始化改造和目标服务器安装尚未执行，分别由作者和接收方按文中分工完成。
