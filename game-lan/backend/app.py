from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import socket
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

try:
    from .ai.pdf_engine import PdfHintEngine  # type: ignore
    from .state import GameState  # type: ignore
except ImportError:  # pragma: no cover - fallback when run as script
    from ai.pdf_engine import PdfHintEngine
    from state import GameState


logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("azure-kaisen")

BASE_DIR = Path(__file__).resolve().parent
DOCS_DIR = BASE_DIR / "docs"
PDF_PATH = DOCS_DIR / "5일차.pdf"
RULES_PATH = BASE_DIR / "ai" / "rules.json"

app = FastAPI(title="에저회전 Azure Kaisen", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TURN_TIMER_SECONDS = int(os.getenv("TURN_TIMER_SECONDS", "30"))
state = GameState(max_rounds=3, turn_timer_seconds=TURN_TIMER_SECONDS)
hint_engine = PdfHintEngine(pdf_path=PDF_PATH, rules_path=RULES_PATH)


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: Dict[str, WebSocket] = {}
        self.ws_to_player: Dict[WebSocket, str] = {}
        self.lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()

    async def register(self, player_id: str, websocket: WebSocket) -> None:
        async with self.lock:
            self.connections[player_id] = websocket
            self.ws_to_player[websocket] = player_id

    async def unregister(self, websocket: WebSocket) -> Optional[str]:
        async with self.lock:
            player_id = self.ws_to_player.pop(websocket, None)
            if player_id:
                self.connections.pop(player_id, None)
            return player_id

    async def send_to(self, player_id: str, message: Dict[str, Any]) -> None:
        websocket = self.connections.get(player_id)
        if not websocket:
            return
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to send to %s: %s", player_id, exc)

    async def broadcast(self, message: Dict[str, Any]) -> None:
        data = json.dumps(message)
        to_remove = []
        for pid, websocket in self.connections.items():
            try:
                await websocket.send_text(data)
            except Exception:
                to_remove.append(pid)
        for pid in to_remove:
            self.connections.pop(pid, None)

    async def close(self, player_id: str) -> None:
        websocket = self.connections.get(player_id)
        if websocket:
            await websocket.close()


manager = ConnectionManager()


def lan_address() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
    except Exception:  # pragma: no cover - fallback path
        ip = socket.gethostbyname(socket.gethostname())
    return ip


@app.on_event("startup")
async def on_startup() -> None:
    ip = lan_address()
    logger.info("Backend ready on http://%s:8000 (WS /ws)", ip)
    logger.info("Frontend dev server expected on http://%s:5173", ip)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.get("/config")
async def config() -> JSONResponse:
    return JSONResponse({"rounds": state.max_rounds, "turnSeconds": state.turn_timer_seconds})


@app.get("/docs/5일차.pdf")
async def get_pdf() -> FileResponse:
    return FileResponse(PDF_PATH)


@app.get("/db")
async def dump_state() -> JSONResponse:
    snapshot = await state.snapshot()
    return JSONResponse(snapshot)


async def send_room_state() -> None:
    public_state = await state.to_public_state()
    await manager.broadcast({"type": "room.state", "payload": public_state})


async def send_turn_event() -> None:
    player = await state.current_turn_player()
    if player:
        await manager.broadcast({"type": "turn.next", "payload": {"playerId": player.id, "name": player.name}})


async def run_timer(current_round: int) -> None:
    logger.info("Timer task started for round %s", current_round)
    while True:
        remaining = await state.update_remaining_ms()
        await manager.broadcast({"type": "tick", "payload": {"round": current_round, "timerMs": remaining}})
        if remaining <= 0:
            logger.info("Timer expired for round %s", current_round)
            await force_resolve()
            break
        await asyncio.sleep(1)


async def start_round_flow() -> None:
    started = await state.start_round_if_possible()
    if not started:
        return
    await send_room_state()
    await send_turn_event()
    await manager.broadcast({"type": "round.started", "payload": {"round": state.round}})
    if state.timer_task and not state.timer_task.done():
        state.timer_task.cancel()
    state.timer_task = asyncio.create_task(run_timer(state.round))


async def ensure_timer_cancelled() -> None:
    if state.timer_task and not state.timer_task.done():
        state.timer_task.cancel()
        try:
            await state.timer_task
        except asyncio.CancelledError:
            pass
        finally:
            state.timer_task = None


async def force_resolve() -> None:
    await ensure_timer_cancelled()
    await state.ensure_all_submissions()
    await state.finish_round()
    await send_room_state()
    await resolve_round()


async def resolve_round() -> None:
    round_index = state.round
    secret = await state.get_secret(round_index) or ""
    submissions = await state.get_round_submissions(round_index)
    previous_summaries = []
    for idx in range(1, round_index):
        round_entries = await state.get_round_submissions(idx)
        summary = ", ".join(filter(None, (sub.word for sub in round_entries.values())))
        if summary:
            previous_summaries.append(summary)

    for submission in submissions.values():
        result = hint_engine.generate_hint(
            secret=secret,
            submitted_word=submission.word,
            previous_round_summaries=previous_summaries,
        )
        submission.hint = result.hint
        submission.ai_score_suggestion = result.ai_score_suggestion
        for flag in result.flags:
            if flag not in submission.flags:
                submission.flags.append(flag)

    scored = await state.calculate_scores()

    # Send personal results
    for player_id, submission in scored.items():
        await manager.send_to(
            player_id,
            {
                "type": "round.result:me",
                "payload": {
                    "round": round_index,
                    "word": submission.word,
                    "hint": submission.hint,
                    "score": submission.total_score,
                    "flags": submission.flags,
                    "aiScoreSuggestion": submission.ai_score_suggestion,
                },
            },
        )

    # Public summary with anonymised entries
    player_order = await state.get_player_order()
    summary_entries = []
    for idx, player_id in enumerate(player_order):
        submission = scored.get(player_id)
        if not submission:
            continue
        summary_entries.append(
            {
                "slot": idx + 1,
                "word": submission.word if submission.word else "(미제출)",
                "score": submission.total_score,
                "flags": submission.flags,
            }
        )
    summary_payload = {"round": round_index, "entries": summary_entries}
    await manager.broadcast({"type": "round.summary", "payload": summary_payload})
    await send_room_state()

    await state.prepare_next_round()
    phase_state = await state.to_public_state()
    await manager.broadcast({"type": "phase.changed", "payload": {"phase": phase_state["phase"], "round": phase_state["round"]}})

    if phase_state["phase"] == "end":
        winner = await state.winner()
        if winner:
            await manager.broadcast({"type": "end.winner", "payload": winner})
        stats = await state.build_stats_payload()
        await manager.broadcast({"type": "stats.open", "payload": stats})
    else:
        await manager.broadcast({"type": "round.ready", "payload": {"round": phase_state["round"] + 1}})


async def handle_set_secret(player_id: str, payload: Dict[str, Any]) -> None:
    player = await state.get_player(player_id)
    if not player or not player.is_host:
        await manager.send_to(player_id, {"type": "error", "payload": {"message": "호스트만 설정할 수 있습니다."}})
        return
    secret = payload.get("secret", "").strip()
    if not secret:
        await manager.send_to(player_id, {"type": "error", "payload": {"message": "제시어를 입력하세요."}})
        return
    phase = (await state.to_public_state())["phase"]
    if phase == "end":
        await manager.send_to(player_id, {"type": "error", "payload": {"message": "게임이 종료되었습니다."}})
        return
    await state.set_secret(secret)
    await manager.send_to(player_id, {"type": "host.secret.accepted", "payload": {"round": state.round + 1}})
    await start_round_flow()


async def handle_submit_word(player_id: str, payload: Dict[str, Any]) -> None:
    current_state = await state.to_public_state()
    if current_state["phase"] != "collecting":
        await manager.send_to(player_id, {"type": "error", "payload": {"message": "지금은 제출할 수 없습니다."}})
        return
    if current_state["turn"] != player_id:
        await manager.send_to(player_id, {"type": "error", "payload": {"message": "당신의 턴이 아닙니다."}})
        return

    word = (payload.get("word") or "").strip()
    if not word:
        await manager.send_to(player_id, {"type": "error", "payload": {"message": "단어를 입력하세요."}})
        return
    if len(word.split()) > 1:
        await manager.send_to(player_id, {"type": "error", "payload": {"message": "단어는 공백 없이 입력하세요."}})
        return

    # Duplicate check
    submissions = await state.get_round_submissions(state.round)
    normalized = word.lower()
    for submission in submissions.values():
        if submission.word.lower() == normalized:
            await manager.send_to(player_id, {"type": "error", "payload": {"message": "이미 제출된 단어입니다."}})
            return

    flags = []
    lowered = word.lower()
    for forbidden in hint_engine.rules.get("forbidden", []):
        if forbidden.lower() in lowered:
            flags.append("forbidden")
            break
    for spoiler in hint_engine.rules.get("spoilers", []):
        if spoiler.lower() in lowered:
            flags.append("too_direct")
            break

    await state.register_submission(player_id, word, flags)
    await state.advance_turn()
    await send_room_state()
    await send_turn_event()

    if await state.all_players_submitted():
        await force_resolve()


async def handle_chat(player_id: str, payload: Dict[str, Any]) -> None:
    message = (payload.get("message") or "").strip()
    if not message:
        return
    clean = mask_forbidden(message)
    player = await state.get_player(player_id)
    await manager.broadcast(
        {
            "type": "chat.message",
            "payload": {
                "playerId": player_id,
                "name": player.name if player else "?",
                "message": clean,
                "ts": int(time.time() * 1000),
            },
        }
    )


def mask_forbidden(message: str) -> str:
    result = message
    for term in (*hint_engine.rules.get("forbidden", []), *hint_engine.rules.get("spoilers", [])):
        if not term:
            continue
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        result = pattern.sub("***", result)
    return result


async def send_stats_to(player_id: str) -> None:
    stats = await state.build_stats_payload()
    await manager.send_to(player_id, {"type": "stats.open", "payload": stats})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    player_id: Optional[str] = None
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"type": "error", "payload": {"message": "Invalid JSON"}}))
                continue

            msg_type = message.get("type")
            payload = message.get("payload", {})

            if msg_type == "join":
                if player_id:
                    await websocket.send_text(json.dumps({"type": "error", "payload": {"message": "이미 참여 중입니다."}}))
                    continue
                name = payload.get("name", "")
                existing_id = payload.get("playerId")
                try:
                    player, _ = await state.add_player(name, existing_id=existing_id)
                except RuntimeError as exc:
                    if str(exc) == "room_full":
                        await websocket.send_text(json.dumps({"type": "error", "payload": {"message": "방이 가득 찼습니다."}}))
                        continue
                    raise
                player_id = player.id
                await manager.register(player_id, websocket)
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "joined",
                            "payload": {
                                "playerId": player.id,
                                "name": player.name,
                                "isHost": player.is_host,
                            },
                        }
                    )
                )
                await send_room_state()
                continue

            if not player_id:
                await websocket.send_text(json.dumps({"type": "error", "payload": {"message": "먼저 참여하세요."}}))
                continue

            if msg_type == "host.set_secret":
                await handle_set_secret(player_id, payload)
            elif msg_type == "submit.word":
                await handle_submit_word(player_id, payload)
            elif msg_type == "chat.say":
                await handle_chat(player_id, payload)
            elif msg_type == "stats.request":
                await send_stats_to(player_id)
            elif msg_type == "ping":
                await manager.send_to(player_id, {"type": "pong", "payload": {"ts": int(time.time() * 1000)}})
            elif msg_type == "leave":
                await manager.send_to(player_id, {"type": "left", "payload": {}})
                break
            else:
                await manager.send_to(player_id, {"type": "error", "payload": {"message": "알 수 없는 이벤트"}})
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    finally:
        detached_id = await manager.unregister(websocket)
        if detached_id:
            await state.mark_disconnected(detached_id)
            await send_room_state()


__all__ = ["app"]
