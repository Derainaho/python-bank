from __future__ import annotations

import csv
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
import tempfile
from typing import Any

from bank.audit import AuditLog, AuditRecord, AuditSeverity, compile_audit_report
from bank.bank_system import Bank
from bank.accounts import AccountStatus
from bank.transactions import Transaction, TransactionStatus


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    if hasattr(value, "value"):
        return getattr(value, "value")
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            return str(value)
    return value


def _flatten_row(prefix: str, value: Any, out: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            _flatten_row(next_prefix, item, out)
        return
    if isinstance(value, list):
        out[prefix] = json.dumps(_normalize(value), ensure_ascii=False)
        return
    out[prefix] = _normalize(value)


def _plt():
    cache_root = Path(tempfile.gettempdir()) / "python-bank-mpl"
    cache_root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_root / "mplconfig"))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_root / "xdg-cache"))
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    Path(os.environ["XDG_CACHE_HOME"]).mkdir(parents=True, exist_ok=True)

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


class ReportBuilder:
    """Генератор текстовых, JSON, CSV-отчётов и графиков по банковским данным."""

    def __init__(
        self,
        bank: Bank,
        transactions: list[Transaction],
        *,
        audit_log: AuditLog | None = None,
        risk_analyzer: Any = None,
    ) -> None:
        self.bank = bank
        self.transactions = list(transactions)
        self.audit_log = audit_log
        self.risk_analyzer = risk_analyzer

    def build_client_report(self, client_id: str) -> dict[str, Any]:
        client = self.bank.get_client(client_id)
        accounts = [self.bank.get_account(number) for number in client.account_numbers]
        account_numbers = set(client.account_numbers)
        client_transactions = [
            tx
            for tx in self.transactions
            if tx.client_id == client_id
            or tx.sender_account in account_numbers
            or tx.receiver_account in account_numbers
        ]
        suspicious = []
        if self.audit_log is not None:
            suspicious = [
                self._serialize_audit_record(r)
                for r in self.audit_log.filter(client_id=client_id, min_severity=AuditSeverity.WARNING)
            ]

        return {
            "report_type": "client",
            "client": {
                "client_id": client.client_id,
                "full_name": client.full_name,
                "age": client.age,
                "status": client.status.value,
                "contacts": {"phone": client.contacts.phone, "email": client.contacts.email},
            },
            "accounts": [dict(acc.get_account_info()) for acc in accounts],
            "totals": {
                "accounts_count": len(accounts),
                "open_balance_sum": sum(acc.balance for acc in accounts if acc.status is not AccountStatus.CLOSED),
                "transactions_count": len(client_transactions),
                "suspicious_operations_count": len(suspicious),
            },
            "transactions": [self._serialize_transaction(tx) for tx in client_transactions],
            "suspicious_operations": suspicious,
        }

    def build_bank_report(self) -> dict[str, Any]:
        ranking = self.bank.get_clients_ranking()
        status_counter = Counter()
        currency_counter = Counter()
        for client_id, _full_name, _total in ranking:
            for acc in self.bank.search_accounts(client_id=client_id):
                status_counter[acc.status.value] += 1
                currency_counter[getattr(acc, "currency").value] += 1

        tx_statuses = Counter(tx.status.value for tx in self.transactions)
        return {
            "report_type": "bank",
            "bank_name": self.bank.name,
            "clients_count": len(ranking),
            "accounts_count": sum(status_counter.values()),
            "total_balance": self.bank.get_total_balance(),
            "account_status_distribution": dict(status_counter),
            "currency_distribution": dict(currency_counter),
            "top_clients": [
                {"client_id": cid, "full_name": name, "balance_sum": total}
                for cid, name, total in ranking[:10]
            ],
            "transaction_statistics": dict(tx_statuses),
        }

    def build_risk_report(self) -> dict[str, Any]:
        suspicious_entries: list[dict[str, Any]] = []
        error_stats: dict[str, int] = {}
        profiles: dict[str, Any] = {}
        if self.audit_log is not None and self.risk_analyzer is not None:
            compiled = compile_audit_report(self.audit_log, self.risk_analyzer)
            suspicious_entries = [
                self._serialize_audit_record(record) for record in compiled["suspicious_entries"]
            ]
            error_stats = dict(compiled["error_statistics"])
            profiles = compiled["client_risk_profiles"]

        return {
            "report_type": "risk",
            "suspicious_operations_count": len(suspicious_entries),
            "suspicious_operations": suspicious_entries,
            "client_risk_profiles": profiles,
            "error_statistics": error_stats,
        }

    def to_text(self, report: dict[str, Any]) -> str:
        rtype = report.get("report_type")
        if rtype == "client":
            client = report["client"]
            return (
                f"Client report: {client['full_name']} ({client['client_id']})\n"
                f"Status: {client['status']}\n"
                f"Accounts: {report['totals']['accounts_count']}\n"
                f"Transactions: {report['totals']['transactions_count']}\n"
                f"Suspicious: {report['totals']['suspicious_operations_count']}"
            )
        if rtype == "bank":
            top = report["top_clients"][:3]
            return (
                f"Bank report: {report['bank_name']}\n"
                f"Clients: {report['clients_count']}\n"
                f"Accounts: {report['accounts_count']}\n"
                f"Total balance: {report['total_balance']:.2f}\n"
                f"Top-3: {top}"
            )
        if rtype == "risk":
            return (
                f"Risk report\n"
                f"Suspicious operations: {report['suspicious_operations_count']}\n"
                f"Error stats: {report['error_statistics']}\n"
                f"Profiles: {len(report['client_risk_profiles'])}"
            )
        return json.dumps(_normalize(report), ensure_ascii=False, indent=2)

    def export_to_json(self, report: dict[str, Any], path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(_normalize(report), ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def export_to_csv(self, report: dict[str, Any], path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        rows = self._report_rows(report)
        if not rows:
            rows = [{"report_type": report.get("report_type", "unknown")}]
        fieldnames = sorted({key for row in rows for key in row})
        with target.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return target

    def save_charts(self, output_dir: str | Path, *, client_id: str) -> dict[str, Path]:
        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        saved = {
            "client_balance_movement": self._save_client_balance_chart(client_id, target_dir),
            "bank_status_pie": self._save_bank_pie_chart(target_dir),
            "risk_bar": self._save_risk_bar_chart(target_dir),
        }
        return saved

    def _save_client_balance_chart(self, client_id: str, output_dir: Path) -> Path:
        plt = _plt()
        client = self.bank.get_client(client_id)
        account_numbers = set(client.account_numbers)
        series = []
        running = 0.0
        for tx in self.transactions:
            delta = 0.0
            if tx.sender_account in account_numbers and tx.status is TransactionStatus.COMPLETED:
                delta -= float(tx.amount) + float(tx.commission)
            if tx.receiver_account in account_numbers and tx.status is TransactionStatus.COMPLETED:
                delta += float(tx.amount)
            if delta:
                running += delta
                series.append((tx.updated_at, running))

        if not series:
            series = [(None, 0.0)]

        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(range(len(series)), [point[1] for point in series], marker="o")
        ax.set_title(f"Balance Movement: {client.full_name}")
        ax.set_xlabel("Operation index")
        ax.set_ylabel("Net change")
        ax.grid(True, alpha=0.3)
        path = output_dir / f"client_{client_id}_balance.png"
        fig.tight_layout()
        fig.savefig(path)
        plt.close(fig)
        return path

    def _save_bank_pie_chart(self, output_dir: Path) -> Path:
        plt = _plt()
        counts = Counter()
        for cid, _name, _sum in self.bank.get_clients_ranking():
            for acc in self.bank.search_accounts(client_id=cid):
                counts[acc.status.value] += 1

        fig, ax = plt.subplots(figsize=(6, 6))
        labels = list(counts.keys()) or ["no_accounts"]
        values = list(counts.values()) or [1]
        ax.pie(values, labels=labels, autopct="%1.0f%%")
        ax.set_title("Bank Accounts by Status")
        path = output_dir / "bank_accounts_pie.png"
        fig.tight_layout()
        fig.savefig(path)
        plt.close(fig)
        return path

    def _save_risk_bar_chart(self, output_dir: Path) -> Path:
        plt = _plt()
        risk_counts = Counter()
        if self.audit_log is not None:
            for entry in self.audit_log.filter(min_severity=AuditSeverity.INFO):
                level = entry.extra.get("risk_level")
                if level:
                    risk_counts[level] += 1

        fig, ax = plt.subplots(figsize=(7, 4))
        labels = list(risk_counts.keys()) or ["low"]
        values = list(risk_counts.values()) or [0]
        ax.bar(labels, values)
        ax.set_title("Risk Levels")
        ax.set_xlabel("Level")
        ax.set_ylabel("Count")
        path = output_dir / "risk_levels_bar.png"
        fig.tight_layout()
        fig.savefig(path)
        plt.close(fig)
        return path

    def _report_rows(self, report: dict[str, Any]) -> list[dict[str, Any]]:
        rtype = report.get("report_type")
        if rtype == "client":
            rows: list[dict[str, Any]] = []
            for account in report.get("accounts", []):
                row: dict[str, Any] = {"section": "account"}
                _flatten_row("", account, row)
                rows.append(row)
            for tx in report.get("transactions", []):
                row = {"section": "transaction"}
                _flatten_row("", tx, row)
                rows.append(row)
            return rows
        if rtype == "bank":
            rows = []
            for item in report.get("top_clients", []):
                row = {"section": "top_client"}
                _flatten_row("", item, row)
                rows.append(row)
            rows.append(
                {
                    "section": "summary",
                    "bank_name": report.get("bank_name"),
                    "clients_count": report.get("clients_count"),
                    "accounts_count": report.get("accounts_count"),
                    "total_balance": report.get("total_balance"),
                }
            )
            return rows
        if rtype == "risk":
            rows = []
            for item in report.get("suspicious_operations", []):
                row = {"section": "suspicious_operation"}
                _flatten_row("", item, row)
                rows.append(row)
            for client_id, profile in report.get("client_risk_profiles", {}).items():
                row = {"section": "client_risk_profile", "client_id": client_id}
                _flatten_row("", profile, row)
                rows.append(row)
            return rows
        flat: dict[str, Any] = {}
        _flatten_row("", report, flat)
        return [flat]

    def _serialize_transaction(self, tx: Transaction) -> dict[str, Any]:
        return {
            "transaction_id": tx.transaction_id,
            "type": tx.type.value,
            "amount": tx.amount,
            "currency": tx.currency.value,
            "commission": tx.commission,
            "sender_account": tx.sender_account,
            "receiver_account": tx.receiver_account,
            "status": tx.status.value,
            "failure_reason": tx.failure_reason,
            "created_at": tx.created_at.isoformat(timespec="seconds"),
            "updated_at": tx.updated_at.isoformat(timespec="seconds"),
            "client_id": tx.client_id,
        }

    def _serialize_audit_record(self, record: AuditRecord) -> dict[str, Any]:
        return {
            "timestamp": record.timestamp.isoformat(timespec="seconds"),
            "severity": record.severity.name,
            "message": record.message,
            "transaction_id": record.transaction_id,
            "client_id": record.client_id,
            "extra": _normalize(record.extra),
        }
