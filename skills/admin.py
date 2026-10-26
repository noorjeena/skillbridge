from django.contrib import admin

from .models import LearningSkill, OfferedSkill, Skill


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
	list_display = ('name', 'category', 'is_active', 'created_at')
	list_filter = ('category', 'is_active')
	search_fields = ('name', 'description')
	actions = ('activate_skills', 'deactivate_skills')

	def has_module_permission(self, request):
		return request.user.is_active and request.user.role == 'ADMIN'

	def has_view_permission(self, request, obj=None):
		return request.user.is_active and request.user.role == 'ADMIN'

	def has_add_permission(self, request):
		return request.user.is_active and request.user.role == 'ADMIN'

	def has_change_permission(self, request, obj=None):
		return request.user.is_active and request.user.role == 'ADMIN'

	def has_delete_permission(self, request, obj=None):
		return request.user.is_active and request.user.role == 'ADMIN'

	@admin.action(description='Activate selected skills')
	def activate_skills(self, request, queryset):
		queryset.update(is_active=True)

	@admin.action(description='Deactivate selected skills')
	def deactivate_skills(self, request, queryset):
		queryset.update(is_active=False)


@admin.register(OfferedSkill)
class OfferedSkillAdmin(admin.ModelAdmin):
	list_display = ('skill', 'profile', 'proficiency', 'created_at')
	list_filter = ('proficiency', 'skill__category')
	search_fields = ('skill__name', 'profile__full_name', 'profile__user__username')
	autocomplete_fields = ('profile', 'skill')


@admin.register(LearningSkill)
class LearningSkillAdmin(admin.ModelAdmin):
	list_display = ('skill', 'profile', 'learning_level', 'created_at')
	list_filter = ('learning_level', 'skill__category')
	search_fields = ('skill__name', 'profile__full_name', 'profile__user__username')
	autocomplete_fields = ('profile', 'skill')
