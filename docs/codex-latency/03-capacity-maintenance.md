# Codex 容量验收与维护

离线 CLI 只审核脱敏证据，不连接 NAS、修改用户或发送模型请求。候选 `2` 仅供用户 5、2 依次试点；上游 `20` 和管理员 `30` 保持原值。没有可靠槽位或代表性请求时不能宣布用户超时已解决。

```powershell
python tools/codex_capacity.py --evidence capacity.json --samples sampler.json --output assessment.json
```

`--samples` 可重复。输入为 `codex_latency.py` 的原始 JSON 报告，使用 `sample_id`（本工具的 task_id）和 `turn_id` 精确关联；不复制正文。CLI 默认以当前 UTC 审核准入时效；历史复核可显式 `--now 2026-11-09T12:00:00Z`，输出保存该参考时间，不能作为当前准入证明。退出码 0 表示至少容量评估或受控验证完成，2 表示证据不足，3 表示必须回滚，1 表示记录格式错误。五个状态独立输出，不能把 CLI 0 当试点通过。

## 脱敏 JSON v1 约定

所有时间为带时区 ISO 8601。NAS 区间来自同一已校准时钟；不把客户端与 NAS 时间相减。`source` 是受控证据文件的定位标识，禁止放凭据、账号姓名和正文。空值代表缺证据，不能填 0 冒充实测。完整顶层结构如下（数组在未取得证据时保持空）：

```json
{
  "schema_version": 1,
  "captured_at": "2026-11-09T12:00:00Z",
  "configuration": {"source": "snapshot-id", "upstream_limit": 20, "admin_limit": 30},
  "baseline": {
    "source": "slot-log-id", "reliable": true,
    "samples": [{"at": "2026-11-09T11:55:00Z", "used": 4, "limit": 20}]
  },
  "groups": [],
  "pilots": []
}
```

基线至少覆盖 300 秒，每次间隔最多 30 秒，结束距离评估时刻最多 60 秒。所有观测的 `limit` 必须为 20，`used` 包括所有流量；峰值后剩余至少 4 个槽位才允许准入。不从均值或健康接口推断容量。历史受控结果可以继续保留，时效仅影响生产准入。

每个 `groups` 元素：`group_id`（唯一）、`phase`（`controlled_1` / `controlled_2` / `pilot_5` / `pilot_2`）、`user_id`（受控用户为 `controlled`，生产为 `5` / `2`）、`limit`、`source`、`complete_logs: true`、`requests`（恰好两条）。每请求包含：

```json
{
  "task_id": "sampler sample_id", "turn_id": "sampler turn_id",
  "gateway_request_id": "redacted-request-id", "correlation_verified": true,
  "upstream_started_at": "2026-11-09T11:58:00Z",
  "upstream_ended_at": "2026-11-09T11:58:10Z",
  "user_wait_started_at": null, "user_wait_ended_at": null,
  "http_status": 200, "errors": []
}
```

`correlation_verified` 必须来自请求标识或审查过的唯一时间线，不可仅按近似时间自动匹配。每请求引用一个独立采样任务，禁止跨组复用同一 turn 或 gateway_request_id。limit1 的两路上游必须串行，且其中一路用户名额等待区间与另一路上游区间严格相交；limit2 必须证明两个上游执行区间严格相交，二者完成、质量检查通过，且无用户名额等待。三组独立结果才通过对应状态。所有 limit1 区间结束后才开始 limit2 组；两类受控组的最后结束时刻都必须不晚于每位生产用户的 `changed_at`。工具以已关联的上游区间检查顺序，事后受控验证仍可单独完成受控评估，但不能追认更早的生产试点。单纯同时提交、两个 HTTP 200 均不能证明实际并发。

每个 `pilots` 元素包含 `user_id`、`original_limit: 1`、`candidate_limit: 2`、`changed_at`、`observed_until`、`source`、`complete_logs: true`、`baseline`（与顶层相同结构，结束在 changed_at 之前最多 60 秒）、`errors: []`、`rollback_completed: false`。观察至少 1800 秒且该窗口内至少三组代表性两路成功并发。用户5先完成观察并通过，才允许改变用户2。每次仅变更一个用户；用户5保留2后再试用户2不属于同时变更。窗口 `errors` 需要覆盖目标用户及共享上游，包含所有错误的类别，不能只保留成功；任一 `account_wait_timeout`、`new_429`、`authentication`、`stream_completion` 必须回滚。请求 `errors` 同样保留异常。关联客户端出现 timeout、disconnected、failed 等异常终止，或缺少 `turn/completed` 正常结束证据时，同样触发流式完成异常回滚；即使分类数组为空、NAS 最后为 HTTP 200，也不能清除该触发。主动取消与已正常结束但质量检查不通过只影响验收，不单独视作流式故障；其他已知保护条件仍生效。即使后来成功或已回滚，也保留触发状态与证据。

## 实际操作与回滚

由管理员在受控位置使用当前有效管理登录路径取得授权。公开版本 `UserHandler` 支持 `GET /api/v1/admin/users/:id` 和 `PUT /api/v1/admin/users/:id`，更新体为 `{"concurrency":2}`；操作前须核对真实运行版本、实际路由和权限，使用现有管理登录或已配置的管理 API key。没有配置的 admin_api_key 不能编造，也不能修改数据库绕过权限。维护工具不保存或输出 token。

先 GET 保存用户原值及上游20/管理员30的脱敏快照，收集五分钟基线。受控用户分别以1、2各取得三组双路任务及 NAS 请求/槽位证据；正式用户仅在 `pilot_eligible` 通过后先用户5，再用户2。每次 PUT 后 GET 回读，确认仅 concurrency 改为2，记录变更时刻并观察至少30分钟。必须同时审查失败记录及其他流量，运行中的请求自然结束。

触发回滚时 PUT `{"concurrency":1}`（或维护快照中实际原值），GET 回读并用正常任务确认认证、流式完成及原入口可用，记录 `rollback_completed` 与证据；不主动中断其他请求。工具输出 `rollback_required` 表示本次曾触发保护条件；`rollback_pending_users` 区分尚待恢复对象。仅无代表性业务请求时保留原值或结束受控评估，不宣布正式试点通过。
