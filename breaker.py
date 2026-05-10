import asyncio
import time
import pytest
import httpx

ROOT = "http://localhost:8000"

async def fresh_slate(c):
    await c.post(f"{ROOT}/v1/debug/vendor", json={"offline": False})
    await c.delete(f"{ROOT}/v1/debug/gate")
    await asyncio.sleep(0.05)

async def kill_vendor(c):
    await c.post(f"{ROOT}/v1/debug/vendor", json={"offline": True})

async def revive_vendor(c):
    await c.post(f"{ROOT}/v1/debug/vendor", json={"offline": False})

@pytest.mark.asyncio
async def test_nominal_flow():
    async with httpx.AsyncClient(timeout=10) as c:
        await fresh_slate(c)
        r = await c.post(f"{ROOT}/v1/generate", json={"text": "summarise distributed systems"})
        assert r.status_code == 200
        body = r.json()
        assert body["degraded"] is False
        assert body["gate"] == "SHUT"
        assert "Generated response" in body["output"]
        print(f"\n[PASS] nominal: {body['output'][:55]}")

@pytest.mark.asyncio
async def test_sid_header_everywhere():
    async with httpx.AsyncClient(timeout=10) as c:
        for path, method, payload in [
            ("/ping",        "GET",  None),
            ("/v1/generate", "POST", {"text": "x"}),
            ("/v1/gate",     "GET",  None),
        ]:
            r = await (c.get(f"{ROOT}{path}") if method == "GET"
                       else c.post(f"{ROOT}{path}", json=payload))
            assert "x-student-id" in r.headers, f"missing header on {path}"
            assert r.headers["x-student-id"] != ""
        print("\n[PASS] X-Student-ID present on all routes")

@pytest.mark.asyncio
async def test_gate_blows_and_fast_fails():
    async with httpx.AsyncClient(timeout=12) as c:
        await fresh_slate(c)
        await kill_vendor(c)

        times = []
        print("\n--- vendor offline ---")
        for i in range(6):
            t0 = time.monotonic()
            r  = await c.post(f"{ROOT}/v1/generate", json={"text": f"req {i}"})
            ms = (time.monotonic() - t0) * 1000
            times.append(ms)
            b  = r.json()
            assert b["degraded"] is True, f"expected degraded on call {i}"
            print(f"  call {i+1}: gate={b['gate']}  {ms:.0f}ms")

        slow = sum(times[:3]) / 3
        fast = sum(times[3:]) / 3
        assert fast < slow * 0.4, f"fast-fail not fast enough: {fast:.0f}ms vs {slow:.0f}ms"

        snap = (await c.get(f"{ROOT}/v1/gate")).json()
        assert snap["gate"] == "BLOWN"
        print(f"\n[PASS] gate BLOWN after 3 strikes  fast-fail={fast:.0f}ms vs slow={slow:.0f}ms")

@pytest.mark.asyncio
async def test_self_heal():
    async with httpx.AsyncClient(timeout=20) as c:
        await fresh_slate(c)
        await kill_vendor(c)
        for _ in range(3):
            await c.post(f"{ROOT}/v1/generate", json={"text": "break it"})

        snap = (await c.get(f"{ROOT}/v1/gate")).json()
        assert snap["gate"] == "BLOWN"

        await revive_vendor(c)
        print("\n  vendor back up — waiting 11s for cooldown...")
        await asyncio.sleep(11)

        r = await c.post(f"{ROOT}/v1/generate", json={"text": "are we live?"})
        b = r.json()
        assert b["degraded"] is False
        assert b["gate"] == "SHUT"
        print(f"[PASS] gate self-healed to SHUT  output={b['output'][:40]}")

@pytest.mark.asyncio
async def test_blast_open_gate():
    async with httpx.AsyncClient(timeout=15) as c:
        await fresh_slate(c)
        await kill_vendor(c)
        for _ in range(3):
            await c.post(f"{ROOT}/v1/generate", json={"text": "trip"})
        await asyncio.sleep(0.1)

        print("\n--- blasting 20 concurrent requests at BLOWN gate ---")
        t0 = time.monotonic()
        results = await asyncio.gather(*[
            c.post(f"{ROOT}/v1/generate", json={"text": f"blast {i}"})
            for i in range(20)
        ])
        wall = (time.monotonic() - t0) * 1000

        assert all(r.json()["degraded"] for r in results)
        assert wall < 1500, f"20 fast-fails took {wall:.0f}ms — too slow"
        print(f"[PASS] 20 requests resolved in {wall:.0f}ms  (without breaker: ~1,200,000ms)")


async def main():
    suite = [
        test_nominal_flow,
        test_sid_header_everywhere,
        test_gate_blows_and_fast_fails,
        test_self_heal,
        test_blast_open_gate,
    ]
    ok = 0
    print("=" * 55)
    print("NoteFlow  —  Gate (Circuit Breaker) Test Suite")
    print("=" * 55)
    for fn in suite:
        try:
            await fn()
            ok += 1
        except Exception as e:
            print(f"[FAIL] {fn.__name__}: {e}")
    print(f"\n{'='*55}")
    print(f"  {ok}/{len(suite)} passed")
    print("=" * 55)

if __name__ == "__main__":
    asyncio.run(main())
