([[Connecting Customer's Agentic Environment]])
### 1) Agent App (synthetic customer “multi-agent system”)

A FastAPI service that simulates a customer’s agent framework behavior without GPUs/LLMs by using CPU + network + concurrency patterns that create the same _coordination failures_.

What it does:
- Exposes workflow endpoints that generate **one trace per workflow run**
- Creates spans representing typical agent roles:
    - `workflow` (root)
    - `planner` (spawns work / sets concurrency)
    - `worker` (unit of work)
    - `tool_call` (HTTP call to tool service)
    - `checkpoint` (simulated state persistence)
    - `token_stream` (long-lived streaming response)
- Exports traces over **OTLP/HTTP** to ATI (direct) or to an optional OTel Collector that forwards to ATI.

Traffic classes it emulates (mapped to your insight):
- **Tool-call fan-out**: many parallel calls competing for connections/CPU
- **Checkpoint writes**: periodic “heavier” spans that add contention
- **Token streaming**: long-lived connections + backpressure effects
- **Retry behavior**: correlated retries that amplify traffic

Key scenarios to run:
- **Fan-out collapse**: large fan-out + constrained concurrency -> queueing/latency spikes
- **Blocking chains**: deep sequential dependency chain -> high end-to-end latency
- **Retry storms**: injected tool errors + retries -> amplification and contention
- **Starvation/contended streaming**: stream while background fan-out runs -> degraded stream behavior

---
### 2) Tool Service(s) (simulated external tools)

A FastAPI service that represents dependencies agents call (search, DB, APIs, function tools, etc.).

What it does:
- Provides endpoints like `/tool/{tool_name}` that:
    - sleep for configurable latency (simulating compute/network)
    - fail with configurable probability (simulating flaky deps)
    - optionally stream chunks (simulating streaming tools)
- Lets you dial:
    - average latency (`delay_ms`)
    - failure rate (`error_rate`)
    - streaming mode (`stream=1`)

This is what enables deterministic reproduction of:
- retries, storms
- fan-out contention
- long critical paths (when chained)
- mixed traffic with streaming

---
### 3) Load Generator (operator-driven “customer traffic”)

Any of:
- `curl` for ad-hoc runs
- `k6` for repeatable load profiles
- `locust` for interactive concurrency testing

What it does:
- Produces concurrent workflow runs and spikes (step-load, burst-load)
- Keeps long-lived streams open while launching background workflows
- Drives the system into p95/p99 regimes you care about

---
### 4) Telemetry path (two modes)

**Mode A: Direct OTLP/HTTP**
- Agent App OTEL exporter → ATI Collector OTLP adapter (`/v1/traces`)

**Mode B: “Customer-like” OTEL Collector**
- Agent App OTEL exporter → OTel Collector → ATI Collector

Mode B is important because many real customers already have an OTel Collector deployed.

---
## How to operate it

### A) Bring the environment up

1. Ensure ATI collector is reachable (or include it in the same compose stack).
2. Start tool service + agent app (docker compose).
3. Verify health:
    - `GET tool-service /health`
    - `GET agent-app /run?...` returns quickly
4. Confirm traces arrive in ATI (via ATI UI/incidents or trace list).

### B) Run scenarios manually (curl)

Fan-out:
- `GET /run?scenario=fanout&fanout=200&concurrency=20&delay_ms=80`

Blocking chain:
- `GET /run?scenario=chain&depth=120&delay_ms=15`

Retry storm:
- `GET /run?scenario=retry&fanout=200&concurrency=30&delay_ms=60&error_rate=0.2&max_retries=4`

Streaming under contention:
- `GET /stream?duration_s=30&tool_delay_ms=300&background_fanout=150`
### C) Run under load (recommended)

Use k6/locust to:
- ramp concurrency (e.g., 1 → 50 → 200 concurrent workflows)
- introduce burst traffic
- mix scenario types in one test window (more realistic)
### D) What “success” looks like in ATI

For each scenario, ATI should be able to:
- reconstruct the per-trace agent DAG (planner → workers → tool calls)
- attribute a root agent/pattern
- create deterministic incidents consistent with:
    - fan-out collapse
    - blocking chain
    - retry storm
    - starvation heuristic  
        and provide actionable recs (reduce concurrency, batch calls, rate limits, restructure planner).