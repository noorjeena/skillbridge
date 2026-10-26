from django.urls import path

from .views import ChatConversationDetailView, ChatListView

app_name = 'chat'

urlpatterns = [
    path('', ChatListView.as_view(), name='chat-list'),
    path('<int:conversation_id>/', ChatConversationDetailView.as_view(), name='chat-detail'),
]
