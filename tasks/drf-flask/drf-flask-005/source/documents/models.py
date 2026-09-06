from django.db import models


class Document(models.Model):
    owner = models.CharField(max_length=20)
    title = models.CharField(max_length=64)
    body = models.TextField()
    revision = models.PositiveIntegerField(default=1)
    deleted = models.BooleanField(default=False)


class RevisionEvent(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE)
    revision = models.PositiveIntegerField()
    action = models.CharField(max_length=20)
