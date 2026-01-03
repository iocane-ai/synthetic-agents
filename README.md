# Synthetic Agent Infrastructure

This is a synthetic agent infrastructure for testing and benchmarking.

This application simulates four main agentic scenarios, designed to generate different types of trace patterns and stress tests:

## 1. Fanout (scenario_fanout)
* Description: Simulates a planner agent that spawns multiple parallel worker agents to execute tool calls concurrently.
* Key Parameters: fanout (total tasks), concurrency (workers), delay_ms (tool latency).
* Goal: Generates wide, shallow traces to test high concurrency handling.
## 2. Chain (scenario_blocking_chain)
* Description: Simulates a deep, sequential chain of blocking calls where one agent waits for the next.
* Key Parameters: depth (number of steps), delay_ms.
* Goal: Generates deep, narrow traces to test deep call stacks and latency propagation.
## 3. Retry Storm (scenario_retry_storm)
* Description: Simulates a scenario with flaky tools where agents must retry executing tasks multiple times.
* Key Parameters: error_rate (probability of failure), max_retries.
* Goal: Tests error handling, retry logic, and exponential backoff behavior.
## 4. Stream (/stream endpoint)
* Description: Simulates an agent streaming tokens (like an LLM response) while simultaneously running background tool calls.
* Key Parameters: duration_s, background_fanout.
* Goal: Simulates resource contention and "starvation" conditions typical in streaming LLM applications.
## 5. Dependency Graph (scenario_dag)
* Description: Simulates a complex dependency graph (Diamond pattern: fork -> join) where multiple parallel branches must complete before aggregation.
* Key Parameters: fanout (branches), delay_ms.
* Goal: Generates traces with synchronization barriers to test tail latency and aggregation handling.
## 6. ReAct Loop (scenario_react)
* Description: Simulates an iterative "Thought-Act-Observe" loop where an agent probabilistically decides to continue or stop.
* Key Parameters: max_steps (upper limit), delay_ms.
* Goal: Generates variable-length traces with repeated structural patterns, common in autonomous agents.
## 7. Human-in-the-Loop (scenario_human)
* Description: Simulates a workflow that pauses for "human feedback," represented by a long sleep duration.
* Key Parameters: human_delay_s (pause duration).
* Goal: Tests system behavior with long-running spans and potential timeout/keep-alive issues.
## 8. RAG / Large Payload (scenario_rag)
* Description: Simulates an agent retrieving large payloads (e.g., from a Vector DB) and then processing them.
* Key Parameters: rag_chunks (number of chunks), rag_chunk_size_kb (size per chunk).
* Goal: Tests the telemetry pipeline's ability to handle large span attributes and high bandwidth.

## Usage

```bash
docker-compose up
```

## OpenTelemetry & Tracing

This project employs the **OpenTelemetry Collector** to gather and process traces.

- **Configuration**: See `otel-collector-config.yaml`.
- **Viewing Traces**: Currently configured to use the `debug` exporter. You can view the raw trace data in the container logs:
  ```bash
  docker logs -f otel-collector
  ```
- **Endpoint**: The collector listens on `0.0.0.0:4318` (HTTP) and `0.0.0.0:4317` (gRPC).

### Sanity Check (executes requests to the agent app scenario endpoints)

```bash
./sanity_check.sh
```

### What to tune (to emulate “customer reality”)

Use these dials to reproduce the failure modes you care about:

#### Fan-out collapse

* fanout high (200–2000)
* concurrency moderate/low (10–50)
* tool delay moderate

#### Blocking chains

* depth high (100–500)
* tool delay small (5–20ms) to create “low per-span latency, high end-to-end latency”

#### Retry storms

* error_rate 0.1–0.3
* max_retries 3–6

#### Starvation / contention

* hit /stream with high background_fanout and tool_delay_ms

#### Integration checkpoints (what you should confirm in ATI)

From this agent app, you should be able to confirm:

* Traces arrive over OTLP/HTTP (/v1/traces). 
* Your schema normalizer can consistently identify:
    * agent identity (ati.agent.id)
    * traffic class (ati.span.kind)
    * fanout/concurrency/retry metadata (attributes)
* Your detectors can be triggered deterministically by scenario parameters (fanout/chain/retry/stream).