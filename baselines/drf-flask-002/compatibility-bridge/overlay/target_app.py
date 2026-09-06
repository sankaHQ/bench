import os
os.environ["DJANGO_SETTINGS_MODULE"] = 'files_project.settings'
from django.core.wsgi import get_wsgi_application
from flask import Flask, request
from werkzeug.wrappers import Response
app = Flask(__name__)
source = get_wsgi_application()
def bridge(**kwargs):
    return Response.from_app(source, request.environ)
app.add_url_rule('/api/files/', "bridge_0", bridge, methods=['GET'], provide_automatic_options=False)
app.add_url_rule('/api/files/', "bridge_1", bridge, methods=['POST'], provide_automatic_options=False)
app.add_url_rule('/api/files.json', "bridge_2", bridge, methods=['GET'], provide_automatic_options=False)
app.add_url_rule('/api/files.json', "bridge_3", bridge, methods=['POST'], provide_automatic_options=False)
app.add_url_rule('/api/files.api', "bridge_4", bridge, methods=['GET'], provide_automatic_options=False)
app.add_url_rule('/api/files.api', "bridge_5", bridge, methods=['POST'], provide_automatic_options=False)
app.add_url_rule('/api/files/<int:identifier>/', "bridge_6", bridge, methods=['GET'], provide_automatic_options=False)
app.add_url_rule('/api/files/<int:identifier>.json', "bridge_7", bridge, methods=['GET'], provide_automatic_options=False)
app.add_url_rule('/api/files/<int:identifier>.api', "bridge_8", bridge, methods=['GET'], provide_automatic_options=False)
app.add_url_rule('/api/files/<int:identifier>/download/', "bridge_9", bridge, methods=['GET'], provide_automatic_options=False)
app.add_url_rule('/api/files/<int:identifier>/download.json', "bridge_10", bridge, methods=['GET'], provide_automatic_options=False)
app.add_url_rule('/api/files/<int:identifier>/download.api', "bridge_11", bridge, methods=['GET'], provide_automatic_options=False)
