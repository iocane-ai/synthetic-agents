# Synthetic Agent Infrastructure

This project provides a synthetic agent infrastructure designed for testing, benchmarking, and generating various trace patterns for observability pipelines. It simulates different agentic behaviors and stress tests.

### Scenarios & Failure Modes

**These failures only appear in prod-like workloads.**

The agent app exposes a `/run` endpoint (simulated by the script above) that generates specific trace patterns. Below is a breakdown of why these patterns matter.

#### 1. Fanout (`fanout`)
Simulates a planner agent spawning multiple parallel worker agents to execute tool calls. Good for testing high concurrency.

*   **Endpoint**: `GET /run?scenario=fanout`
*   **Parameters**: `fanout` (def: 100), `concurrency` (def: 20), `delay_ms` (def: 80).
*   **Analysis**:
    *   **Expected Symptom**: High tail latency (p99) despite low average latency.
    *   **Why normal APMs miss it**: Aggregation metrics often hide the single slow worker among hundreds of successful ones.
    *   **What Iocane ATI reveals**: Pinpoints the exact straggler task that is delaying the entire batch completion.

#### 2. Chain (`chain`)
Simulates a deep, sequential chain where one agent waits for the next. Tests deep call stacks and latency propagation.

*   **Endpoint**: `GET /run?scenario=chain`
*   **Parameters**: `depth` (def: 60), `delay_ms` (def: 80).
*   **Analysis**:
    *   **Expected Symptom**: High end-to-end latency with no obvious single bottleneck.
    *   **Why normal APMs miss it**: Hard to visualize the cumulative effect of small processing delays across extremely deep call stacks.
    *   **What Iocane ATI reveals**: Visualizes the critical path depth and cumulative "death by a thousand cuts" latency.

#### 3. Retry Storm (`retry`)
Simulates flaky tools requiring retries with exponential backoff.

*   **Endpoint**: `GET /run?scenario=retry`
*   **Parameters**: `fanout` (def: 100), `error_rate` (def: 0.1), `max_retries` (def: 3).
*   **Analysis**:
    *   **Expected Symptom**: Intermittent latency spikes and increased system load without apparent traffic increase.
    *   **Why normal APMs miss it**: Often conflate retries with fresh requests or fail to link the retry attempts to the root cause failure.
    *   **What Iocane ATI reveals**: Shows the exact retry sequence, backoff delays, and the cascading failure origin.

#### 4. Dependency Graph (`dag`)
Simulates a diamond pattern dependency graph (fork -> join).

*   **Endpoint**: `GET /run?scenario=dag`
*   **Parameters**: `fanout` (def: 100), `delay_ms` (def: 80).
*   **Analysis**:
    *   **Expected Symptom**: Request duration is purely determined by the slowest branch (Straggler problem).
    *   **Why normal APMs miss it**: Difficulty in automatically identifying which parallel branch is the bottleneck vs which ones are just waiting.
    *   **What Iocane ATI reveals**: Critical path analysis through the complex dependency graph.

#### 5. ReAct Loop (`react`)
Simulates a Reason-Act-Observe loop.

*   **Endpoint**: `GET /run?scenario=react`
*   **Parameters**: `max_steps` (def: 10), `delay_ms` (def: 80).
*   **Analysis**:
    *   **Expected Symptom**: Unpredictable and highly variable latency per request.
    *   **Why normal APMs miss it**: Cannot distinguish between a slow tool call and an agent simply deciding to take more logical steps.
    *   **What Iocane ATI reveals**: The structure of the "thought process," distinguishing step count variance from tool performance issues.

#### 6. Human-in-the-Loop (`human`)
Simulates a workflow pausing for human feedback (long sleep).

*   **Endpoint**: `GET /run?scenario=human`
*   **Parameters**: `human_delay_s` (def: 1.0).
*   **Analysis**:
    *   **Expected Symptom**: Extremely long traces, often timing out at standard gateways/load balancers.
    *   **Why normal APMs miss it**: Treat long pauses as server timeouts or anomalies rather than valid application states.
    *   **What Iocane ATI reveals**: Semantic distinction between "processing time" and "waiting for user" (idle time).

#### 7. RAG / Large Payload (`rag`)
Simulates retrieval of large payloads.

*   **Endpoint**: `GET /run?scenario=rag`
*   **Parameters**: `rag_chunks` (def: 5), `rag_chunk_size_kb` (def: 2).
*   **Analysis**:
    *   **Expected Symptom**: Network saturation and slow processing of specific requests.
    *   **Why normal APMs miss it**: Lack of correlation between payload size (span attributes) and latency.
    *   **What Iocane ATI reveals**: Correlates data size attributes directly with processing time to identify resource bottlenecks.

#### 8. Token Streaming (`/stream`)
Simulates an LLM streaming tokens while background tools run.

*   **Endpoint**: `GET /stream`
*   **Parameters**: `duration_s` (def: 20), `tool_delay_ms` (def: 400).
*   **Analysis**:
    *   **Expected Symptom**: Good Time-To-First-Token (TTFT) but slow overall completion, or background task failures.
    *   **Why normal APMs miss it**: Traditional request/response tracing misses the streaming dynamics and background thread contention.
    *   **What Iocane ATI reveals**: The timeline of token emission versus background tool execution.

## Prerequisites

*   **Docker** and **Docker Compose**
*   **Python 3.9+** (for running scripts/clients if needed, though most interaction is via `curl`)

## Installation

1.  Clone the repository.
2.  Start the services:

    ```bash
    docker-compose up --build
    ```

    This will start:
    *   `agent-app`: The main agent simulation service (Port 8080).
    *   `tool-service`: A mock tool service that agents call (Port 8081).
    *   `otel-collector`: (Optional) OpenTelemetry collector for traces (Ports 4317/4318).

## Usage

### Sanity Check

To verify everything is running correctly, run the included script:

```bash
./sanity_check.sh
```

### Interactive Scenario Generator

The easiest way to explore different scenarios is using the interactive script:

```bash
./generate_scenarios.sh
```

This script allows you to selectively trigger specific scenarios on the primary or secondary agent without memorizing `curl` commands.

## Configuration

Environment variables in `docker-compose.yml`:

*   `TOOL_DELAY_MS`: Default base latency for the mock tool service (default: 80).
*   `TOOL_ERROR_RATE`: Default error rate for the mock tool service (default: 0.0).
*   `SERVICE_NAME`: Service name for traces (default: synthetic-agent-app).
*   `AGENT_NAME`: Optional prefix for agent IDs to simulate multiple meshes.
*   `OTEL_EXPORTER_OTLP_ENDPOINT`: Endpoint for the OpenTelemetry collector.

## Observability

The project includes an OpenTelemetry Collector configuration.

1.  **Enable Collector**: Uncomment the `otel-collector` service in `docker-compose.yml`.
2.  **View Traces**: The default config uses the `debug` exporter. View traces in logs:
    ```bash
    docker logs -f otel-collector
    ```
3.  **Ports**:
    *   `4318`: OTLP HTTP receiver.
    *   `4317`: OTLP gRPC receiver.