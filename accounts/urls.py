from django.urls import path

from .views import (
    HomeView,
    LoginView,
    LogoutView,
    NotificationListView,
    NotificationMarkAllReadView,
    NotificationOpenView,
    NotificationReadView,
    RegisterView,
)


urlpatterns = [
    path('', HomeView.as_view(), name='home'),
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('admin-login/', LoginView.as_view(), name='admin-login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('notifications/', NotificationListView.as_view(), name='notifications'),
    path('notifications/mark-all-read/', NotificationMarkAllReadView.as_view(), name='notifications-mark-all-read'),
    path('notifications/<int:pk>/open/', NotificationOpenView.as_view(), name='notification-open'),
    path('notifications/<int:pk>/read/', NotificationReadView.as_view(), name='notification-read'),
]