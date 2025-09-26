"""State management and scoring logic for Azure Kaisen LAN game."""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any


Phase = str


@dataclass
class Player:
    id: str
    name: str
    is_host: bool = False
    score: int = 0
    last_word: Optional[str] = None
    connected: bool = True
    joined_at: float = field(default_factory=time.time)


@dataclass
class Submission:
    player_id: str
    word: str
    flags: List[str]
    base_score: int = 0
    extra_scores: Dict[str, int] = field(default_factory=dict)
    hint: Optional[str] = None
    ai_score_suggestion: int = 0

    @property
    def total_score(self) -> int:
        return self.base_score + sum(self.extra_scores.values())


class GameState:
    """Holds the authoritative in-memory state for a single-room game."""

    def __init__(self, *, max_rounds: int = 3, turn_timer_seconds: int = 30) -> None:
        self.players: Dict[str, Player] = {}
        self.player_order: List[str] = []
        self.phase: Phase = "lobby"
        self.round: int = 0
        self.turn_index: int = 0
        self.max_rounds = max_rounds
        self.turn_timer_seconds = turn_timer_seconds
        self.remaining_ms: int = turn_timer_seconds * 1000
        self._round_deadline: Optional[float] = None
        self.submissions: Dict[int, Dict[str, Submission]] = {}
        self.secrets: Dict[int, str] = {}
        self.lock = asyncio.Lock()
        self.pending_secret: Optional[str] = None
        self.timer_task: Optional[asyncio.Task] = None
        self._broadcast_callback = None
        self._timer_callback = None

    # --- Player management -------------------------------------------------

    def _generate_player_id(self) -> str:
        return uuid.uuid4().hex

    async def add_player(self, name: str, *, existing_id: Optional[str] = None) -> Tuple[Player, bool]:
        async with self.lock:
            if existing_id and existing_id in self.players:
                player = self.players[existing_id]
                player.connected = True
                player.name = name or player.name
                became_host = False
                return player, became_host

            if len(self.players) >= 5:
                raise RuntimeError("room_full")

            player_id = self._generate_player_id()
            is_host = not any(p.is_host for p in self.players.values())
            player = Player(id=player_id, name=name.strip() or "Player", is_host=is_host)
            self.players[player_id] = player
            self.player_order.append(player_id)
            became_host = is_host
            return player, became_host

    async def mark_disconnected(self, player_id: str) -> None:
        async with self.lock:
            if player_id in self.players:
                self.players[player_id].connected = False
                if self.phase == "collecting":
                    current = self.submissions.setdefault(self.round, {})
                    if player_id not in current:
                        current[player_id] = Submission(
                            player_id=player_id,
                            word="",
                            flags=["timeout", "disconnected"],
                            base_score=0,
                        )

    async def get_player(self, player_id: str) -> Optional[Player]:
        async with self.lock:
            return self.players.get(player_id)

    async def remove_player(self, player_id: str) -> None:
        async with self.lock:
            if player_id not in self.players:
                return
            was_host = self.players[player_id].is_host
            del self.players[player_id]
            self.player_order = [pid for pid in self.player_order if pid != player_id]
            if was_host and self.players:
                # Promote earliest-joined connected player to host
                new_host_id = min(self.players.values(), key=lambda p: p.joined_at).id
                self.players[new_host_id].is_host = True

    # --- Round / phase management -----------------------------------------

    async def set_timer_callback(self, callback) -> None:
        self._timer_callback = callback

    async def set_broadcast_callback(self, callback) -> None:
        self._broadcast_callback = callback

    async def set_secret(self, secret: str) -> None:
        async with self.lock:
            self.pending_secret = secret

    async def get_secret(self, round_index: int) -> Optional[str]:
        async with self.lock:
            return self.secrets.get(round_index)

    async def start_round_if_possible(self) -> bool:
        async with self.lock:
            if self.phase not in {"lobby", "next"}:
                return False
            if not self.pending_secret:
                return False
            if len(self.player_order) < 2:
                return False

            self.round += 1
            if self.round > self.max_rounds:
                self.phase = "end"
                return False

            self.secrets[self.round] = self.pending_secret
            self.pending_secret = None
            self.phase = "collecting"
            self.turn_index = 0
            self.submissions.setdefault(self.round, {})
            self._round_deadline = time.time() + self.turn_timer_seconds
            self.remaining_ms = self.turn_timer_seconds * 1000
            for player in self.players.values():
                player.last_word = None
            return True

    async def advance_turn(self) -> None:
        async with self.lock:
            if self.phase != "collecting" or not self.player_order:
                return
            submitted_players = set(self.submissions.get(self.round, {}).keys())
            for offset in range(1, len(self.player_order) + 1):
                idx = (self.turn_index + offset) % len(self.player_order)
                next_player_id = self.player_order[idx]
                player = self.players.get(next_player_id)
                if not player or not player.connected:
                    continue
                if next_player_id not in submitted_players:
                    self.turn_index = idx
                    break
            else:
                # Everyone submitted
                self.turn_index = 0

    async def current_turn_player(self) -> Optional[Player]:
        async with self.lock:
            if not self.player_order:
                return None
            pid = self.player_order[self.turn_index % len(self.player_order)]
            return self.players.get(pid)

    async def register_submission(self, player_id: str, word: str, flags: List[str]) -> Submission:
        async with self.lock:
            submission = Submission(
                player_id=player_id,
                word=word,
                flags=list(flags),
                base_score=1 if word else 0,
            )
            self.submissions.setdefault(self.round, {})[player_id] = submission
            player = self.players.get(player_id)
            if player:
                player.last_word = word
            return submission

    async def get_round_submissions(self, round_index: int) -> Dict[str, Submission]:
        async with self.lock:
            return dict(self.submissions.get(round_index, {}))

    async def get_player_order(self) -> List[str]:
        async with self.lock:
            return list(self.player_order)

    async def ensure_all_submissions(self) -> None:
        """Fill in placeholder submissions for players who missed the timer."""
        async with self.lock:
            current = self.submissions.setdefault(self.round, {})
            for player_id in self.player_order:
                if player_id not in current:
                    current[player_id] = Submission(
                        player_id=player_id,
                        word="",
                        flags=["timeout"],
                        base_score=0,
                    )
                    player = self.players.get(player_id)
                    if player:
                        player.last_word = None

    async def all_players_submitted(self) -> bool:
        async with self.lock:
            submitted = self.submissions.get(self.round, {})
            expected = 0
            for pid in self.player_order:
                player = self.players.get(pid)
                if player and player.connected:
                    expected += 1
            return len(submitted) >= expected

    async def set_phase(self, phase: Phase) -> None:
        async with self.lock:
            self.phase = phase

    async def calculate_scores(self) -> Dict[str, Submission]:
        async with self.lock:
            submissions = self.submissions.get(self.round, {})
            # Determine uniqueness bonus
            normalized_counts: Dict[str, int] = {}
            for sub in submissions.values():
                key = sub.word.lower().strip()
                if key:
                    normalized_counts[key] = normalized_counts.get(key, 0) + 1

            for sub in submissions.values():
                key = sub.word.lower().strip()
                if sub.base_score > 0 and key and normalized_counts.get(key, 0) == 1:
                    sub.extra_scores["unique"] = 1
                if "too_direct" not in sub.flags and sub.base_score > 0:
                    sub.extra_scores.setdefault("indirect", 1)
                # Apply penalties
                if "forbidden" in sub.flags:
                    sub.extra_scores["forbidden_penalty"] = -1
                if "too_direct" in sub.flags:
                    sub.extra_scores.setdefault("direct_penalty", -1)
                if "off_topic" in sub.flags:
                    sub.extra_scores.setdefault("off_topic", 0)

            for sub in submissions.values():
                player = self.players.get(sub.player_id)
                if player:
                    player.score += sub.total_score
            return submissions

    async def to_public_state(self) -> Dict[str, Any]:
        async with self.lock:
            current_turn_id = None
            if self.player_order:
                current_turn_id = self.player_order[self.turn_index % len(self.player_order)]
            return {
                "phase": self.phase,
                "round": self.round,
                "turn": current_turn_id,
                "timerMs": max(0, self.remaining_ms),
                "players": [
                    {
                        "id": player.id,
                        "name": player.name,
                        "score": player.score,
                        "lastWord": player.last_word,
                        "isHost": player.is_host,
                        "connected": player.connected,
                    }
                    for player in self.players.values()
                ],
            }

    async def update_remaining_ms(self) -> int:
        async with self.lock:
            if not self._round_deadline:
                self.remaining_ms = self.turn_timer_seconds * 1000
            else:
                remaining = int(max(0, (self._round_deadline - time.time()) * 1000))
                self.remaining_ms = remaining
            return self.remaining_ms

    async def finish_round(self) -> None:
        async with self.lock:
            self.phase = "resolving"
            self._round_deadline = None
            self.remaining_ms = 0

    async def prepare_next_round(self) -> None:
        async with self.lock:
            if self.round >= self.max_rounds:
                self.phase = "end"
            else:
                self.phase = "next"
                self.turn_index = 0

    async def winner(self) -> Optional[Dict[str, Any]]:
        async with self.lock:
            if not self.players:
                return None
            top = max(self.players.values(), key=lambda p: (p.score, -self.player_order.index(p.id)))
            return {
                "playerId": top.id,
                "name": top.name,
                "score": top.score,
            }

    async def build_stats_payload(self) -> Dict[str, Any]:
        async with self.lock:
            rounds = []
            for round_index in range(1, self.max_rounds + 1):
                round_subs = self.submissions.get(round_index, {})
                rounds.append({
                    pid: {
                        "word": sub.word,
                        "flags": sub.flags,
                        "score": sub.total_score,
                    }
                    for pid, sub in round_subs.items()
                })
            players = [
                {
                    "id": player.id,
                    "name": player.name,
                    "total": player.score,
                    "perRound": [
                        rounds[r - 1].get(player.id, {"word": "", "flags": [], "score": 0})
                        for r in range(1, self.max_rounds + 1)
                    ],
                }
                for player in self.players.values()
            ]
            players.sort(key=lambda p: p["total"], reverse=True)
            for idx, player in enumerate(players, start=1):
                player["rank"] = idx
            return {
                "rounds": rounds,
                "players": players,
            }


__all__ = ["GameState", "Player", "Submission"]
