from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

@dataclass
class SecretChoice:
    secret: str
    theme: str
    rationale: str
    source: str


@dataclass
class PlayerResult:
    hint: str
    score: int
    flags: List[str]
    meta: Dict[str, Any]


@dataclass
class RoundEvaluation:
    players: Dict[str, PlayerResult]
    summary: List[Dict[str, Any]]
    discussion: str
    source: str

@dataclass
class GeminiSubmission:
    user: str
    input: str

@dataclass
class GeminiPlayerResult:
    user: str
    input: str
    score: int
    hint: str

@dataclass
class GeminiRoundEvaluation:
    results: List[GeminiPlayerResult]