from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from reservations.auth import ApiKeyAuth
from reservations.logic import book, cancel, representation
from reservations.models import Reservation
from reservations.serializers import BookingSerializer


class BaseView(APIView):
    authentication_classes = [ApiKeyAuth]
    permission_classes = [AllowAny]
    parser_classes = [JSONParser]


class BookingView(BaseView):
    def get(self, request):
        rows = Reservation.objects.filter(resource__owner=request.user.username).order_by(
            "start", "id"
        )
        return Response([representation(row) for row in rows])

    def post(self, request):
        serializer = BookingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        body, status = book(request.user.username, serializer.validated_data)
        return Response(body, status=status)


class CancelView(BaseView):
    def post(self, request, identifier):
        body, status = cancel(request.user.username, identifier)
        return Response(body, status=status)
