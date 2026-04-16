"""
День 4: 10 транзакций, очередь с приоритетом и отложенными, процессор.
Запуск: python demo_day4.py
"""

from datetime import datetime, timedelta

from bank import (
    AccountStatus,
    BankAccount,
    Currency,
    Owner,
    PremiumAccount,
    SavingsAccount,
    Transaction,
    TransactionProcessor,
    TransactionQueue,
    TransactionType,
    new_transaction_id,
    run_queue_until_empty,
)


class AdvancingClock:
    """Детерминированное время для демо отложенных транзакций."""

    def __init__(self, start: datetime) -> None:
        self.t = start

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kwargs: float | int) -> None:
        self.t += timedelta(**kwargs)  # type: ignore[arg-type]


def main() -> None:
    clock = AdvancingClock(datetime(2026, 4, 6, 12, 0, 0))
    owner = Owner(full_name="Транзакционный Клиент")

    acc_rub_a = BankAccount(owner, Currency.RUB, account_number="RUB-A-0001", initial_balance=100_000.0)
    acc_rub_b = BankAccount(owner, Currency.RUB, account_number="RUB-B-0002", initial_balance=10_000.0)
    acc_usd = BankAccount(owner, Currency.USD, account_number="USD-C-0003", initial_balance=500.0)
    acc_frozen = BankAccount(owner, Currency.RUB, account_number="FRZ-0004", initial_balance=5_000.0)
    acc_frozen._set_status(AccountStatus.FROZEN)

    acc_save = SavingsAccount(
        owner,
        Currency.RUB,
        min_balance=1_000.0,
        monthly_rate=0.0,
        account_number="SAV-0005",
        initial_balance=8_000.0,
    )
    acc_prem = PremiumAccount(
        owner,
        Currency.RUB,
        single_transaction_limit=1_000_000.0,
        daily_withdraw_limit=5_000_000.0,
        overdraft_limit=50_000.0,
        withdraw_commission=0.0,
        account_number="PRM-0006",
        initial_balance=500.0,
    )

    accounts = {
        a.account_number: a
        for a in (acc_rub_a, acc_rub_b, acc_usd, acc_frozen, acc_save, acc_prem)
    }

    fx = {
        (Currency.RUB, Currency.USD): 0.012,
        (Currency.USD, Currency.RUB): 85.0,
    }

    queue = TransactionQueue(now=clock)
    processor = TransactionProcessor(
        accounts,
        fx_rates=fx,
        external_commission_rate=0.02,
        max_retries=2,
        now=clock,
    )

    txs: list[Transaction] = [
        Transaction(
            new_transaction_id(),
            TransactionType.INTERNAL_TRANSFER,
            1_000.0,
            Currency.RUB,
            0.0,
            "RUB-A-0001",
            "RUB-B-0002",
        ),
        Transaction(
            new_transaction_id(),
            TransactionType.INTERNAL_TRANSFER,
            5_000.0,
            Currency.RUB,
            0.0,
            "RUB-A-0001",
            "SAV-0005",
        ),
        Transaction(
            new_transaction_id(),
            TransactionType.EXTERNAL_TRANSFER,
            3_000.0,
            Currency.RUB,
            0.0,
            "RUB-A-0001",
            None,
            external_party_ref="SWIFT-EXT-001",
        ),
        Transaction(
            new_transaction_id(),
            TransactionType.INTERNAL_TRANSFER,
            10_000.0,
            Currency.RUB,
            0.0,
            "RUB-A-0001",
            "USD-C-0003",
        ),
        Transaction(
            new_transaction_id(),
            TransactionType.INTERNAL_TRANSFER,
            500.0,
            Currency.RUB,
            0.0,
            "RUB-B-0002",
            "RUB-A-0001",
        ),
        Transaction(
            new_transaction_id(),
            TransactionType.INTERNAL_TRANSFER,
            100.0,
            Currency.RUB,
            0.0,
            "FRZ-0004",
            "RUB-B-0002",
        ),
        Transaction(
            new_transaction_id(),
            TransactionType.EXTERNAL_TRANSFER,
            40_000.0,
            Currency.RUB,
            0.0,
            "PRM-0006",
            None,
            external_party_ref="CARD-PAY-777",
        ),
        Transaction(
            new_transaction_id(),
            TransactionType.INTERNAL_TRANSFER,
            2_000.0,
            Currency.USD,
            0.0,
            "USD-C-0003",
            "RUB-A-0001",
        ),
        Transaction(
            new_transaction_id(),
            TransactionType.INTERNAL_TRANSFER,
            50.0,
            Currency.RUB,
            0.0,
            "RUB-B-0002",
            "SAV-0005",
        ),
        Transaction(
            new_transaction_id(),
            TransactionType.INTERNAL_TRANSFER,
            1.0,
            Currency.RUB,
            0.0,
            "RUB-A-0001",
            "RUB-B-0002",
        ),
    ]

    # Очередь: разные приоритеты, одна отложенная, одна будет отменена
    queue.add(txs[0], priority=1)
    queue.add(txs[1], priority=10)
    queue.add(txs[2], priority=5)
    queue.add(txs[3], priority=2)
    queue.add(txs[4], priority=0)
    defer_until = clock.t + timedelta(minutes=30)
    queue.add(txs[5], priority=100, defer_until=defer_until)
    queue.add(txs[6], priority=3)
    queue.add(txs[7], priority=8)
    queue.add(txs[8], priority=0)
    queue.add(txs[9], priority=50)

    cancelled_id = txs[4].transaction_id
    if not queue.cancel(cancelled_id):
        raise RuntimeError("не удалось отменить транзакцию для демо")

    clock.advance(minutes=31)

    results = run_queue_until_empty(queue, processor)

    print("Обработано попыток:", len(results))
    for tid, ok in results:
        tx = next(t for t in txs if t.transaction_id == tid)
        print(f"  {tid}: ok={ok} status={tx.status.value} commission={tx.commission}")

    print("\nИтоговые балансы:")
    for num, acc in sorted(accounts.items()):
        print(f"  {num}: {acc.balance:.2f} {getattr(acc, 'currency', Currency.RUB).value} [{acc.status.value}]")

    print("\nЖурнал ошибок процессора:")
    for line in processor.error_log:
        print(" ", line)

    print("\nОтменённая транзакция:", cancelled_id, txs[4].status)


if __name__ == "__main__":
    main()
