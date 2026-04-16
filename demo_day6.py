"""
День 6: комплексная демонстрация банковской системы.
Запуск: python demo_day6.py
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
import tempfile

from bank import (
    AccountStatus,
    AuditLog,
    AuditSeverity,
    Bank,
    Contacts,
    Currency,
    Portfolio,
    RiskAnalyzer,
    RiskLevel,
    Transaction,
    TransactionProcessor,
    TransactionQueue,
    TransactionStatus,
    TransactionType,
    VirtualAsset,
    compile_audit_report,
    new_transaction_id,
)


class DemoClock:
    def __init__(self, start: datetime) -> None:
        self.current = start

    def __call__(self) -> datetime:
        return self.current

    def advance(self, *, minutes: int = 0, seconds: int = 0) -> None:
        self.current += timedelta(minutes=minutes, seconds=seconds)


def queue_log(tx: Transaction) -> str:
    delay = (
        f", defer_until={tx.process_after.isoformat(timespec='minutes')}"
        if tx.process_after is not None
        else ""
    )
    return (
        f"{tx.transaction_id} [{tx.type.value}] "
        f"{tx.sender_account}->{tx.receiver_account or tx.external_party_ref or 'external'} "
        f"{tx.amount:.2f} {tx.currency.value}, priority={tx.priority}{delay}"
    )


def short_tx_line(tx: Transaction) -> str:
    return (
        f"{tx.transaction_id}: {tx.type.value}, amount={tx.amount:.2f} {tx.currency.value}, "
        f"status={tx.status.value}, reason={tx.failure_reason or '-'}"
    )


def main() -> None:
    clock = DemoClock(datetime(2026, 4, 7, 10, 0, 0))
    bank = Bank("Cursor Demo Bank", now=clock)

    client_specs = [
        ("c001", "Анна Иванова", 28, "+79000000001", "anna@example.com", "1111"),
        ("c002", "Борис Смирнов", 35, "+79000000002", "boris@example.com", "2222"),
        ("c003", "Виктория Орлова", 41, "+79000000003", "vika@example.com", "3333"),
        ("c004", "Глеб Соколов", 24, "+79000000004", "gleb@example.com", "4444"),
        ("c005", "Дарья Волкова", 32, "+79000000005", "daria@example.com", "5555"),
        ("c006", "Егор Панов", 52, "+79000000006", "egor@example.com", "6666"),
    ]

    print("=== Инициализация банка ===")
    for client_id, full_name, age, phone, email, pin in client_specs:
        bank.add_client(
            client_id,
            full_name,
            age,
            Contacts(phone=phone, email=email),
            pin,
        )
    print(f"Клиентов создано: {len(client_specs)}")

    opened_accounts: list[tuple[str, str]] = []
    opened_accounts.append(
        ("c001", bank.open_account("c001", "bank", currency=Currency.RUB, initial_balance=300_000.0))
    )
    opened_accounts.append(
        (
            "c001",
            bank.open_account(
                "c001",
                "savings",
                currency=Currency.RUB,
                initial_balance=150_000.0,
                min_balance=25_000.0,
                monthly_rate=0.004,
            ),
        )
    )
    opened_accounts.append(
        (
            "c002",
            bank.open_account(
                "c002",
                "premium",
                currency=Currency.USD,
                initial_balance=8_000.0,
                single_transaction_limit=100_000.0,
                daily_withdraw_limit=200_000.0,
                overdraft_limit=5_000.0,
                withdraw_commission=35.0,
            ),
        )
    )
    opened_accounts.append(
        ("c002", bank.open_account("c002", "bank", currency=Currency.RUB, initial_balance=90_000.0))
    )
    opened_accounts.append(
        (
            "c003",
            bank.open_account(
                "c003",
                "investment",
                currency=Currency.EUR,
                initial_balance=15_000.0,
                portfolios=[
                    Portfolio(
                        "balanced",
                        {
                            VirtualAsset.STOCKS: 40_000.0,
                            VirtualAsset.BONDS: 20_000.0,
                            VirtualAsset.ETF: 10_000.0,
                        },
                    )
                ],
            ),
        )
    )
    opened_accounts.append(
        ("c003", bank.open_account("c003", "bank", currency=Currency.RUB, initial_balance=60_000.0))
    )
    opened_accounts.append(
        (
            "c004",
            bank.open_account(
                "c004",
                "premium",
                currency=Currency.RUB,
                initial_balance=20_000.0,
                single_transaction_limit=300_000.0,
                daily_withdraw_limit=600_000.0,
                overdraft_limit=150_000.0,
                withdraw_commission=100.0,
            ),
        )
    )
    opened_accounts.append(
        ("c004", bank.open_account("c004", "bank", currency=Currency.KZT, initial_balance=2_500_000.0))
    )
    opened_accounts.append(
        ("c005", bank.open_account("c005", "bank", currency=Currency.CNY, initial_balance=12_000.0))
    )
    opened_accounts.append(
        (
            "c005",
            bank.open_account(
                "c005",
                "savings",
                currency=Currency.USD,
                initial_balance=4_000.0,
                min_balance=1_000.0,
                monthly_rate=0.003,
            ),
        )
    )
    opened_accounts.append(
        ("c006", bank.open_account("c006", "bank", currency=Currency.RUB, initial_balance=40_000.0))
    )
    opened_accounts.append(
        (
            "c006",
            bank.open_account(
                "c006",
                "investment",
                currency=Currency.USD,
                initial_balance=7_000.0,
                portfolios=[
                    Portfolio(
                        "growth",
                        {
                            VirtualAsset.STOCKS: 15_000.0,
                            VirtualAsset.ETF: 12_000.0,
                        },
                    )
                ],
            ),
        )
    )
    print(f"Счетов открыто: {len(opened_accounts)}")

    account_to_client = {account_number: client_id for client_id, account_number in opened_accounts}
    accounts = {number: bank.get_account(number) for _, number in opened_accounts}

    frozen_account = opened_accounts[10][1]
    bank.freeze_account("c006", frozen_account)

    temp_dir = tempfile.TemporaryDirectory()
    audit_path = Path(temp_dir.name) / "day6-audit.jsonl"
    audit = AuditLog(file_path=audit_path, now=clock)
    risk = RiskAnalyzer(
        large_amount=120_000.0,
        huge_amount=400_000.0,
        frequent_threshold_medium=5,
        frequent_threshold_high=9,
        now=clock,
    )
    processor = TransactionProcessor(
        accounts,
        fx_rates={
            (Currency.RUB, Currency.USD): 0.011,
            (Currency.USD, Currency.RUB): 90.0,
            (Currency.RUB, Currency.EUR): 0.01,
            (Currency.EUR, Currency.RUB): 100.0,
            (Currency.RUB, Currency.KZT): 5.0,
            (Currency.KZT, Currency.RUB): 0.2,
            (Currency.RUB, Currency.CNY): 0.08,
            (Currency.CNY, Currency.RUB): 12.5,
            (Currency.USD, Currency.EUR): 0.92,
            (Currency.EUR, Currency.USD): 1.087,
        },
        external_commission_rate=0.025,
        now=clock,
        audit_log=audit,
        risk_analyzer=risk,
        account_to_client=account_to_client,
        risk_block_from=RiskLevel.HIGH,
    )
    queue = TransactionQueue(now=clock)

    c1_main = opened_accounts[0][1]
    c1_save = opened_accounts[1][1]
    c2_premium = opened_accounts[2][1]
    c2_rub = opened_accounts[3][1]
    c3_invest = opened_accounts[4][1]
    c3_rub = opened_accounts[5][1]
    c4_premium = opened_accounts[6][1]
    c4_kzt = opened_accounts[7][1]
    c5_cny = opened_accounts[8][1]
    c5_save = opened_accounts[9][1]
    c6_rub = opened_accounts[10][1]
    c6_invest = opened_accounts[11][1]

    transactions: list[Transaction] = []

    def tx(
        sender: str | None,
        receiver: str | None,
        amount: float,
        currency: Currency,
        tx_type: TransactionType,
        *,
        client_id: str | None,
        external_ref: str | None = None,
        created_at: datetime | None = None,
    ) -> Transaction:
        ts = created_at or clock()
        item = Transaction(
            transaction_id=new_transaction_id(),
            type=tx_type,
            amount=amount,
            currency=currency,
            commission=0.0,
            sender_account=sender,
            receiver_account=receiver,
            created_at=ts,
            updated_at=ts,
            external_party_ref=external_ref,
            client_id=client_id,
        )
        transactions.append(item)
        return item

    normal_batch = [
        tx(c1_main, c2_rub, 12_000.0, Currency.RUB, TransactionType.INTERNAL_TRANSFER, client_id="c001"),
        tx(c2_rub, c3_rub, 8_500.0, Currency.RUB, TransactionType.INTERNAL_TRANSFER, client_id="c002"),
        tx(c3_rub, c1_main, 7_500.0, Currency.RUB, TransactionType.INTERNAL_TRANSFER, client_id="c003"),
        tx(c4_premium, c1_save, 18_000.0, Currency.RUB, TransactionType.INTERNAL_TRANSFER, client_id="c004"),
        tx(c1_main, c5_cny, 5_000.0, Currency.RUB, TransactionType.INTERNAL_TRANSFER, client_id="c001"),
        tx(c2_premium, c1_main, 600.0, Currency.USD, TransactionType.INTERNAL_TRANSFER, client_id="c002"),
        tx(c3_invest, c2_premium, 700.0, Currency.EUR, TransactionType.INTERNAL_TRANSFER, client_id="c003"),
        tx(c4_kzt, c3_rub, 200_000.0, Currency.KZT, TransactionType.INTERNAL_TRANSFER, client_id="c004"),
        tx(c5_cny, c1_main, 700.0, Currency.CNY, TransactionType.INTERNAL_TRANSFER, client_id="c005"),
        tx(c1_main, None, 15_000.0, Currency.RUB, TransactionType.EXTERNAL_TRANSFER, client_id="c001", external_ref="EXT-001"),
        tx(c2_rub, None, 7_500.0, Currency.RUB, TransactionType.EXTERNAL_TRANSFER, client_id="c002", external_ref="EXT-002"),
        tx(c5_save, c2_premium, 500.0, Currency.USD, TransactionType.INTERNAL_TRANSFER, client_id="c005"),
        tx(c6_invest, c1_main, 350.0, Currency.USD, TransactionType.INTERNAL_TRANSFER, client_id="c006"),
        tx(c1_save, c3_rub, 30_000.0, Currency.RUB, TransactionType.INTERNAL_TRANSFER, client_id="c001"),
        tx(c4_premium, None, 50_000.0, Currency.RUB, TransactionType.EXTERNAL_TRANSFER, client_id="c004", external_ref="EXT-003"),
        tx(c2_premium, c5_save, 1_000.0, Currency.USD, TransactionType.INTERNAL_TRANSFER, client_id="c002"),
        tx(c1_main, c6_invest, 900.0, Currency.RUB, TransactionType.INTERNAL_TRANSFER, client_id="c001"),
        tx(c3_rub, c4_premium, 10_000.0, Currency.RUB, TransactionType.INTERNAL_TRANSFER, client_id="c003"),
        tx(c5_cny, None, 900.0, Currency.CNY, TransactionType.EXTERNAL_TRANSFER, client_id="c005", external_ref="EXT-004"),
        tx(c2_rub, c1_main, 3_500.0, Currency.RUB, TransactionType.INTERNAL_TRANSFER, client_id="c002"),
        tx(c3_rub, c5_cny, 6_000.0, Currency.RUB, TransactionType.INTERNAL_TRANSFER, client_id="c003"),
        tx(c1_main, c2_rub, 14_000.0, Currency.RUB, TransactionType.INTERNAL_TRANSFER, client_id="c001"),
        tx(c2_rub, c3_rub, 9_000.0, Currency.RUB, TransactionType.INTERNAL_TRANSFER, client_id="c002"),
        tx(c1_main, c3_rub, 11_000.0, Currency.RUB, TransactionType.INTERNAL_TRANSFER, client_id="c001"),
    ]

    suspicious_batch = [
        tx(c1_main, c2_rub, 180_000.0, Currency.RUB, TransactionType.INTERNAL_TRANSFER, client_id="c001"),
        tx(c1_main, c5_cny, 450_000.0, Currency.RUB, TransactionType.INTERNAL_TRANSFER, client_id="c001"),
        tx(
            c2_rub,
            c3_rub,
            130_000.0,
            Currency.RUB,
            TransactionType.INTERNAL_TRANSFER,
            client_id="c002",
            created_at=datetime(2026, 4, 7, 2, 20, 0),
        ),
        tx(c4_premium, None, 420_000.0, Currency.RUB, TransactionType.EXTERNAL_TRANSFER, client_id="c004", external_ref="EXT-HIGH"),
    ]

    error_batch = [
        tx(c6_rub, c1_main, 5_000.0, Currency.RUB, TransactionType.INTERNAL_TRANSFER, client_id="c006"),
        tx(c5_cny, c2_rub, 40_000.0, Currency.CNY, TransactionType.INTERNAL_TRANSFER, client_id="c005"),
        tx(c1_save, c2_rub, 200_000.0, Currency.RUB, TransactionType.INTERNAL_TRANSFER, client_id="c001"),
        tx(c2_rub, c3_rub, 999_999.0, Currency.RUB, TransactionType.INTERNAL_TRANSFER, client_id="c002"),
        tx(c3_rub, c4_kzt, 5_000.0, Currency.USD, TransactionType.INTERNAL_TRANSFER, client_id="c003"),
        tx(c1_main, "MISSING-ACC", 1_000.0, Currency.RUB, TransactionType.INTERNAL_TRANSFER, client_id="c001"),
        tx(None, c2_rub, 500.0, Currency.RUB, TransactionType.EXTERNAL_TRANSFER, client_id=None, external_ref="BAD-OUT"),
        tx(c6_invest, c1_main, 20_000.0, Currency.USD, TransactionType.INTERNAL_TRANSFER, client_id="c006"),
    ]

    assert len(transactions) == 36

    print(f"Транзакций создано: {len(transactions)}")
    print("\n=== Попадание в очередь ===")
    cancelled_tx_id = ""
    for idx, item in enumerate(transactions):
        priority = 5 if idx < len(normal_batch) else 9 if idx < len(normal_batch) + len(suspicious_batch) else 3
        if idx in {5, 17, 28}:
            clock.advance(minutes=1)
            defer_until = clock() + timedelta(minutes=5)
            queue.add(item, priority=priority, defer_until=defer_until)
        else:
            queue.add(item, priority=priority)
        print("  queued:", queue_log(item))
        if idx == 12:
            cancelled_tx_id = item.transaction_id
            queue.cancel(item.transaction_id)
            print(f"  cancelled: {item.transaction_id}")
        clock.advance(seconds=10)

    clock.advance(minutes=10)

    print("\n=== Исполнение / отклонения ===")
    while True:
        current = queue.pop_due()
        if current is None:
            break
        ok = processor.process(current, queue=queue)
        verdict = "EXECUTED" if ok else "REJECTED"
        print(f"  {verdict}: {short_tx_line(current)}")
        clock.advance(seconds=15)

    report = compile_audit_report(audit, risk)
    status_counts = Counter(tx.status for tx in transactions)
    suspicious_ops = report["suspicious_entries"]

    print("\n=== Сценарий: счета клиента c001 ===")
    client = bank.get_client("c001")
    for number in client.account_numbers:
        print(" ", bank.get_account(number))

    print("\n=== Сценарий: история клиента c001 ===")
    c001_history = [
        tx_item
        for tx_item in transactions
        if tx_item.client_id == "c001"
        or tx_item.sender_account in client.account_numbers
        or tx_item.receiver_account in client.account_numbers
    ]
    for tx_item in c001_history[:10]:
        print(" ", short_tx_line(tx_item))
    if len(c001_history) > 10:
        print(f"  ... ещё {len(c001_history) - 10} операций")

    print("\n=== Сценарий: подозрительные операции ===")
    for record in suspicious_ops[:10]:
        extra = record.extra.get("risk_level", "-")
        print(
            f"  {record.timestamp.isoformat(timespec='seconds')} "
            f"[{record.severity.name}] tx={record.transaction_id} client={record.client_id} "
            f"risk={extra} {record.message}"
        )

    print("\n=== Отчёты ===")
    print("Топ-3 клиентов:")
    for row in bank.get_clients_ranking()[:3]:
        print(" ", row)

    print("Статистика транзакций:")
    print(
        " ",
        {
            "queued_total": len(transactions),
            "completed": status_counts[TransactionStatus.COMPLETED],
            "failed": status_counts[TransactionStatus.FAILED],
            "cancelled": status_counts[TransactionStatus.CANCELLED],
            "high_or_warning_audit_entries": len(suspicious_ops),
            "audit_errors": sum(1 for rec in audit.all_entries() if rec.severity >= AuditSeverity.ERROR),
        },
    )

    print(f"Общий баланс банка: {bank.get_total_balance():.2f}")
    print(f"Записей аудита в памяти: {len(audit.all_entries())}")
    print(f"Строк в audit-файле: {audit_path.read_text(encoding='utf-8').count(chr(10))}")
    print("Статистика ошибок аудита:", report["error_statistics"])
    print("Риск-профили:", report["client_risk_profiles"])
    print(f"Замороженный счёт c006: {frozen_account} -> {bank.get_account(frozen_account).status.value}")
    print(f"Отменённая транзакция: {cancelled_tx_id}")

    temp_dir.cleanup()


if __name__ == "__main__":
    main()
