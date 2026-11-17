# 公司网络 SDD 来源与适配

2026-11-17 从 `ACAurafly/XDance` 已提交主线 `f260db6aa3da21bfc9dbcc7fb47a06426f2ceecf` 移植通用 SDD。保留工具实现、测试、模板、三工具官方 skills、MIT 许可与上游 SHA256；没有复制 XDance 业务模块、模型或历史规格。

入口为 [CONTRIBUTING](https://github.com/ACAurafly/company-network/blob/main/CONTRIBUTING.md)，本次接入的规格为 [007-github-sdd](https://github.com/ACAurafly/company-network/blob/main/specs/007-github-sdd/spec.md)，工作登记为 [Issue #7](https://github.com/ACAurafly/company-network/issues/7)。完整治理文件保存在 GitHub，不随员工构建源码 ZIP 分发。

| 来源范围 | 公司网络适配 |
| --- | --- |
| tooling/sdd.py、verify_issue.py、verify_vendor.py、check_code_size.py | 保留四产物、PR 范围/证据门禁、三工具同步及代码体积检查；新增 current 供阶段读取显式 specs/ 选择，统一 Git 路径分隔符。 |
| .specify、官方 speckit-* skills、tooling/local_speckit | 官方 v1.1.2 清单保持原字节；自动工作流校验器独立固定 v1.2.5/4572a67fe0e72a6837e2d7bb0fda875bc41482e5。 |
| .specify/workflows/xdance | 改为 company-network，选择 Issue 对应 specs/ 并以 verification.md 验收。 |
| 团队 company-* skills、宪章、AGENTS、CONTRIBUTING | 改为公司网络的组件、凭据边界、员工交付与测试入口；三工具副本由 sync-agents 生成。 |
| Issue/PR 模板、SDD/Spec Kit CI、提交钩子 | 改为 bootstrap/tools/tooling/docs，保留 PR Issue、FR、路径检查和 Windows/Linux 工作流校验；增加员工客户端 Windows 离线 CI。 |
| tooling/local_sdd.py | 仅保留历史 .scratch 兼容，不用于新需求。 |

员工打包工具在原隐私检查之后跳过明确的仓库治理路径，未知文件仍要求审查。治理文件不进入员工源码包；公开仓库不包含构建载荷或员工个人配置。原交付 ZIP、哈希及历史验收不改。

本次初始化按用户直接授权部署；自动检查不代表最终人工评审。具体结果与边界见本次规格的 verification.md。
