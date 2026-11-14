"""Compare OpenRouter STT models against the same recorded benchmark clips."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
import statistics
import sys
from collections.abc import Iterable
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402

DEFAULT_MANIFEST = ROOT / "benchmarks" / "stt" / "manifest.json"
DEFAULT_OUTPUT = ROOT / "benchmarks" / "stt" / "results" / "latest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--runs", type=int, default=None, help="Runs per model per clip")
    parser.add_argument(
        "--models",
        nargs="+",
        default=None,
        help="Override the model IDs listed in the manifest",
    )
    return parser.parse_args()


def normalized_words(text: str) -> list[str]:
    return "".join(character.lower() if character.isalnum() else " " for character in text).split()


def word_error_rate(expected: str, actual: str) -> float:
    reference = normalized_words(expected)
    hypothesis = normalized_words(actual)
    if not reference:
        return 0.0 if not hypothesis else 1.0
    previous = list(range(len(hypothesis) + 1))
    for reference_index, reference_word in enumerate(reference, start=1):
        current = [reference_index]
        for hypothesis_index, hypothesis_word in enumerate(hypothesis, start=1):
            current.append(
                min(
                    previous[hypothesis_index] + 1,
                    current[hypothesis_index - 1] + 1,
                    previous[hypothesis_index - 1]
                    + (reference_word != hypothesis_word),
                )
            )
        previous = current
    return previous[-1] / len(reference)


def percentile_95(values: Iterable[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[math.ceil(len(ordered) * 0.95) - 1]


async def transcribe(
    client: httpx.AsyncClient,
    model: str,
    clip_path: Path,
    language: str | None,
) -> dict[str, Any]:
    audio = await asyncio.to_thread(clip_path.read_bytes)
    payload: dict[str, Any] = {
        "model": model,
        "input_audio": {
            "data": base64.b64encode(audio).decode("ascii"),
            "format": clip_path.suffix.lstrip(".").lower(),
        },
    }
    if language:
        payload["language"] = language

    started = perf_counter()
    response = await client.post("/audio/transcriptions", json=payload)
    elapsed = perf_counter() - started
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or not isinstance(body.get("text"), str):
        raise RuntimeError("STT response did not contain text")
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    cost = usage.get("cost") if isinstance(usage, dict) else None
    return {
        "latency_seconds": round(elapsed, 3),
        "text": body["text"].strip(),
        "cost_usd": cost if isinstance(cost, (float, int)) else None,
    }


async def run() -> int:
    arguments = parse_args()
    manifest_path = arguments.manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    runs = arguments.runs or int(manifest.get("runs_per_model", 3))
    models = arguments.models or manifest.get("models", [])
    samples = manifest.get("samples", [])
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required for the benchmark")
    if runs < 1 or not models or not samples:
        raise RuntimeError("Manifest must include samples, models, and at least one run")

    for sample in samples:
        path = manifest_path.parent / sample["file"]
        if not path.is_file():
            raise FileNotFoundError(f"Missing benchmark clip: {path}")

    results: list[dict[str, Any]] = []
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "HTTP-Referer": "http://localhost:8000",
        "X-Title": "Bella AI STT benchmark",
    }
    async with httpx.AsyncClient(
        base_url="https://openrouter.ai/api/v1",
        timeout=settings.openrouter_timeout_seconds,
        headers=headers,
    ) as client:
        for sample in samples:
            clip_path = manifest_path.parent / sample["file"]
            for model in models:
                for attempt in range(1, runs + 1):
                    try:
                        result = await transcribe(client, model, clip_path, settings.whisper_language)
                        result.update(
                            {
                                "sample_id": sample["id"],
                                "scenario": sample["scenario"],
                                "expected_text": sample["expected_text"],
                                "model": model,
                                "attempt": attempt,
                                "wer": (
                                    None
                                    if sample.get("manual_accuracy_review", False)
                                    else round(
                                        word_error_rate(sample["expected_text"], result["text"]),
                                        4,
                                    )
                                ),
                                "manual_accuracy_review": sample.get(
                                    "manual_accuracy_review", False
                                ),
                                "success": True,
                            }
                        )
                    except (httpx.HTTPError, RuntimeError, ValueError) as error:
                        result = {
                            "sample_id": sample["id"],
                            "scenario": sample["scenario"],
                            "model": model,
                            "attempt": attempt,
                            "success": False,
                            "error": str(error),
                        }
                    results.append(result)
                    # Windows PowerShell may use cp1252 and cannot display Tamil text.
                    # Keep the JSON report UTF-8, but make console progress portable.
                    print(json.dumps(result, ensure_ascii=True))

    summary: dict[str, dict[str, float | int]] = {}
    for model in models:
        successful = [item for item in results if item["model"] == model and item["success"]]
        latencies = [float(item["latency_seconds"]) for item in successful]
        wers = [float(item["wer"]) for item in successful if item["wer"] is not None]
        costs = [float(item["cost_usd"]) for item in successful if item["cost_usd"] is not None]
        summary[model] = {
            "successful_runs": len(successful),
            "failed_runs": len([item for item in results if item["model"] == model]) - len(successful),
            "average_latency_seconds": round(statistics.mean(latencies), 3) if latencies else 0.0,
            "p95_latency_seconds": round(percentile_95(latencies), 3),
            "average_wer": round(statistics.mean(wers), 4) if wers else 1.0,
            "total_cost_usd": round(sum(costs), 6),
        }

    report = {"manifest": str(manifest_path), "runs_per_model": runs, "summary": summary, "results": results}
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nSummary")
    print(json.dumps(summary, indent=2))
    print(f"\nSaved {arguments.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
