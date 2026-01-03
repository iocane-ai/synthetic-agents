import asyncio
import os
import random
import time
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor

SERVICE_NAME = os.getenv("SERVICE_NAME", "synthetic-agent-app")
OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
TOOL_BASE = os.getenv("TOOL_BASE", "http://localhost:8081")

resource = Resource.create({"service.name": SERVICE_NAME})
provider = TracerProvider(resource=resource)
processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{OTLP_ENDPOINT}/v1/traces"))
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)

app = FastAPI()


def _attrs(agent_id: str, kind: str, **extra):
    # If AGENT_NAME is set, namespace all agents to allow running multiple distinct meshes
    prefix = os.getenv("AGENT_NAME")
    if prefix:
        agent_id = f"{prefix}:{agent_id}"

    # Keep these stable; ATI can rely on them.
    base = {
        "ati.agent.id": agent_id,
        "ati.span.kind": kind,  # planner|worker|tool_call|checkpoint|token_stream
        "ati.workflow": "demo",
    }
    base.update(extra)
    return base

async def call_tool(client: httpx.AsyncClient, tool: str, delay_ms: int, error_rate: float, attempt: int, stream: bool = False, payload_size_kb: int = 0):
    with tracer.start_as_current_span("tool_call", attributes=_attrs(
        agent_id=f"worker:{tool}",
        kind="tool_call",
        **{
            "ati.tool.name": tool,
            "ati.retry.attempt": attempt,
            "ati.tool.delay_ms": delay_ms,
            "ati.tool.error_rate": error_rate,
            "ati.tool.stream": int(stream),
            "ati.tool.payload_kb": payload_size_kb,
        }
    )):
        params = {"delay_ms": delay_ms, "error_rate": error_rate, "payload_size_kb": payload_size_kb}
        if stream:
            params["stream"] = 1
            r = await client.get(f"{TOOL_BASE}/tool/{tool}", params=params, timeout=30.0)
            r.raise_for_status()
            # Read some bytes to create real backpressure + long-lived IO
            async for _ in r.aiter_lines():
                pass
            return {"ok": True, "stream": True}
        r = await client.get(f"{TOOL_BASE}/tool/{tool}", params=params, timeout=30.0)
        r.raise_for_status()
        return r.json()

async def checkpoint_write(size_kb: int, agent_id: str):
    # Simulate checkpoints as time + payload size (no real payload storage needed)
    with tracer.start_as_current_span("checkpoint", attributes=_attrs(
        agent_id=agent_id,
        kind="checkpoint",
        **{"ati.checkpoint.size_kb": size_kb},
    )):
        await asyncio.sleep(min(0.5, (size_kb / 1024.0) * 0.2))

async def scenario_fanout(concurrency: int, fanout: int, delay_ms: int):
    with tracer.start_as_current_span("planner", attributes=_attrs("planner:v1", "planner", **{
        "ati.fanout": fanout,
        "ati.concurrency": concurrency,
    })):
        sem = asyncio.Semaphore(concurrency)
        async with httpx.AsyncClient() as client:
            async def one(i: int):
                async with sem:
                    with tracer.start_as_current_span("worker", attributes=_attrs(
                        agent_id=f"worker:{i}",
                        kind="worker",
                        **{"ati.worker.index": i}
                    )):
                        return await call_tool(client, tool=f"t{i%5}", delay_ms=delay_ms, error_rate=0.0, attempt=0)

            tasks = [asyncio.create_task(one(i)) for i in range(fanout)]
            await asyncio.gather(*tasks)
        await checkpoint_write(size_kb=128, agent_id="planner:v1")

async def scenario_blocking_chain(depth: int, delay_ms: int):
    with tracer.start_as_current_span("planner", attributes=_attrs("planner:v1", "planner", **{"ati.chain.depth": depth})):
        async with httpx.AsyncClient() as client:
            for i in range(depth):
                with tracer.start_as_current_span("step", attributes=_attrs(
                    agent_id=f"chain:{i}",
                    kind="worker",
                    **{"ati.chain.index": i}
                )):
                    await call_tool(client, tool="chain", delay_ms=delay_ms, error_rate=0.0, attempt=0)
        await checkpoint_write(size_kb=64, agent_id="planner:v1")

