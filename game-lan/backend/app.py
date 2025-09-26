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
    from .ai.azure_agent import AzureAgent, PlayerResult
    from .state import GameState
except ImportError:  # pragma: no cover
    from ai.azure_agent import AzureAgent, PlayerResult
    from state import GameState


logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("azure-kaisen")

BASE_DIR = Path(__file__).resolve().parent
DOCS_DIR = BASE_DIR / "docs"


def _resolve_path(default: Path, override: Optional[str]) -> Path:
    if not override:
        return default
    candidate = Path(override)
    if not candidate.is_absolute():
        candidate = (BASE_DIR / candidate).resolve()
    return candidate


PDF_PATH = _resolve_path(DOCS_DIR / "5일차.pdf", os.getenv("AI_PDF_PATH"))
RULES_PATH = _resolve_path(BASE_DIR / "ai" / "rules.json", os.getenv("AI_RULES_PATH"))
HINTS_ENABLED = os.getenv("AI_HINTS_ENABLED", "1").lower() not in {"0", "false", "off"}

MAX_ROUNDS = int(os.getenv("MAX_ROUNDS", "3"))
SUBMISSION_SECONDS = int(os.getenv("SUBMISSION_SECONDS", "45"))
DISCUSSION_SECONDS = int(os.getenv("DISCUSSION_SECONDS", "45"))
TRANSITION_SECONDS = int(os.getenv("TRANSITION_SECONDS", "12"))

