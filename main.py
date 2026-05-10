import asyncio
import time
import random
from enum import Enum
from typing import Any, Callable, Optional
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

SID = "YOUR-STUDENT-ID"

class Gate(Enum):
    SHUT    = "SHUT"
    BLOWN   = "BLOWN"
    PROBING = "PROBING"

class Breaker:
    def __init__(self, tag: str, trip_at: int = 3, wait: float = 10.0, heal_at: int = 1):
        self.tag      = tag
        self.trip_at  = trip_at
        self.wait     = wait
        self.heal_at  = heal_at
        self._gate    = Gate.SHUT
        self._strikes = 0
        self._wins    = 0
        self._blown_ts: Optional[float] = None
        self._mu      = asyncio.Lock()

    @property
    def gate(self) -> Gate:
        return self._gate

    def _cooldown_elapsed(self) -> bool:
        return self._blown_ts is not None and (time.monotonic() - self._blown_ts) >= self.wait

    async def run(self, fn: Callable, *args, backup: Any = None, **kwargs):
        async with self._mu:
            if self._gate == Gate.BLOWN:
                if self._cooldown_elapsed():
                    self._gate = Gate.PROBING
                    self._wins = 0
                    print(f"[{self.tag}] gate → PROBING")
                else:
                    secs = self.wait - (time.monotonic() - self._blown_ts)
                    print(f"[{self.tag}] gate BLOWN  skip call  resume in {secs:.1f}s")
                    return backup

        try:
            out = await fn(*args, **kwargs) if asyncio.iscoroutinefunction(fn) else fn(*args, **kwargs)
            async with self._mu:
                await self._win()
            return out
        except Exception as err:
            async with self._mu:
                await self._lose(err)
            return backup

    async def _win(self):
        if self._gate == Gate.PROBING:
            self._wins += 1
            if self._wins >= self.heal_at:
                self._gate    = Gate.SHUT
                self._strikes = 0
                print(f"[{self.tag}] gate → SHUT  (recovered)")
        else:
            self._strikes = 0

    async def _lose(self, err: Exception):
        self._strikes  += 1
        self._blown_ts  = time.monotonic()
        print(f"[{self.tag}] strike {self._strikes}  err={err}")
        if self._gate == Gate.PROBING:
            self._gate = Gate.BLOWN
            print(f"[{self.tag}] gate → BLOWN  (probe failed)")
        elif self._strikes >= self.trip_at:
            self._gate = Gate.BLOWN
            print(f"[{self.tag}] gate → BLOWN  (trip threshold hit)")

    def snapshot(self) -> dict:
        return {
            "id":      self.tag,
            "gate":    self._gate.value,
            "strikes": self._strikes,
            "blown_at": self._blown_ts,
        }


_vendor_offline = False

async def vendor_llm(prompt: str) -> str:
    if _vendor_offline:
        await asyncio.sleep(0.3)
        raise ConnectionError("vendor unreachable  (simulated 60s hang)")
    await asyncio.sleep(random.uniform(0.04, 0.14))
    return f"Generated response for prompt: {prompt[:55]!r}"


ai_gate = Breaker(tag="vendor-llm", trip_at=3, wait=10.0)

DEGRADED_MSG = (
    "AI features are offline right now. "
    "We have queued your request and will deliver results once the service recovers."
)

app = FastAPI(title="NoteFlow API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def stamp_response(req: Request, nxt):
    res = await nxt(req)
    res.headers["X-Student-ID"] = SID
    return res

@app.get("/ping")
async def ping():
    return {"ok": True, "service": "NoteFlow", "sid": SID}

@app.post("/v1/generate")
async def generate(req: Request):
    data   = await req.json()
    prompt = data.get("text", "")
    t0     = time.monotonic()
    reply  = await ai_gate.run(vendor_llm, prompt, backup=DEGRADED_MSG)
    ms     = round((time.monotonic() - t0) * 1000, 2)
    return JSONResponse({
        "output":    reply,
        "degraded":  reply == DEGRADED_MSG,
        "gate":      ai_gate.gate.value,
        "elapsed_ms": ms,
    })

@app.get("/v1/gate")
async def gate_state():
    return ai_gate.snapshot()

@app.post("/v1/debug/vendor")
async def toggle_vendor(req: Request):
    global _vendor_offline
    body = await req.json()
    _vendor_offline = bool(body.get("offline", True))
    return {"vendor_offline": _vendor_offline}

@app.delete("/v1/debug/gate")
async def nuke_gate():
    ai_gate._gate     = Gate.SHUT
    ai_gate._strikes  = 0
    ai_gate._blown_ts = None
    return {"reset": True}
