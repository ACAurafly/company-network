# 公司内外 Codex 配对验收

比较工具和离线验证已完成；当前没有公司外真实设备样本，远程 Codex 业务仍为 `not_accepted`。协议对齐已由工单 01 修正，公司内采样可复用工单 02 的统一适配器；这些成果不表示远程问题已经修复。

`tools/codex_vpn_acceptance.py` 使用 Python 3.11+ 标准库，只读本地 JSON，不发网络或模型请求，不连接/断开 VPN、不切换 Wi-Fi、不改路由。它比较 `codex_latency.py` 原始报告中的每个 task/effort/pair，保留失败与可观察重试分母；不信任原报告汇总成功数。缺首可见事件、正常终止、质量或完整轮次的样本不参与正确完成耗时比较。正式可比输入为当前采样器的 schema 2：两侧 `provenance` 的采样器版本、源码 SHA256、任务 manifest SHA256 和 fixture SHA256 必须完整且一致；任务 manifest 与 fixture 还须匹配本比较器使用的当前固定任务。历史 schema 1、混合版本或未知版本仅保留描述统计，状态为 `not_accepted`，配对差值为空；重新取样后再验收，不能手工把 schema 数字改成 2。

## 准备与取样

输出保存在本次调查目录，使用新的文件名，保留原始采样报告与诊断原文。以下命令由负责现场设备的维护者执行；本次实现只运行离线测试。

```powershell
$codexBin = 'C:/Users/raime/AppData/Local/OpenAI/Codex/bin/5449c1f0f26f1f98/codex.exe'
$screenRoot = 'D:/InternetOps/.scratch/codex-vpn-acceptance-20261109'
New-Item -ItemType Directory -Force $screenRoot
& $codexBin --version
python tools/codex_vpn_acceptance.py --help
python -m unittest discover -s tools -p test_codex_vpn_acceptance.py -v
```

优先同设备、同账号、同 provider/海外出口，版本、模型、effort、固定任务和工具一致。维护者确认设备处于公司 Wi-Fi 后采一侧；在独立外部网络（例如本人测试设备蜂窝热点）上按既有客户端正常连接双层 VPN 后采另一侧。仅操作专用测试连接，不抢占员工会话。每对起始时间相隔不超过 15 分钟，尽量交错五对。工具不会替维护者执行网络切换。固定短任务先做筛查，若要验证工具/多轮，再分别以相同 `calculate` / `multi` 任务做五对。

```powershell
# 例：第1对。公司侧与外部侧命令分别在上述对应真实环境执行。
python tools/codex_latency.py --codex $codexBin --workdir $screenRoot --output "$screenRoot/lan-1.json" --task fixed --efforts max --pairs 1 --network company-lan
python tools/codex_latency.py --codex $codexBin --workdir $screenRoot --output "$screenRoot/vpn-1.json" --task fixed --efforts max --pairs 1 --network external-vpn
# 重复到 lan-5.json / vpn-5.json；每对编号与现场记录保持一致。
```

合并五个 `--pairs 1` 报告时仅将 pair 改为对应配对编号，保留 sample UUID、时间、失败及重试。以下离线命令同时拒绝跨 schema、采样源码、固定任务、运行版本和模型合并，原文件不修改：

```powershell
function Merge-Screen([string]$side) {
    $combined = $null
    $rows = @()
    foreach ($pairNo in 1..5) {
        $part = Get-Content -Raw "$screenRoot/$side-$pairNo.json" | ConvertFrom-Json
        if ($null -eq $combined) { $combined = $part }
        if ($part.schema_version -ne 2 -or $part.schema_version -ne $combined.schema_version) { throw 'current sampler schema 2 required' }
        if ($part.runtime_version -ne $combined.runtime_version -or $part.model -ne $combined.model) { throw 'runtime/model changed' }
        foreach ($field in @('sampler_version','source_sha256','task_manifest_sha256','fixture_sha256')) {
            if (-not $part.provenance.$field -or $part.provenance.$field -ne $combined.provenance.$field) { throw "sampler provenance changed: $field" }
        }
        foreach ($row in $part.samples) { $row.pair = $pairNo; $rows += $row }
    }
    $combined.samples = $rows
    $combined.summary = $null # 比较器从原始samples重新统计
    $combined | ConvertTo-Json -Depth 50 | Set-Content -Encoding utf8 "$screenRoot/$side.json"
}
Merge-Screen lan
Merge-Screen vpn
```

外部独立设备也能按相同命令采样并传回脱敏 JSON；分别记录真实设备匿名 ID，不伪造“同设备”。跨设备、账号、出口或超过窗口的结果保留描述及限制，自动可比差值为空，`remote_business_status=not_accepted`。`--network external-vpn` 仅是标签，不能证明身处公司外。

## 附证格式

每侧提供一份人工审阅的脱敏 observation JSON，引用真实证据文件的 SHA256；manifest 再绑定 observation 的 SHA256。工具核对字节与时间关联，不独立认证物理位置，也不将 reviewed 开关视为外部测量。维护者必须核对原始证据，不能凭模板勾选通过。

