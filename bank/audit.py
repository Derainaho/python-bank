from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable


class AuditSeverity(IntEnum):
    """Уровни важности записи аудита (чем больше значение, тем серьезнее)."""

    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50


@dataclass(slots=True)
class AuditRecord:
    """Одна запись журнала аудита."""

    timestamp: datetime
    severity: AuditSeverity
    message: str
    transaction_id: str | None = None
    client_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def matches_filter(
        self,
        *,
        min_severity: AuditSeverity | None = None,
        client_id: str | None = None,
        transaction_id: str | None = None,
        text: str | None = None,
    ) -> bool:
        if min_severity is not None and self.severity < min_severity:
            return False
        if client_id is not None and self.client_id != client_id:
            return False
        if transaction_id is not None and self.transaction_id != transaction_id:
            return False
        if text is not None and text.lower() not in self.message.lower():
            return False
        return True


class AuditLog:
    """Журнал аудита: память + опциональная запись в файл, фильтрация."""

    def __init__(
        self,
        *,
        file_path: str | Path | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._entries: list[AuditRecord] = []
        self._file_path = Path(file_path) if file_path is not None else None
        self._now = now if now is not None else datetime.now
        if self._file_path is not None:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)

    def append(
        self,
        severity: AuditSeverity,
        message: str,
        *,
        transaction_id: str | None = None,
        client_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> AuditRecord:
        rec = AuditRecord(
            timestamp=self._now(),
            severity=severity,
            message=message,
            transaction_id=transaction_id,
            client_id=client_id,
            extra=dict(extra or {}),
        )
        self._entries.append(rec)
        self._persist_record(rec)
        return rec

    def _persist_record(self, rec: AuditRecord) -> None:
        if self._file_path is None:
            return
        payload = asdict(rec)
        payload["severity"] = int(rec.severity)
        payload["timestamp"] = rec.timestamp.isoformat(timespec="seconds")
        line = json.dumps(payload, ensure_ascii=False, default=str)
        with self._file_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def filter(
        self,
        *,
        min_severity: AuditSeverity | None = None,
        client_id: str | None = None,
        transaction_id: str | None = None,
        text: str | None = None,
    ) -> list[AuditRecord]:
        return [
            r
            for r in self._entries
            if r.matches_filter(
                min_severity=min_severity,
                client_id=client_id,
                transaction_id=transaction_id,
                text=text,
            )
        ]

    def all_entries(self) -> tuple[AuditRecord, ...]:
        return tuple(self._entries)

    def error_statistics(self) -> dict[str, int]:
        """Подсчёт сообщений уровня ERROR/CRITICAL по тексту (агрегат для отчёта)."""
        stats: dict[str, int] = {}
        for r in self._entries:
            if r.severity < AuditSeverity.ERROR:
                continue
            key = r.message.split(":", 1)[0].strip() if ":" in r.message else r.message
            stats[key] = stats.get(key, 0) + 1
        return stats


def suspicious_audit_entries(log: AuditLog) -> list[AuditRecord]:
    """Записи, связанные с риском или предупреждениями (для отчёта)."""
    return [r for r in log.all_entries() if r.severity >= AuditSeverity.WARNING]


def compile_audit_report(log: AuditLog, analyzer: Any) -> dict[str, Any]:
    """Сводный отчёт: подозрительные записи, профиль по клиентам (накопленный скор), статистика ошибок."""
    profiles = {cid: analyzer.client_risk_profile(cid) for cid in analyzer.known_client_ids()}
    return {
        "suspicious_entries": suspicious_audit_entries(log),
        "client_risk_profiles": profiles,
        "error_statistics": log.error_statistics(),
    }
