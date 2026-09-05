import os
os.environ["DJANGO_SETTINGS_MODULE"] = 'metrics_project.settings'
from django.core.wsgi import get_wsgi_application
from flask import Flask, request
from werkzeug.wrappers import Response
app = Flask(__name__)
source = get_wsgi_application()
def bridge(**kwargs):
    return Response.from_app(source, request.environ)
app.add_url_rule('/api/accounts/', "bridge_0", bridge, methods=['GET'], provide_automatic_options=False)
app.add_url_rule('/api/summary/', "bridge_1", bridge, methods=['GET'], provide_automatic_options=False)
app.add_url_rule('/api/transactions/', "bridge_2", bridge, methods=['POST'], provide_automatic_options=False)
app.add_url_rule('/api/transactions/<int:identifier>/', "bridge_3", bridge, methods=['PATCH'], provide_automatic_options=False)
app.add_url_rule('/api/transactions/<int:identifier>/', "bridge_4", bridge, methods=['DELETE'], provide_automatic_options=False)
