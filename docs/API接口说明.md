# API 接口说明

本项目 API 合同以两份文件为准：

- 手写摘要：[packages/contracts/api-contract.md](../packages/contracts/api-contract.md)
- 机器可校验 OpenAPI：[packages/contracts/openapi.json](../packages/contracts/openapi.json)

导出命令：

```powershell
python scripts/export_openapi.py
```

也可以通过 npm workspace 根脚本执行：

```powershell
npm.cmd run export:openapi
```

## 维护规则

- 新增或修改后端路由后，必须运行 `python scripts/export_openapi.py`。
- 手写摘要只记录前端和开发者最常看的字段、示例和合规约束。
- OpenAPI JSON 来自 FastAPI app 的实际路由，是检查路径、参数、请求体和响应模型是否漂移的基准。
- sample 数据源、mock LLM 或降级返回仍需在接口摘要中标注当前能力边界。

## 数据状态快速降级

`GET /api/data/status` 使用独立数据库 Session，并受 `DATA_STATUS_TIMEOUT_SECONDS` 控制，默认上限为 `2.5` 秒。
数据库不可用或检查超时时仍返回 `200` envelope，其中 `db_connected=false`、`freshness_status=empty`；该返回只表示当前无法确认数据库状态，不表示已有数据被删除。
