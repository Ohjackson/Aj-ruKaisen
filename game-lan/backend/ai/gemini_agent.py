"""Azure OpenAI orchestrator for the fully automated Azure Kaisen flow."""
from __future__ import annotations

import json
import logging

logger = logging.getLogger("azure-kaisen.ai")
import os
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from .gemini_parser import parse_gemini_response
from .models import (GeminiPlayerResult, GeminiRoundEvaluation,
                     GeminiSubmission, PlayerResult, RoundEvaluation, SecretChoice)


class GeminiAgent:
    """Wrapper around Gemini for game orchestration."""

    def __init__(self, *, hints_enabled: bool = True) -> None:
        self.hints_enabled = hints_enabled

        self.gemini_endpoint = os.getenv("GEMINI_API_ENDPOINT", "").rstrip("/")
        self.gemini_key = os.getenv("GEMINI_API_KEY", "")
        self.gemini_temperature = float(os.getenv("GEMINI_TEMPERATURE", "0.2"))
        self.debug_enabled = os.getenv("GEMINI_DEBUG", "0").lower() in {"1", "true", "yes", "on"}

        self.gemini_enabled = bool(self.gemini_endpoint and self.gemini_key)
        if not self.gemini_enabled:
            logger.warning("Gemini API credentials not fully configured. Fallback will be used.")

        with open(Path(__file__).parent / "gemini_prompt.txt", "r") as f:
            self.prompt_template = f.read()



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
    ) -> GeminiRoundEvaluation:
        if self.gemini_enabled and self.hints_enabled:
            try:
                gemini_submissions = [
                    GeminiSubmission(user=p["name"], input=submissions.get(p["id"], {}).get("word", ""))
                    for p in player_order
                ]

                prompt = self.prompt_template.replace("some_secret_word", secret)

                payload = {
                    "secretWord": secret,
                    "submissions": [s.__dict__ for s in gemini_submissions],
                }

                if self.debug_enabled:
                    logger.debug("[Gemini] Request payload: %s", json.dumps(payload, ensure_ascii=False))

                response_payload = await self._call_gemini(prompt, payload)
                if self.debug_enabled:
                    logger.debug("[Gemini] Raw response: %s", response_payload)
                return parse_gemini_response(response_payload)

            except Exception as exc:
                logger.warning("Gemini round evaluation failed: %s", exc, exc_info=self.debug_enabled)

        # Fallback to a simple evaluation if Gemini fails
        return self._fallback_evaluation(secret=secret, submissions=submissions, player_order=player_order)

    def _fallback_evaluation(
        self,
        *,
        secret: str,
        submissions: Dict[str, Dict[str, Any]],
        player_order: List[Dict[str, Any]],
    ) -> GeminiRoundEvaluation:
        results = []
        for player in player_order:
            submission = submissions.get(player["id"], {})
            word = submission.get("word", "")
            results.append(GeminiPlayerResult(
                user=player["name"],
                input=word,
                score=50 if word else 0,
                hint="This is a fallback hint.",
            ))
        if self.debug_enabled and not self.gemini_enabled:
            logger.debug("[Gemini] Falling back because API is disabled")
        if self.debug_enabled and self.gemini_enabled:
            logger.debug("[Gemini] Falling back evaluation for secret=%s", secret)
        return GeminiRoundEvaluation(results=results)

    async def choose_secret(self, *, round_index: int, used_secrets: List[str]) -> SecretChoice:
        # Simple random word for now, as the main evaluation is done by Gemini
        words = ["apple", "banana", "cherry", "date", "elderberry", "fig", "grape"]
        secret = random.choice(words)
        return SecretChoice(
            secret=secret,
            theme="Random",
            rationale="A random word",
            source="local",
        )

    async def _call_gemini(self, prompt: str, payload: Dict[str, Any]) -> str:
        if not self.gemini_enabled:
            raise RuntimeError("Gemini API is not configured")

        url = f"{self.gemini_endpoint}" # I need to ask the user for the correct URL structure
        
        # The user needs to provide the correct payload structure for Gemini
        gemini_payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {"text": json.dumps(payload)}
                    ]
                }
            ]
        }

        headers = {
            "x-goog-api-key": self.gemini_key,
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            if self.debug_enabled:
                logger.debug("[Gemini] POST %s", url)
                logger.debug("[Gemini] Headers: %s", {k: ('***' if 'key' in k.lower() else v) for k, v in headers.items()})
            response = await client.post(url, headers=headers, json=gemini_payload)
            response.raise_for_status()
            body = response.json()
            if self.debug_enabled:
                logger.debug("[Gemini] Response body: %s", json.dumps(body, ensure_ascii=False))
        
        # This part depends on the Gemini API response structure
        # I will assume it returns the content directly
        content = body.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        if self.debug_enabled:
            logger.debug("[Gemini] Parsed text length: %s", len(content))
        return content


__all__ = [
    "GeminiAgent",
    "GeminiRoundEvaluation",
    "GeminiPlayerResult",
    "SecretChoice",
]
