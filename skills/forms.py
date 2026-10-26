from django import forms

from .models import LearningSkill, OfferedSkill, Skill


class ActiveSkillModelForm(forms.ModelForm):
    def __init__(self, *args, profile=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.profile = profile
        if self.profile is None and self.instance.pk:
            self.profile = self.instance.profile
        skills = Skill.objects.filter(is_active=True).order_by('name')
        self.fields['skill'].queryset = skills
        self.fields['skill'].empty_label = 'Choose a skill'
        self.fields['skill'].widget.attrs['class'] = 'form-select'
        self.fields['skill'].widget.attrs.update({
            'aria-describedby': 'skill-catalogue-help',
            'required': 'required',
        })
        skill_choices = []
        available_skills = list(skills)
        for category_value, category_label in Skill.Category.choices:
            category_skills = [
                (str(skill.pk), skill.name)
                for skill in available_skills
                if skill.category == category_value
            ]
            if category_skills:
                skill_choices.append((category_label, category_skills))
        self.fields['skill'].choices = skill_choices

    def clean(self):
        cleaned_data = super().clean()
        skill = cleaned_data.get('skill')
        if self.profile is not None and skill is not None:
            duplicates = self._meta.model.objects.filter(profile=self.profile, skill=skill)
            if self.instance.pk:
                duplicates = duplicates.exclude(pk=self.instance.pk)
            if duplicates.exists():
                self.add_error('skill', 'This skill is already in this list.')
        return cleaned_data


class OfferedSkillForm(ActiveSkillModelForm):
    class Meta:
        model = OfferedSkill
        fields = ('skill', 'proficiency', 'description')
        widgets = {
            'proficiency': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Optional details about what you can teach',
            }),
        }


class LearningSkillForm(ActiveSkillModelForm):
    class Meta:
        model = LearningSkill
        fields = ('skill', 'learning_level', 'goal')
        widgets = {
            'learning_level': forms.Select(attrs={'class': 'form-select'}),
            'goal': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Optional learning goal',
            }),
        }