from rest_framework.viewsets import ModelViewSet

from orders.models import Order
from orders.serializers import OrderSerializer


class OrderViewSet(ModelViewSet):
    queryset = Order.objects.prefetch_related("items__adjustments").all()
    serializer_class = OrderSerializer
