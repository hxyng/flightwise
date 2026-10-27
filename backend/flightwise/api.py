"""FastAPI server for FlightWise. Run: uvicorn flightwise.api:app --port 8000"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import threading

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import config, demo_cache, llm
from .models import AgentEvent, QueryResult
from .watcher import watcher

log = logging.getLogger("flightwise.api")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=llm.warm, daemon=True).start()
    task = asyncio.create_task(watcher.run())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="FlightWise", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


def _err(status: int, msg: str) -> JSONResponse:
    return JSONResponse({"error": msg, "detail": msg}, status_code=status)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    return _err(500, f"Something went wrong ({exc.__class__.__name__}). Please try again.")


class ChatBody(BaseModel):
    message: str
    history: list[dict] | None = None


class AskBody(BaseModel):
    question: str


class WatchBody(BaseModel):
    flight_number: str
    date: str | None = None


def _sse(ev: AgentEvent) -> dict:
    return {"event": ev.type, "data": ev.model_dump_json()}


async def chat_stream(message: str, history: list[dict] | None):
    """Relay agent events; on failure fall back to a cached answer, else a friendly error."""
    final = ""
    failed = False
    if config.CACHE_FIRST and not history and (hit := demo_cache.get_answer(message, static_only=True)):
        log.info("chat cache hit: %s", message)
        yield _sse(AgentEvent(type="delta", data={"text": hit}))
        yield _sse(AgentEvent(type="message", data={"text": hit, "cached": True}))
        yield _sse(AgentEvent(type="done", data={"history": [
            {"role": "user", "content": message}, {"role": "assistant", "content": hit}]}))
        return
    tools_used: set[str] = set()
    try:
        from .agent import run_agent   # lazy: built by B3
        async for ev in run_agent(message, history):
            if ev.type == "tool_call":
                tools_used.add(ev.data.get("name", ""))
            if ev.type == "message":
                final = ev.data.get("text", "")
            if ev.type == "error":
                failed = True
                continue          # held back: decide below whether the cache can cover it
            if ev.type == "done" and failed and not final:
                continue
            yield _sse(ev)
    except Exception as e:  # noqa: BLE001
        log.warning("agent failed: %s", e)
        failed = True
    if final and not failed:
        demo_cache.save_answer(message, final, tools_used)
    elif failed and not final:
        cached = demo_cache.get_answer(message)
        if cached:
            yield _sse(AgentEvent(type="message", data={"text": cached, "cached": True}))
        else:
            yield _sse(AgentEvent(type="error", data={
                "text": "The AI model or data source isn't reachable right now. "
                        "Check that Ollama is running and try again."}))
        yield _sse(AgentEvent(type="done", data={"history": history or []}))


@app.post("/api/chat")
async def chat(body: ChatBody):
    return EventSourceResponse(chat_stream(body.message, body.history), ping=15)


@app.post("/api/ask")
async def ask(body: AskBody):
    result: QueryResult | None = None
    # The BTS data is historical, so a saved answer to the same question is still correct.
    if config.CACHE_FIRST and (hit := demo_cache.get_result(body.question, offline=False)):
        log.info("ask cache hit: %s", body.question)
        return JSONResponse(hit.model_dump(mode="json"), headers={"X-FlightWise-Cache": "hit"})
    try:
        from .data import nl2sql   # lazy: built by B2
        result = await asyncio.to_thread(nl2sql.ask, body.question)
    except Exception as e:  # noqa: BLE001
        log.warning("ask failed: %s", e)
    if result is not None and not result.error:
        await asyncio.to_thread(demo_cache.save_result, body.question, result)
        return result
    cached = demo_cache.get_result(body.question)
    if cached:
        return JSONResponse(cached.model_dump(mode="json"), headers={"X-FlightWise-Cache": "demo"})
    if result is not None:
        return result
    return QueryResult(question=body.question,
                       error="The data service isn't reachable right now. Please try again.")


@app.get("/api/flights/search")
async def flights_search(origin: str, destination: str, date: str):
    try:
        from .providers import search
        return await search.search_flights(origin.upper(), destination.upper(), date)
    except Exception as e:  # noqa: BLE001
        return _err(502, f"Flight search failed: {e}")


@app.get("/api/flights/status/{flight_number}")
async def flight_status(flight_number: str, date: str | None = None):
    try:
        from .providers import status
        return await status.get_flight_status(flight_number, date)
    except Exception as e:  # noqa: BLE001
        return _err(502, f"Flight status unavailable: {e}")


@app.get("/api/risk")
async def risk(carrier: str, origin: str, hour: int | None = None, month: int | None = None):
    try:
        from .data import nl2sql
        return await asyncio.to_thread(nl2sql.delay_risk, carrier.upper(), origin.upper(), hour, month)
    except Exception as e:  # noqa: BLE001
        return _err(502, f"Delay risk unavailable: {e}")


@app.get("/api/watch")
async def watch_list():
    return watcher.list()


@app.post("/api/watch")
async def watch_add(body: WatchBody):
    try:
        return await watcher.add(body.flight_number, body.date)
    except Exception as e:  # noqa: BLE001
        return _err(502, f"Couldn't watch {body.flight_number}: {e}")


@app.delete("/api/watch/{flight_id}")
async def watch_remove(flight_id: str):
    if not await watcher.remove(flight_id):
        return _err(404, f"No watched flight with id {flight_id}")
    return {"ok": True}


async def event_stream():
    q = watcher.subscribe()
    try:
        while True:
            ev = await q.get()
            yield {"event": ev.type, "data": ev.model_dump_json()}
    finally:
        watcher.unsubscribe(q)


@app.get("/api/events")
async def events():
    return EventSourceResponse(event_stream(), ping=15)


def _provider_names() -> dict:
    for mod in ("status", "search", "mock"):
        try:
            m = __import__(f"flightwise.providers.{mod}", fromlist=["provider_names"])
            return m.provider_names()
        except Exception:  # noqa: BLE001
            continue
    try:
        from . import providers
        return providers.provider_names()
    except Exception:  # noqa: BLE001
        return {}


def _backend_name() -> str:
    try:
        from .data import db
        return db.backend_name()
    except Exception:  # noqa: BLE001
        return "unavailable"


@app.get("/api/health")
async def health():
    llm_ok = await asyncio.to_thread(llm.health)
    pn = await asyncio.to_thread(_provider_names)
    return {"llm": llm_ok, "model": config.OLLAMA_MODEL,
            "db": await asyncio.to_thread(_backend_name),
            "status": pn.get("status", "unavailable"), "search": pn.get("search", "unavailable")}


_dist = config.ROOT / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
