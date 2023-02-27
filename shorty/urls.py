from . import views
from django.urls import path



urlpatterns = [
    path('_admin/', views._admin),
    path('<str:alias>/', views.surl),
    path('', views.index),
]
