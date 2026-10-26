from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Notification, User


@admin.register(User)
class SkillBridgeUserAdmin(UserAdmin):
	list_display = ('username', 'email', 'role', 'is_active', 'is_staff')
	list_filter = (*UserAdmin.list_filter, 'role')
	fieldsets = (*UserAdmin.fieldsets, ('SkillBridge access', {'fields': ('role',)}))
	add_fieldsets = (*UserAdmin.add_fieldsets, ('SkillBridge access', {'fields': ('role',)}))


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
	list_display = ('title', 'recipient', 'notification_type', 'is_read', 'created_at')
	list_filter = ('notification_type', 'is_read', 'created_at')
	date_hierarchy = 'created_at'
	search_fields = ('title', 'recipient__username', 'recipient__email')
	readonly_fields = tuple(field.name for field in Notification._meta.fields)
	exclude = ('related_url',)

	def has_add_permission(self, request):
		return False
