from . import views
from django.urls import path

app_name = 'shorty'

urlpatterns = [
    path('<str:alias>/', views.surl),
]
