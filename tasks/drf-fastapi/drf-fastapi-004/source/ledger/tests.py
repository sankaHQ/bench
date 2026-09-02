from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from ledger.models import Account, AuditLog, LedgerEntry


class LedgerApiTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.operating = Account.objects.create(name="operating", balance="100.00")
        self.reserve = Account.objects.create(name="reserve")

    def test_entry_create_updates_balance_and_audits(self) -> None:
        response = self.client.post(
            "/api/entries/",
            {"account": self.operating.id, "amount": "25.50", "memo": "topup"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["amount"], "25.50")
        self.operating.refresh_from_db()
        self.assertEqual(self.operating.balance, Decimal("125.50"))
        audit = AuditLog.objects.get()
        self.assertEqual(audit.action, "entry-created")
        self.assertEqual(audit.account_id, self.operating.id)
        self.assertEqual(audit.delta, Decimal("25.50"))

    def test_entry_delete_reverses_balance_and_audits(self) -> None:
        entry = LedgerEntry.objects.create(account=self.operating, amount="30.00")
        response = self.client.delete(f"/api/entries/{entry.id}/")
        self.assertEqual(response.status_code, 204)
        self.operating.refresh_from_db()
        self.assertEqual(self.operating.balance, Decimal("100.00"))
        self.assertEqual(
            list(AuditLog.objects.order_by("id").values_list("action", "delta")),
            [("entry-created", Decimal("30.00")), ("entry-deleted", Decimal("-30.00"))],
        )

    def test_transfer_moves_funds_through_entries_and_audits(self) -> None:
        response = self.client.post(
            f"/api/accounts/{self.operating.id}/transfer/",
            {"target": self.reserve.id, "amount": "40.00"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["balance"], "60.00")
        self.reserve.refresh_from_db()
        self.assertEqual(self.reserve.balance, Decimal("40.00"))
        self.assertEqual(
            list(LedgerEntry.objects.order_by("id").values_list("memo", flat=True)),
            ["transfer-out", "transfer-in"],
        )
        self.assertEqual(
            list(AuditLog.objects.order_by("id").values_list("action", flat=True)),
            ["entry-created", "entry-created", "transfer"],
        )

    def test_insufficient_funds_rolls_back_everything(self) -> None:
        response = self.client.post(
            f"/api/accounts/{self.reserve.id}/transfer/",
            {"target": self.operating.id, "amount": "1.00"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"amount": ["Insufficient funds."]})
        self.operating.refresh_from_db()
        self.reserve.refresh_from_db()
        self.assertEqual(self.operating.balance, Decimal("100.00"))
        self.assertEqual(self.reserve.balance, Decimal("0.00"))
        self.assertEqual(LedgerEntry.objects.count(), 0)
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_balance_is_read_only_through_the_api(self) -> None:
        response = self.client.post(
            "/api/accounts/",
            {"name": "savings", "balance": "999.99"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["balance"], "0.00")
        patched = self.client.patch(
            f"/api/accounts/{self.operating.id}/",
            {"balance": "999.99"},
            format="json",
        )
        self.assertEqual(patched.status_code, 200)
        self.operating.refresh_from_db()
        self.assertEqual(self.operating.balance, Decimal("100.00"))

    def test_account_delete_cascades_with_audit_trail(self) -> None:
        LedgerEntry.objects.create(account=self.operating, amount="10.00")
        LedgerEntry.objects.create(account=self.operating, amount="5.00")
        AuditLog.objects.all().delete()
        response = self.client.delete(f"/api/accounts/{self.operating.id}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Account.objects.filter(name="operating").exists())
        self.assertEqual(LedgerEntry.objects.count(), 0)
        # Django's deletion collector fires post_delete in descending pk order.
        self.assertEqual(
            list(AuditLog.objects.order_by("id").values_list("action", "delta")),
            [("entry-deleted", Decimal("-5.00")), ("entry-deleted", Decimal("-10.00"))],
        )
