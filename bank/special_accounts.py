from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any, Mapping

from bank.accounts import AccountStatus, BankAccount, Currency, Owner
from bank.exceptions import InsufficientFundsError, InvalidOperationError


class VirtualAsset(str, Enum):
    """Виртуальные типы активов в портфеле."""

    STOCKS = "stocks"
    BONDS = "bonds"
    ETF = "etf"


_DEFAULT_ANNUAL_RETURN: dict[VirtualAsset, float] = {
    VirtualAsset.STOCKS: 0.08,
    VirtualAsset.BONDS: 0.04,
    VirtualAsset.ETF: 0.06,
}


class SavingsAccount(BankAccount):
    """Накопительный счёт: минимальный остаток и месячная ставка."""

    ACCOUNT_TYPE_LABEL = "SavingsAccount"

    def __init__(
        self,
        owner: Owner,
        currency: Currency,
        min_balance: float,
        monthly_rate: float,
        *,
        account_number: str | None = None,
        initial_balance: float = 0.0,
        status: AccountStatus = AccountStatus.ACTIVE,
        account_id: str | None = None,
    ) -> None:
        if min_balance < 0:
            raise InvalidOperationError("Минимальный остаток не может быть отрицательным.")
        if monthly_rate < 0:
            raise InvalidOperationError("Месячная ставка не может быть отрицательной.")
        if initial_balance < min_balance:
            raise InvalidOperationError("Начальный баланс не может быть ниже минимального остатка.")

        super().__init__(
            owner,
            currency,
            account_number=account_number,
            initial_balance=initial_balance,
            status=status,
            account_id=account_id,
        )
        self._min_balance = float(min_balance)
        self._monthly_rate = float(monthly_rate)

    @property
    def min_balance(self) -> float:
        return self._min_balance

    @property
    def monthly_rate(self) -> float:
        return self._monthly_rate

    def withdraw(self, amount: float) -> None:
        self._validate_positive_amount(amount)
        self._ensure_mutable_for_operations()
        new_balance = self.balance - float(amount)
        if new_balance < self._min_balance:
            raise InsufficientFundsError(
                f"После снятия баланс ({new_balance:.2f}) оказался бы ниже минимума ({self._min_balance:.2f})."
            )
        self._set_balance(new_balance)

    def apply_monthly_interest(self) -> None:
        """Начисляет проценты на текущий остаток (только для активного счёта)."""
        if self.status is not AccountStatus.ACTIVE:
            raise InvalidOperationError("Начисление процентов доступно только для активного счёта.")
        self._set_balance(self.balance * (1.0 + self._monthly_rate))

    def get_account_info(self) -> Mapping[str, Any]:
        base = dict(super().get_account_info())
        base["type"] = self.ACCOUNT_TYPE_LABEL
        base["min_balance"] = self._min_balance
        base["monthly_rate"] = self._monthly_rate
        return base

    def __str__(self) -> str:
        tail = self.account_number[-4:] if len(self.account_number) >= 4 else self.account_number
        return (
            f"{self.ACCOUNT_TYPE_LABEL} | "
            f"клиент: {self.owner.full_name} | "
            f"№ …{tail} | "
            f"статус: {self.status.value} | "
            f"баланс: {self.balance:.2f} {self.currency.value} | "
            f"мин. остаток: {self._min_balance:.2f} | "
            f"ставка/мес: {self._monthly_rate * 100:.3f}%"
        )


