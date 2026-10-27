import asyncio

import pytest

import flightwise.agent as agent
from flightwise import answers

STATUS = {"status": {"flight_number": "AA100", "airline": "American Airlines", "origin": "CLT",
                     "destination": "PHX", "status": "boarding", "departure_local": "Mon 18:54 local",
                     "gate": "B35", "departure_delay_min": 0},
          "risk": {"label": "high", "pct_delayed_15": 48.4, "flights": 1234}}
OFFERS = [
    {"airline": "Alaska Airlines", "flight_numbers": ["AS2396"], "price": 131.0, "stops": 1,
     "departure_local": "Fri 00:30 local", "recommended": True,
     "why": "14% of similar flights delayed 15+ min, $131, 1 stop(s)",
     "risk": {"label": "low", "pct_delayed_15": 14.2}},
    {"airline": "Frontier Airlines", "flight_numbers": ["F9521"], "price": 65.0, "stops": 1,
     "risk": {"label": "medium", "pct_delayed_15": 26.0}},
]


def test_status_answer_has_exact_facts():
    text = answers.render("What's the status of AA100?", [("track_flight", STATUS, True)])
    assert "**AA100** (American Airlines) CLT → PHX: **Boarding**" in text
    assert "gate B35" in text and "on time" in text and "48% of 1,234 similar flights" in text


def test_offers_answer_puts_pick_first_and_cheapest_second():
    text = answers.render("Find me a flight OKC to DEN Friday", [("search_flights", OFFERS, True)])
    pick, cheapest = text.index("Agent pick: Alaska Airlines AS2396"), text.index("Cheapest: Frontier")
    assert pick < cheapest and "$65 (medium risk, 26% delayed)" in text


def test_render_defers_to_model_when_unsure():
    assert answers.render("track AA100", [("track_flight", STATUS, False)]) is None        # a tool failed
    assert answers.render("track AA100", [("mystery_tool", {}, True)]) is None             # unknown result
    assert answers.render("Track AA100 and keep me posted", [("track_flight", STATUS, True)]) is None
    both = answers.render("Track AA100 and keep me posted",
                          [("track_flight", STATUS, True), ("watch_flight", {"flight_number": "AA100"}, True)])
    assert "I'm watching **AA100**" in both


class Scripted:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, messages, tools=None, format=None, think=False):
        self.calls.append(messages)
        return {"role": "assistant", **self.replies.pop(0)}


@pytest.fixture
def templated(monkeypatch):
    monkeypatch.setattr(agent, "TEMPLATE_ANSWERS", True)

    async def track(flight_number, date=None):
        return STATUS
    monkeypatch.setitem(agent.FUNCS, "track_flight", track)


def test_agent_uses_template_plus_one_sentence(monkeypatch, templated):
    fake = Scripted([
        {"content": "", "tool_calls": [{"function": {"name": "track_flight", "arguments": {"flight_number": "AA100"}}}]},
        {"content": "Head to the gate early; this route is often late."},
    ])
    monkeypatch.setattr(agent.llm, "chat", fake)

    async def go():
        return [e async for e in agent.run_agent("What's the status of AA100?")]
    ev = asyncio.run(go())
    msg = next(e for e in ev if e.type == "message").data["text"]
    assert msg.startswith("**AA100** (American Airlines)") and msg.endswith("often late.")
    assert len(fake.calls) == 2 and "ONE short sentence" in fake.calls[1][-1]["content"]
    assert ev[-1].type == "done" and ev[-1].data["history"][-1]["content"] == msg
