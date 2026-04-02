from . import views
from django.urls import path

app_name = 'shorty'

urlpatterns = [
    path('<str:alias>', views.surl, name='alias_no_slash'),
    path('<str:alias>/', views.surl, name='alias'),
    path('',views.index, name='index' ),
]
