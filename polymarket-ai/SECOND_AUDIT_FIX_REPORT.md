# Second Audit Fix Report — Phase 0 Refactoring

## 1. 修复文件列表

| 文件 | 操作 | 说明 |
|---|---|---|
| `phase0/schemas.py` | 重写 | `TzAwareDt` (AfterValidator), `extra="forbid"`, `ResolutionOutcome` enum, PriceSnapshot ge/le |
| `phase0/state.py` | **重写** | 事件溯源状态机: `EventStore` (append-only JSONL + SHA256 hash chain) + `ExperimentStateManager` (两层: experiment/market) |
| `phase0/atomic_write.py` | 重写 | `safe_append_jsonl` 使用 `fcntl.flock` (Linux) + fallback |
| `phase0/price_reveal_service.py` | 重写 | 包工件验证 (hash / market_id); **仅成功后** 转 PRICE_REVEALED |
| `phase0/forecast_lock.py` | 重写 | `parse_version()` 整数排序; `find_latest_version()` 数值 max |
| `phase0/manifest.py` | 修改 | 新增 `ManifestRegistry` (frozen manifest + market_id 存在性验证) |
| `phase0/evaluate.py` | 修改 | `mid=0.0` 不被视为缺失; `_get_market_price()` 显式 `is not None` |
| `phase0/cli.py` | **重写** | `forecast` → 版本化工件; `lock` → validate_package + temporal + market_id; `resolve` → strict Outcome enum + state 验证; `evaluate` → 递归 forecast 目录; 新增 `verify_events` |
| `tests/*.py` | 全部重写 | 164 个测试 (新增 ~50) |

## 2. 审计问题 → 修复位置

| # | 审计问题 | 严重性 | 修复位置 |
|---|---|---|---|
| 1 | 核心 Schema naive timestamp 字符串绕过 | P0 | `TzAwareDt` AfterValidator 运行于解析后, 字符串 `2025-06-01T00:00:00` → naive datetime → 拒绝 |
| 2 | Price Reveal 未验证 Package Artifact | P0 | `PriceRevealService` 读取 packages_root → validate_package → compare hash + market_id chain |
| 3 | 状态机不支持多市场 | P0 | 两层状态: experiment (CREATED/ACTIVE/COMPLETE) + per-market (PACKAGE_READY → EVALUATED) |
| 4 | 状态可通过 JSON 直接伪造 | P0 | 事件溯源: append-only JSONL + SHA256 hash chain + `verify_chain()` 检测篡改/删除/插入 |
| 5 | Reveal 状态转换时机错误 | P0 | 仅在 provider 成功 + snapshot 持久化后调用 `transition_market`; 失败保持 FORECAST_LOCKED |
| 6 | Forecast Version 数字排序错误 | P0 | `parse_version()` 提取整数; `find_latest_version()` 使用 `max()` |
| 7 | CLI evaluate 无法读取版本化 Forecast | P0 | `evaluate` 命令递归 `<forecasts_dir>/<market_id>/v{version}.json` |
| 8 | PriceSnapshot mid=0.0 被当作 False | P1 | `_get_market_price()`: `snap.get("mid") if snap.get("mid") is not None else snap.get("price")` |
| 9 | Manifest → Package 身份链未验证 | P1 | `ManifestRegistry`: 加载 frozen manifest, 验证 hash, market_id 存在性 |
| 10 | lock CLI 未验证 Package | P1 | `validate_package()`, market_id 匹配, temporal check, canonical hash |
| 11 | resolve 命令未严格验证 outcome | P1 | `ResolutionOutcome` Enum (YES/NO); 拒绝 MAYBE/UNKNOWN 等 |
| 12 | Core Pydantic Schema 缺少 `extra="forbid"` | P1 | 所有核心模型: `ConfigDict(extra="forbid")` |
| 13 | `safe_append_jsonl` 并发问题 | P1 | `fcntl.flock` (Linux) + O_APPEND; Windows fallback |
| 14 | `price_before_lock` 测试不正确 | P1 | 重写: state 停于 FORECAST_GENERATED, 使用真实 lock 文件, 因 state 检查失败 |
| 15 | 新增回归测试 | P1 | 见下文 |

## 3. 新增回归测试

