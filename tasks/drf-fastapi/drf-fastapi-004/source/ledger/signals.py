"""Side effects owned by Django signals, not by any view.

Every ledger entry write keeps `Account.balance` and the append-only
`AuditLog` in step. The receivers are connected in `LedgerConfig.ready`,
so the behavior exists only while the `ledger` app config is installed —
a native migration must reproduce these effects explicitly.
"""

from django.db.models import F
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from ledger.models import Account, AuditLog, LedgerEntry


@receiver(post_save, sender=LedgerEntry, dispatch_uid="ledger-entry-created")
def entry_created(sender, instance, created, **kwargs):
    if not created:
        return
    Account.objects.filter(pk=instance.account_id).update(balance=F("balance") + instance.amount)
    AuditLog.objects.create(
        action="entry-created",
        account_id=instance.account_id,
        delta=instance.amount,
    )


@receiver(post_delete, sender=LedgerEntry, dispatch_uid="ledger-entry-deleted")
def entry_deleted(sender, instance, **kwargs):
    Account.objects.filter(pk=instance.account_id).update(balance=F("balance") - instance.amount)
    AuditLog.objects.create(
        action="entry-deleted",
        account_id=instance.account_id,
        delta=-instance.amount,
    )
