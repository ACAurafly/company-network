# Company Network Engineering Constitution
Version: 1.0.0 · Ratified: 2026-11-17

## I. Intent and evidence
所有新变更保留 spec、plan、tasks、verification，篇幅按规模调整。规格描述可观察行为；验证带实际命令、环境和结果，未验证项不得写为通过。

## II. Operational boundaries
员工客户端、运维工具和 SDD 治理各负其责；离线验证与生产部署分别记录。管理员凭据、员工个人配置、订阅及现场原始数据不进入公开仓库。

## III. Compatibility and recovery
协议、配置、载荷和诊断格式变化明确版本与兼容性；生产维护记录回退与验收。员工包继续使用受控载荷和既有打包验证流程，原发布包、校验清单及历史证据保持原文。

## IV. Human accountability
Issue 有负责人；需求/方案确认和最终人工评审分别记录。AI 可起草、实施和验证，不代表人批准。已有用户授权持续有效，不重复申请同一授权。

## V. Maintain one source
根 AGENTS、团队 skills 和模板各有真源，三工具入口同步并检查漂移。官方版本、来源和校验和可追溯；移植来源见 docs/sdd-origin.md。

## VI. Proportionate verification
按改动选择能证明实际行为的检查；结构检查不等于员工实机、远程网络或业务验收。生产操作及员工通知以用户授权为准。

## Governance
新变更遵循 CONTRIBUTING；完成规格保留历史，后续演进另建规格。宪章修改同样走 SDD，不静默改写历史验收。
