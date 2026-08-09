# Backend upgrade implementation

Version 0.4.1 implements the reliability backend blueprint as an authenticated,
tenant-scoped platform. The API remains fail-closed for authorization, trusted-state
checks, and durable execution finalization.

## Runtime control plane

- Formal execution states with legal-transition enforcement
- Append-only execution ledger and transactional outbox
- Idempotency fingerprints, action receipts, cancellation epochs, fencing tokens,
  leases, ACK/retry/dead-letter delivery, worker heartbeats, watchdogs, backpressure,
  and graceful batch draining
- Supabase/PostgreSQL migration in `supabase_execution_control.sql`; the local SQLite
  adapter is retained for development and safe compatibility mode

## Reliability platform

- Indexed observations plus OTLP and OpenInference ingestion
- Adapters for OpenAI Agents, LangGraph, LangChain, CrewAI, Google ADK,
  Microsoft Agent Framework, Anthropic Agent SDK, PydanticAI, LlamaIndex, Mastra,
  Strands, MCP, and Temporal
- PII/secret redaction and deterministic risk-adaptive sampling
- Versioned tool contracts, permission/input checks, independent postconditions,
  evidence provenance, taint propagation, reverification, and runtime taint blocking
- Verified checkpoints, failure-specific recovery plans, and compensating sagas
- Protected datasets, experiments, 16 deterministic evaluators, CI release gates,
  annotation queues, failure clustering, production-failure promotion, drift reports,
  automatic RCA/causal graphs, versioned policy-as-code, shadow/partial rollout,
  alert rules, incidents, simulation-only replay, and reliability calibration
- Protected-vs-unprotected benchmarks, long-horizon goal-drift detection,
  sub-agent cost/risk/cancellation accounting, search filters, and audit export
- Predictive health snapshots covering failure, retry, timeout, latency, token,
  evidence, contradiction, queue-delay, and fallback signals, with trend/anomaly
  analysis and confidence-scored failure forecasts
- SLO evaluation with compliance, error-budget, burn-rate, and healthy/degraded/
  critical state reporting
- Stateful dependency circuit breakers with failure windows, cooldowns, half-open
  probes, safe provider fallback chains, and independently verified recovery
- Deduplicated incident and alert lifecycles with acknowledgement, investigation,
  resolution, automatic regression-dataset promotion, and dashboard/Slack/email/
  webhook notification delivery records
- Evidence-backed human review cases with permission-scoped confirm, compensation,
  resume, and terminate decisions
- Bounded Supabase clients with load-balancer/read-replica routing, endpoint
  circuits, idempotent write rerouting, and failover diagnostics
- Authenticated notification configuration and test-delivery endpoints, with
  HTTPS/SSRF enforcement and HMAC-signed webhook payloads
- Tenant quotas, retention, SSO/encryption/region controls, scoped service accounts,
  hash-only keys, key rotation, and confirmed tenant-data deletion

## SDK ingestion

Python SDK 0.4.1 supports observations, OTLP batches, and framework events. The
dependency-free Node.js SDK is in `software_sdk_js` and supports the same telemetry
plus tool wrapping. Cloud ingestion requires a project API key or a scoped service
account key with `telemetry:write`.

## Release gate

`.github/workflows/reliability-gate.yml` compiles the backend, lints the new modules,
runs the complete regression suite, and checks the Node.js SDK syntax. The standalone
gate can also evaluate a metrics file:

```powershell
python scripts/reliability_gate.py release-metrics.json
```

The default release thresholds cover false negatives, critical-action verification,
reliability regressions, verification latency, and duplicate executions.
