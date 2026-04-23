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
    path('settings/', views.settings_page, name='settings'),
    path('settings/routing/update/', views.global_routing_settings_update, name='global_routing_settings_update'),
    path('settings/fallbacks/create/', views.fallback_destination_create, name='fallback_destination_create'),
    path('settings/fallbacks/<int:pk>/delete/', views.fallback_destination_delete, name='fallback_destination_delete'),
    path('domain/', views.domain_list, name='domain_list'),
    path('domain/<int:pk>/settings/', views.domain_settings, name='domain_settings'),
    path('domain/<int:pk>/settings/update/', views.domain_settings_update, name='domain_settings_update'),
    path('domain/<int:pk>/settings/check-cname/', views.domain_check_cname, name='domain_check_cname'),
    path('url/', views.url, name='url'),
    path('links/', views.links, name='links'),
    path('url/create/', views.url_create, name='url_create'),
    path('url/export.csv', views.links_csv_export, name='links_csv_export'),
    path('url/bulk/', views.url_bulk_action, name='url_bulk_action'),
    path('url/delete/<int:pk>', views.url_delete, name='url_delete'),
    path('url/edit/<int:pk>', views.url_edit, name='url_edit'),
    path('url/toggle-active/<int:pk>', views.url_toggle_active, name='url_toggle_active'),
    path('url/<int:pk>/stats/', views.url_stats, name='url_stats'),
    path('url/<int:pk>/stats/export.csv', views.url_stats_csv_export, name='url_stats_csv_export'),
    path('url/<int:pk>/qr.svg', views.url_qr_code, name='url_qr_code'),
    path('domain/create', views.domain_create, name='domain_create'),
    path('domain/delete/<int:pk>', views.domain_delete, name='domain_delete'),
    path('domain/verify/<int:pk>', views.domain_verify, name='domain_verify'),   
]

handler404 = 'common.views.page_not_found'
