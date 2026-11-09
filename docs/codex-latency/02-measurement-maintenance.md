# 统一采样与会话交接维护

采样工具已具备隔离运行入口；effort 速度建议、现场多轮验证和具体 413 恢复结果须由真实运行证据确认。工具不会修改默认模型、effort、用户聊天或认证配置。

## 使用入口

Python 3.11+，标准库。指定桌面实际使用的 codex.exe，避免混用编辑器扩展版本。`--workdir` 是已存在的调查临时父目录，工具只在其新建并删除本次临时夹具子目录；`--output` 的父目录也须存在。不要将工作目录指向业务目录。

```powershell
$codexBin = 'C:/Users/raime/AppData/Local/OpenAI/Codex/bin/5449c1f0f26f1f98/codex.exe'
$scratchRoot = 'D:/InternetOps/.scratch/codex-latency-remediation-20261109'
# 先验证一个工具/多轮case，再决定批量取样；不需要同时运行两条命令。
python tools/codex_latency.py --codex $codexBin --workdir $scratchRoot --output "$scratchRoot/multi-smoke.json" --task multi --efforts medium --pairs 1 --network company-lan
# 每个pair反转effort顺序；三类任务各5对，共30个独立thread、50轮。
python tools/codex_latency.py --codex $codexBin --workdir $scratchRoot --output "$scratchRoot/effort-screen.json" --efforts max medium --pairs 5 --network company-lan
# 5个独立短任务，用于协议配置对齐验收（还须关联传输日志）。
python tools/codex_latency.py --codex $codexBin --workdir $scratchRoot --output "$scratchRoot/protocol-smoke.json" --smoke --efforts max --pairs 5 --network company-lan
```

默认每轮180秒，初始化/开thread各30秒。返回码0要求所有已执行样本通过，1表示至少一个未验收；每个样本后重写完整脱敏JSON。Ctrl+C保留当前取消样本并结束后续计划，未执行的计划不计为已执行分母。进程强制终止/断电时最后进行中的样本可能未写入，应另标为运行中断，不能根据上次JSON声明全批通过。

调用已安装二进制 `app-server --stdio`，由其读取当前provider及现有认证；不读取/输出原始配置和凭据。固定 `gpt-6.1-sol`，仅 `turn/start.effort` 覆盖本次轮次；thread使用 `ephemeral=true`、`sandbox=read-only`、`approvalPolicy=never`。临时配置只追加 `model_providers.OpenAI.http_headers.X-Request-ID` 叶子键（公开sample UUID），不替换认证headers；当前公司provider为OpenAI，切换provider后先维护这个已知关联键。输出明确记录 `correlation_id` 和 `correlation_header=X-Request-ID`，该值是客户端提交候选，须在NAS访问日志 `request_id` 核对；usage表 `session_id=thread_id` 另提供会话连接。v0.2.20的client_request_id中间件不读取 `X-Client-Request-ID` 头，不能将此前同名字段当成服务端返回或可靠请求连接。必须核对覆盖生效、现有鉴权仍通过。

结果schema v2的 `provenance` 保存采样器版本、当前实际执行源码字节SHA-256及冻结任务manifest SHA-256。manifest是按键排序、无额外空白的UTF-8 JSON，内容为模型、全部任务prompt/预期值/工具要求和固定夹具；只输出哈希，不输出prompt。正式30case需在同一运行结果中核对这些哈希；prompt修正前的smoke仅证明RPC/工具/完成协议，不能作为修正后质量对照。源码哈希针对实际执行文件，Git换行转换可能改变字节哈希，应以运行报告中的值为准。

## 冻结任务和口径

| 任务 | 固定夹具和外部检查 |
| --- | --- |
| fixed | 完整回复必须恰为 `CODEX_LATENCY_OK`，含实际delta及正常终止。 |
| calculate | 动态工具读取本次临时 `numbers.txt` 的17、23、41；工具请求及内容核对成功，最终恰为 `SUM=81`。 |
| multi | 同一临时thread三轮：工具读取后 `FIRST=17`，引用上一轮结果 `SECOND=23`，最后 `SUM=81`；每轮均要求delta、终止和精确结果。 |

