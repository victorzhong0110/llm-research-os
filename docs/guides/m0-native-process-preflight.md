# M0 Native Process Preflight 导读

M0 现在可以把一个原生 Python 任务的启动形状冻结成可复核摘要，但仍然**不能启动它**。
`researchos native preflight` 重新构造静态计划、重新求值计划授权，再检查一个极窄的原生进程
配置。成功输出固定为 `launchAllowed=false`、`isolation=not-enforced` 和
`execution=not-executed`。

## 最小示例

```bash
uv run researchos native preflight \
  examples/native-process-preflight/spec.yaml \
  examples/native-process-preflight/authorization-request.json \
  examples/native-process-preflight/preflight-request.json \
  --registry examples/native-process-preflight/manifest.yaml \
  --format json
```

示例有四个输入：

- `spec.yaml`：只有一个 `example.native-process@0.1.0` task；
- `manifest.yaml`：声明固定 Python JSON-stdio 协议和唯一 capability `process.native`；
- `authorization-request.json`：把 capability grant 绑定到 spec/registry/plan 三摘要；
- `preflight-request.json`：再绑定授权决定摘要、task path、约束与资源上限。

退出码 `0` 只表示生成了可校验的审查报告，不表示可以执行。任一输入无效、摘要陈旧、授权不足、
计划不再是单 task，或清单扩大了权限面时返回 `2`，stdout 不产生成功报告。

## 当前允许的唯一形状

| 检查面 | 要求 |
|---|---|
| 计划 | 单一 task；无 edge、dependency、resource 或 loop |
| runtime | `python`，固定 runner 和 JSON-object-over-stdio protocol |
| capability | 仅 `process.native`，必须在精确计划授权中授予 |
| permission/port/resource | 全部为空 |
| shell/argv | `shell=false`；未来参数只能由可信 runner 固定构造 |
| network/environment | network denied；环境变量 allowlist 为空 |
| workspace | 请求未来使用隔离临时目录，但本命令不创建目录 |
| bounds | wall time、stdout、stderr、termination grace 都有硬上限 |
| entrypoint | 校验 `module.path:callable.path`，报告只给摘要，不回显原文 |

`preflightDigest` 同时覆盖四摘要绑定、task/manifest/config/entrypoint 身份、固定约束、资源上限，
以及“未认证、未持久化、未实施隔离、禁止启动”这组权威状态。报告模型会重算摘要，因此修改任何
被覆盖字段都会失败。

## 为什么还不能启动

预检只是纯函数。它没有证明以下事实：

- 哪个 Python 解释器、虚拟环境和依赖集合会运行；
- 临时目录、网络拒绝和环境清空已由操作系统强制执行；
- 授权来自已认证主体、仍在有效期内且已持久审计；
- 输入制品已安全物化、输出已限流并写入内容寻址存储；
- timeout、terminate/kill、并发取消和进程丢失已映射到正确 Run/Attempt 事实；
- 子进程不会再派生进程、访问设备或绕过宿主限制。

因此不能把 `preflightDigest` 交给 `subprocess` 当作启动令牌，也不能把 entrypoint 摘要当作保密
机制。下一工作包若实现真实执行器，必须新增可实施的隔离和身份绑定，并再次更新威胁模型。

完整字段和摘要载荷见
[NativeProcessPreflight v0alpha1](../protocols/native-process-preflight-v0alpha1.md)，运行时取舍见
[ADR-0008](../adr/0008-native-process-and-oci-runtimes.md)。
