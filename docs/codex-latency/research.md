# Codex 回复慢：公开证据与可验证的改进

**公开资料支持优先区分“高推理投入”“WebSocket 重试与大请求上传”“网关排队和缓存路由”三类耗时。** `max` 适合最复杂任务，确有增加模型工作量的机制；sub2api 的 WebSocket、HTTP bridge 和账号调度也有已合并的相关修复。它们提供排查方向，实际主因仍需与本机请求时间线、NAS 运行版本对应。

研究截止：2026-11-09。仅查公开源码、官方文档和原发 issue/帖子；未访问私有凭据、用户日志或生产配置，未发起模型推理请求。主调查已确认本地服务源于 **Wei-Shaw/sub2api**；本报告不将本地默认配置视为每条活跃会话的实际配置。

## 最高价值的十条证据

1. **`max` 是最大推理投入，降低 effort 是有机制依据的对照实验。** OpenAI 官方将 `medium` 定位为延迟、效果和成本的平衡点，将 `xhigh` 用于收益足以抵偿额外延迟的任务，将 `max` 用于最复杂任务。Codex 配置参考也确认可用 effort 取决于模型和客户端。由此建议把日常执行任务的 `medium/high` 与 `max` 做同任务对照；官方资料没有给出固定加速倍数，也没有保证 NAS 上游接受或原样传递 `max`。资料核对于 2026-11-09。[官方 reasoning 指南](https://developers.openai.com/api/docs/guides/reasoning#reasoning-effort)、[Codex 配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)

2. **客户端 WebSocket 支持与网关上游 WebSocket 是两个独立环节。** Codex 上游源码在 provider 支持 WS 且会话尚未 fallback 时选择 WS；耗尽 provider 重试预算后切到 HTTP，并在该 session 禁用 WS。源码支持把 provider 的 `supports_websockets=false` 作为客户端侧对照方向，具体生效需按安装版本和新会话核验。核对版本：上游 main 于 2026-11-09 的 `8703d32`，并非本机安装版本。[WS 启用条件](https://github.com/openai/codex/blob/8703d32bd0ea5cf26768859a3dd476df906ba053/codex-rs/core/src/client.rs#L1329)、[fallback 行为](https://github.com/openai/codex/blob/8703d32bd0ea5cf26768859a3dd476df906ba053/codex-rs/core/src/client.rs#L2641)

3. **sub2api 官方提供代理出口不稳定时的上游 HTTP/SSE fallback。** README 明确推荐在出口代理反复断开 Responses WS 时配置 `gateway.openai_ws.force_http: true`，Compose 对应 `GATEWAY_OPENAI_WS_FORCE_HTTP=true`。该设置改变网关到上游的协议，客户端仍可连接 WS；它也不强制 HTTP/1.1。账号级 `http_bridge` 另需启用 mode router v2。部署传参修复于 2026-08-24 合并，适合“电脑→NAS→代理→上游”中后半段的对照实验。[官方说明](https://github.com/Wei-Shaw/sub2api/blob/ee58c0013c76ccd3f36439881bc848d342ec1c9d/README.md#L672)、[部署传参修复](https://github.com/Wei-Shaw/sub2api/commit/fb01f5df2cdf3ec0cc06a2fd93e046a10d7881a9)

4. **账号并发排队和 WS 重试可以直接增加首字等待。** 2026-11-09 上游配置示例包含 sticky 排队超时 `120s`、fallback 排队超时 `30s`，以及 WS 重试总预算 `5000ms`、120–2000ms 退避。它们是示例值，NAS 实际值待核对。故 ping 很快、NAS CPU 正常仍可能等待账号槽位；应检查排队、重试次数和账号选择耗时，再调整并发参数。[排队配置](https://github.com/Wei-Shaw/sub2api/blob/ee58c0013c76ccd3f36439881bc848d342ec1c9d/deploy/config.example.yaml#L581)、[WS 重试预算](https://github.com/Wei-Shaw/sub2api/blob/ee58c0013c76ccd3f36439881bc848d342ec1c9d/deploy/config.example.yaml#L425)

5. **短时并发溢出曾永久改变 sticky 账号，修复已合并。** PR #6164 说明：健康账号槽位和等待队列都满时，临时选择其他账号曾覆盖原绑定，导致后续会话迁移和缓存重新预热。2026-08-25 合并的修复保留原绑定，仅让当次请求溢出；PR 包含针对调度路径的回归测试。适用于多账号池且出现并发拥塞的部署，单账号池不能据此获得同样收益。[已合并 PR #6164](https://github.com/Wei-Shaw/sub2api/pull/6164)

6. **WS→HTTP bridge 的缓存身份修复刚于 2026-11-07 合并。** PR #8464 修正 OAuth、`store=false`、开启 Codex 指纹收敛时 bridge 未设置一致身份的问题。作者生产测量显示：不带 `prompt_cache_key` 的客户端在修复前多轮缓存为零，修复后恢复；但作者明确说明 Codex CLI 每次携带该 key，通常已避开“零缓存”症状，CLI 仍受跨路径身份不一致影响。应核对 NAS 是否包含合并提交 `a2f7c12`，而不是仅凭发布日期假定已修复。[已合并 PR #8464 与测试](https://github.com/Wei-Shaw/sub2api/pull/8464)

7. **后续轮次遇到 429 的自动换号需要正确恢复当前上下文。** 2026-08-19 合并的 PR #5845 为 `http_bridge` 实现后续轮次在输出前遇到 429 时换号，重建当前请求并保留工具上下文；对输出后失败、传输错误和 5xx 仍明确失败。另有 2026-11-04 事件报告指出 v0.2.19 的原生 WS 分支可能重放首条请求、丢失上下文；截至本次查询该报告无维护者评论，不能称为已确认修复。两种分支不能混为一谈。[已合并 PR #5845](https://github.com/Wei-Shaw/sub2api/pull/5845)、[原生 WS 用户报告 #8513](https://github.com/Wei-Shaw/sub2api/issues/8513)

8. **代理链和长图像历史可同时造成 WS 重试与 HTTP fallback 长时间等待。** openai/codex #56913 于 2026-10-25 发布：作者提供 Desktop 26.1021.31345/core 0.164.0 的脱敏日志，Clash/Mihomo→VPS→WARP 环境中，WS 五次重试后 fallback，约 28.9MB 压缩 HTTP 请求过八分钟恢复；随后约 38.7MB 请求出现约十五分钟超时。这是用户日志自述，上传、代理和后端等待未分离；它支持检查请求字节数、重试及上传时间，无法证明本公司出口存在同样问题。[原始 issue #56913](https://github.com/openai/codex/issues/56913)

9. **缓存命中很高和已经压缩，都不能保证长会话首字快。** openai/codex #52555 于 2026-10-09 发布：Windows 用户自述同模型 medium、零工具、零 reasoning token 的测试，长会话首字 `42.330s`，新会话 `2.924s`；长会话输入缓存命中 `99.73%`，累计 80 次压缩。该观察支持用新会话做对照，根因仍未确定。官方缓存文档同时说明：前缀、工具定义和部分设置影响复用，压缩会改变前缀；同账号 sticky 和缓存命中应分别检查。[原始 issue #52555](https://github.com/openai/codex/issues/52555)、[官方缓存文档](https://developers.openai.com/api/docs/guides/prompt-caching)

10. **VPN 下 MCP 的慢或失败，有可核查的 DNS 个案，适用条件明确。** openai/codex #58286 于 2026-10-30 发布：Debian 13/Barracuda VPN 合并本地与 VPN DNS 后，内部 HTTP MCP 域名收到抢先的 NXDOMAIN，作者表示加 hosts 映射并重启恢复，增加初始化宽限时间无效。该案例的 DNS 流量和 workaround 是作者自述，未证明 Windows 或其他 VPN 相同；仅在内部 MCP 域名与混合 DNS 条件具备时值得跟进。它不能解释所有纯模型回复等待。[原始 issue #58286](https://github.com/openai/codex/issues/58286)

## 社区经验应怎样使用

Reddit 原发帖作者在 2026-11-09 页面显示约 28 天前，自述十个 rollout 中部分流速从约 40–45 降至 8–15 token/s，切换新 WebSocket 和路由后恢复；作者也承认无法区分连接本身与后端路由状态，并把潜在节省时间标为估算。这适合提出“新会话或重连对照”的假设，不能据此为公司部署增加自动断线逻辑。帖子缺少本次可确认的绝对发布日期。[原帖与作者方法](https://www.reddit.com/r/codex/comments/1wxqhtx/codex_has_a_huge_toks_problem_in_longer_sessions/)

sub2api #2208 于 2026-05-05 报告 v0.1.119→v0.1.122 后，在 gpt-5.5/xhigh/HTTP 路径出现 200–600 秒和大量 reasoning/output token；作者怀疑丢弃 reasoning item 及 fast 策略过滤。该报告没有维护者根因确认，现行版本是否继承这些行为需查源码和最终请求，不能把历史建议直接当当前修复。[原始 issue #2208](https://github.com/Wei-Shaw/sub2api/issues/2208)

## 对公司链路最有用的三步

1. **先确认每条慢请求的实际 model、effort、传输和耗时阶段。** 同时记录客户端发出请求、网关入站/排队/上游首事件、客户端首可见输出和完成时间；保留重试次数、请求字节数、账号切换及 cached/reasoning token 的汇总。SSE/WS 建连成功只证明连接建立，不能代替模型首字指标。
2. **做两个独立且可恢复的对照。** 对日常任务比较 `max` 与 `medium/high`；出现重连时分别比较客户端→NAS 的 WS 与 HTTP、NAS→上游的 WS 与 `force_http`。每次只改变一个因素，保持模型、同类任务和出口一致；对照请求可能消耗订阅或 API 额度，应由主调查按已授权范围执行。
3. **核对 NAS 的镜像 digest、版本和有效配置，再安排升级或调度调整。** 对照 #6164、#5845、#8464 的合并提交；若等待发生在账号槽位，优化账号容量与队列；若发生在大请求上传或 WS 重试，处理出口和 transport；若新会话明显恢复，先做简短交接再开新会话。缓存优化收益应以真实请求统计确认。

版本边界：本次源码截面为 sub2api `ee58c001`、Codex `8703d32`，均为 2026-11-09 main；未把它们当作稳定发布版，也未验证 NAS 包含哪些提交。公开资料足以确认机制与历史修复，无法单独给出本公司的根因或加速比例。MCP/技能的普遍性性能开销未找到足够强的一手对照证据，因此本报告不建议批量禁用技能或插件。

审校记录：完成事实与版本核对、三轮自检，分别删除重复结论、明确观察与推断、检查适用条件及中文表达；按本子任务约束未递归派发审读。

## 补充：按现场运行版本 v0.2.20 核对

**v0.2.20 源码足以解释“客户端尝试 WS、唯一 OAuth 账号关闭 WS、五次失败后 HTTP 成功”的现场现象；账号 `mode=off` 不会自动成为 `http_bridge`。** 本节以发布标签固定源码；现场版本由主调查提供的 `/api/v1/settings/public.version=0.2.20` 确认。Docker 镜像标签因存在 update-runtime 挂载，不能代表当前二进制版本。

- **WS 入口要求与账号模式。** `ResponsesWebSocket` 路径设置 `requiredTransport=ResponsesWebsocketV2Ingress`，随后调用 `SelectAccountWithSchedulerForCapability`。`isOpenAIAccountTransportCompatible` 在 mode router v2 开启时仅允许 `ctx_pool/passthrough/http_bridge/shared/dedicated`，`off` 返回 false；router 关闭时以 resolver 的 WSv2 结果判断，而 `enabled=false` 使 resolver 返回 HTTP 的 `account_disabled`。`ResolveOpenAIResponsesWebSocketV2Mode` 优先读 OAuth mode，再读 enabled，false 映射 off。故两种 router 状态下均不能把现场 off 账号作为普通 OpenAI WS 入口的可用账号；需明确选择 `http_bridge` 才具备该入口兼容性。即便绕过选号进入 forwarder，off 分支也返回 policy violation。[入口要求](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/handler/openai_gateway_handler.go#L2712)、[选号调用与失败](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/handler/openai_gateway_handler.go#L2844)、[兼容性函数](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/service/openai_account_scheduler.go#L2536)、[mode/enabled 解析](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/service/account.go#L2282)、[resolver](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/service/openai_ws_protocol_resolver.go#L70)、[forwarder 的 off 分支](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/service/openai_ws_forwarder_ingress.go#L120)

- **`filtered: excluded=1` 与上述原因相容。** 高级调度直接记录 `transport_incompatible`；legacy 调度则先选出账号，发现 transport 不兼容后释放槽位、加入内部 `effectiveExcludedIDs`，再次选号时便可能得到 `excluded=1`。因此该日志与外层 `excluded_account_count=0` 可以同时成立；单独看到 excluded 仍不能跳过账号配置和调用分支的核对。[高级过滤](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/service/openai_account_scheduler.go#L1438)、[legacy 重选循环](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/service/openai_account_scheduler.go#L2448)

- **`usage_logs.first_token_ms` 有 semantic 与 visible 两种口径，代码默认 semantic。** semantic 跳过 `response.created/queued/in_progress/metadata/keepalive` 后，以首个语义 SSE 事件计时，可能包括尚无文字的 output-item 事件；visible 要求非空 delta、文本、工具参数或其他可用内容。因此它既非首个任意 SSE 事件，也不一定是屏幕首个文字 token。HTTP 普通流与 passthrough 流均调用相同分类器，最终将 `FirstTokenMs` 写入 usage。实际统计口径由运行时设置决定，尚待现场读取。[metadata 列表](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/service/openai_gateway_passthrough.go#L1051)、[visible 定义](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/service/openai_gateway_passthrough.go#L1192)、[semantic 与默认值](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/service/openai_gateway_passthrough.go#L1235)、[普通 HTTP 计时](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/service/openai_gateway_response_handling.go#L739)、[passthrough 计时](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/service/openai_gateway_passthrough.go#L2166)

- **本次成功 HTTP 请求的 first_token_ms 与 duration_ms 均不是客户端全程耗时。** handler 先读取入站 body、选号并获取账号槽位，再调用 `Forward`；`Forward` 内第 41 行创建 `startTime`。HTTP first-token 以它为起点；duration 在流处理完成并构造结果时取 `time.Since(startTime)`，再由 `RecordUsage` 原样写库。这包含该次 Forward 内的请求处理、建立上游连接、发送和等待/读取上游响应等，排除入站上传、前置调度/槽位排队和此前独立失败的 WS 请求。Forward 内早于 startTime 的少量预处理亦不计入。由此不能用成功 usage 的 TTFT 去否定客户端之前的重试等待。[读入站 body](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/handler/openai_gateway_handler.go#L424)、[先抢槽位再 Forward](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/handler/openai_gateway_handler.go#L782)、[计时起点](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/service/openai_gateway_forward.go#L41)、[普通 HTTP duration](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/service/openai_gateway_forward.go#L1353)、[passthrough duration](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/service/openai_gateway_passthrough.go#L532)、[usage 写入](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/service/openai_gateway_usage.go#L339)

- **usage 的 input_tokens 已扣除缓存读取和缓存写入。** `RecordUsage` 计算 `actualInputTokens=max(上游input_tokens-cache_read-cache_creation,0)`，并将其存入 `usage_logs.InputTokens`；cache read 与 cache creation 分列。对正常 OpenAI 记录，重建总输入应加回这两列，缓存命中率的分母也应包含它们。不要把 `cache_read/input_tokens` 当作总输入缓存比例。[互斥 token 桶](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/service/openai_gateway_usage.go#L180)、[日志字段赋值](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/service/openai_gateway_usage.go#L402)

- **64MB 的确切值是 `64<<20`，即 64MiB 解压后上限。** HTTP body 先受网关 `MaxBodySize` 的 `MaxBytesReader` 限制；带 zstd/gzip/deflate 的 body 解压时还受 64MiB 上限限制，读取上限加一字节，发现超限即释放缓冲并返回 `http.MaxBytesError`，不会把截断内容继续转发。错误分类映射 HTTP 413，handler 格式化为 `Request body too large, limit is 64MB`。未压缩/归一化 JSON 另受有效 `Gateway.MaxBodySize` 限制；zstd decoder 自身还限定 8MiB window 和 64MiB memory，decoder 错误与显式超限应按实际日志区分。该限制在完整入站 body 读取/解压阶段，早于上面的 Forward 计时，失败请求通常没有成功 usage。[HTTP 长度限制](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/server/middleware/request_body_limit.go#L11)、[解压与超限检查](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/pkg/httputil/body.go#L233)、[归一化 JSON 上限](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/pkg/httputil/body.go#L285)、[413 分类](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/pkg/httputil/body_read_error.go#L85)、[handler 消息](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/handler/request_body_read_log.go#L17)

据此，当前最小改动方向是让客户端能力声明与网关账号能力一致，先验证关闭客户端 WS 后能否消除五次重试。若需要保留客户端 WS，则应明确配置并验证账号的 `http_bridge`，同时核对 mode router v2；仅维持 off 或改全局上游 HTTP 开关不能等同完成该兼容配置。任何修改仍由主调查按现场证据和授权执行。

**TTFT 配置位置已进一步核实：`openai_ttft_mode` 是数据库中的系统设置，不是 `config.yaml` 的 gateway/server 字段。** `SettingKeyOpenAITTFTMode="openai_ttft_mode"`；运行时通过 `settingRepo.GetMultiple` 读取并缓存 60 秒。`normalizeOpenAITTFTMode` 仅识别 visible，其余值（包括未设置）都返回 semantic；数据库读取失败也显式回退 semantic。管理后台“网关转发行为”中的“OpenAI Responses 首 token 统计口径”对应此字段，可在管理设置 API 响应的 `openai_ttft_mode` 或系统设置表同名 key 中只读核对。[key 定义](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/service/domain_constants.go#L666)、[数据库读取及失败回退](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/service/setting_gateway_runtime.go#L901)、[空值默认 semantic](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/service/setting_parse.go#L1005)、[后台设置返回](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/handler/admin/setting_handler.go#L292)

v0.2.20 的该读取链没有环境变量分支，`config.go` 也没有 `openai_ttft_mode` 配置项；因此没有本次源码支持的 TTFT mode 环境变量名。`GATEWAY_*TTFT*` 中的调度权重或 sticky-escape 阈值服务于选号，不改变 usage 的 first_token_ms 口径。仅检查 `gateway={}`、`server={}` 或 `GATEWAY_OPENAI_WS_*` 环境变量，仍不能确定此数据库设置的当前值。[运行时读取链](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/service/setting_gateway_runtime.go#L984)、[配置结构](https://github.com/Wei-Shaw/sub2api/blob/v0.2.20/backend/internal/config/config.go#L1433)
