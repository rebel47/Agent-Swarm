"""OpenAI benchmark client. No paid requests without explicit --real."""
import argparse
import asyncio
import csv
import json
import os
import time
from pathlib import Path

import httpx

from evaluate import check_fixtures, score

ROOT = Path(__file__).parent


async def main(args):
    counts = check_fixtures(ROOT / "fixtures")
    if not args.real:
        print(json.dumps({"fixtures_validated": counts, "llm_calls": 0}, indent=2))
        return
    token = os.getenv("SWARM_API_TOKEN")
    if not token:
        raise SystemExit("SWARM_API_TOKEN is required; use the application's API_TOKEN")
    results = []
    async with httpx.AsyncClient(base_url=args.api.rstrip("/"), timeout=30,
                                 headers={"Authorization": "Bearer " + token}) as client:
        for fixture in ["small", "complex"]:
            truth = json.loads((ROOT / "fixtures" / fixture / "ground_truth.json").read_text())
            objective = "Investigate correctness, data isolation, query safety and performance. Cite exact source evidence and report uncertainty."
            for mode in ["single", "fixed", "adaptive"]:
                for repeat in range(args.repeats):
                    started = time.monotonic()
                    response = await client.post("/jobs", json={
                        "objective": objective, "workspace_id": fixture, "mode": mode,
                        "fixed_agent_count": args.fixed_agents if mode == "fixed" else None})
                    response.raise_for_status()
                    job_id = response.json()["id"]
                    while True:
                        response = await client.get("/jobs/" + job_id)
                        response.raise_for_status()
                        job = response.json()
                        if job["status"] != "RUNNING":
                            break
                        if time.monotonic() - started > args.timeout:
                            await client.post("/jobs/" + job_id + "/cancel")
                            raise TimeoutError("Benchmark job exceeded timeout; cancellation requested")
                        await asyncio.sleep(1)
                    metrics = job["metrics"]
                    results.append({
                        "evaluation": "real_openai", "fixture": fixture, "mode": mode,
                        "repeat": repeat, "job_id": job_id, "status": job["status"],
                        "execution_s": round(time.monotonic() - started, 3),
                        "tokens": metrics["tokens"], "estimated_cost_usd": metrics["estimated_cost_usd"],
                        "agents_created": metrics["total_agents"], "max_concurrency": metrics["max_concurrency"],
                        "redundant_requests": metrics["redundant_requests"], "recoveries": metrics["recoveries"],
                        "models": sorted({agent["model"] for agent in job["agents"]}),
                        "model_allocation": metrics["model_allocation"],
                        "model_costs": metrics["model_costs"],
                        "cached_input_tokens": metrics["cached_input_tokens"],
                        "cache_write_tokens": metrics["cache_write_tokens"],
                        "reasoning_tokens": metrics["reasoning_tokens"],
                        "limits": metrics["limits"], **score(job["report"], truth)})
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    with (output / "results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=results[0])
        writer.writeheader()
        writer.writerows(results)
    summary = ["# Real LLM benchmark results", "",
               "Counts match known source locations; semantic correctness requires review.", "",
               "| Fixture | Mode | Status | Matches | Tokens | Cost estimate | Agents |",
               "|---|---|---|---:|---:|---:|---:|"]
    for row in results:
        summary.append("| {fixture} | {mode} | {status} | {matched_known_defects} | {tokens} | {estimated_cost_usd:.6f} | {agents_created} |".format(**row))
    (output / "summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print(f"Saved {len(results)} real OpenAI evaluations to {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real", action="store_true", help="Explicitly authorize paid investigations")
    parser.add_argument("--api", default="http://localhost:8000/api/v1")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--fixed-agents", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--output", default=str(ROOT / "results"))
    args = parser.parse_args()
    if args.repeats < 1 or args.fixed_agents < 1:
        parser.error("repeats and fixed-agents must be positive")
    asyncio.run(main(args))
