---
name: company-sdd-delivery
description: Locate the company-network four-artifact lifecycle, PR checks, and review evidence when preparing a repository change for delivery.
---

# company-sdd-delivery

流程真源为 CONTRIBUTING.md 与 .specify/memory/constitution.md。
新工作从 GitHub Issue 创建：python tooling/sdd.py new <slug> --issue <number>。
设置 SPECIFY_FEATURE_DIRECTORY 后使用官方 speckit skills；现有目录复用参数见 CONTRIBUTING.md。
网络部署、员工交付与验证边界见 README.md 和相关维护记录；只读本任务相关入口。
交付前运行 python tooling/sdd.py check --spec specs/<id> --require-complete，并运行适用测试。
PR 使用 .github/pull_request_template.md；正文保留独立 Spec: 行。
输出需求→任务→证据映射和未完成项；只有实际完成的任务才能勾选。
