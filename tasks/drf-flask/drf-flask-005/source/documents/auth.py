from types import SimpleNamespace

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed


class ApiKeyAuth(BaseAuthentication):
    def authenticate_header(self, request):
        return "ApiKey"

    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        if not header:
            raise AuthenticationFailed("Authentication credentials were not provided.")
        owner = {"ApiKey team-a": "alpha", "ApiKey team-b": "beta"}.get(header)
        if owner is None:
            raise AuthenticationFailed("Invalid API key.")
        return SimpleNamespace(username=owner, is_authenticated=True), None
