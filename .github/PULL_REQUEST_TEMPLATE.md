## 切片

<!-- 一条 PR 一个切片。引用对应的 issue，或 ADR-0038 E4 中的 M1-n。 -->

## 变更

-

## 边界

<!--
这条切片明确不做什么。
是否新增可执行能力（进程、插件、网络、模型调用、付费动作）？若是，威胁模型的哪一行已更新？
是否改动已发布 schema？若是，协议差异是什么？
-->

## 检查

- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `uv run mypy src`
- [ ] `uv run pytest`
- [ ] `uv run researchos schema --check-all`
- [ ] `node conformance/digest/verify.mjs`（改动 digest 相关时）
- [ ] 协议文档 / 导读 / 威胁模型 / ADR 索引已按需同步
- [ ] 来自 fork 的 PR：每个提交已 `git commit -s`（DCO 1.1）
