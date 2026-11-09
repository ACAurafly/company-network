# 02 网络诊断、对照测速与最小修复

Status: ready-for-agent
Execution: implemented; gateway-applied; colleague-field-validation-deferred-by-user
Blocked by: 01

实现范围：应用内脱敏诊断导出、阶段耗时/会话状态记录，以及可重复的 DNS/TCP/TLS/TTFB 冷热请求对照工具。根据父对话网络调查记录选择有证据的最小网络适配或可评审的网关修复；不能把历史 Fake-IP 推测当根因。

验收：脱敏和错误传播测试；保留失败样本/重试、缓存与连接复用事实；固定目标逐目标统计。真实业务验证与环境限制分开记录。客户端与网络策略不得放宽认证、证书或外层隔离；不清共享 DNS 缓存，不自动修改他人代理配置。

实现者用独立 worktree/分支，在 01 集成后开始。调查笔记见 ../network-investigation.md（父对话维护）。
