from django.urls import path

from .admin_views import (
    AdminAssignmentListView,
    AdminDashboardHomeView,
    AdminMatchListView,
    AdminMessageListView,
    AdminNotificationListView,
    AdminPartnershipListView,
    AdminReviewListView,
    AdminSessionListView,
    AdminSkillCreateView,
    AdminSkillDeleteView,
    AdminSkillListView,
    AdminSkillToggleView,
    AdminSkillUpdateView,
    AdminUserDetailView,
    AdminUserListView,
)


app_name = 'admin_dashboard'

urlpatterns = [
    path('', AdminDashboardHomeView.as_view(), name='overview'),
    path('users/', AdminUserListView.as_view(), name='users'),
    path('users/<int:pk>/', AdminUserDetailView.as_view(), name='user-detail'),
    path('skills/', AdminSkillListView.as_view(), name='skills'),
    path('skills/add/', AdminSkillCreateView.as_view(), name='skill-add'),
    path('skills/<int:pk>/edit/', AdminSkillUpdateView.as_view(), name='skill-edit'),
    path('skills/<int:pk>/toggle/', AdminSkillToggleView.as_view(), name='skill-toggle'),
    path('skills/<int:pk>/delete/', AdminSkillDeleteView.as_view(), name='skill-delete'),
    path('matches/', AdminMatchListView.as_view(), name='matches'),
    path('partnerships/', AdminPartnershipListView.as_view(), name='partnerships'),
    path('sessions/', AdminSessionListView.as_view(), name='sessions'),
    path('assignments/', AdminAssignmentListView.as_view(), name='assignments'),
    path('reviews/', AdminReviewListView.as_view(), name='reviews'),
    path('messages/', AdminMessageListView.as_view(), name='messages'),
    path('notifications/', AdminNotificationListView.as_view(), name='notifications'),
]
