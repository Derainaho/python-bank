"""
День 5: аудит, риск-анализ, блокировка опасных операций, отчёты.
Запуск: python demo_day5.py
"""

from datetime import datetime, timedelta
from pathlib import Path
import tempfile

from bank import (
    AuditLog,
    AuditSeverity,
    BankAccount,
    Currency,
    Owner,
    RiskAnalyzer,
    RiskLevel,
    Transaction,
    TransactionProcessor,
    TransactionQueue,
    TransactionType,
    compile_audit_report,
    new_transaction_id,
    run_queue_until_empty,
)


class Clock:
    def __init__(self, t: datetime) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t

    def advance(self, seconds: float = 0.0, **kwargs: int) -> None:
        self.t += timedelta(seconds=seconds, **kwargs)


def main() -> None:
    clock = Clock(datetime(2026, 4, 6, 14, 0, 0))
    owner = Owner(full_name="Аудит Клиент")

    a_main = BankAccount(owner, Currency.RUB, account_number="AUD-MAIN", initial_balance=2_000_000.0)
    a_sec = BankAccount(owner, Currency.RUB, account_number="AUD-SEC", initial_balance=50_000.0)
    a_new = BankAccount(owner, Currency.RUB, account_number="AUD-NEW", initial_balance=0.0)
    accounts = {a.account_number: a for a in (a_main, a_sec, a_new)}

    mapping = {"AUD-MAIN": "client-alpha", "AUD-SEC": "client-beta", "AUD-NEW": "client-gamma"}

    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "audit.jsonl"
        audit = AuditLog(file_path=log_path, now=clock)
        risk = RiskAnalyzer(
            large_amount=150_000.0,
            huge_amount=500_000.0,
            frequent_window=timedelta(minutes=5),
            frequent_threshold_medium=3,
            frequent_threshold_high=8,
            now=clock,
        )

        processor = TransactionProcessor(
            accounts,
            now=clock,
            audit_log=audit,
            risk_analyzer=risk,
            account_to_client=mapping,
            risk_block_from=RiskLevel.HIGH,
        )

        txs: list[Transaction] = []

        def mk(
            amount: float,
            to: str,
            *,
            night: bool = False,
            client: str | None = "client-alpha",
        ) -> Transaction:
            ts = clock.t if not night else clock.t.replace(hour=2, minute=30)
            return Transaction(
                new_transaction_id(),
                TransactionType.INTERNAL_TRANSFER,
                amount,
                Currency.RUB,
                0.0,
                "AUD-MAIN",
                to,
                created_at=ts,
                updated_at=ts,
                client_id=client,
            )

        # Обычные переводы
        txs.append(mk(5_000.0, "AUD-SEC"))
        clock.advance(seconds=1)
        txs.append(mk(12_000.0, "AUD-SEC"))
        clock.advance(seconds=1)
        txs.append(mk(8_000.0, "AUD-SEC"))

        # Частые операции (серия)
        for _ in range(4):
            txs.append(mk(1_000.0, "AUD-SEC"))
            clock.advance(seconds=1)

        # Крупная сумма (средний риск)
        txs.append(mk(180_000.0, "AUD-SEC"))
        clock.advance(seconds=1)

        # Ночная операция + крупная → высокий риск, блок
        txs.append(
            Transaction(
                new_transaction_id(),
                TransactionType.INTERNAL_TRANSFER,
                520_000.0,
                Currency.RUB,
                0.0,
                "AUD-MAIN",
                "AUD-SEC",
                created_at=datetime(2026, 4, 6, 3, 0, 0),
                updated_at=datetime(2026, 4, 6, 3, 0, 0),
                client_id="client-alpha",
            )
        )

        # Перевод на «новый» счёт (первый входящий)
        txs.append(mk(25_000.0, "AUD-NEW", client="client-alpha"))

        # Ещё одна нормальная
        txs.append(mk(3_000.0, "AUD-SEC", client="client-alpha"))

        queue = TransactionQueue(now=clock)
        for tx in txs:
            queue.add(tx, priority=0)

        run_queue_until_empty(queue, processor)

        report = compile_audit_report(audit, risk)

        print("Всего записей аудита:", len(audit.all_entries()))
        print("Подозрительных (severity ≥ WARNING):", len(report["suspicious_entries"]))
        print("Профили клиентов:", report["client_risk_profiles"])
        print("Статистика ошибок (ERROR+):", report["error_statistics"])
        print("Файл журнала (строк):", log_path.read_text(encoding="utf-8").count("\n"))

        print("\nФильтр по клиенту client-alpha:")
        for r in audit.filter(client_id="client-alpha", min_severity=AuditSeverity.INFO):
            print(f"  {r.timestamp.isoformat()} [{r.severity.name}] {r.message}")


if __name__ == "__main__":
    main()
