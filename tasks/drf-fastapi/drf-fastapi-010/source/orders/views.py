from __future__ import annotations

from typing import Any

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from orders.models import Order, OrderEvent
from orders.serializers import OrderPatchSerializer, OrderSerializer, TransitionSerializer
from orders.state_machine import LEGAL_TRANSITIONS


def conflict_response(order: Order, provided_version: int) -> Response:
    return Response(
        {
            "detail": "Version conflict.",
            "expected_version": order.version,
            "provided_version": provided_version,
        },
        status=status.HTTP_409_CONFLICT,
    )


class OrderViewSet(ModelViewSet):
    queryset = Order.objects.all()
    serializer_class = OrderSerializer

    @transaction.atomic
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = OrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = serializer.save()
        OrderEvent.objects.create(
            order=order,
            kind=OrderEvent.Kind.CREATED,
            from_status=order.status,
            to_status=order.status,
            version=order.version,
        )
        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)

    @transaction.atomic
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        request_serializer = OrderPatchSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        provided_version = request_serializer.validated_data.pop("version")
        order = get_object_or_404(Order.objects.select_for_update(), pk=kwargs["pk"])
        if order.version != provided_version:
            return conflict_response(order, provided_version)

        for field, value in request_serializer.validated_data.items():
            setattr(order, field, value)
        order.version += 1
        order.save(update_fields=[*request_serializer.validated_data, "version"])
        OrderEvent.objects.create(
            order=order,
            kind=OrderEvent.Kind.UPDATED,
            from_status=order.status,
            to_status=order.status,
            version=order.version,
        )
        return Response(OrderSerializer(order).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def transition(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        request_serializer = TransitionSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        provided_version = request_serializer.validated_data["version"]
        target = request_serializer.validated_data["to_status"]
        order = get_object_or_404(Order.objects.select_for_update(), pk=kwargs["pk"])

        if order.version != provided_version:
            return conflict_response(order, provided_version)

        allowed = LEGAL_TRANSITIONS[order.status]
        if target not in allowed:
            return Response(
                {
                    "detail": (f"Transition from {order.status} to {target} is not allowed."),
                    "allowed": list(allowed),
                },
                status=status.HTTP_409_CONFLICT,
            )

        previous_status = order.status
        order.status = target
        order.version += 1
        order.save(update_fields=["status", "version"])
        OrderEvent.objects.create(
            order=order,
            kind=OrderEvent.Kind.TRANSITIONED,
            from_status=previous_status,
            to_status=target,
            version=order.version,
        )
        return Response(OrderSerializer(order).data)
