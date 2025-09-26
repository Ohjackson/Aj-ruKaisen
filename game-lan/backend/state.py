"""State management for the Azure-driven version of Azure Kaisen."""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


Phase = str


def _resolve_host_player_name() -> str:
    for env_key in ("HOST_PLAYER_NAME", "playerName", "PLAYER_NAME"):
        value = os.getenv(env_key)
        if value and value.strip():
            return value.strip()
    return "로켓단"


HOST_PLAYER_NAME = _resolve_host_player_name()
logger = logging.getLogger("azure-kaisen.state")


@dataclass
class Player:
    id: str
    name: str
    is_host: bool = False
    ready: bool = False
    score: int = 0
    last_word: Optional[str] = None
    connected: bool = True
    joined_at: float = field(default_factory=time.time)


@dataclass
class Submission:
    player_id: str
    word: str
    flags: List[str] = field(default_factory=list)
    score: int = 0
    hint: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)


class GameState:
    """In-memory authoritative state for the LAN room."""

    def __init__(
        self,
        *,
        max_rounds: int = 3,
        submission_seconds: int = 45,
        discussion_seconds: int = 45,
        transition_seconds: int = 12,
    ) -> None:
        self.max_rounds = max_rounds
        self.submission_seconds = submission_seconds
        self.discussion_seconds = discussion_seconds
        self.transition_seconds = transition_seconds

        self.players: Dict[str, Player] = {}
        self.player_order: List[str] = []
        self.round: int = 0
        self.phase: Phase = "lobby"
        self.remaining_ms: int = 0
        self.timer_deadline: Optional[float] = None
        self.timer_task: Optional[asyncio.Task] = None

        self.submissions: Dict[int, Dict[str, Submission]] = {}
        self.secret_by_round: Dict[int, str] = {}
        self.hint_payloads: Dict[int, Dict[str, Any]] = {}
        self.chat_history: List[Dict[str, Any]] = []

        self.lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Player management
    # ------------------------------------------------------------------
    def _sync_host_flags(self) -> None:
        for player in self.players.values():
            player.is_host = player.name == HOST_PLAYER_NAME

    def _new_player_id(self) -> str:
        return uuid.uuid4().hex

    async def add_player(self, name: str, *, existing_id: Optional[str] = None) -> Player:
        async with self.lock:
            incoming = (name or "").strip()

            if existing_id and existing_id in self.players:
                player = self.players[existing_id]
                player.connected = True
                if incoming:
                    player.name = incoming
                self._sync_host_flags()
                return player

            if len(self.players) >= 5:
                raise RuntimeError("room_full")

            player_id = self._new_player_id()
            player = Player(
                id=player_id,
                name=incoming or "Player",
            )
            self.players[player_id] = player
            self.player_order.append(player_id)
            self._sync_host_flags()
            return player

    async def remove_player(self, player_id: str) -> None:
        async with self.lock:
            player = self.players.pop(player_id, None)
            if not player:
                return
            self.player_order = [pid for pid in self.player_order if pid != player_id]
            self._sync_host_flags()

    async def mark_disconnected(self, player_id: str) -> None:
        async with self.lock:
            player = self.players.get(player_id)
            if player:
                player.connected = False
                player.ready = False

    async def set_ready(self, player_id: str, ready: bool) -> None:
        async with self.lock:
            player = self.players.get(player_id)
            if player:
                player.ready = ready

    async def toggle_ready(self, player_id: str) -> bool:
        async with self.lock:
            player = self.players.get(player_id)
            if not player:
                return False
            player.ready = not player.ready
            return player.ready

    async def all_ready(self) -> bool:
        async with self.lock:
            connected_players = [p for p in self.players.values() if p.connected]
            if not connected_players:
                return False
            return all(player.ready for player in connected_players)

    async def reset_ready(self) -> None:
        async with self.lock:
            for player in self.players.values():
                player.ready = False

    async def reset_game(self) -> None:
        async with self.lock:
            self.round = 0
            self.phase = "ready"
            self.remaining_ms = 0
            self.timer_deadline = None
            self.submissions.clear()
            self.secret_by_round.clear()
            self.hint_payloads.clear()
            for player in self.players.values():
                player.score = 0
                player.last_word = None

    async def get_player(self, player_id: str) -> Optional[Player]:
        async with self.lock:
            return self.players.get(player_id)

    async def list_players(self) -> List[Player]:
        async with self.lock:
            return [self.players[pid] for pid in self.player_order if pid in self.players]

    # ------------------------------------------------------------------
    # Phase & timer management
    # ------------------------------------------------------------------
    async def set_phase(self, phase: Phase, duration_seconds: Optional[int] = None) -> None:
        async with self.lock:
            self.phase = phase
            if duration_seconds is None:
                self.timer_deadline = None
                self.remaining_ms = 0
            else:
                self.timer_deadline = time.time() + duration_seconds
                self.remaining_ms = duration_seconds * 1000

    async def update_remaining_ms(self) -> int:
        async with self.lock:
            if not self.timer_deadline:
                self.remaining_ms = 0
            else:
                self.remaining_ms = int(max(0, (self.timer_deadline - time.time()) * 1000))
            return self.remaining_ms

    # ------------------------------------------------------------------
    # Round & submission helpers
    # ------------------------------------------------------------------
    async def start_new_round(self, secret: str) -> int:
        async with self.lock:
            self.round += 1
            self.secret_by_round[self.round] = secret
            self.submissions[self.round] = {}
            self.hint_payloads.pop(self.round, None)
            for player in self.players.values():
                player.last_word = None
            return self.round

    async def get_secret(self, round_index: int) -> Optional[str]:
        async with self.lock:
            return self.secret_by_round.get(round_index)

    async def used_secrets(self) -> List[str]:
        async with self.lock:
            return [self.secret_by_round[idx] for idx in range(1, self.round + 1) if idx in self.secret_by_round]

    async def record_submission(self, player_id: str, word: str) -> Submission:
        async with self.lock:
            submission = Submission(player_id=player_id, word=word)
            player = self.players.get(player_id)
            if player:
                player.last_word = word
            self.submissions.setdefault(self.round, {})[player_id] = submission
            return submission

    async def ensure_missed_submissions(self) -> None:
        async with self.lock:
            current = self.submissions.setdefault(self.round, {})
            for player_id in self.player_order:
                if player_id not in current:
                    current[player_id] = Submission(player_id=player_id, word="", flags=["timeout"])
                    player = self.players.get(player_id)
                    if player:
                        player.last_word = None

    async def everyone_submitted(self) -> bool:
        async with self.lock:
            current = self.submissions.get(self.round, {})
            expected = sum(1 for player in self.players.values() if player.connected)
            return len(current) >= expected and expected > 0

    async def store_hint_result(self, round_index: int, player_id: str, *, hint: str, score: int, flags: List[str], meta: Optional[Dict[str, Any]] = None) -> None:
        async with self.lock:
            submission = self.submissions.setdefault(round_index, {}).setdefault(player_id, Submission(player_id=player_id, word=""))
            submission.hint = hint
            submission.score = score
            submission.flags = flags
            submission.meta = meta or {}
            player = self.players.get(player_id)
            if player:
                player.score += score

    async def get_round_submissions(self, round_index: int) -> Dict[str, Submission]:
        async with self.lock:
            return dict(self.submissions.get(round_index, {}))

    async def get_public_state(self) -> Dict[str, Any]:
        async with self.lock:
            return {
                "phase": self.phase,
                "round": self.round,
                "timerMs": max(0, self.remaining_ms),
                "players": [
                    {
                        "id": player.id,
                        "name": player.name,
                        "score": player.score,
                        "lastWord": player.last_word,
                        "isHost": player.is_host,
                        "ready": player.ready,
                        "connected": player.connected,
                    }
                    for player in self.players.values()
                ],
                "maxRounds": self.max_rounds,
            }

    async def winner(self) -> Optional[Dict[str, Any]]:
        async with self.lock:
            if not self.players:
                return None
            leader = max(self.players.values(), key=lambda p: (p.score, -self.player_order.index(p.id)))
            return {"playerId": leader.id, "name": leader.name, "score": leader.score}

    async def build_stats(self) -> Dict[str, Any]:
        async with self.lock:
            rounds: List[Dict[str, Any]] = []
            for idx in range(1, self.max_rounds + 1):
                round_subs = self.submissions.get(idx, {})
                rounds.append({
                    pid: {
                        "word": submission.word,
                        "score": submission.score,
                        "flags": submission.flags,
                        "hint": submission.hint,
                    }
                    for pid, submission in round_subs.items()
                })
            players = [
                {
                    "id": player.id,
                    "name": player.name,
                    "total": player.score,
                    "perRound": [
                        rounds[r - 1].get(player.id, {"word": "", "score": 0, "flags": [], "hint": ""})
                        for r in range(1, self.max_rounds + 1)
                    ],
                }
                for player in self.players.values()
            ]
            players.sort(key=lambda p: p["total"], reverse=True)
            for rank, player in enumerate(players, start=1):
                player["rank"] = rank
            return {"rounds": rounds, "players": players}

    async def snapshot(self) -> Dict[str, Any]:
        async with self.lock:
            return {
                "phase": self.phase,
                "round": self.round,
                "remainingMs": self.remaining_ms,
                "maxRounds": self.max_rounds,
                "players": [
                    {
                        "id": p.id,
                        "name": p.name,
                        "isHost": p.is_host,
                        "ready": p.ready,
                        "score": p.score,
                        "lastWord": p.last_word,
                        "connected": p.connected,
                    }
                    for p in self.players.values()
                ],
                "secrets": {
                    str(round_index): {
                        "stored": round_index in self.secret_by_round,
                        "length": len(self.secret_by_round[round_index]) if round_index in self.secret_by_round else 0,
                    }
                    for round_index in range(1, self.max_rounds + 1)
                },
                "submissions": {
                    str(round_index): {
                        pid: {
                            "word": submission.word,
                            "score": submission.score,
                            "flags": submission.flags,
                            "hint": submission.hint,
                        }
                        for pid, submission in round_subs.items()
                    }
                    for round_index, round_subs in self.submissions.items()
                },
                "chatHistory": list(self.chat_history),
            }

    async def add_chat_message(self, *, player_id: str, name: str, message: str, timestamp: int) -> None:
        async with self.lock:
            self.chat_history.append(
                {
                    "playerId": player_id,
                    "name": name,
                    "message": message,
                    "ts": timestamp,
                }
            )
            if len(self.chat_history) > 200:
                self.chat_history = self.chat_history[-200:]
        logger.info("chat[%s] %s: %s", timestamp, name, message)

    async def get_chat_history(self) -> List[Dict[str, Any]]:
        async with self.lock:
            return list(self.chat_history)


__all__ = ["GameState", "Player", "Submission"]
