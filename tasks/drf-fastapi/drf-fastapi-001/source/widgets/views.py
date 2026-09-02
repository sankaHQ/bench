from rest_framework.viewsets import ModelViewSet

from widgets.models import Widget
from widgets.serializers import WidgetSerializer


class WidgetViewSet(ModelViewSet):
    queryset = Widget.objects.all()
    serializer_class = WidgetSerializer
