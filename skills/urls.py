from django.urls import path

from .views import (
    LearningSkillCreateView,
    LearningSkillDeleteView,
    LearningSkillUpdateView,
    OfferedSkillCreateView,
    OfferedSkillDeleteView,
    OfferedSkillUpdateView,
    SkillListView,
)

app_name = 'skills'

urlpatterns = [
    path('', SkillListView.as_view(), name='index'),
    path('teach/add/', OfferedSkillCreateView.as_view(), name='teach-add'),
    path('teach/<int:pk>/edit/', OfferedSkillUpdateView.as_view(), name='teach-edit'),
    path('teach/<int:pk>/delete/', OfferedSkillDeleteView.as_view(), name='teach-delete'),
    path('learn/add/', LearningSkillCreateView.as_view(), name='learn-add'),
    path('learn/<int:pk>/edit/', LearningSkillUpdateView.as_view(), name='learn-edit'),
    path('learn/<int:pk>/delete/', LearningSkillDeleteView.as_view(), name='learn-delete'),
]