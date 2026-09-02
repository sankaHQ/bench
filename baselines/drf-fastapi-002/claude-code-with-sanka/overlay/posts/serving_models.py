"""Unmanaged shadow of rest_framework.authtoken.models.Token.

Lets the serving process read auth tokens through the Django ORM without
INSTALLED_APPS containing "rest_framework.authtoken" (and therefore without
importing rest_framework at all). Points at the same, already-migrated
authtoken_token table.
"""

from django.contrib.auth.models import User
from django.db import models


class AuthToken(models.Model):
    key = models.CharField(max_length=40, primary_key=True)
    user = models.OneToOneField(User, related_name="+", on_delete=models.DO_NOTHING)
    created = models.DateTimeField()

    class Meta:
        app_label = "posts"
        db_table = "authtoken_token"
        managed = False

    def __str__(self) -> str:
        return self.key
