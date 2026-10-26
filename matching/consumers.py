import json

from channels.db import database_sync_to_async
from channels.exceptions import DenyConnection
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.core.exceptions import ValidationError
from django.utils.html import escape

from accounts.models import User
from .models import Message
from .services import conversation_for_user, send_message


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope['user']
        if not user or not user.is_authenticated or getattr(user, 'role', None) != User.Role.STUDENT:
            await self.close()
            raise DenyConnection

        self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']
        self.conversation = await database_sync_to_async(self.get_conversation)(user)
        if not self.conversation:
            await self.close()
            raise DenyConnection

        await self.channel_layer.group_add(f'chat_{self.conversation_id}', self.channel_name)
        await self.accept()

    def get_conversation(self, user):
        return conversation_for_user(user, self.conversation_id)

    async def receive_json(self, content):
        if not isinstance(content, dict):
            return
        message_text = (content.get('message') or '').strip()
        if not message_text:
            await self.send_json({'error': 'Message content is required.'})
            return
        if len(message_text) > 2000:
            await self.send_json({'error': 'Messages must be 2000 characters or fewer.'})
            return

        try:
            saved = await database_sync_to_async(self.save_message)(message_text)
        except (ValidationError, ValueError, PermissionError) as exc:
            await self.send_json({'error': str(exc)})
            return

        payload = {
            'type': 'chat.message',
            'message': {
                'id': saved.pk,
                'sender': saved.sender.username,
                'sender_name': saved.sender.student_profile.full_name or saved.sender.username,
                'content': escape(saved.content),
                'created_at': saved.created_at.isoformat(),
                'is_read': saved.is_read,
            },
        }
        await self.channel_layer.group_send(f'chat_{self.conversation_id}', payload)

    def save_message(self, message_text):
        return send_message(self.conversation, self.scope['user'], message_text)

    async def chat_message(self, event):
        await self.send_json(event['message'])

    async def disconnect(self, code):
        await self.channel_layer.group_discard(f'chat_{self.conversation_id}', self.channel_name)
