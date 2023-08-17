from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

app_name = 'common'

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='common/login.html'), name='login'),
    # path('login/', auth_views.LoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('signup/', views.signup, name='signup'),
    path('domain/', views.domain_list, name='domain_list'),
    path('url/', views.url, name='url'),
    path('url/create/', views.url_create, name='url_create'),
    path('url/delete/<int:pk>', views.url_delete, name='url_delete'),
    path('url/edit/<int:pk>', views.url_edit, name='url_edit'),
    path('domain/create', views.domain_create, name='domain_create'),
    path('domain/delete/<int:pk>', views.domain_delete, name='domain_delete'),
    path('domain/verify/<int:pk>', views.domain_verify, name='domain_verify'),   
]

handler404 = 'common.views.page_not_found'