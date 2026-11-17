# Verification: 007-github-sdd

## Evidence
| Requirement | Evidence | Result |
|---|---|---|
| FR-001 | ACAurafly 身份已核实；Gitleaks 8.30.1 扫描全部远端分支历史 21 提交和候选文件，0 泄露；REST 无认证请求返回 private=false、visibility=public，禁用凭据助手的 git ls-remote 成功。 | passed |
| FR-002 | Windows/Python 3.12：tooling/tests 57 项通过、0 skip（含官方 v1.2.5 工作流校验）；sync-agents --check 8 文件一致；verify_vendor 验证 v1.1.2 的 54 个官方文件。来源见 docs/sdd-origin.md。 | passed |
| FR-003 | PR #8 的 [SDD Policy/Tooling](https://github.com/ACAurafly/company-network/actions/runs/44013668193) 已通过，含真实 Issue #7、范围覆盖及三工具检查；本地 check --require-complete 通过，失败/不完整规格的拒绝由 tooling/tests 覆盖。 | passed |
| FR-004 | tools 全套 56 项通过；Core 19 / Adapter 5 / Lifecycle 16 / Diagnostics 36 均通过；使用既有 1.3 测试 EXE 和显式载荷实际打包，60 源码/4 员工条目、资源/CRC/SHA256 全通过。仅验证打包兼容，未新建员工业务验收。 | passed |
| FR-005 | 提交 05267e9 的 [员工 CI](https://github.com/ACAurafly/company-network/actions/runs/44013667567) 76 + 56 项通过；[Spec Kit Windows/Linux](https://github.com/ACAurafly/company-network/actions/runs/44013667531) 各 15 项通过；[SDD](https://github.com/ACAurafly/company-network/actions/runs/44013668193) 两项检查通过。员工 CI 显式声明 pwsh/UTF-8 测试进程，临时路径先 resolve 再核对归属。 | passed |

Result: passed、verified，或注明理由的 not-applicable；其余状态不可交付。

## Open Items
自动验证已完成；最终人工评审待人工处理，未由 AI 代签。本轮无新的生产网络变更或员工分发。最终 PR/主线复核结果另存运维工作目录 artifacts/company-network-sdd-20261117/report.md。

英文 Windows 生产进程的中文 WScript 快捷方式已出现代码页限制；CI 使用显式 UTF-8 测试进程，这项结果不视为生产英文代码页兼容性验收。
