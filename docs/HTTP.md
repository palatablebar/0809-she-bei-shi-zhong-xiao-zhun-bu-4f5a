# 阶段接口

`POST /api/stages/<stage>` 接收 `multipart/form-data`。字段 `sample=dirty`、`sample=clean` 或 `file=<CSV>` 三选一。阶段为 `intake`、`prepare`、`calculate`、`policy`、`balance`。预览不入库。

`POST /api/runs` 接收同样的输入，执行全批并返回运行报告。`GET /api/runs` 返回最近 50 批。`GET /api/runs/<id>` 查询一批和当前复核状态。

`PATCH /api/runs/<id>` 接收 `revision`、`status` 和 `note`。状态使用 `APPROVED` 或 `HELD`。冲突返回 409，客户端读取新版本后重试。

批次与对账阶段的响应带有 `groups` 与 `orphans`：`groups` 按设备组给出核对账（输入、采信、隔离、被拒及记录键）、阻碍原因与签发状态；`orphans` 列出无法归属设备组的隔离行。

`POST /api/runs/<id>/groups/<case>/issue` 签发单个设备组并固定该组证据。组核对未完整返回 409（`GROUP_BLOCKED`），重复签发返回 409（`GROUP_FINALIZED`），组不存在返回 404。提交失败时原批次与记录保持不变。

`GET /api/runs/<id>/evidence` 下载内含运行清单、行号隔离、业务证据、按组签发结果和复核信息的 JSON。
