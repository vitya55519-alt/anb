from __future__ import annotations

import secrets
from dataclasses import dataclass

from models.app_models import PaymentMethod
from services.db import SessionLocal


STATUS_LABELS = {
    "active": "включён",
    "disabled": "выключен",
    "soon": "скоро",
}

TYPE_LABELS = {
    "stars": "Telegram Stars",
    "qr": "QR-код",
    "link": "Ссылка / провайдер",
}

SCOPE_LABELS = {
    "digital_stars": "цифровые покупки внутри Telegram",
    "external_only": "внешний / нецифровой сценарий",
}

DEFAULT_METHODS = {
    "telegram_stars": {
        "display_name": "Telegram Stars",
        "method_type": "stars",
        "status": "active",
        "scope": "digital_stars",
        "is_system": True,
        "instructions": "Основной и обязательный способ оплаты цифровых товаров и услуг внутри Telegram.",
    },
    "lava": {
        "display_name": "Lava",
        "method_type": "link",
        "status": "soon",
        "scope": "external_only",
        "is_system": False,
        "instructions": "Заготовка для внешнего сценария. URL можно добавить из админки.",
    },
}


@dataclass(frozen=True)
class PaymentMethodView:
    id: int
    method_key: str
    display_name: str
    method_type: str
    status: str
    scope: str
    is_system: bool
    qr_photo_file_id: str | None
    external_url: str | None
    instructions: str

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def type_label(self) -> str:
        return TYPE_LABELS.get(self.method_type, self.method_type)

    @property
    def scope_label(self) -> str:
        return SCOPE_LABELS.get(self.scope, self.scope)

    @property
    def button_text(self) -> str:
        icon = {"active": "✅", "disabled": "⏸", "soon": "🕒"}.get(self.status, "•")
        return f"{icon} {self.display_name}"


def _to_view(row: PaymentMethod) -> PaymentMethodView:
    return PaymentMethodView(
        id=row.id,
        method_key=row.method_key,
        display_name=row.display_name,
        method_type=row.method_type or "qr",
        status=row.status or "disabled",
        scope=row.scope or "external_only",
        is_system=bool(row.is_system),
        qr_photo_file_id=row.qr_photo_file_id,
        external_url=row.external_url,
        instructions=row.instructions or "",
    )


def ensure_default_payment_methods() -> None:
    with SessionLocal() as session:
        changed = False
        for method_key, defaults in DEFAULT_METHODS.items():
            row = session.query(PaymentMethod).filter_by(method_key=method_key).first()
            if row is None:
                session.add(PaymentMethod(method_key=method_key, **defaults))
                changed = True
        if changed:
            session.commit()


def list_payment_methods() -> list[PaymentMethodView]:
    ensure_default_payment_methods()
    with SessionLocal() as session:
        rows = session.query(PaymentMethod).order_by(PaymentMethod.is_system.desc(), PaymentMethod.id.asc()).all()
        return [_to_view(row) for row in rows]


def get_payment_method(method_id: int) -> PaymentMethodView | None:
    ensure_default_payment_methods()
    with SessionLocal() as session:
        row = session.get(PaymentMethod, int(method_id))
        return _to_view(row) if row else None


def create_payment_method(method_type: str, display_name: str) -> PaymentMethodView:
    if method_type not in {"qr", "link"}:
        raise ValueError("unsupported payment method type")
    name = (display_name or "").strip()
    if not 1 <= len(name) <= 120:
        raise ValueError("Название должно быть от 1 до 120 символов.")
    with SessionLocal() as session:
        row = PaymentMethod(
            method_key=f"manual_{method_type}_{secrets.token_hex(6)}",
            display_name=name,
            method_type=method_type,
            status="disabled",
            scope="external_only",
            is_system=False,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _to_view(row)


def update_payment_method(method_id: int, **changes) -> PaymentMethodView:
    allowed = {"display_name", "status", "qr_photo_file_id", "external_url", "instructions"}
    clean = {k: v for k, v in changes.items() if k in allowed}
    if "status" in clean and clean["status"] not in STATUS_LABELS:
        raise ValueError("unknown payment status")
    with SessionLocal() as session:
        row = session.get(PaymentMethod, int(method_id))
        if row is None:
            raise ValueError("Способ оплаты не найден.")
        if row.method_type == "stars":
            # Digital purchases inside Telegram must remain Stars-only. Keep the system method active.
            clean.pop("status", None)
        for key, value in clean.items():
            setattr(row, key, value)
        session.commit()
        session.refresh(row)
        return _to_view(row)


def delete_payment_method(method_id: int) -> bool:
    with SessionLocal() as session:
        row = session.get(PaymentMethod, int(method_id))
        if row is None:
            return False
        if row.is_system or row.method_type == "stars":
            raise ValueError("Системный способ оплаты удалить нельзя.")
        session.delete(row)
        session.commit()
        return True
