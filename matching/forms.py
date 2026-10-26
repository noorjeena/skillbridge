from django import forms

from .models import MatchRequest


class MatchRequestForm(forms.ModelForm):
    class Meta:
        model = MatchRequest
        fields = ('message',)
        widgets = {
            'message': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Add a short note (optional)',
            }),
        }