async def scenario_retry_storm(fanout: int, concurrency: int, delay_ms: int, error_rate: float, max_retries: int):
    with tracer.start_as_current_span("planner", attributes=_attrs("planner:v1", "planner", **{
        "ati.fanout": fanout,
        "ati.concurrency": concurrency,
        "ati.retry.max": max_retries,
    })):
        sem = asyncio.Semaphore(concurrency)
        async with httpx.AsyncClient() as client:
            async def one(i: int):
                async with sem:
                    tool = f"r{i%5}"
                    attempt = 0
                    backoff = 0.02
                    while True:
                        try:
                            return await call_tool(client, tool=tool, delay_ms=delay_ms, error_rate=error_rate, attempt=attempt)
                        except Exception:
                            attempt += 1
                            if attempt > max_retries:
                                return {"ok": False}
                            await asyncio.sleep(backoff)
                            backoff = min(backoff * 2, 0.5)

            tasks = [asyncio.create_task(one(i)) for i in range(fanout)]
            await asyncio.gather(*tasks)
        await checkpoint_write(size_kb=256, agent_id="planner:v1")

async def scenario_dag(fanout: int, delay_ms: int):
    # Diamond pattern: Planner -> workers (parallel) -> aggregator (single)
    with tracer.start_as_current_span("planner", attributes=_attrs("planner:v1", "planner", **{"ati.dag.fanout": fanout})):
        async with httpx.AsyncClient() as client:
            # Fork
            results = []
            async def branch(i: int):
                with tracer.start_as_current_span("branch_worker", attributes=_attrs(
                    agent_id=f"branch:{i}",
                    kind="worker",
                )):
                   return await call_tool(client, tool=f"dag_{i}", delay_ms=delay_ms, error_rate=0.0, attempt=0)

            results = await asyncio.gather(*[branch(i) for i in range(fanout)])
            
            # Join/Aggregate
            with tracer.start_as_current_span("aggregator", attributes=_attrs("aggregator:v1", "worker")):
                 await call_tool(client, tool="aggregator", delay_ms=delay_ms, error_rate=0.0, attempt=0)
        
        await checkpoint_write(size_kb=64, agent_id="planner:v1")

async def scenario_react(max_steps: int, delay_ms: int):
    # ReAct: Thought -> Act -> Observe -> Repeat
    with tracer.start_as_current_span("agent_core", attributes=_attrs("agent:v1", "planner", **{"ati.react.max_steps": max_steps})):
        async with httpx.AsyncClient() as client:
            for i in range(max_steps):
                # Thought
                with tracer.start_as_current_span("thought", attributes=_attrs(f"thought:{i}", "internal", **{"ati.step": i})):
                    # Simulate verbose logging of "LLM reasoning"
                    reasoning_trace = f"Thought {i}: Analysis of previous step... Plan: Execute step_{i}..."
                    trace.get_current_span().set_attribute("ati.llm.prompt", reasoning_trace)
                    await asyncio.sleep(0.01 + random.random() * 0.05)
                
                # Act (Tool Call)
                with tracer.start_as_current_span("act", attributes=_attrs(f"act:{i}", "tool_call", **{"ati.step": i})):
                     await call_tool(client, tool=f"step_{i}", delay_ms=delay_ms, error_rate=0.0, attempt=0)
                
                # Observe (simulated by logic)
                if random.random() < 0.1: # 10% chance to finish early
                    break
                    
        await checkpoint_write(size_kb=128, agent_id="agent:v1")

async def scenario_human(delay_s: float):
    # Human in the loop: Planner -> Wait -> Resume
    with tracer.start_as_current_span("planner", attributes=_attrs("planner:v1", "planner", **{"ati.human.delay_s": delay_s})):
        # Phase 1: Pre-human
        async with httpx.AsyncClient() as client:
             await call_tool(client, tool="pre_human", delay_ms=100, error_rate=0.0, attempt=0)
             
        # Human step (simulated long wait)
        with tracer.start_as_current_span("human_feedback", attributes=_attrs("human", "interactive")):
            await asyncio.sleep(delay_s)
            
        # Phase 2: Post-human
        async with httpx.AsyncClient() as client:
             await call_tool(client, tool="post_human", delay_ms=100, error_rate=0.0, attempt=0)

