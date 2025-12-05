"""
User authentication forms.
"""
from django import forms
from .models import User


class SignUpForm(forms.ModelForm):
    """User registration form."""
    password = forms.CharField(widget=forms.PasswordInput, min_length=8)
    password_confirmation = forms.CharField(widget=forms.PasswordInput, label='Confirm Password')
    
    class Meta:
        model = User
        fields = ['email', 'name']
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('A user with this email already exists.')
        return email
    
    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirmation = cleaned_data.get('password_confirmation')
        
        if password and password_confirmation and password != password_confirmation:
            raise forms.ValidationError('Passwords do not match.')
        
        return cleaned_data


class SignInForm(forms.Form):
    """User login form."""
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput)


class PasswordResetRequestForm(forms.Form):
    """Password reset request form."""
    email = forms.EmailField()


class PasswordResetForm(forms.Form):
    """Password reset form."""
    password = forms.CharField(widget=forms.PasswordInput, min_length=8)
    password_confirmation = forms.CharField(widget=forms.PasswordInput, label='Confirm Password')
    
    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirmation = cleaned_data.get('password_confirmation')
        
        if password and password_confirmation and password != password_confirmation:
            raise forms.ValidationError('Passwords do not match.')
        
        return cleaned_data

