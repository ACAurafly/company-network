# Codex 中转可靠性维护

2026-11-17，关联 [Issue #9](https://github.com/ACAurafly/company-network/issues/9) 和 [规格](../../specs/009-codex-relay/spec.md)。已部署出站 HTTP/1.1、有界等待及用户批准的限额备用上游。架构比较见 [决策记录](../decisions-codex-relay-reliability.md)。

## 运行版本与配置

有效程序是挂载的更新运行文件；本轮为 0.2.21、提交 `10ba8f9b4dc2e6023d4a9879ab77b21841babd10`。镜像内置程序版本不同，维护时先核实容器实际命令和挂载文件，不以镜像标签判断。

持久化网关配置：

```yaml
gateway:
  openai_http2:
    enabled: false
  openai_response_header_timeout: 45
  openai_first_output_timeout_seconds: 60
  openai_high_effort_first_output_timeout_seconds: 120
  stream_data_interval_timeout: 90
```

这些是等待响应头、首个语义输出及流数据间隔的预算；持续输出的合法长任务可以超过 120 秒。HTTP/1.1 配置作用于 NAS 到 OpenAI 的 HTTP 出站，不改变员工 Responses API 入口。修改配置后需让网关重新加载；本轮保留镜像、网络、挂载和凭据，仅重启应用容器。

## 限额备用

原订阅账号保持优先，备用 API 账号使用较低优先级和并发 1。通过管理 API 设置其 `extra.quota_daily_limit` 为用户批准的美元阈值，`quota_daily_reset_mode=rolling`；实际金额、账号及凭据仅留在受控记录。

同时启用三个原生设置：

```text
openai_advanced_scheduler_enabled=true
openai_advanced_scheduler_sticky_weighted_enabled=true
openai_advanced_scheduler_subscription_priority_enabled=true
```

订阅优先根据真实账号的 `plan_type` 判断；应读取或刷新真实元数据，不能伪造。每轮重新评估可用账号，避免主账号恢复后仍因旧会话绑定持续使用付费备用。结构上不可迁移的 previous_response_id 仍须遵守上游上下文约束。

额度是本网关的记账停用阈值，起点由 `quota_daily_start` 计算，不是 OpenAI 项目的硬扣费上限。只统计经本网关记账的使用；外部直连和在途请求的结算可能越过阈值。部署前应确认现有账号及预算授权，不在这里公开密钥或原始账单。

## 验证与恢复

先在禁止外联的独立 Docker 网络使用同一程序、独立数据库/Redis 和 TLS/SSE 上游夹具。不得复制生产令牌到故障环境。确认 CA 可读、实际协议为 HTTP/1.1，并验证：正常流、无响应头、仅保活、停流、过载、取消，以及备用选择、恢复回切、额度耗尽排除。

本轮七项协议/故障/取消检查和四项备用/额度演练全部通过；生产主链路及备用专用临时组共九次变更后请求完整完成。备用用量已核对到正确账号，费用计数实际增加。临时用户、密钥、订阅、组、容器及网络已撤销；服务健康，观察期没有新增 HTTP/2 错误。另跑既有工具回归：

```powershell
python -m unittest discover -s tools -p 'test_codex*.py' -v
```

44 项通过。真实业务、离线回归和故障夹具分别记录，不能互相替代；HTTP 200 也不能替代 `response.completed`。

配置变更前保存原字节、候选字节、权限及哈希，恢复前检查现态仍匹配候选。完整回退先禁用备用并恢复原调度开关、优先级与并发，再恢复原网关配置并重启；保留已经产生的用量账目。回退脚本和私有备份路径位于受控运维交付，本轮仅执行预检，没有在生产主动制造故障或耗尽真实额度。

本地加固不会消除上游容量不足。备用不支持的模型、外部链路故障和长期稳定仍有边界；依据具体错误与完整流事件判断，不承诺所有任务固定耗时。
