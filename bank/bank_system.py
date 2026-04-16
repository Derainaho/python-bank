from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum
from typing import Any, Literal

from bank.accounts import AbstractAccount, AccountStatus, BankAccount, Currency, Owner
from bank.exceptions import (
    ClientBlockedError,
    InvalidOperationError,
    OutsideBusinessHoursError,
    UnknownClientError,
)
from bank.special_accounts import InvestmentAccount, Portfolio, PremiumAccount, SavingsAccount


class ClientStatus(str, Enum):
    """Статус клиента в системе банка."""

    ACTIVE = "active"
    BLOCKED = "blocked"


@dataclass(slots=True)
class Contacts:
    """Контактные данные клиента."""

    phone: str
    email: str


@dataclass
class Client:
    """Клиент банка: ФИО, идентификатор, статус, счета, контакты."""

    client_id: str
    full_name: str
    age: int
    contacts: Contacts
    pin: str
    status: ClientStatus = ClientStatus.ACTIVE
    account_numbers: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.age < 18:
            raise InvalidOperationError("Клиент должен быть не моложе 18 лет.")
        if not self.client_id.strip():
            raise InvalidOperationError("Идентификатор клиента не может быть пустым.")
        if not self.full_name.strip():
            raise InvalidOperationError("ФИО не может быть пустым.")

    def add_account_number(self, number: str) -> None:
        if number not in self.account_numbers:
            self.account_numbers.append(number)

    def remove_account_number(self, number: str) -> None:
        if number in self.account_numbers:
            self.account_numbers.remove(number)


AccountKind = Literal["bank", "savings", "premium", "investment"]

_MAX_FAILED_AUTH = 3
_NIGHT_START = time(0, 0, 0)
_NIGHT_END = time(5, 0, 0)


def _is_night_window(t: time) -> bool:
    return _NIGHT_START <= t < _NIGHT_END


