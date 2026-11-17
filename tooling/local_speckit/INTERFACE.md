# Local Spec Kit adapter
Python 阶段脚本的兼容适配；新工作入口见 [CONTRIBUTING](../../CONTRIBUTING.md)。
输入为显式 SPECIFY_FEATURE_DIRECTORY 和阶段参数，输出为规格路径、模板及前置检查结果，不以分支猜规格。
.specify/scripts/python/ 委托本目录阶段实现；来源固定于 docs/sdd-origin.md 所列 XDance 提交。完整上游文件及校验清单另见 tooling/vendor/spec-kit/。
tooling/local_sdd.py 仅兼容旧 .scratch 工作；公司新需求使用 GitHub Issue、tooling/sdd.py 与 specs/。
路径冲突、缺少前置文件或模板时返回错误；已有 spec/plan 不覆盖。定向维护时运行 tooling/tests/test_local_sdd.py。
