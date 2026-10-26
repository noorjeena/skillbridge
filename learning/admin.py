from django.contrib import admin

from .models import Assignment, Evaluation, LearningDirection, LearningMaterial, LearningPlan, Lesson, LearningSession, Review, Submission


@admin.register(LearningDirection)
class LearningDirectionAdmin(admin.ModelAdmin):
	list_display = ('partnership', 'teacher', 'learner', 'skill', 'status', 'created_at')
	list_filter = ('status', 'skill__category')
	search_fields = ('teacher__full_name', 'teacher__user__username', 'learner__full_name', 'learner__user__username', 'skill__name')
	autocomplete_fields = ('partnership', 'teacher', 'learner', 'skill')


@admin.register(LearningPlan)
class LearningPlanAdmin(admin.ModelAdmin):
	list_display = ('title', 'learning_direction', 'created_by', 'status', 'created_at')
	list_filter = ('status', 'learning_direction__skill')
	search_fields = ('title', 'learning_direction__teacher__user__username', 'learning_direction__learner__user__username')
	autocomplete_fields = ('learning_direction', 'created_by')
	readonly_fields = ('progress_percentage',)

	@admin.display(description='Progress')
	def progress_percentage(self, plan):
		return f'{plan.progress_percentage}%'


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
	list_display = ('title', 'learning_plan', 'order', 'estimated_duration', 'status', 'updated_at')
	list_filter = ('status', 'learning_plan__status')
	search_fields = ('title', 'learning_plan__title', 'learning_plan__learning_direction__skill__name')
	autocomplete_fields = ('learning_plan',)


@admin.register(LearningMaterial)
class LearningMaterialAdmin(admin.ModelAdmin):
	list_display = ('title', 'lesson', 'material_type', 'created_by', 'created_at')
	list_filter = ('material_type', 'created_at')
	date_hierarchy = 'created_at'
	search_fields = ('title', 'description', 'lesson__title', 'created_by__username')
	autocomplete_fields = ('lesson', 'created_by')
	readonly_fields = ('created_at', 'updated_at')


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
	list_display = ('title', 'lesson', 'created_by', 'status', 'due_date', 'resource_file', 'created_at')
	list_filter = ('status', 'created_at')
	date_hierarchy = 'created_at'
	search_fields = ('title', 'instructions', 'lesson__title', 'created_by__username')
	autocomplete_fields = ('lesson', 'created_by')
	readonly_fields = ('created_at', 'updated_at')


@admin.register(LearningSession)
class LearningSessionAdmin(admin.ModelAdmin):
	list_display = ('title', 'learning_direction', 'lesson', 'status', 'scheduled_start', 'scheduled_end', 'created_by')
	list_filter = ('status', 'scheduled_start', 'learning_direction__skill')
	date_hierarchy = 'scheduled_start'
	search_fields = ('title', 'learning_direction__teacher__user__username', 'learning_direction__learner__user__username', 'lesson__title')
	autocomplete_fields = ('learning_direction', 'lesson', 'created_by')
	readonly_fields = ('created_at', 'updated_at')


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
	list_display = ('assignment', 'learner', 'status', 'submitted_at', 'updated_at')
	list_filter = ('status', 'submitted_at')
	date_hierarchy = 'submitted_at'
	search_fields = ('assignment__title', 'learner__full_name', 'learner__user__username', 'answer_text')
	autocomplete_fields = ('assignment', 'learner')
	readonly_fields = ('submitted_at', 'updated_at')


@admin.register(Evaluation)
class EvaluationAdmin(admin.ModelAdmin):
	list_display = ('submission', 'evaluator', 'score', 'status', 'created_at', 'updated_at')
	list_filter = ('status', 'created_at', 'updated_at')
	date_hierarchy = 'created_at'
	search_fields = (
		'submission__assignment__title',
		'submission__learner__full_name',
		'submission__learner__user__username',
		'evaluator__username',
	)
	autocomplete_fields = ('submission', 'evaluator')
	readonly_fields = tuple(field.name for field in Evaluation._meta.fields)

	def has_add_permission(self, request):
		return False

	def has_delete_permission(self, request, obj=None):
		return False


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
	list_display = ('reviewer', 'reviewee', 'learning_direction', 'rating', 'created_at', 'updated_at')
	list_filter = ('rating', 'created_at', 'learning_direction__skill')
	date_hierarchy = 'created_at'
	search_fields = (
		'reviewer__full_name',
		'reviewer__user__username',
		'reviewee__full_name',
		'reviewee__user__username',
		'learning_direction__skill__name',
		'comment',
	)
	autocomplete_fields = ('learning_direction', 'reviewer', 'reviewee')
