from django.contrib import admin

from .models import LearningPartnership, Match, MatchRequest


class ReadOnlyAdmin(admin.ModelAdmin):
	def has_add_permission(self, request):
		return False

	def has_change_permission(self, request, obj=None):
		return False

	def has_delete_permission(self, request, obj=None):
		return False


@admin.register(Match)
class MatchAdmin(ReadOnlyAdmin):
	list_display = ('student_one', 'student_two', 'compatibility_score', 'match_type', 'status', 'updated_at')
	list_filter = ('match_type', 'status')
	search_fields = (
		'student_one__full_name',
		'student_one__user__username',
		'student_two__full_name',
		'student_two__user__username',
	)
	readonly_fields = tuple(field.name for field in Match._meta.fields)


@admin.register(MatchRequest)
class MatchRequestAdmin(ReadOnlyAdmin):
	list_display = ('sender', 'receiver', 'match', 'status', 'created_at', 'responded_at')
	list_filter = ('status', 'match__match_type')
	search_fields = ('sender__full_name', 'sender__user__username', 'receiver__full_name', 'receiver__user__username')
	readonly_fields = tuple(field.name for field in MatchRequest._meta.fields)


@admin.register(LearningPartnership)
class LearningPartnershipAdmin(ReadOnlyAdmin):
	list_display = ('student_one', 'student_two', 'relationship_type', 'status', 'created_at')
	list_filter = ('relationship_type', 'status')
	search_fields = (
		'student_one__full_name',
		'student_one__user__username',
		'student_two__full_name',
		'student_two__user__username',
	)
	readonly_fields = tuple(field.name for field in LearningPartnership._meta.fields)
