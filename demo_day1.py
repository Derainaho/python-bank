"""
Демонстрация Day 1: активный и замороженный счета, ошибки, валидные операции.
Запуск из корня репозитория: python demo_day1.py
"""

from bank import (
    AccountFrozenError,
    BankAccount,
    AccountStatus,
    Currency,
    InsufficientFundsError,
    Owner,
)


def main() -> None:
    owner = Owner(full_name="Дядя Петя")

    active = BankAccount(
        owner=owner,
        currency=Currency.RUB,
        account_number="40817810099910004321",
        initial_balance=1000.0,
        status=AccountStatus.ACTIVE,
    )

    frozen = BankAccount(
        owner=Owner(full_name="Мария Сидорова"),
        currency=Currency.USD,
        status=AccountStatus.FROZEN,
    )

    print("=== Активный счёт ===")
    print(active)
    active.deposit(250.5)
    active.withdraw(100.0)
    print("После пополнения и снятия:", active)

    print("\n=== Замороженный счёт ===")
    print(frozen)

    print("\nПопытка пополнения замороженного счёта:")
    try:
        frozen.deposit(10.0)
    except AccountFrozenError as e:
        print(f"  Ожидаемо: {type(e).__name__}: {e}")

    print("\nПопытка снятия с замороженного счёта:")
    try:
        frozen.withdraw(1.0)
    except AccountFrozenError as e:
        print(f"  Ожидаемо: {type(e).__name__}: {e}")

    print("\nПопытка снять больше, чем на счёте:")
    try:
        active.withdraw(10_000_000.0)
    except InsufficientFundsError as e:
        print(f"  Ожидаемо: {type(e).__name__}: {e}")

    print("\nИнформация по счетам (get_account_info):")
    print(dict(active.get_account_info()))
    print(dict(frozen.get_account_info()))


if __name__ == "__main__":
    main()
