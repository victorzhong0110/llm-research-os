# 参与贡献（中文）

> 本文是 [CONTRIBUTING.md](CONTRIBUTING.md) 的中文版。英文版是权威文本；完整规则见[工程规范](docs/engineering-standards.md)（英文）。

语言、注释、作者身份与覆盖率门槛见 [ADR-0040](docs/adr/0040-english-primary-and-engineering-standards.md) 与[工程规范](docs/engineering-standards.md)。本项目是预发布的研究控制面。M0 内核证明已收口（[ADR-0037](docs/adr/0037-m0-kernel-proof-closure.md)）。M1 离线研究助手闭环与 M2 本地／两机范围已按 [ADR-0062](docs/adr/0062-m1-m2-acceptance-and-m3-boundary.md) 验收，已合并的 main 中证据身份基线为 `7e5fc33`，M3 首片脚手架（`#81`）后为 `e1282c5`。M3 工作包在集成后的计划文档 [docs/plans/m3-development-plan.md](docs/plans/m3-development-plan.md) 中规划，并通过验收矩阵跟踪；`Issue #53` 只跟踪 native 授权消费。顺序、安全门与依赖关系仍以计划文档为准；不得用新代码改写 M1/M2 的验收身份。

## 规划与实施分工

维护者将全局计划和规范性指导交由规划／审查助手（当前为 ChatGPT/Codex）维护。指定执行者负责范围内的代码、测试、包内文档和候选证据。涉及任务范围、依赖、权限或验收条件的变更，应明确提出差异，不得自行替换总计划。常规实现与修复自主完成；合并和发布仍由维护者决定。详见[开发协作规则](docs/development-governance.md)及 [ADR-0064](docs/adr/0064-planning-and-implementation-ownership.md)。

## 开发环境

需要 Python 3.12+ 与 [uv](https://docs.astral.sh/uv/)。训练后端不安装到控制面环境。

```bash
uv sync --locked --all-groups
```

提交前跑与 CI 相同的检查：

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest --cov=llm_research_os --cov-fail-under=85
uv run researchos schema --check-all
node conformance/digest/verify.mjs
uv build
```

CI 在 Ubuntu 与 macOS 上、Python 3.12 与 3.13 要求全部通过；3.14 是允许失败的前瞻作业。覆盖率门槛为 85%（开启分支覆盖后当前树约 88%；90% 不是门，见工程规范）。

## 切片方式

- 一条 PR 一个切片。切片有明确的“做什么”和“不做什么”；后者写进 PR 描述与对应的导读。
- 引入新的约束或取舍才写 ADR（宪章 §23 E10）。新增命令、报告或 CLI 表面写协议文档（`docs/protocols/`）与导读（`docs/guides/`），不单独立 ADR。
- 已发布的 JSON Schema 是对外契约，不要手工编辑 `schemas/`。修改 Pydantic 模型后用 `researchos schema --output ...` 重新生成，并把 schema 差异当作协议变更审查；新增契约在 `src/llm_research_os/cli/contracts.py` 登记一处。
- 每个协议对象带正反例语料（`examples/`），无效样例必须说明为什么无效。
- 任何新增的可执行能力（进程、插件、网络、模型调用、付费动作）在合并前需要更新[活威胁模型](docs/security/threat-model.md)并通过其安全门。标为“planned”的缓解不是当前代码的安全属性。
- `ready`、`authorized`、预检成功、模拟 `completed` 都不是启动凭证或科学结论；不要在文档或代码里把它们写成那样。

## 提交要求

- 提交信息使用 Conventional Commits 前缀（`feat:`、`fix:`、`docs:`、`refactor:`、`ci:`、`chore:`）。
- 提交作者是你本人的身份与常用邮箱；不接受编辑器或 agent 注入的 `Co-authored-by` 机器身份。每个 clone 执行一次 `./scripts/install-git-hooks.sh` 可在本地剥离；CI 对每条 PR 都会拒绝这类 trailer。
- 仓库内容以英文为主要语言（代码、注释、CLI 文案、ADR、协议、导读、威胁模型、模板）；README 与 CONTRIBUTING 维护中文版；宪章 v0.1 与第 18 章以中文原文为准。Issue 与 PR 中英文皆可。
- 来自 fork 的 PR：每个提交须带 [Developer Certificate of Origin 1.1](https://developercertificate.org/) 签署，即 `git commit -s` 产生的 `Signed-off-by: 姓名 <邮箱>` 行。CI 只对 fork PR 强制这一项。本项目不要求 CLA。
- 保持 `uv.lock` 与 `pyproject.toml` 一致；锁文件变更需要在 PR 里说明原因。

## 许可

Copyright 2026 victorzhong0110。代码与原创文档按 [Apache-2.0](LICENSE) 发布；归属见 [NOTICE](NOTICE)。提交贡献即表示同意按该许可证第 5 条提交。数据集、论文、模型权重与第三方笔记不因此获得同一许可证，来源与权利须单独记录（宪章 §10、ADR-0019）。

## 安全

漏洞不要放在公开 issue。按 [SECURITY.md](SECURITY.md) 走私密渠道。
