from __future__ import annotations

import heapq
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from bank.accounts import AbstractAccount, AccountStatus, Currency
from bank.exceptions import (
    AccountClosedError,
    AccountFrozenError,
    InsufficientFundsError,
    InvalidOperationError,
)
from bank.special_accounts import PremiumAccount, SavingsAccount


class TransactionType(str, Enum):
    """Тип транзакции."""

    INTERNAL_TRANSFER = "internal_transfer"
    EXTERNAL_TRANSFER = "external_transfer"


class TransactionStatus(str, Enum):
    """Статус обработки."""

    PENDING = "pending"
    QUEUED = "queued"
    DEFERRED = "deferred"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def new_transaction_id(prefix: str = "tx") -> str:
    """Генерирует уникальный идентификатор транзакции."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass(slots=True)
class Transaction:
    """Транзакция: идентификатор, тип, суммы, участники, статус, время."""

    transaction_id: str
    type: TransactionType
    amount: float
    currency: Currency
    commission: float
    sender_account: str | None
    receiver_account: str | None
    status: TransactionStatus = TransactionStatus.PENDING
    failure_reason: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    priority: int = 0
    process_after: datetime | None = None
    retry_count: int = 0
    external_party_ref: str | None = None
    client_id: str | None = None

    def touch(self, *, now: Callable[[], datetime] | None = None) -> None:
        fn = now or datetime.now
        self.updated_at = fn()


class TransactionQueue:
    """
    Очередь транзакций: приоритет (больше — раньше), отложенные по времени, отмена.
    Готовые к исполнению элементы извлекаются через pop_due.
    """

    def __init__(self, *, now: Callable[[], datetime] | None = None) -> None:
        self._now = now if now is not None else datetime.now
        self._seq = 0
        # (-priority, seq, tx_id) — seq стабилизирует порядок при равном приоритете
        self._ready_heap: list[tuple[int, int, str]] = []
        # (process_after, -priority, seq, tx_id)
        self._deferred_heap: list[tuple[datetime, int, int, str]] = []
        self._items: dict[str, Transaction] = {}

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def add(
        self,
        tx: Transaction,
        *,
        priority: int = 0,
        defer_until: datetime | None = None,
    ) -> None:
        if tx.transaction_id in self._items:
            raise InvalidOperationError("Транзакция с таким ID уже в очереди.")
        if tx.status in (TransactionStatus.COMPLETED, TransactionStatus.CANCELLED):
            raise InvalidOperationError("Нельзя поставить в очередь завершённую или отменённую транзакцию.")

        tx.priority = priority
        tx.touch(now=self._now)

        if defer_until is not None:
            if defer_until <= self._now():
                raise InvalidOperationError("Отложенное время должно быть в будущем.")
            tx.process_after = defer_until
            tx.status = TransactionStatus.DEFERRED
            heapq.heappush(
                self._deferred_heap,
                (defer_until, -priority, self._next_seq(), tx.transaction_id),
            )
        else:
            tx.process_after = None
            tx.status = TransactionStatus.QUEUED
            heapq.heappush(self._ready_heap, (-priority, self._next_seq(), tx.transaction_id))

        self._items[tx.transaction_id] = tx

    def cancel(self, transaction_id: str) -> bool:
        """Отмена, если транзакция ещё в очереди (queued/deferred/pending)."""
        tx = self._items.get(transaction_id)
        if tx is None:
            return False
        if tx.status not in (
            TransactionStatus.PENDING,
            TransactionStatus.QUEUED,
            TransactionStatus.DEFERRED,
        ):
            return False
        tx.status = TransactionStatus.CANCELLED
        tx.failure_reason = "Отменено пользователем или системой."
        tx.touch(now=self._now)
        return True

    def _promote_deferred(self) -> None:
        now = self._now()
        while self._deferred_heap and self._deferred_heap[0][0] <= now:
            when, neg_pri, seq, tx_id = heapq.heappop(self._deferred_heap)
            tx = self._items.get(tx_id)
            if tx is None or tx.status is TransactionStatus.CANCELLED:
                continue
            pri = -neg_pri
            tx.status = TransactionStatus.QUEUED
            tx.process_after = None
            tx.touch(now=self._now)
            heapq.heappush(self._ready_heap, (-pri, seq, tx_id))

    def pop_due(self) -> Transaction | None:
        """Следующая транзакция к исполнению (с учётом отложенных)."""
        self._promote_deferred()
        while self._ready_heap:
            _neg_pri, _seq, tx_id = heapq.heappop(self._ready_heap)
            tx = self._items.get(tx_id)
            if tx is None or tx.status is TransactionStatus.CANCELLED:
                continue
            if tx.status is not TransactionStatus.QUEUED:
                continue
            return tx
        return None

    def __len__(self) -> int:
        return len(self._items)

    def peek_all_ids(self) -> frozenset[str]:
        return frozenset(self._items.keys())

    def requeue_failed(self, tx: Transaction) -> None:
        """Повторная постановка в очередь после временной ошибки (использует текущий priority)."""
        if tx.status is not TransactionStatus.QUEUED:
            return
        heapq.heappush(self._ready_heap, (-tx.priority, self._next_seq(), tx.transaction_id))


class TransactionProcessor:
    """
    Исполнение транзакций: комиссии, конвертация, повторные попытки, журнал ошибок.
    """

    def __init__(
        self,
        accounts: Mapping[str, AbstractAccount],
        *,
        fx_rates: dict[tuple[Currency, Currency], float] | None = None,
        external_commission_rate: float = 0.02,
        max_retries: int = 2,
        now: Callable[[], datetime] | None = None,
        audit_log: Any = None,
        risk_analyzer: Any = None,
        account_to_client: Mapping[str, str] | None = None,
        risk_block_from: Any = None,
    ) -> None:
        self._accounts = dict(accounts)
        self._fx: dict[tuple[Currency, Currency], float] = dict(fx_rates or {})
        self._external_commission_rate = float(external_commission_rate)
        self._max_retries = int(max_retries)
        self._now = now if now is not None else datetime.now
        self._error_log: list[str] = []
        self._audit = audit_log
        self._risk = risk_analyzer
        self._account_to_client = dict(account_to_client or {})
        # По умолчанию блокируем только высокий риск; MEDIUM можно включить явно.
        if risk_block_from is None:
            from bank.risk import RiskLevel as _RL

            self._risk_block_from = _RL.HIGH
        else:
            self._risk_block_from = risk_block_from

    @property
    def error_log(self) -> tuple[str, ...]:
        return tuple(self._error_log)

    def _log_error(self, message: str) -> None:
        self._error_log.append(f"[{self._now().isoformat(timespec='seconds')}] {message}")

    def convert(self, amount: float, from_currency: Currency, to_currency: Currency) -> float:
        if from_currency == to_currency:
            return float(amount)
        direct = self._fx.get((from_currency, to_currency))
        if direct is not None:
            return float(amount) * float(direct)
        reverse = self._fx.get((to_currency, from_currency))
        if reverse is not None and reverse != 0:
            return float(amount) / float(reverse)
        raise InvalidOperationError(f"Нет курса для пары {from_currency.value}->{to_currency.value}.")

    def _ensure_account_operable(self, acc: AbstractAccount, label: str) -> None:
        if acc.status is AccountStatus.CLOSED:
            raise AccountClosedError(f"{label}: счёт закрыт.")
        if acc.status is AccountStatus.FROZEN:
            raise AccountFrozenError(f"{label}: счёт заморожен.")

    def _debit_allowed_balance(self, acc: AbstractAccount, debit: float) -> None:
        """Правило «не в минус», кроме премиума в пределах овердрафта; накопительный — мин. остаток."""
        new_balance = acc.balance - float(debit)
        if isinstance(acc, PremiumAccount):
            floor = -acc.overdraft_limit
            if new_balance < floor:
                raise InsufficientFundsError("Превышен лимит овердрафта премиального счёта.")
            return
        if isinstance(acc, SavingsAccount):
            if new_balance < acc.min_balance:
                raise InsufficientFundsError("Нарушен минимальный остаток накопительного счёта.")
            return
        if new_balance < 0:
            raise InsufficientFundsError("Недостаточно средств (перевод в минус запрещён для этого типа счёта).")

    def _apply_debit(self, acc: AbstractAccount, debit: float) -> None:
        self._debit_allowed_balance(acc, debit)
        acc._set_balance(acc.balance - float(debit))

    def _apply_credit(self, acc: AbstractAccount, credit: float) -> None:
        self._ensure_account_operable(acc, "Получатель")
        acc._set_balance(acc.balance + float(credit))

    def _compute_commission(self, tx: Transaction) -> float:
        if tx.type is TransactionType.EXTERNAL_TRANSFER:
            return round(float(tx.amount) * self._external_commission_rate, 2)
        return 0.0

    def process(self, tx: Transaction, *, queue: TransactionQueue | None = None) -> bool:
        """
        Пытается исполнить транзакцию. Возвращает True при успехе.
        При ошибке пишет в error_log; при retryable и переданной queue — повторная постановка до max_retries.
        """
        tx.touch(now=self._now)

        if tx.status is TransactionStatus.CANCELLED:
            self._log_error(f"{tx.transaction_id}: пропуск — отменена.")
            return False

        def fail(reason: str, *, retryable: bool = False) -> bool:
            tx.failure_reason = reason
            tx.touch(now=self._now)
            self._log_error(f"{tx.transaction_id}: {reason}")
            if self._audit is not None:
                from bank.audit import AuditSeverity

                self._audit.append(
                    AuditSeverity.ERROR,
                    f"Ошибка исполнения: {reason}",
                    transaction_id=tx.transaction_id,
                    client_id=getattr(tx, "client_id", None),
                )
            if retryable and queue is not None and tx.retry_count < self._max_retries:
                tx.retry_count += 1
                tx.status = TransactionStatus.QUEUED
                tx.failure_reason = None
                queue.requeue_failed(tx)
                return False
            tx.status = TransactionStatus.FAILED
            return False

        try:
            if self._risk is not None:
                from bank.audit import AuditSeverity
                from bank.risk import RiskLevel

                assessment = self._risk.analyze(tx, account_to_client=self._account_to_client or None)
                sev = (
                    AuditSeverity.INFO
                    if assessment.level is RiskLevel.LOW
                    else AuditSeverity.WARNING
                    if assessment.level is RiskLevel.MEDIUM
                    else AuditSeverity.ERROR
                )
                if self._audit is not None:
                    self._audit.append(
                        sev,
                        f"Риск-оценка: {assessment.level.value} (score={assessment.score})",
                        transaction_id=tx.transaction_id,
                        client_id=getattr(tx, "client_id", None),
                        extra=assessment.to_extra(),
                    )

                rank = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}
                if rank[assessment.level] >= rank[self._risk_block_from]:
                    return fail("Операция заблокирована политикой риск-менеджмента.", retryable=False)

            commission = self._compute_commission(tx)
            tx.commission = commission

            if tx.type is TransactionType.INTERNAL_TRANSFER:
                if not tx.sender_account or not tx.receiver_account:
                    return fail("Внутренний перевод требует sender и receiver.")
                sender = self._accounts.get(tx.sender_account)
                receiver = self._accounts.get(tx.receiver_account)
                if sender is None or receiver is None:
                    return fail("Счёт отправителя или получателя не найден в реестре.")
                self._ensure_account_operable(sender, "Отправитель")
                self._ensure_account_operable(receiver, "Получатель")

                recv_currency: Currency = getattr(receiver, "currency")
                send_currency: Currency = getattr(sender, "currency")

                amount_recv = self.convert(float(tx.amount), tx.currency, recv_currency)
                total_send = float(tx.amount) + commission
                if tx.currency != send_currency:
                    return fail("Валюта транзакции должна совпадать с валютой счёта отправителя.")
                self._apply_debit(sender, total_send)
                self._apply_credit(receiver, amount_recv)

            elif tx.type is TransactionType.EXTERNAL_TRANSFER:
                if not tx.sender_account:
                    return fail("Внешний перевод требует отправителя.")
                sender = self._accounts.get(tx.sender_account)
                if sender is None:
                    return fail("Счёт отправителя не найден в реестре.")
                self._ensure_account_operable(sender, "Отправитель")
                send_currency = getattr(sender, "currency")
                if tx.currency != send_currency:
                    return fail("Валюта транзакции должна совпадать с валютой счёта отправителя.")
                total = float(tx.amount) + commission
                self._apply_debit(sender, total)
            else:
                return fail(f"Неизвестный тип {tx.type!r}.")

            tx.status = TransactionStatus.COMPLETED
            tx.failure_reason = None
            tx.touch(now=self._now)
            if self._risk is not None:
                self._risk.register_completed(tx)
            if self._audit is not None:
                from bank.audit import AuditSeverity

                self._audit.append(
                    AuditSeverity.INFO,
                    "Транзакция успешно исполнена.",
                    transaction_id=tx.transaction_id,
                    client_id=getattr(tx, "client_id", None),
                )
            return True

        except (InsufficientFundsError, AccountFrozenError, AccountClosedError, InvalidOperationError) as e:
            return fail(str(e), retryable=False)
        except Exception as e:  # noqa: BLE001
            return fail(f"Внутренняя ошибка: {e!s}", retryable=False)


def run_queue_until_empty(queue: TransactionQueue, processor: TransactionProcessor) -> list[tuple[str, bool]]:
    """Демо-хелпер: исполняет все неотменённые элементы очереди по порядку pop_due."""
    results: list[tuple[str, bool]] = []
    while True:
        tx = queue.pop_due()
        if tx is None:
            break
        ok = processor.process(tx, queue=queue)
        results.append((tx.transaction_id, ok))
    return results