`read_fixture` 仅服务当前thread/turn、固定工具名及 `{"key":"numbers"}`；读取显式临时夹具并核对完整内容，不接受任意路径。固定task文本在源码公开，响应只在内存做质量断言，结果文件不保存正文。其他服务端请求（包括审批）立即拒绝并记录分类，避免等待UI造成死锁。

每轮首可见输出直接取第一个非空 `item/agentMessage/delta`；终止取对应 `turn/completed`，两者都以提交 `turn/start` 的单调时钟为起点。缺任一关键事件，标记未验收。完整文本 `item/completed` 仅用于质量检查，不能替代首可见事件。`elapsed_ms` 是任务第一轮提交前至最后轮完成/失败观察的同进程耗时，包含轮间调度，不含app-server初始化和清理；`initialization_ms`、`app_server_lifetime_ms` 单列。逐轮 `observed_elapsed_ms` 是本机观察停止点，不能冒充缺失的完成事件。

每个样本记录UUID/header关联、RPC请求号、thread/turn ID、UTC关联时间、模型、effort、已知网络位置、轮次用量及工具状态。真实上游request ID、网关semantic首事件、用户名额、账号槽位、传输协议无直接事件时留空及原因，不从首字倒推。`error.willRetry` 计数仅表示本地可观察重试信号；原始上游尝试数仍需网关记录。stderr仅统计已知类别，不落原文。HTTP错误只白名单保留错误类别/状态码，避免错误message携带正文或密钥。

所有执行样本进入task/effort分母，失败、超时、断流、取消、质量失败均保留；耗时描述统计仅针对正确完整样本并写出其n。每个pair保留两档是否均通过及medium减max差值，不能丢弃失败对后仅汇报成功。每组全部质量通过后才讨论该类速度差异；五对只支持中位数、范围等描述，无稳定P95或跨组因果承诺。每样本新app-server和thread、无预热；上游缓存未人为清空，按usage报告缓存输入token，不声称所有请求冷缓存。多轮上下文固定三轮；其他组不跨thread复用历史。

Windows使用本次子进程专属Job Object，关闭时连同其后代清理；若不能建立Job则拒绝采样。POSIX使用独立进程组。不会枚举或终止已有Codex会话。离线验证入口：

```powershell
python -m unittest discover -s tools -p test_codex_latency.py -v
```

测试含脱敏外部事件序列、重试/误序/同turn重复、漏终止/漏首字、失败分母、敏感字段过滤、断流/超时、审批拒绝、工具路径拒绝，以及真实本地假app-server子进程的管道与Job清理。它们不请求模型；现场采样与NAS关联是独立验收。

## 纯文本交接与413恢复

先只读关联已有413时间、thread/request标识和网关日志，记录归属置信度及正文来源类别（历史/图片/工具输出/未知）。无法明确对应的记录保留归属缺口。不要为复现向生产发送超大正文，不提高正文上限，不自动复制或删除任何原有用户聊天。

在原聊天中人工整理以下短交接，检查无凭据、无全量历史后，用户选定新聊天再粘贴。原聊天与证据留存不变。

```text
目标：当前要交付什么；完成的判据是什么。
已确认结论：只写有证据的事实与必要数字。
证据位置：本地文件或已有文档链接；说明哪一段支持结论。
有效约束：权限、不可改动对象、已批准范围、版本与运行条件。
未完成事项：按优先级列最多三项；标出当前阻塞。
下一步：第一项可执行动作，以及怎样核对结果。
```

新聊天先复述目标、有效约束和下一步，再完成原未完成目标中的一个可核对步骤；核对输出质量、正常流式结束和同时间窗口无413，并将新旧thread/request ID及证据链接写入原工单。工具不会创建/移动真实用户聊天。只有原失败记录已明确关联、同一目标恢复且无413，才能标记该会话恢复；无原会话同目标耗时基线时只声明可用性恢复，不声明加速。需要原会话基线时优先已有正常记录，禁止反复发送已知超限请求。
