# 网络诊断与可评审候选规则

这些工具不会连接 VPN、清 DNS/Fake-IP 缓存或修改代理。网络探测会主动发起明确指定的 HTTPS GET；网关工具只写新候选文件，不覆盖源配置。

## Windows HTTPS 对照

使用 Python 3 标准库及 Windows 自带 `curl.exe`，无需安装依赖：

```powershell
python tools/network_probe.py --output build/before.json --feishu-root https://YOUR-TENANT.feishu.cn/
python tools/network_probe.py --output build/after.json --feishu-root https://YOUR-TENANT.feishu.cn/
python tools/network_probe.py --compare build/before.json build/after.json
python -m unittest discover -s tools -p test_network_tools.py -v
```

每个固定目标默认 20 次冷请求、20 次热请求。Google 固定为 `https://www.google.com/generate_204`；飞书只允许用户提供的 HTTPS 根路径，不接受用户名、密码、查询、片段或文档路径。使用相同租户、设备、账号、网络、代理/TUN 状态及相近时段保存旧/新结果。`--count 2` 仅用于短样本验证，少于 20 的组不通过性能门槛。

冷请求分别启动 curl 进程，使用 fresh-connect 和 no-sessionid；热请求在同一个 curl 进程内先预热，再通过 `--next` 保留连接缓存。每次传输记录 `num_connects`、local_ip、remote_ip 和连接复用事实。实际复用连接的 DNS、TCP、TLS、HTTPS 就绪时间为 null，热请求比较发起到首字节的耗时。OS 和上游 DNS 缓存未清理、命中状态未控制，因此不能称为 DNS 冷启动。

DNS、TCP、TLS 分段来自 curl 累积时间之差；HTTPS 就绪是 time_appconnect，首字节是 time_starttransfer。输出保留每次失败、curl 原生退出码、HTTP 状态、总耗时。自动重试明确关闭（retry_count=0）；失败不会被悄悄重试后用最后一次成功覆盖。缺失输出、超时或无法启动也保留占位失败样本。失败样本中的阶段零值不代表阶段已完成，以 timing_valid 为准。分位数列明有效测量数，保留完整失败率；任一失败均阻止性能门槛通过。

比较按每目标、每冷热组报告。冷 HTTPS 就绪 p95 降低至少 30%、热首字节 p95 劣化不超过 10%、两侧每组至少 20 样本且全部成功，才满足工具计算的数值门槛；同环境和缓存条件仍须人工核实。Google 204 或飞书根路径 302 仅表示这些网络请求结果，不能替代飞书登录、消息同步或授权文档及其图片加载验收。

不导出 curl 原始错误消息、请求/响应头、正文、有效跳转 URL。结果中的 URL 仅为以上预先验证的固定目标。首次生产取样前可检查 `curl.exe --version`：本工具依赖 `%{json}` write-out；不支持时会保留解析失败样本，不能将该组视为通过。

## 精确域名 DIRECT 候选

已证实 VPN Azure 外层入口被网关 MATCH 规则送入海外代理。候选工具仅将以下规则放在两个配置各自 `rules` 列表最前：

```text
DOMAIN,office-trial-2dd76438.vpnazure.net,DIRECT
```

把活动配置和持久 gateway-tail 的私有副本交给工具：

```powershell
python tools/gateway_policy.py --active private/config.yaml --tail private/gateway-tail.yaml --output-dir private/candidates
```

输出为 `config.candidate.yaml`、`gateway-tail.candidate.yaml` 及两侧源/候选 SHA256。终端仅打印规则与摘要，不打印 secret、节点账号、引用或原配置。候选保留源文件全部其余配置，仍可能含凭据，应留在原有受限管理目录；不要提交或粘贴到报告。工具支持顶层块式 rules，支持 CRLF/LF、带引号规则和 rules 后其他顶层块；遇到同域冲突规则或不支持语法会拒绝。候选目标须不存在；再次生成用新目录。对候选内容重复计算保持幂等。

实际部署由管理员单独执行：先对活动 config 与持久 gateway-tail 分别保存可恢复备份并记录 hash，再用运行中的同版本 `mihomo -t -f config.candidate.yaml` 校验。gateway-tail 是持久片段时，应按现有拼装流程生成完整配置，并对完整配置执行同样校验。校验通过后先更新持久片段和活动配置，再通过现有受认证的管理入口热加载。保留原有 secret、节点及引用，不在命令行打印认证信息。

热加载后确认该精确入口命中 DIRECT，重新建立本次测试 VPN，以相同目标获取新样本；连接缓存中的旧连接不会因加规则自动变成新路径。不清共享 Fake-IP/DNS 缓存，不扩大为整个 vpnazure.net 域，不修改证书固定或个人认证。验证失败时同时还原两份备份、重新校验并热加载；复核活动与持久配置的 hash 和回滚结果。

## 客户端诊断与窗口边界

主窗口“导出诊断”通过保存对话框写本地 JSON，不自动发送。文件含版本、UTC/本地时间、最近 256 条进程内单调时钟状态/阶段/错误码、双层会话及路由摘要、接口/DNS、只读 IPv4/IPv6 路由、当前用户代理和已运行网络软件进程名。TUN 名称推断与进程存在不等于发生冲突；系统代理摘要不代表所有应用自有代理。文件明确区分 VPN 就绪与业务未验收。

采集使用后台独立读取，不持有操作门，不阻塞取消/断开。每个信息源独立失败；不保存原始会话输出、命令行、登录身份、密码、认证头、Cookie 或文档正文。最终 JSON 经过字符串/字段脱敏，URL 仅保留 origin，移除路径、查询、userinfo 和片段，JWT 被移除。接口和 IP 信息仍属于诊断数据，应按公司故障资料流程处理。

主窗口 X/Alt+F4 直接关闭并释放窗口，与 VPN 连接、断开和后台操作独立，不弹确认、不等待状态查询。后台 ClientHost 保留托盘、单实例找回和操作；桌面或托盘会创建新窗口。主动最小化仍可收起。托盘“断开并退出”是单独的明确操作，只在确认断开后退出后台；断开失败保留控制能力。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File bootstrap/Test-Diagnostics.ps1
```

测试使用替身会话与隐藏窗口，不操作真实 VPN 或当前用户桌面快捷方式。原生系统关闭命令覆盖 unknown、连接中、已连接、查询中、断开失败后的真实窗口释放与重建。飞书 60 分钟消息、授权文档/图片、公司外网络、真实 Chrome 非客户端 X 与桌面/托盘重开仍需现场验收。
