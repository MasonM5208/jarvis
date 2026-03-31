"""
benchmarks/scheduler.py — Background benchmark loop + FastAPI endpoints.
"""

from __future__ import annotations
import asyncio
from typing import TYPE_CHECKING
from logger import get_logger

if TYPE_CHECKING:
    from agent.agent import JarvisAgent

log = get_logger(__name__)
INTERVAL_HOURS = 6


async def _benchmark_loop(agent: "JarvisAgent"):
    from benchmarks.runner import BenchmarkRunner
    runner = BenchmarkRunner(agent)
    await asyncio.sleep(300)  # wait 5 min after startup
    while True:
        try:
            log.info("bench_scheduled_run_start")
            summary = await runner.run_all()
            log.info("bench_scheduled_run_done", passed=summary["passed"],
                     total=summary["total_cases"], avg_score=summary["avg_score"])
        except Exception as e:
            log.error("bench_scheduled_run_error", error=str(e))
        await asyncio.sleep(INTERVAL_HOURS * 3600)


def start_benchmark_scheduler(agent: "JarvisAgent"):
    asyncio.create_task(_benchmark_loop(agent))
    log.info("bench_scheduler_started", interval_hours=INTERVAL_HOURS)


from pydantic import BaseModel
from typing import Optional

class BenchRunRequest(BaseModel):
    case_ids: Optional[list[str]] = None


def register_benchmark_routes(app, agent: "JarvisAgent"):
    from fastapi import HTTPException
    from benchmarks.runner import BenchmarkRunner

    @app.post("/bench/run")
    async def run_benchmark(req: BenchRunRequest):
        runner = BenchmarkRunner(agent)
        try:
            return await runner.run_all(case_ids=req.case_ids)
        except Exception as e:
            raise HTTPException(500, str(e))

    @app.get("/bench/history")
    async def bench_history(limit: int = 10):
        return BenchmarkRunner(agent).get_history(limit=limit)

    @app.get("/bench/drift/{case_id}")
    async def bench_drift(case_id: str, limit: int = 20):
        return BenchmarkRunner(agent).get_drift(case_id=case_id, limit=limit)

    @app.get("/bench/cases")
    async def bench_cases():
        from benchmarks.suite import BENCHMARK_SUITE
        return [
            {"id": c.id, "query_class": c.query_class, "tags": c.tags, "prompt": c.prompt[:80]}
            for c in BENCHMARK_SUITE
        ]
