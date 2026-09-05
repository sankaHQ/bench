from decimal import Decimal

from django.test import TestCase

from wallets.models import AuditEvent, Transfer, Wallet
from wallets.services import transfer_money


class TransferContractTests(TestCase):
    def test_replay_does_not_debit_or_audit_twice(self):
        source = Wallet.objects.create(tenant="north", name="Main", balance=Decimal("10.00"))
        target = Wallet.objects.create(tenant="north", name="Reserve", balance=Decimal("0.00"))
        first = transfer_money("north", source.id, target.id, Decimal("2.50"), "once")
        second = transfer_money("north", source.id, target.id, Decimal("2.50"), "once")
        self.assertEqual((first[1], second[1]), (201, 200))
        source.refresh_from_db()
        self.assertEqual(source.balance, Decimal("7.50"))
        self.assertEqual(Transfer.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.count(), 1)