class PremiumAccount(BankAccount):
    """Премиальный счёт: повышенные лимиты, овердрафт, фиксированная комиссия за снятие."""

    ACCOUNT_TYPE_LABEL = "PremiumAccount"

    def __init__(
        self,
        owner: Owner,
        currency: Currency,
        single_transaction_limit: float,
        daily_withdraw_limit: float,
        overdraft_limit: float,
        withdraw_commission: float,
        *,
        account_number: str | None = None,
        initial_balance: float = 0.0,
        status: AccountStatus = AccountStatus.ACTIVE,
        account_id: str | None = None,
    ) -> None:
        if single_transaction_limit <= 0 or daily_withdraw_limit <= 0:
            raise InvalidOperationError("Лимиты должны быть положительными.")
        if overdraft_limit < 0:
            raise InvalidOperationError("Лимит овердрафта не может быть отрицательным.")
        if withdraw_commission < 0:
            raise InvalidOperationError("Комиссия не может быть отрицательной.")

        super().__init__(
            owner,
            currency,
            account_number=account_number,
            initial_balance=initial_balance,
            status=status,
            account_id=account_id,
        )
        self._single_transaction_limit = float(single_transaction_limit)
        self._daily_withdraw_limit = float(daily_withdraw_limit)
        self._overdraft_limit = float(overdraft_limit)
        self._withdraw_commission = float(withdraw_commission)
        self._daily_spent = 0.0
        self._daily_spent_on: date | None = None

    @property
    def single_transaction_limit(self) -> float:
        return self._single_transaction_limit

    @property
    def daily_withdraw_limit(self) -> float:
        return self._daily_withdraw_limit

    @property
    def overdraft_limit(self) -> float:
        return self._overdraft_limit

    @property
    def withdraw_commission(self) -> float:
        return self._withdraw_commission

    def _reset_daily_if_needed(self) -> None:
        today = date.today()
        if self._daily_spent_on != today:
            self._daily_spent = 0.0
            self._daily_spent_on = today

    def withdraw(self, amount: float) -> None:
        self._validate_positive_amount(amount)
        self._ensure_mutable_for_operations()

        if amount > self._single_transaction_limit:
            raise InvalidOperationError(
                f"Сумма превышает лимит одной операции ({self._single_transaction_limit:.2f})."
            )

        total_debit = float(amount) + self._withdraw_commission
        self._reset_daily_if_needed()
        if self._daily_spent + total_debit > self._daily_withdraw_limit:
            raise InvalidOperationError(
                f"Превышен дневной лимит снятий (с учётом комиссий): {self._daily_withdraw_limit:.2f}."
            )

        new_balance = self.balance - total_debit
        floor = -self._overdraft_limit
        if new_balance < floor:
            raise InsufficientFundsError(
                "Недостаточно средств с учётом овердрафта и комиссии за операцию."
            )

        self._set_balance(new_balance)
        self._daily_spent += total_debit

    def get_account_info(self) -> Mapping[str, Any]:
        base = dict(super().get_account_info())
        base["type"] = self.ACCOUNT_TYPE_LABEL
        base["single_transaction_limit"] = self._single_transaction_limit
        base["daily_withdraw_limit"] = self._daily_withdraw_limit
        base["overdraft_limit"] = self._overdraft_limit
        base["withdraw_commission"] = self._withdraw_commission
        return base

    def __str__(self) -> str:
        tail = self.account_number[-4:] if len(self.account_number) >= 4 else self.account_number
        return (
            f"{self.ACCOUNT_TYPE_LABEL} | "
            f"клиент: {self.owner.full_name} | "
            f"№ …{tail} | "
            f"статус: {self.status.value} | "
            f"баланс: {self.balance:.2f} {self.currency.value} | "
            f"овердрафт до {self._overdraft_limit:.2f} | "
            f"комиссия снятия: {self._withdraw_commission:.2f}"
        )


@dataclass(slots=True)
class Portfolio:
    """Именованный портфель: распределение стоимости по виртуальным активам."""

    name: str
    holdings: dict[VirtualAsset, float]

    def total_value(self) -> float:
        return sum(self.holdings.values())


