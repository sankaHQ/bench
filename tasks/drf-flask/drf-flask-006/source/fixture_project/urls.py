from django.urls import path
from reservations.views import BookingView, CancelView

urlpatterns = [
    path("api/bookings/", BookingView.as_view()),
    path("api/bookings/<int:identifier>/cancel/", CancelView.as_view()),
]
