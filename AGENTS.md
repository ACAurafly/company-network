# Company Network Agent Guide

本仓库维护公司网络 Windows 员工客户端、网络诊断和受控运维工具。先读 README.md 定位当前交付和验证入口；所有新变更（含文档、配置、skill、CI）执行完整 SDD，篇幅按规模调整。

## 工作登记与身份
GitHub Issue 是新工作的登记与交付状态入口，仓库固定为 `ACAurafly/company-network`。先创建或关联 Issue，记录目标、验收、负责人及进行中状态；补充要求和内部步骤复用原 Issue。普通问答不登记。
写 GitHub 前用 `gh api user --jq .login` 确认 ACAurafly；Git 作者、提交者同为 ACAurafly，禁止使用 raime7。创建或更新后回读。既有用户授权持续有效，不重复申请同一授权。

## SDD 入口
- 流程与验收真源：[CONTRIBUTING.md](CONTRIBUTING.md)；原则：[constitution](.specify/memory/constitution.md)。
- 创建规格：`python tooling/sdd.py new <slug> --issue <number>`；保留 `specs/<id>/{spec,plan,tasks,verification}.md`。
- 显式设置 `SPECIFY_FEATURE_DIRECTORY=specs/<id>`，不以 Git 分支猜规格。同一 checkout 不并发切换 feature 状态。
- 从用户明确范围选择 bootstrap、tools、tooling 或 docs，再定向读取实现；接口/配置变化写明兼容性、错误行为和回退。
- 任务有 T 编号和 FR 关联；交付记录实际命令、环境、结果及未验证项。AI 不代签人工批准，最终人工评审状态如实保留。
- PR 正文独立一行 `Spec: specs/<id>`；草稿用于前期评审，正式评审门禁检查完成任务、FR 证据、Issue 和改动范围。
- 团队 skills 真源为 `tooling/skills/`；`python tooling/sdd.py sync-agents` 同步 Codex、Claude Code、Copilot，`--check` 检查漂移。官方来源和校验见 `tooling/vendor/spec-kit/`。

## 验证与运维边界
按 README 和 CONTRIBUTING 运行适用检查；结构检查不替代实机、员工网络或业务验收。仅运行离线测试时不得宣称生产验证。生产账号、网络切换和员工通知以用户授权范围为准。
管理员凭据留在本机 `%LOCALAPPDATA%/CodexPrivate`；不提交 token、密码、订阅、个人 VPN 配置、私密载荷或现场原始数据。构建使用显式载荷路径及现有员工打包工具。
既有 `docs/issues/` 与维护记录保留历史；新工作使用 GitHub Issue 和 specs/，不批量重写已完成文档。运维工作目录的新交付与调查按其 AGENTS.md 归档。

| 规则 | 检查入口 |
| --- | --- |
| PR 关联 Issue、规格、任务与 FR 证据 | SDD Policy / sdd.py check、verify_issue.py |
| 三工具入口一致、官方来源固定 | SDD Tooling / sync-agents --check、verify_vendor.py |
| 暂存手写代码不超过 20,480 字节 | .githooks/pre-commit / check_code_size.py |
| 打包及既有离线行为可用 | Company Network Tests / README 验证入口 |