class InvestmentAccount(BankAccount):
    """Инвестиционный счёт: ликвидный остаток + виртуальные портфели активов."""

    ACCOUNT_TYPE_LABEL = "InvestmentAccount"

    def __init__(
        self,
        owner: Owner,
        currency: Currency,
        portfolios: list[Portfolio],
        *,
        account_number: str | None = None,
        initial_balance: float = 0.0,
        status: AccountStatus = AccountStatus.ACTIVE,
        account_id: str | None = None,
        liquidation_fee_rate: float = 0.005,
    ) -> None:
        if liquidation_fee_rate < 0 or liquidation_fee_rate >= 1:
            raise InvalidOperationError("Ставка комиссии за вывод должна быть в диапазоне [0, 1).")
        for p in portfolios:
            for v in p.holdings.values():
                if v < 0:
                    raise InvalidOperationError("Стоимость позиции в портфеле не может быть отрицательной.")

        super().__init__(
            owner,
            currency,
            account_number=account_number,
            initial_balance=initial_balance,
            status=status,
            account_id=account_id,
        )
        self._portfolios = list(portfolios)
        self._liquidation_fee_rate = float(liquidation_fee_rate)

    @property
    def portfolios(self) -> tuple[Portfolio, ...]:
        return tuple(self._portfolios)

    @property
    def liquidation_fee_rate(self) -> float:
        return self._liquidation_fee_rate

    def total_portfolio_value(self) -> float:
        return sum(p.total_value() for p in self._portfolios)

    def total_equity(self) -> float:
        return self.balance + self.total_portfolio_value()

    def withdraw(self, amount: float) -> None:
        self._validate_positive_amount(amount)
        self._ensure_mutable_for_operations()
        fee = float(amount) * self._liquidation_fee_rate
        total = float(amount) + fee
        if total > self.balance:
            raise InsufficientFundsError("Недостаточно ликвидных средств с учётом комиссии за вывод.")
        self._set_balance(self.balance - total)

    def project_yearly_growth(
        self,
        annual_returns: Mapping[VirtualAsset, float] | None = None,
    ) -> Mapping[str, Any]:
        """
        Упрощённая проекция стоимости портфелей через год по заданным или базовым ставкам.
        Ликвидный остаток (balance) в проекции не реинвестируется (0%%).
        """
        rates = dict(annual_returns) if annual_returns is not None else dict(_DEFAULT_ANNUAL_RETURN)
        per_portfolio: dict[str, float] = {}
        for p in self._portfolios:
            projected = 0.0
            for asset, value in p.holdings.items():
                r = rates.get(asset, _DEFAULT_ANNUAL_RETURN.get(asset, 0.0))
                projected += value * (1.0 + r)
            per_portfolio[p.name] = projected

        current_invested = self.total_portfolio_value()
        projected_invested = sum(per_portfolio.values())
        return {
            "per_portfolio": per_portfolio,
            "invested_now": current_invested,
            "invested_projected_1y": projected_invested,
            "cash_now": self.balance,
            "total_equity_now": self.total_equity(),
            "total_equity_projected_1y": self.balance + projected_invested,
        }

    def get_account_info(self) -> Mapping[str, Any]:
        base = dict(super().get_account_info())
        base["type"] = self.ACCOUNT_TYPE_LABEL
        base["portfolios"] = [
            {"name": p.name, "holdings": {a.value: v for a, v in p.holdings.items()}} for p in self._portfolios
        ]
        base["total_portfolio_value"] = self.total_portfolio_value()
        base["total_equity"] = self.total_equity()
        base["liquidation_fee_rate"] = self._liquidation_fee_rate
        return base

    def __str__(self) -> str:
        tail = self.account_number[-4:] if len(self.account_number) >= 4 else self.account_number
        return (
            f"{self.ACCOUNT_TYPE_LABEL} | "
            f"клиент: {self.owner.full_name} | "
            f"№ …{tail} | "
            f"статус: {self.status.value} | "
            f"кэш: {self.balance:.2f} {self.currency.value} | "
            f"портфели: {self.total_portfolio_value():.2f} | "
            f"капитал: {self.total_equity():.2f}"
        )
