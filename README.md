# YOUR NAME | YOUR-STUDENT-ID

## NoteFlow Backend — PDC Assignment 2

Circuit Breaker implementation in FastAPI preventing a slow LLM vendor from taking down the entire server.

---

## Project Layout

```
.
├── main.py                  FastAPI app + Breaker state machine
├── test_circuit_breaker.py  5-test suite (pytest or standalone)
└── requirements.txt
```

---

## Quickstart

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Docs at `http://localhost:8000/docs`

---

## Running Tests

Terminal 1 — server must be running first:
```bash
uvicorn main:app --port 8000
```

Terminal 2 — run suite:
```bash
# with pytest
pytest test_circuit_breaker.py -v

# or standalone
python test_circuit_breaker.py
```

Test 4 (`test_self_heal`) waits 11 seconds for the cooldown window. Total runtime ~15s.

---

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/ping` | Health check |
| POST | `/v1/generate` | LLM call through gate |
| GET | `/v1/gate` | Current gate state |
| POST | `/v1/debug/vendor` | Toggle vendor failure `{"offline": true}` |
| DELETE | `/v1/debug/gate` | Reset gate to SHUT |

---

## Gate States

```
SHUT  ──(3 strikes)──▶  BLOWN  ──(10s cooldown)──▶  PROBING
 ▲                                                       │
 └──────────────────(probe passes)──────────────────────┘
```

| State | Calls | Config |
|-------|-------|--------|
| SHUT | Pass through to vendor | `trip_at=3` |
| BLOWN | Instant fallback, no call made | `wait=10.0s` |
| PROBING | One trial call | `heal_at=1` |

---

## What the Tests Prove

1. **Nominal** — healthy vendor returns real output, gate stays SHUT
2. **Header** — `X-Student-ID` present on every route and method
3. **Trips and fast-fails** — gate blows at 3 strikes; subsequent calls are 60% faster
4. **Self-heals** — gate moves BLOWN → PROBING → SHUT when vendor recovers
5. **Blast test** — 20 concurrent requests against BLOWN gate complete in under 1.5s
