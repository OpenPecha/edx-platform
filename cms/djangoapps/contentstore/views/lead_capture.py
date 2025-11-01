"""
Views for handling lead capture forms in Studio.
"""
import logging
from django.http import JsonResponse, HttpResponseRedirect
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import csrf_protect
from django.contrib import messages
from django.urls import reverse
from django.utils.translation import gettext as _

from ..forms import HowItWorksContactForm
from ..integrations.google_sheets import submit_to_google_sheets

log = logging.getLogger(__name__)


@require_http_methods(["POST"])
@csrf_protect
def submit_howitworks_contact(request):
    """
    Handle contact form submission from the How It Works page.
    
    Supports both AJAX and regular form submissions.
    """
    form = HowItWorksContactForm(request.POST)
    
    if form.is_valid():
        try:
            # Submit to Google Sheets
            success = submit_to_google_sheets(form.cleaned_data)
            
            if success:
                log.info(f"Contact form submitted successfully from {request.META.get('REMOTE_ADDR')}")
                
                # Handle AJAX requests
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': True,
                        'message': _('Thank you! We will contact you soon.')
                    })
                
                # Handle regular form submissions
                messages.success(request, _('Thank you! We will contact you soon.'))
                return HttpResponseRedirect(reverse('howitworks') + '?submitted=1')
            
            else:
                log.error("Failed to submit contact form to Google Sheets")
                error_message = _('Sorry, there was a problem submitting your request. Please try again later.')
                
                # Handle AJAX requests
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False,
                        'message': error_message
                    }, status=500)
                
                # Handle regular form submissions
                messages.error(request, error_message)
                return HttpResponseRedirect(reverse('howitworks') + '?error=1')
        
        except Exception as e:
            log.error(f"Unexpected error in contact form submission: {e}")
            error_message = _('Sorry, there was a problem submitting your request. Please try again later.')
            
            # Handle AJAX requests
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'message': error_message
                }, status=500)
            
            # Handle regular form submissions
            messages.error(request, error_message)
            return HttpResponseRedirect(reverse('howitworks') + '?error=1')
    
    else:
        # Form validation failed
        log.warning(f"Contact form validation failed: {form.errors}")
        
        # Handle AJAX requests
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'message': _('Please correct the errors below.'),
                'errors': form.errors
            }, status=400)
        
        # Handle regular form submissions
        messages.error(request, _('Please correct the errors in the form.'))
        return HttpResponseRedirect(reverse('howitworks') + '?validation_error=1')
