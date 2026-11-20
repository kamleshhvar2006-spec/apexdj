from django.urls import path, re_path

from logistics import views

urlpatterns = [
    path('', views.index),
    path('api/health', views.health),
    path('api/track/<str:tracking_id>', views.track),
    path('api/bookings', views.bookings),
    path('api/admin/login', views.admin_login),
    path('api/admin/dashboard', views.admin_dashboard),
    path('api/admin/shipments/<str:tracking_id>', views.admin_update),
    re_path(r'^api/', views.api_not_found),
]
