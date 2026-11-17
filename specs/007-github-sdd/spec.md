---
id: 007-github-sdd
issue: 7
owner: ACAurafly
status: verified
paths: [AGENTS.md, CLAUDE.md, CONTRIBUTING.md, README.md, .gitignore, .gitattributes, .agents/**, .claude/**, .github/**, .githooks/**, .specify/**, tooling/**, tools/package_release.py, tools/test_release_sources.py, tools/test_codex_transport.py, bootstrap/Test-Lifecycle.ps1, docs/sdd-origin.md, docs/agents/issue-tracker.md]
---
# Feature Specification: 007-github-sdd

## User Scenarios & Testing
用户要求公司网络拥有公开 GitHub 云端仓库并复制 XDance SDD。已有私有 ACAurafly/company-network；复用历史和默认分支，避免重复仓库。后续维护者可从 Issue 创建同编号规格，使用三种 AI 工具协作并通过 PR 验收。

## Requirements
- **FR-001**: 现有仓库设为 public，历史及新增内容经过凭据扫描，匿名读取成功；身份保持 ACAurafly。
- **FR-002**: 从固定 XDance 提交复制完整四产物 SDD、Spec Kit 三工具入口和来源校验；阶段工作流指向当前公司网络规格。
- **FR-003**: PR 门禁检查真实 Issue、spec.paths、任务和 FR 证据；草稿与正式评审要求明确区分。
- **FR-004**: 新治理目录不阻断员工打包，不进入员工源码包；未知或私密跟踪文件继续拒绝；既有离线测试通过。
- **FR-005**: GitHub Actions 在 Windows/Linux 实测 SDD 与员工客户端检查，维护入口和验证记录可追溯。

## Success Criteria
五项 FR 均提供命令或线上证据。仅公开源码，不上传运维目录、载荷、凭据或历史发布包。未进行新的生产网络变更或员工实机分发。

## Clarifications
2026-11-17 用户本轮直接授权部署和 public。首次流程接入属于该部署授权；最终人工评审单独标为未代签，不将自动检查当成人工批准。
