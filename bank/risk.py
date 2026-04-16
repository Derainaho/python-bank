from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from enum import Enum
from typing import Any


def _tx_type_value(tx: Any) -> str:
    t = getattr(tx, "type", None)
    return getattr(t, "value", str(t))


class RiskLevel(str, Enum):
    """Итоговый уровень риска операции."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(slots=True)
class RiskSignal:
    """Отдельный фактор риска."""

    code: str
    description: str
    weight: int


@dataclass(slots=True)
class RiskAssessment:
    """Результат анализа."""

    level: RiskLevel
    score: int
    signals: list[RiskSignal] = field(default_factory=list)

    def to_extra(self) -> dict[str, Any]:
        return {
            "risk_level": self.level.value,
            "risk_score": self.score,
            "risk_signals": [s.code for s in self.signals],
        }


_NIGHT_START = time(0, 0, 0)
_NIGHT_END = time(5, 0, 0)


def _is_night(ts: datetime) -> bool:
    t = ts.time()
    return _NIGHT_START <= t < _NIGHT_END


class RiskAnalyzer:
    """
    Эвристики: крупная сумма, частые операции, перевод на «новый» счёт, ночное время.
    После успешной операции вызывайте register_completed(tx).
    """

    def __init__(
        self,
        *,
        large_amount: float = 100_000.0,
        huge_amount: float = 500_000.0,
        frequent_window: timedelta = timedelta(minutes=5),
        frequent_threshold_medium: int = 4,
        frequent_threshold_high: int = 10,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._large_amount = float(large_amount)
        self._huge_amount = float(huge_amount)
        self._frequent_window = frequent_window
        self._freq_med = int(frequent_threshold_medium)
        self._freq_high = int(frequent_threshold_high)
        self._now = now if now is not None else datetime.now

        self._receiver_has_incoming: set[str] = set()
        self._sender_times: dict[str, deque[datetime]] = defaultdict(deque)
        self._client_scores: dict[str, int] = defaultdict(int)

    def register_completed(self, tx: Any) -> None:
        """Помечает получателя как уже получавшего входящие (для внутренних переводов)."""
        if _tx_type_value(tx) == "internal_transfer" and tx.receiver_account:
            self._receiver_has_incoming.add(tx.receiver_account)
        if tx.sender_account:
            self._sender_times[tx.sender_account].append(tx.updated_at)

    def _prune_sender(self, sender: str, ts: datetime) -> int:
        q = self._sender_times[sender]
        cutoff = ts - self._frequent_window
        while q and q[0] < cutoff:
            q.popleft()
        return len(q)

    def analyze(
        self,
        tx: Any,
        *,
        account_to_client: Mapping[str, str] | None = None,
    ) -> RiskAssessment:
        signals: list[RiskSignal] = []
        score = 0
        ts = tx.created_at
        ref = self._now()
        sender = tx.sender_account or ""

        amt = float(tx.amount)
        if amt >= self._huge_amount:
            signals.append(RiskSignal("huge_amount", f"Сумма {amt:.2f} ≥ порога «крупно»", 4))
            score += 4
        elif amt >= self._large_amount:
            signals.append(RiskSignal("large_amount", f"Сумма {amt:.2f} ≥ порога «заметно»", 2))
            score += 2

        if _is_night(ts):
            signals.append(RiskSignal("night", "Операция инициирована в ночное окно 00:00–05:00", 2))
            score += 2

        if _tx_type_value(tx) == "internal_transfer" and tx.receiver_account:
            if tx.receiver_account not in self._receiver_has_incoming:
                signals.append(RiskSignal("new_receiver", "Первый входящий на счёт получателя", 2))
                score += 2

        if sender:
            recent_count = self._prune_sender(sender, ref)
            if recent_count >= self._freq_high:
                signals.append(RiskSignal("burst_high", f"Частые операции с отправителя: {recent_count}+ за окно", 4))
                score += 4
            elif recent_count >= self._freq_med:
                signals.append(RiskSignal("burst_medium", f"Повышенная частота операций: {recent_count} за окно", 2))
                score += 2

        if score >= 6:
            level = RiskLevel.HIGH
        elif score >= 3:
            level = RiskLevel.MEDIUM
        else:
            level = RiskLevel.LOW

        cid = None
        if account_to_client and sender:
            cid = account_to_client.get(sender)
        if cid:
            self._client_scores[cid] += score

        return RiskAssessment(level=level, score=score, signals=signals)

    def client_risk_profile(self, client_id: str) -> dict[str, Any]:
        """Накопленный «скор» по клиенту (после серии анализов)."""
        return {
            "client_id": client_id,
            "accumulated_risk_score": int(self._client_scores.get(client_id, 0)),
        }

    def known_client_ids(self) -> frozenset[str]:
        """Клиенты, по которым уже накапливалась оценка риска."""
        return frozenset(self._client_scores.keys())
