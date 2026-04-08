"""Пользовательские исключения для операций со счётами."""


class AccountFrozenError(Exception):
    """Операция недоступна: счёт заморожен."""

    pass


class AccountClosedError(Exception):
    """Операция недоступна: счёт закрыт."""

    pass


class InvalidOperationError(Exception):
    """Некорректная операция (сумма, тип операции и т.п.)."""

    pass


class InsufficientFundsError(Exception):
    """Недостаточно средств на счёте."""

    pass
