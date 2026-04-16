"""
День 7: отчётность и визуализация.
Запуск: python demo_day7.py
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import tempfile

from bank import (
    AuditLog,
    Bank,
    Contacts,
    Currency,
    Portfolio,
    ReportBuilder,
    RiskAnalyzer,
    RiskLevel,
    Transaction,
    TransactionProcessor,
    TransactionQueue,
    TransactionType,
    VirtualAsset,
    new_transaction_id,
)


class DemoClock:
    def __init__(self, start: datetime) -> None:
        self.current = start

    def __call__(self) -> datetime:
        return self.current

    def advance(self, *, minutes: int = 0, seconds: int = 0) -> None:
        self.current += timedelta(minutes=minutes, seconds=seconds)


def main() -> None:
    clock = DemoClock(datetime(2026, 4, 8, 11, 0, 0))
    bank = Bank("Report Demo Bank", now=clock)

    clients = [
        ("c101", "Ирина Павлова", 29, "+79001110001", "irina@example.com", "1111"),
        ("c102", "Кирилл Зотов", 38, "+79001110002", "kirill@example.com", "2222"),
        ("c103", "Лев Серов", 45, "+79001110003", "lev@example.com", "3333"),
        ("c104", "Марина Лебедева", 31, "+79001110004", "marina@example.com", "4444"),
    ]
    for client_id, name, age, phone, email, pin in clients:
        bank.add_client(client_id, name, age, Contacts(phone=phone, email=email), pin)

    opened: list[tuple[str, str]] = [
        ("c101", bank.open_account("c101", "bank", currency=Currency.RUB, initial_balance=180_000.0)),
        (
            "c101",
            bank.open_account(
                "c101",
                "savings",
                currency=Currency.USD,
                initial_balance=5_000.0,
                min_balance=1_000.0,
                monthly_rate=0.003,
            ),
        ),
        (
            "c102",
            bank.open_account(
                "c102",
                "premium",
                currency=Currency.RUB,
                initial_balance=50_000.0,
                single_transaction_limit=250_000.0,
                daily_withdraw_limit=500_000.0,
                overdraft_limit=100_000.0,
                withdraw_commission=50.0,
            ),
        ),
        ("c102", bank.open_account("c102", "bank", currency=Currency.EUR, initial_balance=12_000.0)),
        (
            "c103",
            bank.open_account(
                "c103",
                "investment",
                currency=Currency.USD,
                initial_balance=8_000.0,
                portfolios=[
                    Portfolio(
                        "global",
                        {
                            VirtualAsset.STOCKS: 18_000.0,
                            VirtualAsset.BONDS: 7_000.0,
                            VirtualAsset.ETF: 9_000.0,
                        },
                    )
                ],
            ),
        ),
        ("c104", bank.open_account("c104", "bank", currency=Currency.CNY, initial_balance=20_000.0)),
    ]

    account_to_client = {account_number: client_id for client_id, account_number in opened}
    accounts = {number: bank.get_account(number) for _, number in opened}

    audit = AuditLog(now=clock)
    risk = RiskAnalyzer(
        large_amount=80_000.0,
        huge_amount=250_000.0,
        frequent_threshold_medium=3,
        frequent_threshold_high=6,
        now=clock,
    )
    processor = TransactionProcessor(
        accounts,
        fx_rates={
            (Currency.RUB, Currency.USD): 0.011,
            (Currency.USD, Currency.RUB): 90.0,
            (Currency.RUB, Currency.EUR): 0.01,
            (Currency.EUR, Currency.RUB): 100.0,
            (Currency.RUB, Currency.CNY): 0.08,
            (Currency.CNY, Currency.RUB): 12.5,
        },
        external_commission_rate=0.02,
        now=clock,
        audit_log=audit,
        risk_analyzer=risk,
        account_to_client=account_to_client,
        risk_block_from=RiskLevel.HIGH,
    )
    queue = TransactionQueue(now=clock)

    c101_rub = opened[0][1]
    c101_usd = opened[1][1]
    c102_premium = opened[2][1]
    c102_eur = opened[3][1]
    c103_invest = opened[4][1]
    c104_cny = opened[5][1]

    txs = [
        Transaction(new_transaction_id(), TransactionType.INTERNAL_TRANSFER, 10_000.0, Currency.RUB, 0.0, c101_rub, c102_premium, client_id="c101"),
        Transaction(new_transaction_id(), TransactionType.INTERNAL_TRANSFER, 400.0, Currency.USD, 0.0, c101_usd, c101_rub, client_id="c101"),
        Transaction(new_transaction_id(), TransactionType.EXTERNAL_TRANSFER, 20_000.0, Currency.RUB, 0.0, c102_premium, None, external_party_ref="EXT-R1", client_id="c102"),
        Transaction(new_transaction_id(), TransactionType.INTERNAL_TRANSFER, 9_000.0, Currency.EUR, 0.0, c102_eur, c101_rub, client_id="c102"),
        Transaction(new_transaction_id(), TransactionType.INTERNAL_TRANSFER, 500.0, Currency.USD, 0.0, c103_invest, c101_usd, client_id="c103"),
        Transaction(new_transaction_id(), TransactionType.INTERNAL_TRANSFER, 6_000.0, Currency.CNY, 0.0, c104_cny, c101_rub, client_id="c104"),
        Transaction(
            new_transaction_id(),
            TransactionType.INTERNAL_TRANSFER,
            300_000.0,
            Currency.RUB,
            0.0,
            c101_rub,
            c102_premium,
            client_id="c101",
            created_at=datetime(2026, 4, 8, 2, 10, 0),
            updated_at=datetime(2026, 4, 8, 2, 10, 0),
        ),
        Transaction(new_transaction_id(), TransactionType.INTERNAL_TRANSFER, 999_999.0, Currency.CNY, 0.0, c104_cny, c102_premium, client_id="c104"),
    ]

    for item in txs:
        queue.add(item, priority=5)
        clock.advance(seconds=20)

    while True:
        item = queue.pop_due()
        if item is None:
            break
        processor.process(item, queue=queue)
        clock.advance(seconds=15)

    builder = ReportBuilder(bank, txs, audit_log=audit, risk_analyzer=risk)
    client_report = builder.build_client_report("c101")
    bank_report = builder.build_bank_report()
    risk_report = builder.build_risk_report()

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        client_json = builder.export_to_json(client_report, out / "client_report.json")
        client_csv = builder.export_to_csv(client_report, out / "client_report.csv")
        bank_json = builder.export_to_json(bank_report, out / "bank_report.json")
        bank_csv = builder.export_to_csv(bank_report, out / "bank_report.csv")
        risk_json = builder.export_to_json(risk_report, out / "risk_report.json")
        risk_csv = builder.export_to_csv(risk_report, out / "risk_report.csv")
        charts = builder.save_charts(out / "charts", client_id="c101")

        print("=== Текстовые отчёты ===")
        print(builder.to_text(client_report))
        print()
        print(builder.to_text(bank_report))
        print()
        print(builder.to_text(risk_report))

        print("\n=== Экспорт JSON / CSV ===")
        for path in (client_json, client_csv, bank_json, bank_csv, risk_json, risk_csv):
            print(" ", path.name, "saved")

        print("\n=== Графики ===")
        for name, path in charts.items():
            print(f"  {name}: {path.name}")

        print("\n=== Краткая проверка содержимого ===")
        print("Клиентских операций:", len(client_report["transactions"]))
        print("Топ клиентов:", bank_report["top_clients"][:3])
        print("Подозрительных операций:", risk_report["suspicious_operations_count"])


if __name__ == "__main__":
    main()
