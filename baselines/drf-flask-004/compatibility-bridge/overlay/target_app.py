import os
os.environ["DJANGO_SETTINGS_MODULE"] = 'wallet_project.settings'
from django.core.wsgi import get_wsgi_application
from flask import Flask, request
from werkzeug.wrappers import Response
app = Flask(__name__)
source = get_wsgi_application()
def bridge(**kwargs):
    return Response.from_app(source, request.environ)
app.add_url_rule("/api/wallets/", "list", bridge, methods=["GET"])
app.add_url_rule("/api/transfers/", "transfer", bridge, methods=["POST"])
