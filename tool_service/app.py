import asyncio
import os
import random
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

app = FastAPI()

DEFAULT_DELAY_MS = int(os.getenv("TOOL_DELAY_MS", "80"))
DEFAULT_ERROR_RATE = float(os.getenv("TOOL_ERROR_RATE", "0.0"))

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/tool/{tool_name}")
async def tool_call(
    tool_name: str, 
    delay_ms: int | None = None, 
    error_rate: float | None = None, 
    stream: int = 0,
    payload_size_kb: int = 0
):
    d = DEFAULT_DELAY_MS if delay_ms is None else delay_ms
    e = DEFAULT_ERROR_RATE if error_rate is None else error_rate

    if random.random() < e:
        raise HTTPException(status_code=503, detail=f"{tool_name} unavailable")

    if stream == 1:
        async def gen():
            # Simulate token/tool streaming
            chunks = 50
            per = max(d / chunks, 1)
            for i in range(chunks):
                await asyncio.sleep(per / 1000.0)
                yield f"chunk {i} from {tool_name}\n"
        return StreamingResponse(gen(), media_type="text/plain")

    await asyncio.sleep(d / 1000.0)
    
    response = {"tool": tool_name, "delay_ms": d, "ok": True}
    if payload_size_kb > 0:
        # Generate dummy payload roughly size_kb
        # 1KB = 1024 chars roughly
        response["payload"] = "a" * (payload_size_kb * 1024)
        
    return response
