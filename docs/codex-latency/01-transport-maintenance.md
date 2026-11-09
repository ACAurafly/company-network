# Codex 客户端 HTTP 传输维护

2026-11-09：本机当前 `OpenAI` provider 已将 `supports_websockets` 从 `true` 改为 `false`。字节核对通过，原始配置其余字节（包括 BOM、换行、注释和认证字段）保持一致。真实请求是否直接使用 HTTP、五个新会话及至少三轮工具任务是否正常完成，仍由主验收记录确认。

## 操作

使用 Python 3.11 或更新版本，从仓库根目录运行。先关闭配置编辑器，避免其他进程同时保存配置；保留现有桌面进程，让独立新会话读取配置。修改前确认目标 provider、公司入口和管理员授权；本工具只支持显式 `[model_providers.<简单名称>]` 表及字面量布尔值，不支持的合法 TOML 写法会安全拒绝，不自动重排。

下面的公司入口为本次现场已核对值。维护其他设备时必须独立核对当前入口，不从命令示例推断。入口参数不得包含用户名、密码、查询参数或任何密钥。

```powershell
# 只验证并计算候选，不写文件。
python tools/codex_transport.py --config C:/Users/raime/.codex/config.toml --provider OpenAI --expected-base-url http://192.168.1.29:8080/v1
# 原值为 true 且所有检查通过时，备份后应用。
python tools/codex_transport.py --config C:/Users/raime/.codex/config.toml --provider OpenAI --expected-base-url http://192.168.1.29:8080/v1 --apply
```

工具核对顶层 `model_provider`、目标 provider 的 `base_url` 与当前 WS 值，解析修改后的完整 TOML 确认仅目标语义改变；实际写入只替换布尔值的字节。写入前再次核对现态并检查文件是否发生变化，以临时文件原子替换，写入后核对完整字节。操作期间仍应避免外部写配置；工具无法锁定其他应用的编辑器。

备份保存在进程实际 `%LOCALAPPDATA%/CodexPrivate` 中，要求这个受控目录预先存在。桌面应用的该环境变量可能指向应用包 LocalCache；以成功输出的 `private_backup` 为准。备份包含全部原始私有配置，禁止进入 Git、员工交付包或普通调查目录。JSON 输出只保留状态、时间、字段、哈希和私有备份位置，不输出配置、认证值或解析器原始报错；退出码 0 表示该操作完成，1 表示拒绝或错误。默认只验证，重复应用已为 false 的配置会拒绝，不能据此误判首次修改失败。

## 验证及回滚

```powershell
python -m unittest discover -s tools -p test_codex_transport.py -v
# 用本次成功输出的真实备份路径替换占位符。
python tools/codex_transport.py --config C:/Users/raime/.codex/config.toml --provider OpenAI --expected-base-url http://192.168.1.29:8080/v1 --rollback '<private_backup>'
```

五项测试覆盖 BOM/两种换行及其他 provider/合成认证字段保留、错误 provider/入口/当前值拒绝、多行字符串中的伪配置拒绝、后续编辑的回滚保护，以及真实文件备份和逐字节恢复。测试只使用合成配置。

回滚前校验当前 provider 与入口，且当前文件必须逐字节等于备份关闭 WS 后的结果；有后续编辑时拒绝自动恢复，维护者需先核对差异。成功回滚完整恢复原文件字节并保留私有备份；恢复后的真实认证、任务与流式完成仍须复测。此次没有为演示回滚而短暂恢复生产 WS。

本轮脱敏应用记录位于运维目录 `.scratch/codex-latency-remediation-20261109/transport-apply.json`，不进入 Git。SHA256 从 `58458c12a2a8de556e359997ab0353e84a8be2f3c00b6c0c987b64c99571b802` 变为 `511f32a9bb02fbad7bf70755365559648b016bf0e29577217005b0dc63087c6a`；只说明配置字节的状态，不代替业务完成证据。故障场景及业务验收要求见 [工单 01](issues/01-align-client-transport.md)。
