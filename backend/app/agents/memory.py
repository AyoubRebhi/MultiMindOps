"""
Agent memory system.

Provides short-term caching (prompt → output) and a structured decision log
for all agents in the DevSecOps AI platform.

Classes:
    MemoryEntry      — one cached prompt/output pair with metadata
    DecisionRecord   — one recorded agent decision
    AgentMemory      — the main memory manager
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Data models ───────────────────────────────────────────────────────────────


@dataclass
class MemoryEntry:
    """A single cached prompt → output record."""

    key: str
    agent_name: str
    prompt: str
    output: Dict[str, Any]
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    access_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryEntry":
        return cls(
            key=data["key"],
            agent_name=data["agent_name"],
            prompt=data["prompt"],
            output=data["output"],
            confidence=data.get("confidence", 1.0),
            metadata=data.get("metadata", {}),
            timestamp=data.get("timestamp", time.time()),
            access_count=data.get("access_count", 0),
        )


@dataclass
class DecisionRecord:
    """A structured record of one agent decision."""

    agent: str
    decision: str
    reasoning: str
    confidence: float
    context: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── AgentMemory ───────────────────────────────────────────────────────────────


class AgentMemory:
    """
    Short-term memory for a single agent.

    Features
    --------
    - **Prompt caching** — store and retrieve LLM outputs keyed by prompt hash.
    - **TTL expiry** — optionally expire entries after N seconds.
    - **Capacity limit** — evict oldest entries when max_entries is exceeded.
    - **Decision log** — append structured decisions with confidence scores.
    - **Optional persistence** — load/save to a JSON file across restarts.

    Usage
    -----
    >>> mem = AgentMemory("InfrastructureAgent")
    >>> mem.remember(prompt, response, confidence=0.9)
    >>> entry = mem.recall(prompt)        # MemoryEntry or None
    >>> mem.has_cached(prompt)            # bool
    >>> mem.record_decision("use_rag", "RAG was available", confidence=0.95)
    >>> mem.get_decision_history(last_n=5)
    """

    def __init__(
        self,
        agent_name: str,
        max_entries: int = 100,
        persist_path: Optional[str] = None,
        ttl_seconds: Optional[float] = None,
    ):
        self.agent_name = agent_name
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self.persist_path = Path(persist_path) if persist_path else None

        self._store: Dict[str, MemoryEntry] = {}
        self._decisions: List[DecisionRecord] = []

        if self.persist_path and self.persist_path.exists():
            self._load()

    # ── Write ─────────────────────────────────────────────────────────────────

    def remember(
        self,
        prompt: str,
        output: Dict[str, Any],
        confidence: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Cache a prompt → output pair.

        Parameters
        ----------
        prompt:     The exact user prompt (used as cache key after hashing).
        output:     The LLM response dict to cache.
        confidence: Quality score 0–1 (degraded on retries, used for cache eviction policy).
        metadata:   Optional extra context stored alongside the entry.

        Returns
        -------
        str  — the 32-char hex cache key.
        """
        key = self._hash(prompt)
        self._store[key] = MemoryEntry(
            key=key,
            agent_name=self.agent_name,
            prompt=prompt,
            output=output,
            confidence=confidence,
            metadata=metadata or {},
        )
        self._trim()
        logger.debug("[%s] Memorized key=%s conf=%.2f", self.agent_name, key[:8], confidence)
        if self.persist_path:
            self._save()
        return key

    def record_decision(
        self,
        decision: str,
        reasoning: str,
        confidence: float = 1.0,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append a structured decision to the history log."""
        self._decisions.append(
            DecisionRecord(
                agent=self.agent_name,
                decision=decision,
                reasoning=reasoning,
                confidence=confidence,
                context=context or {},
            )
        )
        logger.info("[%s] Decision: %s (conf=%.2f)", self.agent_name, decision, confidence)

    # ── Read ──────────────────────────────────────────────────────────────────

    def recall(self, prompt: str) -> Optional[MemoryEntry]:
        """
        Retrieve a cached entry.

        Returns None if:
        - The prompt was never cached.
        - The entry's TTL has expired.
        """
        key = self._hash(prompt)
        entry = self._store.get(key)
        if entry is None:
            return None
        if self.ttl_seconds and (time.time() - entry.timestamp) > self.ttl_seconds:
            del self._store[key]
            logger.debug("[%s] Entry expired key=%s", self.agent_name, key[:8])
            return None
        entry.access_count += 1
        return entry

    def has_cached(self, prompt: str) -> bool:
        """True if a valid (non-expired) cached entry exists for this prompt."""
        return self.recall(prompt) is not None

    def get_decision_history(self, last_n: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return decision history as a list of dicts (newest last)."""
        history = self._decisions
        if last_n:
            history = history[-last_n:]
        return [d.to_dict() for d in history]

    def stats(self) -> Dict[str, Any]:
        """Snapshot of current memory usage."""
        return {
            "agent": self.agent_name,
            "cached_entries": len(self._store),
            "decisions": len(self._decisions),
            "persisted": self.persist_path is not None,
        }

    def clear(self) -> None:
        """Wipe all cached entries and decisions."""
        self._store.clear()
        self._decisions.clear()

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.strip().encode()).hexdigest()[:32]

    def _trim(self) -> None:
        """Evict oldest entries when max_entries is exceeded."""
        if len(self._store) <= self.max_entries:
            return
        evict = sorted(self._store.values(), key=lambda e: e.timestamp)
        for entry in evict[: len(self._store) - self.max_entries]:
            del self._store[entry.key]

    def _save(self) -> None:
        try:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)  # type: ignore[union-attr]
            payload = {
                "agent_name": self.agent_name,
                "entries": {k: v.to_dict() for k, v in self._store.items()},
                "decisions": [d.to_dict() for d in self._decisions],
            }
            self.persist_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning("[%s] Persist failed: %s", self.agent_name, exc)

    def _load(self) -> None:
        try:
            payload = json.loads(self.persist_path.read_text(encoding="utf-8"))  # type: ignore[union-attr]
            self._store = {
                k: MemoryEntry.from_dict(v) for k, v in payload.get("entries", {}).items()
            }
            self._decisions = [DecisionRecord(**d) for d in payload.get("decisions", [])]
            logger.info(
                "[%s] Loaded %d entries from %s",
                self.agent_name,
                len(self._store),
                self.persist_path,
            )
        except Exception as exc:
            logger.warning("[%s] Load from disk failed: %s", self.agent_name, exc)
