"""Azure OpenAI orchestrator for the fully automated Azure Kaisen flow."""
from __future__ import annotations

import json
import logging
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from .pdf_engine import PdfHintEngine


logger = logging.getLogger("azure-kaisen.ai")


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


class AzureAgent:
    """Wrapper around Azure OpenAI (or local fallback) for game orchestration."""

    def __init__(self, *, pdf_path: Path, rules_path: Path, hints_enabled: bool = True) -> None:
        self.hints_enabled = hints_enabled
        self.pdf_engine = PdfHintEngine(pdf_path=pdf_path, rules_path=rules_path)
        self.rules = self.pdf_engine.rules
        self.sentences = self.pdf_engine.sentences

        self.azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
        self.azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
        self.azure_key = os.getenv("AZURE_OPENAI_KEY", "")
        self.azure_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
        self.azure_temperature = float(os.getenv("AZURE_OPENAI_TEMPERATURE", "0.2"))

        self.azure_enabled = bool(self.azure_endpoint and self.azure_deployment and self.azure_key)
        if not self.azure_enabled:
            logger.warning("Azure OpenAI credentials not fully configured. Fallback hint engine will be used.")

        self._cached_keywords = self._build_keyword_pool()

    # ------------------------------------------------------------------
    # Keyword/context helpers
    # ------------------------------------------------------------------
    def _build_keyword_pool(self) -> List[str]:
        keywords: List[str] = []
        for sentence in self.sentences:
            for token in self.pdf_engine._extract_keywords(sentence):  # type: ignore[attr-defined]
                if len(token) < 3:
                    continue
                if token in self.rules.get("forbidden", []):
                    continue
                if token in self.rules.get("spoilers", []):
                    continue
                keywords.append(token)
        deduped = sorted(set(keywords))
        if not deduped:
            deduped = ["azure", "cloud", "agent"]
        return deduped

    def _sample_context(self, max_sentences: int = 12) -> str:
        return "\n".join(self.sentences[:max_sentences])

    # ------------------------------------------------------------------
    # Secret selection
    # ------------------------------------------------------------------
    async def choose_secret(self, *, round_index: int, used_secrets: List[str]) -> SecretChoice:
        if self.azure_enabled:
            try:
                payload = await self._call_azure(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are the Azure Kaisen game master AI. "
                                "Pick a single secret keyword from the provided lecture excerpts. "
                                "Avoid words already used in previous rounds. Respond ONLY with JSON."
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "round": round_index,
                                    "usedSecrets": used_secrets,
                                    "rules": {
                                        "forbidden": self.rules.get("forbidden", []),
                                        "spoilers": self.rules.get("spoilers", []),
                                    },
                                    "context": self._sample_context(18),
                                    "keywordPool": random.sample(self._cached_keywords, min(40, len(self._cached_keywords))),
                                }
                            ),
                        },
                    ],
                )
                data = json.loads(payload)
                secret = data.get("secret", "").strip()
                theme = data.get("theme", "Mystery")
                rationale = data.get("rationale", "")
                if secret and secret.lower() not in {k.lower() for k in used_secrets}:
                    logger.info("Azure selected secret for round %s", round_index)
                    return SecretChoice(secret=secret, theme=theme, rationale=rationale, source="azure")
            except Exception as exc:  # pragma: no cover - network failure fallback
                logger.warning("Azure secret selection failed: %s", exc)

        secret = self._fallback_secret(used_secrets)
        logger.info("Fallback secret selected for round %s: %s", round_index, secret)
        return SecretChoice(
            secret=secret,
            theme="Fallback",
            rationale="Random keyword from PDF context",
            source="fallback",
        )

    def _fallback_secret(self, used_secrets: List[str]) -> str:
        used_lower = {s.lower() for s in used_secrets}
        candidates = [token for token in self._cached_keywords if token.lower() not in used_lower]
        if not candidates:
            candidates = self._cached_keywords
        return random.choice(candidates)

    # ------------------------------------------------------------------
    # Round evaluation
    # ------------------------------------------------------------------
    async def evaluate_round(
        self,
        *,
        round_index: int,
        secret: str,
        submissions: Dict[str, Dict[str, Any]],
        player_order: List[Dict[str, Any]],
    ) -> RoundEvaluation:
        if self.azure_enabled and self.hints_enabled:
            try:
                payload = await self._call_azure(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are the Azure Kaisen game master. "
                                "Given the secret keyword and player submissions, evaluate each player. "
                                "Return JSON with per-player hints, scores (0-3), flags, and a public summary."
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "round": round_index,
                                    "secret": secret,
                                    "rules": self.rules,
                                    "context": self._sample_context(16),
                                    "players": player_order,
                                    "submissions": submissions,
                                }
                            ),
                        },
                    ],
                )
                data = json.loads(payload)
                player_results = data.get("players", {})
                if player_results:
                    return self._coerce_evaluation(player_results, data)
            except Exception as exc:  # pragma: no cover - network failure fallback
                logger.warning("Azure round evaluation failed: %s", exc)

        logger.info("Using fallback PDF engine evaluation for round %s", round_index)
        return self._fallback_evaluation(secret=secret, submissions=submissions, player_order=player_order)

    def _coerce_evaluation(self, player_results: Dict[str, Any], data: Dict[str, Any]) -> RoundEvaluation:
        players: Dict[str, PlayerResult] = {}
        for player_id, payload in player_results.items():
            hint = str(payload.get("hint", "힌트가 도착하지 않았습니다.")).strip()
            score = int(payload.get("score", 0))
            flags = payload.get("flags", [])
            if not isinstance(flags, list):
                flags = [str(flags)]
            meta = payload.get("meta", {})
            players[player_id] = PlayerResult(hint=hint, score=score, flags=[str(f) for f in flags], meta=meta)
        summary = data.get("summary", [])
        if not isinstance(summary, list):
            summary = []
        discussion = str(data.get("discussion", ""))
        return RoundEvaluation(players=players, summary=summary, discussion=discussion, source="azure")

    def _fallback_evaluation(
        self,
        *,
        secret: str,
        submissions: Dict[str, Dict[str, Any]],
        player_order: List[Dict[str, Any]],
    ) -> RoundEvaluation:
        # Compute uniqueness counts
        normalized_counts: Dict[str, int] = {}
        for payload in submissions.values():
            word = payload.get("word", "").strip().lower()
            if word:
                normalized_counts[word] = normalized_counts.get(word, 0) + 1

        players: Dict[str, PlayerResult] = {}
        summary: List[Dict[str, Any]] = []
        previous_round_words = [info.get("word", "") for info in submissions.values() if info.get("word")]
        for player in player_order:
            player_id = player["id"]
            submission = submissions.get(player_id, {})
            word = submission.get("word", "")
            hint_result = self.pdf_engine.generate_hint(
                secret=secret,
                submitted_word=word,
                previous_round_summaries=[", ".join(previous_round_words)],
            )
            score = 1 if word else 0
            if word and normalized_counts.get(word.strip().lower(), 0) == 1:
                score += 1
            if "too_direct" not in hint_result.flags and word:
                score += 1
            if "forbidden" in hint_result.flags:
                score -= 1

            players[player_id] = PlayerResult(
                hint=hint_result.hint,
                score=max(score, 0),
                flags=hint_result.flags,
                meta={"fallback": True},
            )
            summary.append(
                {
                    "playerId": player_id,
                    "name": player.get("name"),
                    "word": word or "(미제출)",
                    "score": max(score, 0),
                    "flags": hint_result.flags,
                }
            )
        discussion = "PDF 기반 힌트 엔진이 자동으로 점수와 힌트를 산출했습니다."
        return RoundEvaluation(players=players, summary=summary, discussion=discussion, source="fallback")

    # ------------------------------------------------------------------
    # Azure HTTP helper
    # ------------------------------------------------------------------
    async def _call_azure(self, *, messages: List[Dict[str, str]]) -> str:
        if not self.azure_enabled:
            raise RuntimeError("Azure OpenAI is not configured")

        url = f"{self.azure_endpoint}/openai/deployments/{self.azure_deployment}/chat/completions"
        payload = {
            "messages": messages,
            "temperature": self.azure_temperature,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "api-key": self.azure_key,
            "Content-Type": "application/json",
        }
        params = {"api-version": self.azure_api_version}
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, headers=headers, params=params, json=payload)
            response.raise_for_status()
            body = response.json()
        choices = body.get("choices", [])
        if not choices:
            raise RuntimeError("Azure response contained no choices")
        content = choices[0]["message"]["content"]
        return content


__all__ = [
    "AzureAgent",
    "RoundEvaluation",
    "PlayerResult",
    "SecretChoice",
]