async def scenario_rag(chunk_count: int, chunk_size_kb: int, delay_ms: int):
    # RAG: Planner -> Retrieval (Large Payload) -> Generation
    with tracer.start_as_current_span("planner", attributes=_attrs("planner:v1", "planner", **{"ati.rag.chunks": chunk_count})):
        async with httpx.AsyncClient() as client:
             # Retrieval with massive payload
             total_kb = chunk_count * chunk_size_kb
             with tracer.start_as_current_span("retrieval", attributes=_attrs("retriever", "tool_call", **{"ati.rag.total_kb": total_kb})):
                 result = await call_tool(client, tool="vector_db", delay_ms=delay_ms, error_rate=0.0, attempt=0, payload_size_kb=total_kb)
                 
                 # BAD PRACTICE: Log the entire huge payload to the span attributes!
                 if isinstance(result, dict) and "payload" in result:
                     trace.get_current_span().set_attribute("ati.rag.content", result["payload"])
                 
             # Simulated generation processing
             with tracer.start_as_current_span("generation", attributes=_attrs("llm", "generation")):
                 await asyncio.sleep(0.1 + (total_kb / 5000.0)) # sleep proprotional to size

@app.get("/run")
async def run(
    scenario: Literal["fanout", "chain", "retry", "dag", "react", "human", "rag"] = "fanout",
    fanout: int = 100,
    concurrency: int = 20,
    delay_ms: int = 80,
    depth: int = 60,
    error_rate: float = 0.1,
    max_retries: int = 3,
    max_steps: int = 10,
    human_delay_s: float = 1.0,
    rag_chunks: int = 5,
    rag_chunk_size_kb: int = 2,
):
    start = time.time()
    with tracer.start_as_current_span("workflow", attributes=_attrs("workflow", "workflow", **{"ati.scenario": scenario})):
        if scenario == "fanout":
            await scenario_fanout(concurrency=concurrency, fanout=fanout, delay_ms=delay_ms)
        elif scenario == "chain":
            await scenario_blocking_chain(depth=depth, delay_ms=delay_ms)
        elif scenario == "retry":
            await scenario_retry_storm(fanout=fanout, concurrency=concurrency, delay_ms=delay_ms, error_rate=error_rate, max_retries=max_retries)
        elif scenario == "dag":
            await scenario_dag(fanout=fanout, delay_ms=delay_ms)
        elif scenario == "react":
            await scenario_react(max_steps=max_steps, delay_ms=delay_ms)
        elif scenario == "human":
            await scenario_human(delay_s=human_delay_s)
        elif scenario == "rag":
            await scenario_rag(chunk_count=rag_chunks, chunk_size_kb=rag_chunk_size_kb, delay_ms=delay_ms)
        else:
            raise HTTPException(400, "unknown scenario")
    return {"ok": True, "scenario": scenario, "elapsed_s": round(time.time() - start, 3)}

@app.get("/stream")
async def stream(duration_s: int = 20, tool_delay_ms: int = 400, background_fanout: int = 50):
    """
    Simulates token streaming while background tool calls run.
    This creates contention/starvation-like conditions without GPUs.
    """
    async def gen():
        with tracer.start_as_current_span("token_stream", attributes=_attrs("streamer:v1", "token_stream", **{
            "ati.stream.duration_s": duration_s,
            "ati.bg.fanout": background_fanout,
        })):
            # kick off background work
            bg_task = asyncio.create_task(scenario_fanout(concurrency=10, fanout=background_fanout, delay_ms=tool_delay_ms))
            t0 = time.time()
            i = 0
            while time.time() - t0 < duration_s:
                # emit "tokens"
                yield f"token {i}\n"
                i += 1
                await asyncio.sleep(0.05)
            await bg_task
    return StreamingResponse(gen(), media_type="text/plain")
