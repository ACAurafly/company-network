# 公司网络研发流程

所有新代码、文档、配置、prompt、skill 和 CI 使用从 XDance 移植的完整 SDD。[来源记录](docs/sdd-origin.md)说明固定提交及适配。历史交付、维护记录和已完成规格保持原文。

## 环境与初始化
Python >=3.11、Git；员工客户端另需 Windows x64 和 .NET Framework 4.8 编译器。

```bash
python -m pip install -r tooling/requirements.txt
python tooling/sdd.py doctor
```

官方 Spec Kit v1.1.2 三工具 skills、脚本和 MIT 许可已入库。Codex 用 `$speckit-specify` 等 `$speckit-*`；Claude Code/Copilot 用 `/speckit-specify` 等 `/speckit-*`。自动工作流校验器独立固定为 v1.2.5，见 tooling/requirements-speckit.txt。不要在根目录运行 init --force 覆盖公司模板。

每个 checkout 检查已有 hooks 后启用提交检查；已有自定义钩子先整合：

```bash
git config --get core.hooksPath
git config --local core.hooksPath .githooks
```

钩子检查暂存手写源码（含测试），单文件上限 20,480 字节，超限按功能拆分。文档、二进制、第三方和明确生成文件不计；来源标记见 .gitattributes。存量检查用 `python tooling/check_code_size.py --all`；无关历史文件不随本次变更重构。

## 一次变更
1. 在 ACAurafly/company-network 创建或关联 Issue，写目标、负责人、影响范围、验收和进行中状态。一个交付对应一个规格目录，内部步骤放 tasks.md。
2. 创建分支及四份产物：

```bash
git switch -c spec/007-example
python tooling/sdd.py new example --issue 7
```

PowerShell 设置 `$env:SPECIFY_FEATURE_DIRECTORY = "specs/007-example"`；Bash 设置 `export SPECIFY_FEATURE_DIRECTORY=specs/007-example`。编号取 Issue 号。官方脚本复用同目录时传 `--allow-existing-branch --number 7 --short-name example`，核对路径，不覆盖已有文件。

3. **Specify / clarify**：明确场景、FR 编号、成功与失败行为，消除影响实现的歧义。
4. **Plan / checklist**：记录组件、接口、兼容性、验证，以及生产部署与回退。配置和协议保持单一真源。
5. **Tasks / analyze**：用 T 编号、依赖及 FR 关联拆分任务，核对规格、方案和任务一致性。
6. **Implement / converge**：按任务实现并验证；范围改变先更新 spec/plan。只勾选实际完成的任务。
7. **Verification**：每个 FR 记录命令、结果、环境/提交、证据链接和限制。Result 使用 passed、verified 或说明原因的 not-applicable；pending/failed/blocked 不通过正式评审门禁。
8. **Review / delivery**：草稿 PR 用于需求和方案评审；正式评审前通过完整门禁。正文独立一行 `Spec: specs/007-example`。需求/方案确认和最终人工批准分别记录，AI 不代签。

自动阶段串联见 .specify/workflows/company-network/workflow.yml；`python tooling/sdd.py current` 回读当前规格。feature 独立于分支，.specify/feature.json 仅本机使用，不提交。并行工作使用独立 checkout。

## 适用检查

```bash
python tooling/sdd.py check --spec specs/007-example --require-complete
python tooling/sdd.py sync-agents --check
python tooling/verify_vendor.py
python -m unittest discover -s tooling/tests -v
python -m unittest discover -s tools -p "test_*.py" -v
```

自动工作流完整校验需 `python -m pip install -r tooling/requirements-speckit.txt`；未安装明确 skip，CI 在 Windows/Linux 安装并检查。员工程序四个 PowerShell 测试及打包命令见 README。SDD CI 验证真实 Issue、spec.paths 覆盖改动、任务及 FR 证据；员工客户端 CI 运行 Windows 离线回归。

离线检查不代替员工实机或生产业务验收。员工打包不包含治理文件；源码允许范围继续拒绝未知文件和私密配置。公开仓库不包含载荷、员工包或凭据。

## 历史与后续维护
新工作用 GitHub Issue；docs/issues/ 与 docs/codex-latency/issues/ 保留原状态。旧 .scratch 调查按 [历史入口](docs/agents/issue-tracker.md) 接续；tooling/local_sdd.py 仅作历史兼容。
团队 skills 真源为 tooling/skills/，修改后运行 sync-agents。完成规格保留历史，后续演进另建规格并引用原记录。提交与 GitHub 写操作一律使用 ACAurafly。
