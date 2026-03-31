"""
benchmarks/suite.py — JARVIS self-benchmark test cases.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class BenchmarkCase:
    id: str
    query_class: str
    prompt: str
    score_fn: Callable[[str], float]
    timeout_s: int = 45
    tags: list[str] = field(default_factory=list)


def _contains_any(response: str, keywords: list[str]) -> bool:
    r = response.lower()
    return any(k.lower() in r for k in keywords)

def _contains_all(response: str, keywords: list[str]) -> bool:
    r = response.lower()
    return all(k.lower() in r for k in keywords)

def _not_error(response: str) -> bool:
    error_phrases = ["i encountered an error", "error:", "failed to", "i'm unable"]
    return not any(p in response.lower() for p in error_phrases)

def _length_score(response: str, min_chars: int = 50) -> float:
    return min(1.0, len(response) / max(min_chars, 1))


BENCHMARK_SUITE: list[BenchmarkCase] = [

    BenchmarkCase(
        id="general_001",
        query_class="general",
        prompt="What is the capital of France?",
        score_fn=lambda r: 1.0 if "paris" in r.lower() else 0.0,
    ),

    BenchmarkCase(
        id="general_002",
        query_class="general",
        prompt="What is 17 multiplied by 43?",
        score_fn=lambda r: 1.0 if "731" in r else 0.0,
    ),

    BenchmarkCase(
        id="general_003",
        query_class="general",
        prompt="Summarize the concept of compound interest in 2-3 sentences.",
        score_fn=lambda r: (
            0.4 * _not_error(r) +
            0.3 * _contains_any(r, ["interest", "compound", "principal", "grows"]) +
            0.3 * _length_score(r, min_chars=80)
        ),
    ),

    BenchmarkCase(
        id="datetime_001",
        query_class="general",
        prompt="What is today's date and time?",
        score_fn=lambda r: (
            0.5 * _contains_any(r, ["2025", "2026", "2027", "monday", "tuesday",
                                     "wednesday", "thursday", "friday", "saturday", "sunday"]) +
            0.5 * _contains_any(r, ["am", "pm", ":", "time"])
        ),
        tags=["get_current_datetime"],
    ),

    BenchmarkCase(
        id="file_001",
        query_class="code",
        prompt="Create a file at ~/jarvis_bench_test.txt with the content 'benchmark ok'",
        score_fn=lambda r: (
            1.0 if _contains_any(r, ["written", "created", "benchmark ok", "✅"]) and _not_error(r)
            else 0.3 if _not_error(r)
            else 0.0
        ),
        tags=["write_file"],
    ),

    BenchmarkCase(
        id="file_002",
        query_class="code",
        prompt="Read the file at ~/jarvis_bench_test.txt and tell me its contents.",
        score_fn=lambda r: 1.0 if "benchmark ok" in r.lower() else 0.0,
        tags=["read_file"],
    ),

    BenchmarkCase(
        id="file_003",
        query_class="code",
        prompt="List the files in my home directory.",
        score_fn=lambda r: (
            0.5 * _not_error(r) +
            0.5 * _contains_any(r, ["downloads", "documents", "desktop", "library", "📄", "📁"])
        ),
        tags=["list_directory"],
    ),

    BenchmarkCase(
        id="code_001",
        query_class="code",
        prompt="Run this Python code and tell me the output: print(sum(range(1, 101)))",
        score_fn=lambda r: 1.0 if "5050" in r else 0.0,
        tags=["run_python"],
    ),

    BenchmarkCase(
        id="code_002",
        query_class="code",
        prompt="Write and run a Python snippet that generates the first 5 fibonacci numbers.",
        score_fn=lambda r: (
            1.0 if _contains_all(r, ["1", "2", "3", "5", "8"])
            else 0.5 if _contains_any(r, ["fibonacci", "fib", "1, 1, 2, 3"])
            else 0.0
        ),
        tags=["run_python"],
    ),

    BenchmarkCase(
        id="web_001",
        query_class="general",
        prompt="Search the web for the current price of gold per ounce.",
        score_fn=lambda r: (
            0.5 * _not_error(r) +
            0.5 * _contains_any(r, ["$", "usd", "ounce", "oz", "gold", "per"])
        ),
        tags=["web_search"],
        timeout_s=60,
    ),

    BenchmarkCase(
        id="web_002",
        query_class="general",
        prompt="Search the web: who is the current US Secretary of the Treasury?",
        score_fn=lambda r: (
            0.5 * _not_error(r) +
            0.5 * _contains_any(r, ["bessent", "secretary", "treasury"])
        ),
        tags=["web_search"],
        timeout_s=60,
    ),

    BenchmarkCase(
        id="memory_001",
        query_class="recall",
        prompt="What do you know about me?",
        score_fn=lambda r: (
            0.4 * _not_error(r) +
            0.3 * _contains_any(r, ["mason", "indiana", "finance", "horn", "jarvis"]) +
            0.3 * _length_score(r, min_chars=50)
        ),
    ),

    BenchmarkCase(
        id="shell_001",
        query_class="code",
        prompt="Run the shell command: echo 'jarvis_bench_shell_ok'",
        score_fn=lambda r: 1.0 if "jarvis_bench_shell_ok" in r else 0.0,
        tags=["run_shell"],
    ),

    BenchmarkCase(
        id="study_001",
        query_class="study",
        prompt="Explain the difference between systematic and unsystematic risk in finance.",
        score_fn=lambda r: (
            0.3 * _contains_any(r, ["systematic", "market", "diversif"]) +
            0.3 * _contains_any(r, ["unsystematic", "specific", "company", "firm"]) +
            0.2 * _not_error(r) +
            0.2 * _length_score(r, min_chars=100)
        ),
    ),

    BenchmarkCase(
        id="study_002",
        query_class="study",
        prompt="What is the capital asset pricing model (CAPM)?",
        score_fn=lambda r: (
            0.4 * _contains_any(r, ["capm", "capital asset", "expected return", "beta"]) +
            0.3 * _contains_any(r, ["risk", "market", "premium"]) +
            0.3 * _length_score(r, min_chars=80)
        ),
    ),

    BenchmarkCase(
        id="macos_001",
        query_class="general",
        prompt="Send me a macOS notification with title 'JARVIS Bench' and message 'test ok'",
        score_fn=lambda r: (
            1.0 if _contains_any(r, ["sent", "notification", "✅", "displayed"]) and _not_error(r)
            else 0.3 if _not_error(r)
            else 0.0
        ),
        tags=["send_notification"],
    ),
]
