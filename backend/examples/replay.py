"""Send a fake customer conversation to the running local API."""

from __future__ import annotations

import json
import time
from urllib.request import Request, urlopen

BASE_URL = "http://127.0.0.1:8000"


def post(path: str, payload: dict | None = None) -> dict:
    request = Request(
        BASE_URL + path,
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def main() -> None:
    session = post("/api/v1/sessions", {
        "product": {
            "name": "Demo Python Course (fictional)",
            "description": "Example £99/month subscription",
            "facts": [
                "The course costs £99 per month.",
                "Lessons are recorded and can be replayed.",
                "The course provides a self-paced study option.",
                "Refund policy has not been specified.",
            ],
        }
    })
    session_id = session["session_id"]
    print("Created session:", session_id)

    script = [
        ("salesperson", "What are you hoping to learn?"),
        ("customer", "I want to learn Python for work."),
        ("salesperson", "What questions do you have about the course?"),
        ("customer", "Are the lessons recorded?"),
        ("customer", "I like the course, but £99 per month is too expensive."),
        ("salesperson", "I can help you figure out whether it suits your budget."),
        ("customer", "I'd sign up if there were more flexibility."),
    ]
    for speaker, text in script:
        result = post(f"/api/v1/sessions/{session_id}/turns", {"speaker": speaker, "text": text})
        analysis = result["analysis"]
        print(f"\n{speaker.upper()}: {text}")
        print("  Signal:", analysis["buying_signal"], "| Objections:", analysis["objections"])
        recommendation = analysis["recommendation"]
        if recommendation:
            print("  Coaching:", recommendation["suggested_response"])
            if recommendation["supporting_facts"]:
                print("  Approved facts:", recommendation["supporting_facts"])
        time.sleep(0.4)

    post(f"/api/v1/sessions/{session_id}/end")
    print("\nSession ended.")


if __name__ == "__main__":
    main()
