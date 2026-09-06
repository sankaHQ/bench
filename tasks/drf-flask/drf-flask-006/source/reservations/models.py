from django.db import models


class Resource(models.Model):
    owner = models.CharField(max_length=20)
    name = models.CharField(max_length=50)
    capacity = models.PositiveIntegerField()


class Reservation(models.Model):
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE)
    start = models.DateTimeField()
    end = models.DateTimeField()
    seats = models.PositiveIntegerField()
    cancelled = models.BooleanField(default=False)


class BookingEvent(models.Model):
    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE)
    action = models.CharField(max_length=20)
