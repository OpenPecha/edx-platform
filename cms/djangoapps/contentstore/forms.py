"""
Forms for Studio content store.
"""
from django import forms
from django.utils.translation import gettext_lazy as _


class HowItWorksContactForm(forms.Form):
    """
    Contact form for the Studio "How It Works" page.
    """
    
    name = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Your full name'),
            'aria-describedby': 'name-help'
        }),
        label=_('Full Name'),
        help_text=_('Enter your full name')
    )
    
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': _('your.email@example.com'),
            'aria-describedby': 'email-help'
        }),
        label=_('Email Address'),
        help_text=_('We will use this to contact you')
    )
    
    organization = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Your organization or institution'),
            'aria-describedby': 'organization-help'
        }),
        label=_('Organization'),
        help_text=_('Optional: Your organization or institution name')
    )

    organization_description = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': _('Briefly describe your organization or needs'),
            'aria-describedby': 'organization-description-help'
        }),
        label=_('Organization Description'),
        help_text=_('Optional: A short description to help us understand your context')
    )
    
    def clean_email(self):
        """Validate email field."""
        email = self.cleaned_data.get('email')
        if email:
            email = email.lower().strip()
        return email
    
    def clean_name(self):
        """Validate name field."""
        name = self.cleaned_data.get('name')
        if name:
            name = name.strip()
            if len(name) < 2:
                raise forms.ValidationError(_('Name must be at least 2 characters long'))
        return name
