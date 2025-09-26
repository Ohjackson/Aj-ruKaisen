"""Lightweight PDF-based hint engine for Azure Kaisen.

This engine avoids external LLM usage by extracting sentences from the
provided PDF and composing indirect hints that help players deduce the
secret without revealing it."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from pypdf import PdfReader


_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ가-힣0-9]{2,}")


@dataclass
class HintResult:
    hint: str
    ai_score_suggestion: int
    flags: List[str]


class PdfHintEngine:
    def __init__(self, *, pdf_path: Path, rules_path: Path) -> None:
        self.pdf_path = pdf_path
        self.rules_path = rules_path
        self.rules = self._load_rules(rules_path)
        self.sentences = self._load_sentences(pdf_path)
        self.keyword_index = self._build_index(self.sentences)

    # ------------------------------------------------------------------
    # Loading helpers
    # ------------------------------------------------------------------
    def _load_rules(self, path: Path) -> Dict[str, Sequence[str]]:
        with path.open("r", encoding="utf-8") as f:
            rules = json.load(f)
        rules.setdefault("forbidden", [])
        rules.setdefault("spoilers", [])
        rules.setdefault("noise", [])
        rules.setdefault("penalties", {})
        return rules

    def _load_sentences(self, path: Path) -> List[str]:
        reader = PdfReader(str(path))
        text_parts: List[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            text = text.replace("\u200b", " ")
            text_parts.append(text)
        full_text = "\n".join(text_parts)
        # Simple sentence split that keeps Korean/Japanese punctuation
        raw_sentences = re.split(r"(?<=[\.!?。？！])\s+", full_text)
        cleaned = []
        for sentence in raw_sentences:
            s = sentence.strip()
            if len(s) < 10:
                continue
            cleaned.append(s)
        return cleaned

    def _extract_keywords(self, text: str) -> List[str]:
        return [m.group(0).lower() for m in _WORD_RE.finditer(text)]

    def _build_index(self, sentences: Sequence[str]):
        index: Dict[str, List[int]] = {}
        for idx, sentence in enumerate(sentences):
            for word in set(self._extract_keywords(sentence)):
                index.setdefault(word, []).append(idx)
        return index

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """Hot-reload the PDF and rules."""
        self.rules = self._load_rules(self.rules_path)
        self.sentences = self._load_sentences(self.pdf_path)
        self.keyword_index = self._build_index(self.sentences)

    # Core hint generation -------------------------------------------------
    def generate_hint(
        self,
        *,
        secret: str,
        submitted_word: str,
        previous_round_summaries: Optional[Sequence[str]] = None,
    ) -> HintResult:
        secret_tokens = self._extract_keywords(secret)
        submission_tokens = self._extract_keywords(submitted_word)
        candidate_indices = self._collect_candidate_indices(secret_tokens, submission_tokens)

        best_sentence, relevance = self._pick_best_sentence(candidate_indices, secret_tokens, submission_tokens)

        if not best_sentence:
            hint_text = self._fallback_hint(submitted_word, previous_round_summaries)
            suggestion = 0 if not submitted_word else 1
        else:
            hint_text = self._redact_terms(best_sentence, [secret] + list(self.rules.get("spoilers", [])))
            suggestion = 2 if relevance > 1 else 1

        flags = self._derive_flags(secret_tokens, submission_tokens, hint_text)
        return HintResult(hint=hint_text, ai_score_suggestion=suggestion, flags=flags)

    # Candidate selection helpers -----------------------------------------
    def _collect_candidate_indices(self, secret_tokens: Sequence[str], submission_tokens: Sequence[str]) -> List[int]:
        candidates = set()
        for token in secret_tokens:
            for idx in self.keyword_index.get(token, []):
                candidates.add(idx)
        for token in submission_tokens:
            for idx in self.keyword_index.get(token, []):
                candidates.add(idx)
        return sorted(candidates)

    def _pick_best_sentence(
        self,
        candidate_indices: Sequence[int],
        secret_tokens: Sequence[str],
        submission_tokens: Sequence[str],
    ) -> Tuple[Optional[str], int]:
        best_sentence = None
        best_score = 0
        secret_set = set(secret_tokens)
        submission_set = set(submission_tokens)
        spoilers = {term.lower() for term in self.rules.get("spoilers", [])}

        for idx in candidate_indices:
            if idx >= len(self.sentences):
                continue
            sentence = self.sentences[idx]
            tokens = set(self._extract_keywords(sentence))
            if any(token in secret_set for token in tokens):
                # Skip sentences that explicitly use the secret tokens
                continue
            if any(token in spoilers for token in tokens):
                continue
            match_score = 0
            if submission_set:
                match_score += len(tokens & submission_set)
            if secret_set:
                # prefer sentences in proximity to secret concepts
                match_score += int(len(tokens & secret_set) * 1.5)
            # add slight boost when sentence comes from earlier section to encourage variety
            positional_bonus = max(0, 5 - int(math.log2(idx + 2)))
            total_score = match_score + positional_bonus
            if total_score > best_score:
                best_score = total_score
                best_sentence = sentence
        return best_sentence, best_score

    def _redact_terms(self, text: str, terms: Sequence[str]) -> str:
        redacted = text
        for term in terms:
            if not term:
                continue
            pattern = re.compile(re.escape(term), re.IGNORECASE)
            redacted = pattern.sub("?" * min(len(term), 3), redacted)
        return redacted.strip()

    def _fallback_hint(self, submitted_word: str, previous_round_summaries: Optional[Sequence[str]]) -> str:
        if submitted_word:
            message = f"제출한 단어 '{submitted_word}'에서 파생된 주제를 다시 살펴보세요. 자료의 다른 장에서 간접적인 실마리를 찾을 수 있습니다."
        else:
            message = "이번에는 단서를 찾지 못했어요. 다음 턴에는 자료에서 떠오르는 핵심 개념을 짚어보세요."
        if previous_round_summaries:
            message += " 이전 라운드의 요약을 참고하면 흐름을 이어가는데 도움이 됩니다."
        return message

    def _derive_flags(self, secret_tokens: Sequence[str], submission_tokens: Sequence[str], hint_text: str) -> List[str]:
        flags: List[str] = []
        secret_set = set(secret_tokens)
        submission_set = set(submission_tokens)
        forbidden = {term.lower() for term in self.rules.get("forbidden", [])}
        spoilers = {term.lower() for term in self.rules.get("spoilers", [])}

        if secret_set and submission_set & secret_set:
            flags.append("too_direct")
        if submission_set & forbidden:
            flags.append("forbidden")
        if submission_set & spoilers:
            flags.append("too_direct")
        if not submission_set:
            flags.append("off_topic")
        elif submission_set.isdisjoint(self.keyword_index.keys()):
            flags.append("off_topic")
        if any(term in hint_text.lower() for term in spoilers):
            if "too_direct" not in flags:
                flags.append("too_direct")
        return flags


__all__ = ["PdfHintEngine", "HintResult"]
