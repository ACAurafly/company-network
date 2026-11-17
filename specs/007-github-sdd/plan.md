# Implementation Plan: 007-github-sdd

## Summary
复用 ACAurafly/company-network，以 XDance 固定提交的治理基础设施为源；在隔离 checkout 适配后通过 PR 验证，再按本轮部署授权同步 main 并公开。

## Technical Context
Python >=3.11、PyYAML/jsonschema；固定 Spec Kit skills v1.1.2，工作流校验器 v1.2.5。SDD 的 new/check/sync-agents 沿用来源，新增 current 将显式规格交给自动阶段；保留旧 local_sdd 的历史兼容。无公司业务模块或生产配置迁移。

## Constitution Check
新流程覆盖 Issue、四份产物、任务/FR 追溯和人工评审记录。凭据及私密载荷不进入仓库；旧发布与现场记录不改。用户已授权本次初始化部署，AI 不代签最终人工批准。

## Project Structure
新增根贡献指南、AGENTS、三工具入口、.specify、.github、.githooks、tooling；tools/package_release.py 仅增加治理文件跳过规则，已有隐私拒绝先执行。docs/sdd-origin.md 锁定来源；README 导航更新。

英文 Windows CI 使用 pwsh 读取 UTF-8 脚本；生命周期套件可显式传入 UTF-8 测试进程 manifest，使中文快捷方式在已声明的代码页下执行。生产英文系统兼容性单独保留调查。

## Verification and Rollout
先运行 SDD/Spec Kit、运维工具和四个 Windows 离线套件；用真实 Git 暂存文件验证源码包筛选。Gitleaks 扫描全部历史及新文件，检查匿名读取及 GitHub Actions。部署不改生产网络；回退代码可撤销本次提交，公开可见性是用户指定结果。最终人工评审如实标为待评审。
