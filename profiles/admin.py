from django.contrib import admin

from .models import StudentProfile


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
	list_display = ('full_name', 'user', 'department', 'academic_year', 'completion_status')
	list_filter = ('department', 'academic_year')
	search_fields = ('full_name', 'user__username', 'user__email', 'department')
	readonly_fields = ('completion_status',)

	@admin.display(description='Profile completion')
	def completion_status(self, profile):
		return f'{profile.completion_percentage}%'
