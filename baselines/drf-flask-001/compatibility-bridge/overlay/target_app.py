import os
os.environ["DJANGO_SETTINGS_MODULE"] = 'workflow_project.settings'
from django.core.wsgi import get_wsgi_application
from flask import Flask, request
from werkzeug.wrappers import Response
app = Flask(__name__)
source = get_wsgi_application()
def bridge(**kwargs):
    return Response.from_app(source, request.environ)
app.add_url_rule('/api/orders/', "bridge_0", bridge, methods=['GET'], provide_automatic_options=False)
app.add_url_rule('/api/orders/', "bridge_1", bridge, methods=['POST'], provide_automatic_options=False)
app.add_url_rule('/api/orders/<int:identifier>/', "bridge_2", bridge, methods=['GET'], provide_automatic_options=False)
app.add_url_rule('/api/orders/<int:identifier>/', "bridge_3", bridge, methods=['PATCH'], provide_automatic_options=False)
app.add_url_rule('/api/orders/<int:identifier>/transition/', "bridge_4", bridge, methods=['POST'], provide_automatic_options=False)
