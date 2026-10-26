from django import forms

from skills.models import Skill


class AdminSkillForm(forms.ModelForm):
    class Meta:
        model = Skill
        fields = ('name', 'category', 'description', 'is_active')
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off',
                'placeholder': 'e.g. Python',
            }),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'A short description to help students choose this skill.',
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_name(self):
        return ' '.join(self.cleaned_data['name'].split())
