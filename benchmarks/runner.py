"""
benchmarks/runner.py — Runs the benchmark suite against the live JARVIS agent.
"""

from __future__ import annotations

import asyncio
import time
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from benchmarks.suite import BENCHMARK_SUITE, BenchmarkCase
from ga.logger import ga_logger
from logger import get_logger

if TYPE_CHECKING:
    from agent.agent import JarvisAgent

log = get_logger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "ga_logs.db"

BENCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS benchmark_runs (
    id          TEXT PRIMARY KEY,
    case_id     TEXT NOT NULL,
    query_class TEXT NOT NULL,
    score       REAL NOT NULL,
    passed      INTEGER NOT NULL,
    latency_ms  INTEGER,
    response    TEXT,
    error       TEXT,
    timestamp   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS benchmark_summaries (
    id              TEXT PRIMARY KEY,
    total_cases     INTEGER,
    passed          INTEGER,
    failed          INTEGER,
    avg_score       REAL,
    avg_latency_ms  INTEGER,
    scores_by_class TEXT,
    timestamp       REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bench_case_id   ON benchmark_runs(case_id);
CREATE INDEX IF NOT EXISTS idx_bench_timestamp ON benchmark_runs(timestamp);
"""


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.executescript(BENCH_SCHEMA)
    return c


class BenchmarkRunner:
    PASS_THRESHOLD = 0.6

    def __init__(self, agent: "JarvisAgent"):
        self.agent = agent

    def _run_case(self, case: BenchmarkCase) -> dict:
        import uuid
        entry_id = str(uuid.uuid4())[:12]
        t0 = time.time()
        error = None
        response = ""
        score = 0.0

        try:
            response = self.agent.chat(case.prompt, session_id=f"bench_{case.id}_{entry_id}")
            score = case.score_fn(response)
            score = max(0.0, min(1.0, score))
        except Exception as e:
            error = str(e)
            score = 0.0
            log.error("bench_case_error", case_id=case.id, error=error)

        latency_ms = int((time.time() - t0) * 1000)
        passed = score >= self.PASS_THRESHOLD

        log.info("bench_case_done", case_id=case.id, score=round(score, 3),
                 passed=passed, latency_ms=latency_ms)

        with _conn() as c:
            c.execute(
                """INSERT INTO benchmark_runs
                   (id, case_id, query_class, score, passed, latency_ms, response, error, timestamp)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (entry_id, case.id, case.query_class, score, int(passed),
                 latency_ms, response[:500], error, time.time()),
            )

        ga_logger.log_inference(
            session_id=f"bench_{case.id}_{entry_id}",
            message=case.prompt,
            response=response,
            latency_ms=latency_ms,
            query_class=case.query_class,
            genome_id="default",
        )

        return {
            "id": entry_id,
            "case_id": case.id,
            "query_class": case.query_class,
            "score": score,
            "passed": passed,
            "latency_ms": latency_ms,
            "response": response[:200],
            "error": error,
        }

    async def run_all(self, case_ids: list[str] | None = None) -> dict:
        import json, uuid

        cases = BENCHMARK_SUITE
        if case_ids:
            cases = [c for c in cases if c.id in case_ids]

        log.info("bench_run_start", total=len(cases))
        results = []

        for case in cases:
            result = await asyncio.get_event_loop().run_in_executor(
                None, self._run_case, case
            )
            results.append(result)
            await asyncio.sleep(1)

        passed = sum(1 for r in results if r["passed"])
        failed = len(results) - passed
        avg_score = sum(r["score"] for r in results) / max(len(results), 1)
        avg_latency = int(sum(r["latency_ms"] for r in results) / max(len(results), 1))

        class_scores: dict[str, list[float]] = {}
        for r in results:
            class_scores.setdefault(r["query_class"], []).append(r["score"])
        class_avg = {k: round(sum(v) / len(v), 3) for k, v in class_scores.items()}

        summary = {
            "id": str(uuid.uuid4())[:12],
            "total_cases": len(results),
            "passed": passed,
            "failed": failed,
            "pass_rate": round(passed / max(len(results), 1), 3),
            "avg_score": round(avg_score, 3),
            "avg_latency_ms": avg_latency,
            "scores_by_class": class_avg,
            "results": results,
        }

        with _conn() as c:
            c.execute(
                """INSERT INTO benchmark_summaries
                   (id, total_cases, passed, failed, avg_score, avg_latency_ms, scores_by_class, timestamp)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (summary["id"], len(results), passed, failed,
                 avg_score, avg_latency, json.dumps(class_avg), time.time()),
            )

        log.info("bench_run_done", passed=passed, failed=failed,
                 avg_score=round(avg_score, 3), scores_by_class=class_avg)

        return summary

    def get_history(self, limit: int = 10) -> list[dict]:
        with _conn() as c:
            rows = c.execute(
                "SELECT * FROM benchmark_summaries ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_drift(self, case_id: str, limit: int = 20) -> list[dict]:
        with _conn() as c:
            rows = c.execute(
                """SELECT score, passed, latency_ms, timestamp
                   FROM benchmark_runs WHERE case_id = ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (case_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]
