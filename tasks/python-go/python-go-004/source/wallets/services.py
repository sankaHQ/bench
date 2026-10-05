from decimal import Decimal

from django.db import transaction

from wallets.models import AuditEvent, Transfer, Wallet


def transfer_money(tenant: str, source: int, destination: int, amount: Decimal, key: str):
    with transaction.atomic():
        wallets = {
            w.id: w
            for w in Wallet.objects.select_for_update().filter(
                tenant=tenant, id__in=[source, destination]
            )
        }
        if source not in wallets or destination not in wallets:
            return {"detail": "Wallet not found."}, 404, False
        prior = Transfer.objects.filter(tenant=tenant, idempotency_key=key).first()
        if prior is not None:
            if (prior.source_id, prior.destination_id, prior.amount) != (
                source,
                destination,
                amount,
            ):
                return (
                    {"detail": "Idempotency key already used for a different transfer."},
                    409,
                    False,
                )
            return _serialize(prior), 200, True
        if wallets[source].balance < amount:
            return {"detail": "Insufficient funds."}, 409, False
        wallets[source].balance -= amount
        wallets[destination].balance += amount
        wallets[source].save(update_fields=["balance"])
        wallets[destination].save(update_fields=["balance"])
        record = Transfer.objects.create(
            tenant=tenant,
            source_id=source,
            destination_id=destination,
            amount=amount,
            idempotency_key=key,
        )
        AuditEvent.objects.create(transfer=record, event="transferred")
        return _serialize(record), 201, False


def _serialize(record):
    return {
        "id": record.id,
        "source": record.source_id,
        "destination": record.destination_id,
        "amount": format(record.amount, ".2f"),
        "idempotency_key": record.idempotency_key,
    }
