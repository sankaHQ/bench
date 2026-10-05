from django.urls import path
from wallets.views import TransferView, WalletListView

urlpatterns = [
    path("api/wallets/", WalletListView.as_view()),
    path("api/transfers/", TransferView.as_view()),
]
