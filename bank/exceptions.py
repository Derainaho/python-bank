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


class OutsideBusinessHoursError(Exception):
    """Операции запрещены в ночное окно (00:00–05:00)."""

    pass


class ClientBlockedError(Exception):
    """Клиент заблокирован (например, после неверных попыток входа)."""

    pass


class UnknownClientError(Exception):
    """Клиент с указанным ID не найден."""

    pass
