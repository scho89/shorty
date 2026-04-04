from django.contrib.auth import views as auth_views
from django.urls import path
from . import views

app_name = 'common'

urlpatterns = [
    # path('login/', auth_views.LoginView.as_view(template_name='common/login.html'), name='login'),
    # path('login/', auth_views.LoginView.as_view(), name='login'),
    path('login/', views.signin, name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('username-reminder/', views.username_reminder_request, name='username_reminder_request'),
    path('password-reset/', views.password_reset_request, name='password_reset_request'),
    path('password-reset/verify/', views.password_reset_verify, name='password_reset_verify'),
    path('signup/', views.signup, name='signup'),
    path('account/', views.account_settings, name='account_settings'),
    path('help/', views.help_page, name='help'),
    path('domain/', views.domain_list, name='domain_list'),
    path('url/', views.url, name='url'),
    path('links/', views.links, name='links'),
    path('url/create/', views.url_create, name='url_create'),
    path('url/delete/<int:pk>', views.url_delete, name='url_delete'),
    path('url/edit/<int:pk>', views.url_edit, name='url_edit'),
    path('url/<int:pk>/stats/', views.url_stats, name='url_stats'),
    path('url/<int:pk>/qr.svg', views.url_qr_code, name='url_qr_code'),
    path('domain/create', views.domain_create, name='domain_create'),
    path('domain/delete/<int:pk>', views.domain_delete, name='domain_delete'),
    path('domain/verify/<int:pk>', views.domain_verify, name='domain_verify'),   
]

handler404 = 'common.views.page_not_found'