app = FastAPI(title="에저회전 Azure Kaisen", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

state = GameState(
    max_rounds=MAX_ROUNDS,
    submission_seconds=SUBMISSION_SECONDS,
    discussion_seconds=DISCUSSION_SECONDS,
    transition_seconds=TRANSITION_SECONDS,
)
ai_agent = AzureAgent(pdf_path=PDF_PATH, rules_path=RULES_PATH, hints_enabled=HINTS_ENABLED)


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
        to_remove: list[str] = []
        for pid, websocket in self.connections.items():
            try:
                await websocket.send_text(data)
            except Exception:
                to_remove.append(pid)
        for pid in to_remove:
            self.connections.pop(pid, None)


manager = ConnectionManager()


def lan_address() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
    except Exception:  # pragma: no cover
        ip = socket.gethostbyname(socket.gethostname())
    return ip


@app.on_event("startup")
async def on_startup() -> None:
    ip = lan_address()
    logger.info("Backend ready on http://%s:8000", ip)
    logger.info("Frontend dev server expected on http://%s:5173", ip)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.get("/config")
async def get_config() -> JSONResponse:
    return JSONResponse(
        {
            "rounds": MAX_ROUNDS,
            "submissionSeconds": SUBMISSION_SECONDS,
            "discussionSeconds": DISCUSSION_SECONDS,
            "transitionSeconds": TRANSITION_SECONDS,
        }
    )


@app.get("/docs/5일차.pdf")
async def get_pdf() -> FileResponse:
    return FileResponse(PDF_PATH)


@app.get("/db")
async def dump_state() -> JSONResponse:
    snapshot = await state.snapshot()
    return JSONResponse(snapshot)


# ---------------------------------------------------------------------------
# Timer helpers
# ---------------------------------------------------------------------------
async def cancel_timer() -> None:
    if state.timer_task and not state.timer_task.done():
        state.timer_task.cancel()
        try:
            await state.timer_task
        except asyncio.CancelledError:
            pass
    state.timer_task = None


async def run_timer(phase: str, round_index: int, on_expire) -> None:
    expired = False
    try:
        while True:
            remaining = await state.update_remaining_ms()
            await manager.broadcast({"type": "tick", "payload": {"phase": phase, "round": round_index, "timerMs": remaining}})
            if remaining <= 0:
                expired = True
                break
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        return
    finally:
        state.timer_task = None
    if expired:
        await on_expire()


async def start_stage(phase: str, *, duration: int, round_index: int, on_expire) -> None:
    await cancel_timer()
    await state.set_phase(phase, duration)
    await broadcast_state()
    await manager.broadcast({"type": "phase.changed", "payload": {"phase": phase, "round": round_index}})
    state.timer_task = asyncio.create_task(run_timer(phase, round_index, on_expire))


async def broadcast_state() -> None:
    public_state = await state.get_public_state()
    await manager.broadcast({"type": "room.state", "payload": public_state})


# ---------------------------------------------------------------------------
# Game flow helpers
# ---------------------------------------------------------------------------
async def start_submission_phase(round_index: int) -> None:
    async def on_expire():
        await finalize_round(round_index, reason="timer")

    await start_stage("submission", duration=SUBMISSION_SECONDS, round_index=round_index, on_expire=on_expire)


async def start_discussion_phase(round_index: int, discussion_prompt: str) -> None:
    async def on_expire():
        await start_transition_phase(round_index)

    await cancel_timer()
    await state.set_phase("discussion", DISCUSSION_SECONDS)
    await broadcast_state()
    await manager.broadcast({"type": "phase.changed", "payload": {"phase": "discussion", "round": round_index, "prompt": discussion_prompt}})
    state.timer_task = asyncio.create_task(run_timer("discussion", round_index, on_expire))


async def start_transition_phase(round_index: int) -> None:
    async def on_expire():
        await maybe_start_next_round()

    await start_stage("transition", duration=TRANSITION_SECONDS, round_index=round_index, on_expire=on_expire)


async def maybe_start_next_round() -> None:
    await cancel_timer()
    if state.round >= state.max_rounds:
        await conclude_game()
        return
    await begin_round()


async def conclude_game() -> None:
    await cancel_timer()
    await state.set_phase("end")
    await broadcast_state()
    winner = await state.winner()
    if winner:
        await manager.broadcast({"type": "end.winner", "payload": winner})
    stats = await state.build_stats()
    await manager.broadcast({"type": "stats.open", "payload": stats})
    await state.reset_ready()
    await state.set_phase("ready")
    await broadcast_state()


async def begin_round() -> None:
    used = await state.used_secrets()
    choice = await ai_agent.choose_secret(round_index=state.round + 1, used_secrets=used)
    round_index = await state.start_new_round(choice.secret)
    await manager.broadcast({"type": "round.prep", "payload": {"round": round_index, "theme": choice.theme, "source": choice.source, "rationale": choice.rationale}})
    await start_submission_phase(round_index)


async def finalize_round(round_index: int, *, reason: str) -> None:
    current_state = await state.get_public_state()
    if current_state["round"] != round_index or current_state["phase"] != "submission":
        return

    await cancel_timer()
    await state.set_phase("resolution")
    await state.ensure_missed_submissions()
    await broadcast_state()
    await manager.broadcast({"type": "phase.changed", "payload": {"phase": "resolution", "round": round_index, "reason": reason}})

    secret = await state.get_secret(round_index) or ""
    submissions = await state.get_round_submissions(round_index)
    players = await state.list_players()

    submission_payload = {
        pid: {"word": sub.word, "flags": sub.flags}
        for pid, sub in submissions.items()
    }
    player_payload = [
        {"id": player.id, "name": player.name, "connected": player.connected}
        for player in players
    ]

    evaluation = await ai_agent.evaluate_round(
        round_index=round_index,
        secret=secret,
        submissions=submission_payload,
        player_order=player_payload,
    )

    for player in players:
        result = evaluation.players.get(player.id)
        if not result:
            result = PlayerResult(hint="AI 응답을 받지 못했습니다.", score=0, flags=["ai_missing"], meta={"source": evaluation.source})
        await state.store_hint_result(
            round_index,
            player.id,
            hint=result.hint,
            score=result.score,
            flags=result.flags,
            meta=result.meta,
        )
        await manager.send_to(
            player.id,
            {
                "type": "round.result:me",
                "payload": {
                    "round": round_index,
                    "hint": result.hint,
                    "score": result.score,
                    "flags": result.flags,
                    "meta": result.meta,
                },
            },
        )

    decorated_summary = []
    for entry in evaluation.summary:
        entry_copy = dict(entry)
        pid = entry_copy.get("playerId")
        if pid:
            match = next((p for p in players if p.id == pid), None)
            if match and not entry_copy.get("name"):
                entry_copy["name"] = match.name
        decorated_summary.append(entry_copy)

    summary_payload = {
        "round": round_index,
        "source": evaluation.source,
        "entries": decorated_summary,
    }
    await manager.broadcast({"type": "round.summary", "payload": summary_payload})
    await broadcast_state()

    await start_discussion_phase(round_index, evaluation.discussion)


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------
def mask_forbidden(message: str) -> str:
    result = message
    for term in (*ai_agent.rules.get("forbidden", []), *ai_agent.rules.get("spoilers", [])):
        if not term:
            continue
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        result = pattern.sub("***", result)
    return result


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------
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
                    player = await state.add_player(name, existing_id=existing_id)
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
                await broadcast_state()
                continue

            if not player_id:
                await websocket.send_text(json.dumps({"type": "error", "payload": {"message": "먼저 입장하세요."}}))
                continue

            if msg_type == "player.ready_toggle":
                current = await state.get_public_state()
                if current["phase"] not in {"lobby", "ready", "end"}:
                    await manager.send_to(player_id, {"type": "error", "payload": {"message": "지금은 READY를 변경할 수 없습니다."}})
                    continue
                ready = await state.toggle_ready(player_id)
                await manager.broadcast({"type": "player.ready", "payload": {"playerId": player_id, "ready": ready}})
                await broadcast_state()
            elif msg_type == "host.start_game":
                player = await state.get_player(player_id)
                if not player or not player.is_host:
                    await manager.send_to(player_id, {"type": "error", "payload": {"message": "방장만 시작할 수 있습니다."}})
                    continue
                if not await state.all_ready():
                    await manager.send_to(player_id, {"type": "error", "payload": {"message": "모든 플레이어가 READY 상태여야 합니다."}})
                    continue
                await cancel_timer()
                await state.reset_game()
                await broadcast_state()
                await begin_round()
            elif msg_type == "submit.word":
                current = await state.get_public_state()
                if current["phase"] != "submission":
                    await manager.send_to(player_id, {"type": "error", "payload": {"message": "지금은 제출할 수 없습니다."}})
                    continue
                word = (payload.get("word") or "").strip()
                if not word:
                    await manager.send_to(player_id, {"type": "error", "payload": {"message": "단어를 입력하세요."}})
                    continue
                if len(word.split()) > 1:
                    await manager.send_to(player_id, {"type": "error", "payload": {"message": "공백 없는 단어만 제출 가능합니다."}})
                    continue
                await state.record_submission(player_id, word)
                await broadcast_state()
                if await state.everyone_submitted():
                    await finalize_round(current["round"], reason="all_submitted")
            elif msg_type == "chat.say":
                current = await state.get_public_state()
                if current["phase"] not in {"discussion", "lobby", "ready"}:
                    await manager.send_to(player_id, {"type": "error", "payload": {"message": "지금은 대화할 수 없습니다."}})
                    continue
                message_text = (payload.get("message") or "").strip()
                if not message_text:
                    continue
                masked = mask_forbidden(message_text)
                player = await state.get_player(player_id)
                await manager.broadcast(
                    {
                        "type": "chat.message",
                        "payload": {
                            "playerId": player_id,
                            "name": player.name if player else "?",
                            "message": masked,
                            "ts": int(time.time() * 1000),
                        },
                    }
                )
            elif msg_type == "stats.request":
                stats = await state.build_stats()
                await manager.send_to(player_id, {"type": "stats.open", "payload": stats})
            elif msg_type == "ping":
                await manager.send_to(player_id, {"type": "pong", "payload": {}})
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
            await broadcast_state()


__all__ = ["app"]
