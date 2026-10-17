# LLM Research OS

围绕一张可交互地图组织的个人 LLM 研究工作空间。
把研究问题、实验、自己的 Agent、算力、服务状态和证据放在同一视野中，
点击组件即可查看背后的具体信息。

[English](README.md) · [Dashboard 使用指南](docs/guides/research-dashboard.md) ·
[当前待办](https://github.com/victorzhong0110/llm-research-os/issues/159)

## 工作空间是什么样的

Dashboard 是一张具有分组和逻辑关系的地图。Browse 用来阅读，Edit 用来编排，
AI 模式用来请自己的 Agent 协助维护。悬停看摘要，点击查看来源数据、图表和注明
作者的解读。地图变大后，可以使用搜索、缩放、折叠和小地图导航。

| 地图区域 | 可以查看的内容 |
| --- | --- |
| 研究与实验 | 研究问题、准备笔记、已记录的 Run、结果及证据 |
| 算力与执行 | 已接入的数据源观测、Worker 信息和已记录的任务活动 |
| 服务与可靠性 | 官方服务报告、导入的服务观测及其时效 |
| 决策与管理 | 人类决策、异议、费用／预算来源和恢复信息 |

通过包含、并列、固定位置和可选箭头组织相关工作。移动卡片改变视图；
执行依赖和权限通过各自的审查操作处理。外观提供黑白 Graphite、暖纸 Warm paper
和自定义主题。

地图包含预设和可配置组件。只有数据源存在时才会显示对应观测；缺少服务器负载、
利用率、费用或 Agent 活动时，会明确显示缺失。官方整体状态与自己的请求健康分开呈现。

## 从仓库开始体验

需要 Python 3.12+ 和 [uv](https://docs.astral.sh/uv/)。仓库已包含构建后的浏览器界面，
以下步骤无需 Node、模型密钥或 GPU。

```bash
git clone https://github.com/victorzhong0110/llm-research-os.git
cd llm-research-os
uv sync --locked --all-groups
uv run researchos app init \
  --root ./research-workspace \
  --project my-research \
  --control-db control/events.sqlite \
  --cas-root cas \
  --worker-root worker
uv run researchos web serve --root ./research-workspace --port 8787
```

打开服务器打印的 bootstrap URL，进入本地 Dashboard 并建立浏览器会话。
这个 URL 含有会话引导信息，请妥善保管。

1. 选择 **Create my first brief**，写下研究问题和什么结果算有进展。
   材料和资源可以暂时不确定。
2. 审阅并保存。目标与准备笔记会成为地图上可编辑的区域。重新加载页面前保存地图。
3. 阅读笔记，尝试 Edit，切换主题。可以添加 **OpenAI official status** 或
   **Claude official status** 组件，在能够访问公共互联网时手动刷新。

研究 brief 保存的是准备笔记。从笔记到可执行实验的引导配置仍在开发中。
高级研究和执行操作已经存在，但部分操作仍要求预先安装配置并提供内部标识。

也可以另建一个包含已有研究记录的离线演示工作空间：

```bash
uv run researchos workspace demo --root ./research-demo
uv run researchos web serve --root ./research-demo --port 8788
```

演示使用确定性 Mock 模型和模拟 Run；示例数据不代表真实训练结果。
安装 wheel 也会包含浏览器界面和离线材料。从本地构建或收到的 wheel 安装，请参阅
[安装与恢复指南](docs/guides/r15-installation-and-recovery.md)。项目目前处于预发布阶段。

## 接入自己的 Agent

AI 模式会向工作空间收件箱写入持久、限定范围的请求。自己的 Agent 用
`researchos dashboard inbox` 读取，用 `researchos dashboard reply` 回复，
也可以提出绑定地图版本的修改。系统会检查固定位置、选定范围及编辑冲突。
打开 AI 模式本身不会自动启动 LLM 或 Agent。

详见 [Agent 工作流](docs/guides/research-dashboard.md#connect-your-own-agent) 和
[组件契约](docs/protocols/dashboard-document-v0alpha1.md)。

## 实现与验证状态

<!-- generated-status:start -->

| 范围 | 状态 |
| --- | --- |
| Dashboard | 地图、Browse/Edit/AI、持久布局与主题已集成（#156） |
| First use | 研究 brief 引导已提供（#157）；材料、资源与可执行计划配置仍在开发 |
| Agent | 持久限定范围的收件箱与地图提案；回复由自己的 Agent 提供 |
| Provider status | 手动采集 OpenAI／Claude 公共报告（#158），显示来源与过期状态；开发环境直连尚未验证 |
| Execution and evaluation | 已实现审查后的原生 CPU、远端 Worker 执行、真实 CPU 评估和持久报告；工作包及实机验收仍有缺口 |
| Human / real-host acceptance | 已制定 dashboard-v1 任务；尚无当前地图的独立真人试用，旧检查点测试暂停 |
| Historical M1/M2 | 离线研究及特定本地／两机 CPU、CUDA、MPS 证据已按 ADR-0062 在原身份范围内验收 |
| Release | 预发布 0.0.0；未公开发布，无付费云验收声明 |

[当前 M3 证据与缺口](docs/evidence/m3/acceptance-matrix.md) · [历史 M1/M2 范围](docs/adr/0062-m1-m2-acceptance-and-m3-boundary.md)。
实现快照: `6b49255`; 历史已验收证据: `57ffdae`。

<!-- generated-status:end -->

当前重点是执行准备引导、更多具有真实来源的组件，以及独立用户的首次使用评估。
见 [#159](https://github.com/victorzhong0110/llm-research-os/issues/159) 和
[Dashboard 交付计划](docs/plans/research-dashboard.md)。

当前限制包括：官方状态需要手动刷新，尚无内置主机利用率采集器；旧工作空间备份格式
不包含 `dashboard.sqlite`，已保存的地图需单独导出。资源笔记不代表机器已连接或预算
已分配。浏览器自动化和截图不能替代真人可用性验收。

## 研究与执行基础

地图下面是共享的研究控制面：版本化规格、追加式事件、按内容寻址的产物、人类决策，
以及保留的 AI 异议。CLI、Python 和浏览器共用领域服务与操作收据。
经过审查的执行会绑定计划、材料、环境及 Worker 权限。

取消请求与实际观测到停止分开记录。未确认的结果保持 unknown，不会自动重新启动任务。
经过审查的原生代码遵循所选宿主执行配置的限制；执行配置无法强制落实的必要隔离要求
会被拒绝。详见 [安全策略](SECURITY.md)、[威胁模型](docs/security/threat-model.md) 和
[原生执行指南](docs/guides/m3-native-reviewed-execution.md)。

## 文档入口

- [Dashboard 使用与编排](docs/guides/research-dashboard.md)
- [安装、诊断、备份与恢复](docs/guides/r15-installation-and-recovery.md)
- [Dashboard 验收任务与实机检查](docs/guides/dashboard-acceptance.md)
- [M3 计划](docs/plans/m3-development-plan.md) 与 [证据矩阵](docs/evidence/m3/acceptance-matrix.md)
- [全部指南](docs/guides)、[协议](docs/protocols) 与 [架构决策](docs/adr/README.md)
- [参与贡献](CONTRIBUTING.zh-CN.md)、[工程标准](docs/engineering-standards.md) 与 [变更记录](CHANGELOG.md)

## 开发

```bash
uv sync --locked --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -m "not oci_live and not slow and not ray_native_live" \
  --cov=llm_research_os --cov-fail-under=85
uv run researchos schema --check-all
python scripts/project_status.py --check
node conformance/digest/verify.mjs
uv build
```

前端源码在 `web/`；重新构建需要按 [工作台指南](docs/guides/m3-workbench.md) 使用固定的
Node/npm 流程。发布的 JSON Schema 是外部契约，应从注册的模型重新生成，
不要直接修改生成文件。

## 许可

Copyright 2026 victorzhong0110。[Apache-2.0](LICENSE)，另见 [NOTICE](NOTICE)。
当前项目名称是工作名。版本发布、tag 与公开分发需要单独决定。
