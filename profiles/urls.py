from django.urls import path

from .views import ProfileDetailView, ProfileUpdateView


urlpatterns = [
    path('', ProfileDetailView.as_view(), name='profile-detail'),
    path('edit/', ProfileUpdateView.as_view(), name='profile-edit'),
]