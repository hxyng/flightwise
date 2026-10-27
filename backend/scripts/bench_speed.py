"""Time a fixed demo sequence through the real API (in-process) and record every LLM call.

Usage (from backend/):  python scripts/bench_speed.py <label>
Writes research/bench-<label>.json. Alternates data questions and agent requests on purpose,
the way a live demo does, so prompt-cache misses between prompt types show up.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flightwise import config, llm  # noqa: E402
from flightwise.api import app  # noqa: E402

STEPS = [
    ("ask", "When's the best time to fly out of OKC?"),        # one of the 5 demo questions
    ("chat", "Track AA100 and keep me posted"),
    ("ask", "Which airport has the most cancelled flights?"),  # not a demo question
    ("chat", "Find me a flight OKC to DEN this Friday"),
    ("ask", "Which day of the week has the worst delays?"),    # demo question
]


def run_step(client: TestClient, kind: str, text: str) -> dict:
    start = len(llm.STATS)
    t = time.time()
    first_text = None
    if kind == "ask":
        r = client.post("/api/ask", json={"question": text})
        body = r.json()
        answer, cached = body.get("answer"), "X-FlightWise-Cache" in r.headers   # "hit" or offline "demo"
    else:
        answer, cached = None, False
        with client.stream("POST", "/api/chat", json={"message": text}) as r:
            event = None
            for line in r.iter_lines():
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                elif line.startswith("data:") and event in ("delta", "message"):
                    if first_text is None:
                        first_text = round(time.time() - t, 1)
                    data = json.loads(line[5:])["data"]
                    if event == "message":
                        answer, cached = data.get("text"), bool(data.get("cached"))
    calls = list(llm.STATS)[start:]
    return {
        "kind": kind, "text": text, "wall_s": round(time.time() - t, 1), "first_text_s": first_text,
        "cached_answer": cached, "llm_calls": len(calls), "calls": calls,
        "answer": (answer or "")[:300],
    }


def main(label: str) -> None:
    out = Path(config.ROOT) / "research" / f"bench-{label}.json"
    with TestClient(app) as client:
        time.sleep(2)   # let the startup warm-up call finish so it isn't counted
        llm.STATS.clear()
        results = []
        for kind, text in STEPS:
            res = run_step(client, kind, text)
            results.append(res)
            print(f"{res['wall_s']:7.1f}s  {res['llm_calls']} calls  cached={res['cached_answer']!s:5}  {kind}: {text}")
    total = round(sum(r["wall_s"] for r in results), 1)
    out.write_text(json.dumps({"label": label, "total_s": total, "steps": results}, indent=2), encoding="utf-8")
    print(f"total {total}s -> {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "run")
