from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from bank.exceptions import (
    AccountClosedError,
    AccountFrozenError,
    InsufficientFundsError,
    InvalidOperationError,
)


class AccountStatus(str, Enum):
    """Статус счёта."""

    ACTIVE = "active"
    FROZEN = "frozen"
    CLOSED = "closed"


class Currency(str, Enum):
    """Допустимые валюты счёта."""

    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"
    KZT = "KZT"
    CNY = "CNY"


@dataclass(frozen=True, slots=True)
class Owner:
    """Данные владельца счёта."""

    full_name: str


def _generate_short_account_number() -> str:
    """Короткий идентификатор счёта (8 шестнадцатеричных символов)."""
    return uuid.uuid4().hex[:8]


class AbstractAccount(ABC):
    """Абстрактная модель банковского счёта."""

    def __init__(
        self,
        account_id: str,
        owner: Owner,
        initial_balance: float = 0.0,
        status: AccountStatus = AccountStatus.ACTIVE,
    ) -> None:
        if initial_balance < 0:
            raise InvalidOperationError("Начальный баланс не может быть отрицательным.")

        self._account_id = account_id
        self._owner = owner
        self._balance = float(initial_balance)
        self._status = status

    @property
    def account_id(self) -> str:
        return self._account_id

    @property
    def owner(self) -> Owner:
        return self._owner

    @property
    def balance(self) -> float:
        return self._balance

    @property
    def status(self) -> AccountStatus:
        return self._status

    def _set_balance(self, value: float) -> None:
        self._balance = value

    def _set_status(self, value: AccountStatus) -> None:
        self._status = value

    @abstractmethod
    def deposit(self, amount: float) -> None:
        """Пополнение счёта."""

    @abstractmethod
    def withdraw(self, amount: float) -> None:
        """Снятие со счёта."""

    @abstractmethod
    def get_account_info(self) -> Mapping[str, Any]:
        """Сводная информация о счёте."""


class BankAccount(AbstractAccount):
    """Конкретный банковский счёт с валидацией и проверкой статуса."""

    ACCOUNT_TYPE_LABEL = "BankAccount"

    def __init__(
        self,
        owner: Owner,
        currency: Currency,
        *,
        account_number: str | None = None,
        initial_balance: float = 0.0,
        status: AccountStatus = AccountStatus.ACTIVE,
        account_id: str | None = None,
    ) -> None:
        self._account_number = account_number or _generate_short_account_number()
        self._currency = currency
        aid = account_id or f"acc-{self._account_number}"
        super().__init__(aid, owner, initial_balance=initial_balance, status=status)

    @property
    def account_number(self) -> str:
        return self._account_number

    @property
    def currency(self) -> Currency:
        return self._currency

    def _validate_positive_amount(self, amount: float) -> None:
        if not isinstance(amount, (int, float)):
            raise InvalidOperationError("Сумма должна быть числом.")
        if amount <= 0:
            raise InvalidOperationError("Сумма должна быть положительной.")

    def _ensure_mutable_for_operations(self) -> None:
        if self.status is AccountStatus.CLOSED:
            raise AccountClosedError("Счёт закрыт, операции недоступны.")
        if self.status is AccountStatus.FROZEN:
            raise AccountFrozenError("Счёт заморожен, операции недоступны.")

    def deposit(self, amount: float) -> None:
        self._validate_positive_amount(amount)
        self._ensure_mutable_for_operations()
        self._set_balance(self.balance + float(amount))

    def withdraw(self, amount: float) -> None:
        self._validate_positive_amount(amount)
        self._ensure_mutable_for_operations()
        if amount > self.balance:
            raise InsufficientFundsError("Недостаточно средств на счёте.")
        self._set_balance(self.balance - float(amount))

    def get_account_info(self) -> Mapping[str, Any]:
        return {
            "type": self.ACCOUNT_TYPE_LABEL,
            "account_id": self.account_id,
            "account_number": self.account_number,
            "owner": self.owner.full_name,
            "balance": self.balance,
            "currency": self.currency.value,
            "status": self.status.value,
        }

    def __str__(self) -> str:
        tail = self._account_number[-4:] if len(self._account_number) >= 4 else self._account_number
        return (
            f"{self.ACCOUNT_TYPE_LABEL} | "
            f"клиент: {self.owner.full_name} | "
            f"№ …{tail} | "
            f"статус: {self.status.value} | "
            f"баланс: {self.balance:.2f} {self.currency.value}"
        )
