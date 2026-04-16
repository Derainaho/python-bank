"""
День 3: Bank, клиенты, вход, заморозка, подозрительные события, ночной запрет.
Запуск: python demo_day3.py
"""

from datetime import datetime

from bank import (
    AccountStatus,
    Bank,
    ClientBlockedError,
    Contacts,
    Currency,
    InvalidOperationError,
    OutsideBusinessHoursError,
    Portfolio,
    VirtualAsset,
)


def main() -> None:
    bank = Bank("Демо-банк")

    print("=== Регистрация клиентов ===")
    bank.add_client(
        "c1",
        "Алексей Смирнов",
        29,
        Contacts(phone="+79001234567", email="alex@example.com"),
        pin="1111",
    )
    bank.add_client(
        "c2",
        "Елена Волкова",
        41,
        Contacts(phone="+79007654321", email="elena@example.com"),
        pin="2222",
    )
    bank.add_client(
        "c3",
        "Олег Новиков",
        22,
        Contacts(phone="+79990001122", email="oleg@example.com"),
        pin="3333",
    )

    print("Всего клиентов: 3 (c1, c2, c3)")

    print("\n=== Возраст < 18 ===")
    try:
        bank.add_client(
            "minor",
            "Ребёнок",
            16,
            Contacts(phone="0", email="m@x"),
            pin="0000",
        )
    except InvalidOperationError as e:
        print("Ожидаемо:", e)

    print("\n=== Открытие счетов ===")
    a1 = bank.open_account("c1", "bank", currency=Currency.RUB, initial_balance=10_000.0)
    a2 = bank.open_account(
        "c1",
        "savings",
        currency=Currency.RUB,
        initial_balance=5_000.0,
        min_balance=1_000.0,
        monthly_rate=0.004,
    )
    a3 = bank.open_account("c2", "bank", currency=Currency.USD, initial_balance=3_000.0)
    bank.open_account(
        "c3",
        "investment",
        currency=Currency.RUB,
        initial_balance=50_000.0,
        portfolios=[
            Portfolio("main", {VirtualAsset.STOCKS: 20_000.0, VirtualAsset.ETF: 10_000.0}),
        ],
    )
    c1_nums = sorted(
        getattr(a, "account_number", "")
        for a in bank.search_accounts(client_id="c1")
        if getattr(a, "account_number", None)
    )
    print("Счета c1:", c1_nums)

    print("\n=== Аутентификация ===")
    print("Верный PIN c1:", bank.authenticate_client("c1", "1111"))
    print("Неверный PIN c2:")
    for i in range(3):
        ok = bank.authenticate_client("c2", "wrong")
        print(f"  попытка {i + 1}: {ok}, статус:", bank.get_client("c2").status)

    print("Вход заблокированного c2:", bank.authenticate_client("c2", "2222"))

    print("\n=== Операция от заблокированного клиента ===")
    try:
        bank.freeze_account("c2", a3)
    except ClientBlockedError as e:
        print(type(e).__name__ + ":", e)

    print("\n=== Заморозка счёта c1 ===")
    bank.freeze_account("c1", a1)
    acc = bank.get_account(a1)
    print(a1, "статус:", acc.status)
    bank.unfreeze_account("c1", a1)
    print("После разморозки:", acc.status)

    print("\n=== Поиск счетов (RUB, активные) ===")
    found = bank.search_accounts(currency=Currency.RUB, status=AccountStatus.ACTIVE)
    print("Найдено:", len(found))

    print("\n=== Балансы и рейтинг ===")
    print("Сумма по незакрытым счетам:", bank.get_total_balance())
    for row in bank.get_clients_ranking():
        print(" ", row)

    print("\n=== Ночное окно 00:00–05:00 (фиксированное время) ===")
    night_bank = Bank("Ночной", now=lambda: datetime(2026, 4, 6, 2, 15, 0))
    night_bank.add_client(
        "n1",
        "Ночной клиент",
        30,
        Contacts(phone="1", email="n@n"),
        pin="9999",
    )
    try:
        night_bank.open_account("n1", "bank", currency=Currency.RUB)
    except OutsideBusinessHoursError as e:
        print("Ожидаемо:", e)
    print("Подозрительные события (ночной банк):", night_bank.suspicious_events)

    print("\n=== Подозрительные события (основной банк), последние 5 ===")
    for line in bank.suspicious_events[-5:]:
        print(" ", line)


if __name__ == "__main__":
    main()
