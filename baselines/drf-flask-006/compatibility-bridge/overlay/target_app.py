import os
os.environ["DJANGO_SETTINGS_MODULE"]="fixture_project.settings"
from django.core.wsgi import get_wsgi_application
from flask import Flask, request
from werkzeug.wrappers import Response
app=Flask(__name__)
source=get_wsgi_application()
def bridge(**kwargs):
    return Response.from_app(source, request.environ)
app.add_url_rule('/api/bookings/', "bridge0", bridge, methods=["GET","HEAD","POST","PUT","PATCH","DELETE","OPTIONS"])
app.add_url_rule('/api/bookings/<int:identifier>/cancel/', "bridge1", bridge, methods=["GET","HEAD","POST","PUT","PATCH","DELETE","OPTIONS"])