class Bank:
    """Управление клиентами и счетами, базовая защита и ограничения по времени."""

    def __init__(
        self,
        name: str,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.name = name
        self._now = now if now is not None else datetime.now
        self._clients: dict[str, Client] = {}
        self._accounts: dict[str, AbstractAccount] = {}
        self._failed_auth_attempts: dict[str, int] = {}
        self._suspicious_events: list[str] = []

    @property
    def suspicious_events(self) -> tuple[str, ...]:
        return tuple(self._suspicious_events)

    def _log_suspicious(self, message: str) -> None:
        self._suspicious_events.append(message)

    def _current_time(self) -> datetime:
        return self._now()

    def _ensure_not_night(self, operation: str) -> None:
        t = self._current_time().time()
        if _is_night_window(t):
            msg = f"[{operation}] попытка операции в ночное окно 00:00–05:00"
            self._log_suspicious(msg)
            raise OutsideBusinessHoursError("Операции недоступны с 00:00 до 05:00.")

    def _get_client(self, client_id: str) -> Client:
        client = self._clients.get(client_id)
        if client is None:
            raise UnknownClientError(f"Клиент {client_id!r} не найден.")
        return client

    def get_client(self, client_id: str) -> Client:
        """Возвращает клиента по ID."""
        return self._get_client(client_id)

    def get_account(self, account_number: str) -> AbstractAccount:
        """Возвращает счёт по номеру."""
        acc = self._accounts.get(account_number)
        if acc is None:
            raise InvalidOperationError(f"Счёт {account_number!r} не найден.")
        return acc

    def _ensure_client_can_operate(self, client: Client) -> None:
        if client.status is ClientStatus.BLOCKED:
            raise ClientBlockedError("Клиент заблокирован.")

    def add_client(
        self,
        client_id: str,
        full_name: str,
        age: int,
        contacts: Contacts,
        pin: str,
    ) -> Client:
        if client_id in self._clients:
            raise InvalidOperationError(f"Клиент с ID {client_id!r} уже существует.")
        client = Client(
            client_id=client_id,
            full_name=full_name,
            age=age,
            contacts=contacts,
            pin=pin,
        )
        self._clients[client_id] = client
        self._failed_auth_attempts[client_id] = 0
        return client

    def authenticate_client(self, client_id: str, pin: str) -> bool:
        """Проверка PIN. Три неверные попытки подряд — блокировка клиента."""
        try:
            client = self._get_client(client_id)
        except UnknownClientError:
            self._log_suspicious(f"Вход: неизвестный client_id {client_id!r}")
            return False

        if client.status is ClientStatus.BLOCKED:
            self._log_suspicious(f"Вход: заблокированный клиент {client_id!r}")
            return False

        if pin == client.pin:
            self._failed_auth_attempts[client_id] = 0
            return True

        n = self._failed_auth_attempts.get(client_id, 0) + 1
        self._failed_auth_attempts[client_id] = n
        self._log_suspicious(f"Неверный PIN для клиента {client_id!r} (попытка {n}/{_MAX_FAILED_AUTH})")

        if n >= _MAX_FAILED_AUTH:
            client.status = ClientStatus.BLOCKED
            self._log_suspicious(f"Клиент {client_id!r} заблокирован после {_MAX_FAILED_AUTH} неверных попыток входа.")

        return False

    def open_account(
        self,
        client_id: str,
        kind: AccountKind = "bank",
        *,
        currency: Currency,
        initial_balance: float = 0.0,
        **options: Any,
    ) -> str:
        self._ensure_not_night("open_account")
        client = self._get_client(client_id)
        self._ensure_client_can_operate(client)

        owner = Owner(full_name=client.full_name)
        account: AbstractAccount

        if kind == "bank":
            account = BankAccount(owner, currency, initial_balance=initial_balance, **options)
        elif kind == "savings":
            try:
                min_balance = float(options.pop("min_balance"))
                monthly_rate = float(options.pop("monthly_rate"))
            except KeyError as e:
                raise InvalidOperationError("Для savings укажите min_balance и monthly_rate.") from e
            account = SavingsAccount(
                owner,
                currency,
                min_balance,
                monthly_rate,
                initial_balance=initial_balance,
                **options,
            )
        elif kind == "premium":
            try:
                st = float(options.pop("single_transaction_limit"))
                dw = float(options.pop("daily_withdraw_limit"))
                od = float(options.pop("overdraft_limit"))
                wc = float(options.pop("withdraw_commission"))
            except KeyError as e:
                raise InvalidOperationError(
                    "Для premium укажите single_transaction_limit, daily_withdraw_limit, "
                    "overdraft_limit и withdraw_commission."
                ) from e
            account = PremiumAccount(
                owner,
                currency,
                st,
                dw,
                od,
                wc,
                initial_balance=initial_balance,
                **options,
            )
        elif kind == "investment":
            try:
                portfolios = options.pop("portfolios")
            except KeyError as e:
                raise InvalidOperationError("Для investment укажите portfolios (список Portfolio).") from e
            if not isinstance(portfolios, list) or not all(isinstance(p, Portfolio) for p in portfolios):
                raise InvalidOperationError("Для investment нужен список Portfolio.")
            account = InvestmentAccount(
                owner,
                currency,
                portfolios=portfolios,
                initial_balance=initial_balance,
                **options,
            )
        else:
            raise InvalidOperationError(f"Неизвестный тип счёта: {kind!r}")

        number = getattr(account, "account_number", None)
        if not isinstance(number, str) or not number:
            raise InvalidOperationError("Внутренняя ошибка: у счёта нет номера.")
        if number in self._accounts:
            raise InvalidOperationError("Коллизия номера счёта.")

        self._accounts[number] = account
        client.add_account_number(number)
        return number

    def close_account(self, client_id: str, account_number: str) -> None:
        self._ensure_not_night("close_account")
        client = self._get_client(client_id)
        self._ensure_client_can_operate(client)

        if account_number not in client.account_numbers:
            raise InvalidOperationError("Счёт не принадлежит клиенту или уже закрыт.")

        account = self._accounts.get(account_number)
        if account is None:
            raise InvalidOperationError("Счёт не найден.")

        if account.status is AccountStatus.CLOSED:
            raise InvalidOperationError("Счёт уже закрыт.")

        if account.balance != 0:
            raise InvalidOperationError("Нельзя закрыть счёт с ненулевым балансом.")

        account._set_status(AccountStatus.CLOSED)
        client.remove_account_number(account_number)

    def freeze_account(self, client_id: str, account_number: str) -> None:
        self._ensure_not_night("freeze_account")
        client = self._get_client(client_id)
        self._ensure_client_can_operate(client)

        if account_number not in client.account_numbers:
            raise InvalidOperationError("Счёт не принадлежит клиенту.")

        account = self._accounts[account_number]
        if account.status is AccountStatus.CLOSED:
            raise InvalidOperationError("Нельзя заморозить закрытый счёт.")
        account._set_status(AccountStatus.FROZEN)

    def unfreeze_account(self, client_id: str, account_number: str) -> None:
        self._ensure_not_night("unfreeze_account")
        client = self._get_client(client_id)
        self._ensure_client_can_operate(client)

        if account_number not in client.account_numbers:
            raise InvalidOperationError("Счёт не принадлежит клиенту.")

        account = self._accounts[account_number]
        if account.status is not AccountStatus.FROZEN:
            raise InvalidOperationError("Счёт не в статусе «заморожен».")
        account._set_status(AccountStatus.ACTIVE)

    def search_accounts(
        self,
        *,
        client_id: str | None = None,
        status: AccountStatus | None = None,
        currency: Currency | None = None,
        number_contains: str | None = None,
    ) -> list[AbstractAccount]:
        results: list[AbstractAccount] = []
        if client_id is not None and client_id not in self._clients:
            return []

        filter_client = self._clients[client_id] if client_id is not None else None

        for acc in self._accounts.values():
            num = getattr(acc, "account_number", None)
            if filter_client is not None:
                if not isinstance(num, str) or num not in filter_client.account_numbers:
                    continue
            if status is not None and acc.status is not status:
                continue
            if currency is not None:
                cur = getattr(acc, "currency", None)
                if cur is not currency:
                    continue
            if number_contains is not None:
                if not isinstance(num, str) or number_contains not in num:
                    continue
            results.append(acc)
        return results

    def get_total_balance(self) -> float:
        total = 0.0
        for acc in self._accounts.values():
            if acc.status is AccountStatus.CLOSED:
                continue
            total += acc.balance
        return total

    def get_clients_ranking(self) -> list[tuple[str, str, float]]:
        """Рейтинг клиентов по сумме балансов открытых (не закрытых) счетов (без пересчёта валют)."""
        ranked: list[tuple[str, str, float]] = []
        for cid, client in self._clients.items():
            s = 0.0
            for num in client.account_numbers:
                acc = self._accounts.get(num)
                if acc is None or acc.status is AccountStatus.CLOSED:
                    continue
                s += acc.balance
            ranked.append((cid, client.full_name, s))
        ranked.sort(key=lambda x: x[2], reverse=True)
        return ranked
