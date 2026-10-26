from django.urls import path

from .views import (
    LearningPartnershipListView,
    MatchDetailView,
    MatchDiscoveryView,
    MatchRequestCreateView,
    MatchRequestRespondView,
    MatchRequestsView,
)

app_name = 'matching'

urlpatterns = [
    path('', MatchDiscoveryView.as_view(), name='index'),
    path('<int:pk>/', MatchDetailView.as_view(), name='detail'),
    path('<int:pk>/request/', MatchRequestCreateView.as_view(), name='request'),
    path('requests/', MatchRequestsView.as_view(), name='requests'),
    path('requests/<int:pk>/<str:action>/', MatchRequestRespondView.as_view(), name='respond'),
    path('partnerships/', LearningPartnershipListView.as_view(), name='partnerships'),
]