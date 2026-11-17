# Spec Kit v1.1.2

上游：https://github.com/github/spec-kit/tree/v1.1.2；MIT 许可见 LICENSE。
由固定 tag 的 specify init 与 integration install 生成，脚本选 py；Copilot 多工具共存安装在临时目录显式使用 --force 后审查复制。
manifest.json 登记未修改的官方脚本、skills、集成状态和工作流的 SHA256。公司改写的 spec/plan/tasks 模板与 constitution 不属于上游完整性清单。
公司团队 skills 的真源在 tooling/skills/，与官方 speckit-* skills 分开命名。

```bash
python tooling/verify_vendor.py
```

升级先在临时目录生成三套入口，审查上游变化与本地模板兼容性，再更新版本、manifest 和本文档；运行完整工具及现有业务检查。不要直接在仓库根运行 init --force 覆盖公司规范。
