from decimal import Decimal
from types import SimpleNamespace

from rest_framework import serializers
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from wallets.models import Wallet
from wallets.services import transfer_money


class TenantKeyAuthentication(BaseAuthentication):
    def authenticate(self, request):
        value = request.headers.get("Authorization")
        if value is None:
            return None
        tenant = {"ApiKey north-key": "north", "ApiKey south-key": "south"}.get(value)
        if tenant is None:
            raise AuthenticationFailed("Invalid tenant key.")
        return SimpleNamespace(is_authenticated=True), tenant

    def authenticate_header(self, request):
        return 'ApiKey realm="wallets"'


class TransferInput(serializers.Serializer):
    source = serializers.IntegerField(min_value=1)
    destination = serializers.IntegerField(min_value=1)
    amount = serializers.DecimalField(max_digits=9, decimal_places=2, min_value=Decimal("0.01"))
    idempotency_key = serializers.CharField(max_length=40)

    def validate(self, attrs):
        if attrs["source"] == attrs["destination"]:
            raise serializers.ValidationError("Source and destination must differ.")
        return attrs


class WalletListView(APIView):
    authentication_classes = [TenantKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            [
                {"id": w.id, "name": w.name, "balance": format(w.balance, ".2f")}
                for w in Wallet.objects.filter(tenant=request.auth).order_by("id")
            ]
        )


class TransferView(APIView):
    authentication_classes = [TenantKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = TransferInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        body, status, replayed = transfer_money(
            request.auth,
            data["source"],
            data["destination"],
            data["amount"],
            data["idempotency_key"],
        )
        return Response(body, status=status, headers={"X-Idempotent-Replay": str(replayed).lower()})
