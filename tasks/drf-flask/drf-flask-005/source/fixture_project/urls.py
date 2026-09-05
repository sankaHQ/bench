from django.urls import path
from documents.views import DocumentView

urlpatterns = [path("api/documents/<int:identifier>/", DocumentView.as_view())]
