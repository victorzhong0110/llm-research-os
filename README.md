# LLM Research OS

> 当前名称为临时工作名，正式名称将在公开发布前通过 ADR 确认。

LLM Research OS 是一个独立、开源、模型无关、训练后端无关、算力供应商无关的 LLM 研究操作系统。它用于表达研究问题、组合实验、让 AI 提出并反驳方案、在本地或远程 Worker 上执行，并记录训练、评测、系统、成本、血缘与 AI 决策。

## 当前状态

项目宪章 v0.1 及第 18 章技术基线已经接受。当前进入 M0：先证明研究定义、协议、验证、事件与模拟运行时，不执行真实 GPU 训练。

## M0 目标

1. 编写短版 ADR 与持续更新的威胁模型；
2. 定义 `ResearchSpec v0alpha1` 的 Pydantic 模型；
3. 生成版本化 JSON Schema，并提供正反例；
4. 实现验证器与语义差异；
5. 定义 CloudEvents 兼容的 `ResearchEvent`；
6. 建立 SQLite 最小事实源与 `SimulatedRuntime`；
7. 在无 GPU 条件下跑通首个纵向闭环。

## 已接受基线

- Python 3.12+、`pyproject.toml`、uv；
- Pydantic 是 M0 编写入口，版本化 JSON Schema 是对外契约；
- 追加式事件、可重建投影与内容寻址制品；
- 独立 Research IR，不附属于 NeMo、ms-swift 或任何 Agent 框架；
- 研究者默认拥有最终决定权，AI 可以并应当提交异议；
- 任何真实 GPU 消费、外部账户操作或不可逆操作仍需单独批准。

## 项目文档

- [项目宪章与最小内核规格 v0.1](docs/charter-v0.1.md)
- [第 18 章决策指南与确认记录 v0.1](docs/chapter-18-decision-guide-v0.1.md)
- [ResearchSpec v0alpha1规范说明](docs/protocols/research-spec-v0alpha1.md)
- [架构决策记录](docs/adr/README.md)
- [持续威胁模型](docs/security/threat-model.md)

## 本地开发

需要 Python 3.12+ 和 [uv](https://docs.astral.sh/uv/)。训练后端不安装到核心控制面环境中。

```bash
uv sync --locked --all-groups
uv run researchos validate examples/valid/minimal.yaml
uv run researchos schema --check schemas/research-spec/v0alpha1.schema.json
uv run ruff check .
uv run mypy src
uv run pytest
```

生成的 JSON Schema 是第三方实现使用的语言中立契约：

```text
schemas/research-spec/v0alpha1.schema.json
```

不要手工编辑该文件。修改 Pydantic 编写模型后，使用以下命令重新生成并审查协议差异：

```bash
uv run researchos schema --output schemas/research-spec/v0alpha1.schema.json
```

## 当前安全边界

M0只验证规范、差异和模拟语义，不执行任意训练代码、插件或远程Worker。任何真实GPU消费、外部账户操作或不可逆操作仍需单独批准。安全问题请参阅[安全政策](SECURITY.md)。

## License

Apache License 2.0. See [LICENSE](LICENSE).