证据应包括：设备网络/接口/默认路由与外部接入来源、客户端“导出诊断”的 UTC 和双层会话/路由摘要、证书固定与精确 VPN 入口 DIRECT 的既有部署/命中证据，以及脱敏账号/出口一致性记录。外网说明需证明确为蜂窝/住宅等公司外接入；公司内部接入 VPN 的记录不算外部样本。原始诊断文件可能含接口和 IP 信息，留在受控调查目录；不要复制认证、完整配置、正文或身份信息到 observation。

```json
{
  "schema_version": 1,
  "reviewed": true,
  "device_id": "device-anonymous-a",
  "account_id": "account-anonymous-a",
  "egress_id": "egress-anonymous-a",
  "source_refs": [
    {"path": "external-diagnostics.json", "sha256": "REPLACE_WITH_ACTUAL_SHA256"},
    {"path": "external-access-and-route-review.json", "sha256": "REPLACE_WITH_ACTUAL_SHA256"}
  ],
  "samples": {
    "REPLACE_WITH_ACTUAL_SAMPLE_UUID": {
      "captured_utc": "2026-11-09T08:00:00+00:00",
      "location": "outside_company",
      "access_type": "cellular",
      "outer_active": true,
      "inner_active": true,
      "route_ready": true,
      "certificate_pin_match": true,
      "vpn_entry_direct": true,
      "workload_comparable": true,
      "difference_explained": false,
      "stage_clock": "local_monotonic_duration",
      "stages_ms": {"vpn_ready_ms": null, "nas_connect_ms": null, "upstream_wait_ms": null}
    }
  }
}
```

`samples` 每个键对应 sampler 中的真实 `sample_id`；每个样本都要覆盖，capture 时间距任务开始不超过 15 分钟。公司侧 `location=company_lan`，不要求外部双层 VPN 状态。`workload_comparable` 来自同任务夹具、上下文、预热、输入输出及缓存用量的逐项审阅，不能因为 task 名相同就自动判真。未知时删除该键或写 false。`difference_explained` 仅在有上下文/缓存/上游对应解释时填 true，证据写入引用文件。

阶段时长只允许来自对应本机进程单调时钟的时长；跨主机 UTC 只作关联，不相减构造耗时。VPN 就绪、到 NAS、上游等待缺测就保留 null，网关 semantic 首事件不能充当客户端首可见内容。客户端现有诊断的会话布尔值和路由摘要证明就绪状态，不能自行转换成阶段时长。

将两侧 observation 保存为 `lan-observation.json` / `vpn-observation.json`，补齐实际来源 hash。用此命令生成最终 manifest：

```powershell
$manifest = @{}
foreach ($entry in @(@('company_lan','lan-observation.json'), @('external_vpn','vpn-observation.json'))) {
    $manifest[$entry[0]] = @{ path = $entry[1]; sha256 = (Get-FileHash -Algorithm SHA256 "$screenRoot/$($entry[1])").Hash.ToLowerInvariant() }
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 "$screenRoot/evidence.json"
python tools/codex_vpn_acceptance.py --lan "$screenRoot/lan.json" --vpn "$screenRoot/vpn.json" --evidence "$screenRoot/evidence.json" --output "$screenRoot/comparison.json"
```

返回 0 表示各 task/effort 至少五对可比且正确完成，状态为 `descriptive_screening_complete`；1 表示 `not_accepted`，2 表示输入/输出错误。结果只支持本次描述性筛查，不能据此承诺稳定 P95、因果倍数或建议改网。VPN 侧独有失败、同一接入阶段至少三对变慢、任务差异缺上下文或上游解释，会产生针对性复测触发。定位重复瓶颈且有可回滚候选后，另行评审网络变更。

## 网络附证独立统计

沿用 `network_probe.py` 每目标至少 20 次独立连接和 20 次实际复用连接，保留 warmup 与失败。维护者可在两侧分别执行以下命令后加入比较；该探测仅辅助解释 HTTPS 网络，不代替 Codex 模型任务，也不强制以 NAS 健康 HTTPS 检查为业务前提。

```powershell
python tools/network_probe.py --count 20 --output "$screenRoot/lan-network.json"
python tools/network_probe.py --count 20 --output "$screenRoot/vpn-network.json"
python tools/codex_vpn_acceptance.py --lan "$screenRoot/lan.json" --vpn "$screenRoot/vpn.json" --evidence "$screenRoot/evidence.json" --lan-network "$screenRoot/lan-network.json" --vpn-network "$screenRoot/vpn-network.json" --output "$screenRoot/comparison-with-network.json"
```

两条 probe 命令分别在对应位置执行。默认目标是 Google 204，仅表示此目标的 HTTPS；NAS 建连/上游等待需用实际客户端或已授权采集的相关证据单列。工具不自动请求 NAS 或上游。DNS 缓存命中未知保持 unknown；冷连接必须 `num_connects=1`，热连接必须实际复用；有失败、少于20、warmup失败或计时未知均不完成网络采样。网络性能整体保持 `not_accepted`，不得用策略文本相同或 HTTP 200 代替环境可比性和真实模型验收。

## 本次交付边界

2026-11-09 完成离线解析/比较、哈希附证检查和测试。没有连接 NAS、切换网络、操作 VPN 或发真实模型请求；未产生公司外业务样本。当前远程业务未验收，未声称远程问题修复。具体测试由工单 04 记录，现场结果到位后用相同工具复测，保留原始文件和比较产物。