| 测试 | 说明 |
|---|---|
| `test_naive_timestamp_string_rejected_all_models` | Forecast, Manifest, Lock, Resolution, PriceSnapshot, EvalSummary 分别测试 |
| `test_extra_field_rejected` | 核心模型 extra="forbid" |
| `test_mid_zero_is_valid_probability` + `test_mid_one` | 0.0 和 1.0 是合法概率 |
| `test_bid_out_of_range` / `test_negative_spread` | PriceSnapshot 范围校验 |
| `test_invalid_outcome_rejected` | ResolutionOutcome 严格枚举 |
| `test_missing_package_artifact` | 缺失包工件阻断 reveal |
| `test_package_hash_mismatch` | 包 hash 不匹配阻断 reveal |
| `test_package_market_mismatch` | 包 market_id 不匹配阻断 reveal |
| `test_provider_failure_keeps_state_forecast_locked` | Provider 失败后状态保持 |
| `test_version_sort_v12_after_v9` | 数字版本排序 |
| `test_multi_market_independent_lifecycle` | M001/M002 独立生命周期 |
| `test_event_tamper_detected` | 事件编辑被 hash chain 检测 |
| `test_event_delete_detected` | 事件删除被检测 |
| `test_registry_accepts_market_id_and_id` | ManifestRegistry 兼容两种 market_id 格式 |
| `test_market_not_in_manifest_rejected` | 验证 market 存在性 |
| **总计** | **~50 个新增断言** |

## 4. pytest 最终结果

```
164 passed in 1.87s
```

| 测试文件 | 数量 |
|---|---|
| test_schema.py | 38 |
| test_manifest.py | 12 |
| test_package_firewall.py | 17 |
| test_temporal_integrity.py | 12 |
| test_forecast_lock.py | 15 |
| test_price_reveal.py | 17 |
| test_evaluate.py | 20 |
| test_state_machine.py | 21 |
| test_market_identity.py | 5 |
| test_atomic_write.py | 7 |
| test_end_to_end.py | 2 |
| **总计** | **164** |

## 5. Simulation 最终结果

| 场景 | 结果 | 说明 |
|---|---|---|
| happy_path | PASS | 完整流水线 |
| market_taint | PASS | `best_ask` 拦截 |
| temporal_leakage | PASS | cutoff 后证据 |
| **price_before_lock** | **PASS** | 真正测试 state=FORECAST_GENERATED, 非 missing file |
| invalid_forecast_json | PASS | `p_yes=1.7` |
| manifest_tamper | PASS | Hash 不匹配 |
| extreme_forecast_error | PASS | Brier/LogLoss |
| fake_lock | PASS | 空 lock 拦截 |
| tampered_lock | PASS | 篡改 lock 拦截 |
| wrong_market_lock | PASS | 错误 market lock |
| forecast_artifact_tamper | PASS | 篡改 forecast |
| camelcase_taint | PASS | `bestAsk` camelCase |
| **multi_market** | **PASS** | M001 + M002 独立 PRICE_REVEALED |
| **package_artifact_tamper** | **PASS** | 包篡改拦截 |
| **missing_package_artifact** | **PASS** | 缺失包拦截 |
| **provider_failure** | **PASS** | Provider 失败后状态保持 FORECAST_LOCKED |
| **state_tamper** | **PASS** | Hash chain 检测篡改 |
| **version_over_10** | **PASS** | v12 > v9 |
| **missing_lock** | **PASS** | 缺失 lock 拦截 |
| **总计 19/19** | **全部 PASS** | |

## 6. 已知剩余问题 (Phase 0 范围外)

- `fcntl.flock` 仅在 Linux 上有效; Windows 回退到旧的非并发 JSONL 追加
- `httpx` 和 `pytest-env` 作为依赖安装但 Phase 0 未使用
- `HermesForecastProvider` 仍然是 skeleton
- `MarketSnapshotProvider` 仅支持 fixture, 不支持真实 API
- `AuditTrail` 存在但未集成到业务路径
- 未安装 coverage 工具

## 7. 明确未实现功能

| 功能 | 状态 |
|---|---|
| 真实 Polymarket API 连接 | 不存在 |
| 钱包创建或密钥管理 | 不存在 |
| 签名或助记词 | 不存在 |
| 订单提交 | 不存在 |
| 自动下注或交易 | 不存在 |
| 真实 LLM 集成 | 不存在 |
| 实时数据管道 | 不存在 |
| 数据库/Vector DB/Kafka/Redis | 不存在 |
| Web UI | 不存在 |
| Phase 1+ 功能 | 未实现 |
