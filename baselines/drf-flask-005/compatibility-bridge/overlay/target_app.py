import os
os.environ["DJANGO_SETTINGS_MODULE"]="fixture_project.settings"
from django.core.wsgi import get_wsgi_application
from flask import Flask, request
from werkzeug.wrappers import Response

class SourceHeadersResponse(Response):
    def get_wsgi_headers(self, environ):
        result = super().get_wsgi_headers(environ)
        # DRF retains Allow on 304; Werkzeug normally strips this header.
        if self.status_code == 304 and "Allow" in self.headers:
            result["Allow"] = self.headers["Allow"]
        return result

app=Flask(__name__)
app.response_class=SourceHeadersResponse
source=get_wsgi_application()
def bridge(**kwargs):
    return SourceHeadersResponse.from_app(source, request.environ)
app.add_url_rule('/api/documents/<int:identifier>/', "bridge0", bridge, methods=["GET","HEAD","POST","PUT","PATCH","DELETE","OPTIONS"])
