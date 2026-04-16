"""
День 2: несколько счетов каждого типа и операции.
Запуск: python demo_day2.py
"""

from bank import (
    Currency,
    InsufficientFundsError,
    InvalidOperationError,
    InvestmentAccount,
    Owner,
    Portfolio,
    PremiumAccount,
    SavingsAccount,
    VirtualAsset,
)


def main() -> None:
    print("=== SavingsAccount ×2 ===")
    s1 = SavingsAccount(
        Owner("Анна К."),
        Currency.RUB,
        min_balance=500.0,
        monthly_rate=0.005,
        initial_balance=5_000.0,
        account_number="40817810000000001111",
    )
    s2 = SavingsAccount(
        Owner("Борис К."),
        Currency.EUR,
        min_balance=100.0,
        monthly_rate=0.0025,
        initial_balance=1_200.0,
    )
    print(s1)
    s1.deposit(200.0)
    s1.withdraw(4_000.0)
    print("После пополнения и снятия:", s1)
    s1.apply_monthly_interest()
    print("После начисления процентов за месяц:", s1)
    print(s2)
    try:
        s2.withdraw(1_200.0)
    except InsufficientFundsError as e:
        print("Снятие ниже минимума заблокировано:", e)

    print("\n=== PremiumAccount ×2 ===")
    p1 = PremiumAccount(
        Owner("VIP 1"),
        Currency.USD,
        single_transaction_limit=50_000.0,
        daily_withdraw_limit=80_000.0,
        overdraft_limit=2_000.0,
        withdraw_commission=25.0,
        initial_balance=800.0,
        account_number="40817810000000002222",
    )
    p2 = PremiumAccount(
        Owner("VIP 2"),
        Currency.RUB,
        single_transaction_limit=1_000_000.0,
        daily_withdraw_limit=2_000_000.0,
        overdraft_limit=500_000.0,
        withdraw_commission=500.0,
        initial_balance=100_000.0,
    )
    print(p1)
    p1.withdraw(1_500.0)
    print("Снятие с овердрафтом и комиссией, баланс:", p1.balance)
    print(p2)
    try:
        p2.withdraw(2_000_000.0)
    except InvalidOperationError as e:
        print("Превышен лимит одной операции:", e)

    print("\n=== InvestmentAccount ×2 ===")
    inv1 = InvestmentAccount(
        Owner("Инвестор А"),
        Currency.RUB,
        portfolios=[
            Portfolio(
                "balanced",
                {VirtualAsset.STOCKS: 50_000.0, VirtualAsset.BONDS: 30_000.0, VirtualAsset.ETF: 20_000.0},
            )
        ],
        initial_balance=15_000.0,
        account_number="40817810000000003333",
        liquidation_fee_rate=0.01,
    )
    inv2 = InvestmentAccount(
        Owner("Инвестор Б"),
        Currency.USD,
        portfolios=[
            Portfolio("growth", {VirtualAsset.STOCKS: 10_000.0, VirtualAsset.ETF: 5_000.0}),
            Portfolio("defensive", {VirtualAsset.BONDS: 25_000.0}),
        ],
        initial_balance=2_000.0,
    )
    print(inv1)
    inv1.withdraw(1_000.0)
    print("После снятия с комиссией за ликвидацию:", inv1)
    print(inv2)
    proj = inv2.project_yearly_growth()
    print("Проекция на год (inv2):", proj)

    print("\n=== Полиморфизм: get_account_info() ===")
    for acc in (s1, p1, inv1):
        print(dict(acc.get_account_info()))


if __name__ == "__main__":
    main()
