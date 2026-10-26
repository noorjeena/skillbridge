"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from learning.views import (
    ProtectedAssignmentResourceStorageView,
    ProtectedLearningMaterialStorageView,
    ProtectedSubmissionStorageView,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path(
        'admin-dashboard/',
        include('accounts.admin_urls', namespace='admin_dashboard'),
    ),
    path('', include('accounts.urls')),
    path('profile/', include('profiles.urls')),
    path('skills/', include('skills.urls')),
    path('matching/', include('matching.urls')),
    path('chat/', include('matching.chat_urls')),
    path('learning/', include('learning.urls')),
    path(
        'media/learning_materials/<path:filepath>',
        ProtectedLearningMaterialStorageView.as_view(),
        name='protected-learning-material-media',
    ),
    path(
        'media/assignment_submissions/<path:filepath>',
        ProtectedSubmissionStorageView.as_view(),
        name='protected-submission-media',
    ),
    path(
        'media/assignment_resources/<path:filepath>',
        ProtectedAssignmentResourceStorageView.as_view(),
        name='protected-assignment-resource-media',
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
