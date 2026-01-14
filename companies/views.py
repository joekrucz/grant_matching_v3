"""
Company views.
"""
import os
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django_ratelimit.decorators import ratelimit
from django.core.paginator import Paginator
from django.db.models.functions import Lower
from django.db.models import Q, Count
from django.conf import settings
from django.urls import reverse
from django.http import HttpResponse
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from .models import Company, FundingSearch, GrantMatchResult, FundingSearchFile, FundingQuestionnaire
from .services import (
    CompaniesHouseService,
    CompaniesHouseError,
    ThreeSixtyGivingService,
    ThreeSixtyGivingError,
    ChatGPTMatchingService,
    GrantMatchingError,
)
from grants_aggregator import CELERY_AVAILABLE
from grants.models import Grant, GRANT_SOURCES

# Import tasks only if Celery is available
if CELERY_AVAILABLE:
    from .tasks import match_grants_with_chatgpt
else:
    match_grants_with_chatgpt = None


@login_required
def companies_list(request):
    """List companies for the current user."""
    # SECURITY: Only show companies owned by the current user (unless admin)
    if request.user.admin:
        # Admins can see all companies
        companies = Company.objects.all().select_related('user').order_by(Lower('name'))
    else:
        # Regular users only see their own companies
        companies = Company.objects.filter(user=request.user).select_related('user').order_by(Lower('name'))
    
    # Pagination
    paginator = Paginator(companies, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'companies/list.html', {'page_obj': page_obj})


@login_required
def funding_searches_list(request):
    """List all funding searches for the current user."""
    # SECURITY: Only show funding searches owned by the current user (unless admin)
    if request.user.admin:
        # Admins can see all funding searches
        funding_searches = FundingSearch.objects.all().select_related('user', 'company').prefetch_related('match_results').order_by('-created_at')
    else:
        # Regular users only see their own funding searches
        funding_searches = FundingSearch.objects.filter(user=request.user).select_related('user', 'company').prefetch_related('match_results').order_by('-created_at')
    
    # Pagination
    paginator = Paginator(funding_searches, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'companies/funding_searches_list.html', {'page_obj': page_obj})


@login_required
def questionnaires_list(request):
    """List all questionnaires for the current user."""
    # SECURITY: Only show questionnaires owned by the current user (unless admin)
    if request.user.admin:
        questionnaires = FundingQuestionnaire.objects.all().select_related('user').annotate(
            usage_count=Count('funding_searches')
        ).order_by('-updated_at')
    else:
        questionnaires = FundingQuestionnaire.objects.filter(
            user=request.user
        ).annotate(
            usage_count=Count('funding_searches')
        ).order_by('-updated_at')
    
    # Pagination
    paginator = Paginator(questionnaires, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'companies/questionnaires_list.html', {'page_obj': page_obj})


@login_required
def questionnaire_create(request):
    """Create a new questionnaire."""
    from .models import TRL_LEVELS
    from django.utils import timezone
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'Name is required.')
            return render(request, 'companies/questionnaire_form.html', {
                'trl_levels': TRL_LEVELS,
                'grant_sources': GRANT_SOURCES,
                'mode': 'create',
            })
        
        # SECURITY: Validate name length
        if len(name) > 255:
            messages.error(request, 'Name must be 255 characters or less.')
            return render(request, 'companies/questionnaire_form.html', {
                'trl_levels': TRL_LEVELS,
                'grant_sources': GRANT_SOURCES,
                'mode': 'create',
            })
        
        # Collect questionnaire data
        questionnaire_data = {
            'company_stage': request.POST.get('company_stage', ''),
            'company_size': request.POST.get('company_size', ''),
            'primary_sector': request.POST.get('primary_sector', ''),
            'company_location': {
                'country': request.POST.get('country', ''),
                'region': request.POST.get('region', ''),
                'city': request.POST.get('city', ''),
            },
            'project_name': request.POST.get('project_name', ''),
            'project_description': request.POST.get('project_description', ''),
            'problem_statement': request.POST.get('problem_statement', ''),
            'trl_levels': request.POST.getlist('trl_levels'),
            'let_system_decide_trl': request.POST.get('let_system_decide_trl') == 'on',
            'project_types': request.POST.getlist('project_types'),
            'funding_amount_needed': request.POST.get('funding_amount_needed', ''),
            'funding_timeline': request.POST.get('funding_timeline', ''),
            'funding_purposes': request.POST.getlist('funding_purposes'),
            'organization_type': request.POST.get('organization_type', ''),
            'geographic_eligibility': request.POST.get('geographic_eligibility', ''),
            'collaboration_requirements': request.POST.get('collaboration_requirements', ''),
            'previous_grant_experience': request.POST.get('previous_grant_experience', ''),
            'key_strengths': request.POST.getlist('key_strengths'),
            'project_impact': request.POST.get('project_impact', ''),
            'target_market': request.POST.get('target_market', ''),
            'grant_sources_preference': request.POST.getlist('grant_sources_preference'),
            'exclusions': request.POST.getlist('exclusions'),
            'additional_information': request.POST.get('additional_information', ''),
        }
        
        # Validate TRL levels
        valid_trl_values = [choice[0] for choice in TRL_LEVELS]
        validated_trl_levels = [
            level for level in questionnaire_data['trl_levels']
            if level in valid_trl_values
        ]
        questionnaire_data['trl_levels'] = validated_trl_levels
        
        # Handle let_system_decide_trl flag
        if questionnaire_data.get('let_system_decide_trl'):
            questionnaire_data['let_system_decide_trl'] = True
        else:
            questionnaire_data['let_system_decide_trl'] = False
        
        # Validate grant sources
        valid_source_codes = [source[0] for source in GRANT_SOURCES]
        validated_sources = [
            source for source in questionnaire_data['grant_sources_preference']
            if source in valid_source_codes
        ]
        questionnaire_data['grant_sources_preference'] = validated_sources
        
        # Check if this should be default
        is_default = request.POST.get('is_default') == 'on'
        
        # If setting as default, unset other defaults
        if is_default:
            FundingQuestionnaire.objects.filter(
                user=request.user,
                is_default=True
            ).update(is_default=False)
        
        questionnaire = FundingQuestionnaire.objects.create(
            user=request.user,
            name=name,
            questionnaire_data=questionnaire_data,
            is_default=is_default,
        )
        
        messages.success(request, 'Questionnaire created successfully.')
        return redirect('companies:questionnaire_detail', id=questionnaire.id)
    
    # GET request
    context = {
        'trl_levels': TRL_LEVELS,
        'grant_sources': GRANT_SOURCES,
        'mode': 'create',
    }
    return render(request, 'companies/questionnaire_form.html', context)


@login_required
def questionnaire_detail(request, id):
    """View and edit a questionnaire."""
    from .models import TRL_LEVELS
    
    questionnaire = get_object_or_404(FundingQuestionnaire, id=id)
    
    # Check permissions
    if request.user != questionnaire.user and not request.user.admin:
        messages.error(request, 'You do not have permission to view this questionnaire.')
        return redirect('companies:questionnaires_list')
    
    if request.method == 'POST':
        # Handle updates
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'Name is required.')
            return redirect('companies:questionnaire_detail', id=id)
        
        # SECURITY: Validate name length
        if len(name) > 255:
            messages.error(request, 'Name must be 255 characters or less.')
            return redirect('companies:questionnaire_detail', id=id)
        
        # Update questionnaire data
        questionnaire_data = {
            'company_stage': request.POST.get('company_stage', ''),
            'company_size': request.POST.get('company_size', ''),
            'primary_sector': request.POST.get('primary_sector', ''),
            'company_location': {
                'country': request.POST.get('country', ''),
                'region': request.POST.get('region', ''),
                'city': request.POST.get('city', ''),
            },
            'project_name': request.POST.get('project_name', ''),
            'project_description': request.POST.get('project_description', ''),
            'problem_statement': request.POST.get('problem_statement', ''),
            'trl_levels': request.POST.getlist('trl_levels'),
            'let_system_decide_trl': request.POST.get('let_system_decide_trl') == 'on',
            'project_types': request.POST.getlist('project_types'),
            'funding_amount_needed': request.POST.get('funding_amount_needed', ''),
            'funding_timeline': request.POST.get('funding_timeline', ''),
            'funding_purposes': request.POST.getlist('funding_purposes'),
            'organization_type': request.POST.get('organization_type', ''),
            'geographic_eligibility': request.POST.get('geographic_eligibility', ''),
            'collaboration_requirements': request.POST.get('collaboration_requirements', ''),
            'previous_grant_experience': request.POST.get('previous_grant_experience', ''),
            'key_strengths': request.POST.getlist('key_strengths'),
            'project_impact': request.POST.get('project_impact', ''),
            'target_market': request.POST.get('target_market', ''),
            'grant_sources_preference': request.POST.getlist('grant_sources_preference'),
            'exclusions': request.POST.getlist('exclusions'),
            'additional_information': request.POST.get('additional_information', ''),
        }
        
        # Validate TRL levels
        valid_trl_values = [choice[0] for choice in TRL_LEVELS]
        validated_trl_levels = [
            level for level in questionnaire_data['trl_levels']
            if level in valid_trl_values
        ]
        questionnaire_data['trl_levels'] = validated_trl_levels
        
        # Handle let_system_decide_trl flag
        if questionnaire_data.get('let_system_decide_trl'):
            questionnaire_data['let_system_decide_trl'] = True
        else:
            questionnaire_data['let_system_decide_trl'] = False
        
        # Validate grant sources
        valid_source_codes = [source[0] for source in GRANT_SOURCES]
        validated_sources = [
            source for source in questionnaire_data['grant_sources_preference']
            if source in valid_source_codes
        ]
        questionnaire_data['grant_sources_preference'] = validated_sources
        
        is_default = request.POST.get('is_default') == 'on'
        if is_default:
            FundingQuestionnaire.objects.filter(
                user=request.user,
                is_default=True
            ).exclude(id=questionnaire.id).update(is_default=False)
        
        questionnaire.name = name
        questionnaire.questionnaire_data = questionnaire_data
        questionnaire.is_default = is_default
        questionnaire.save()
        
        messages.success(request, 'Questionnaire updated successfully.')
        return redirect('companies:questionnaire_detail', id=id)
    
    # GET request
    context = {
        'questionnaire': questionnaire,
        'trl_levels': TRL_LEVELS,
        'grant_sources': GRANT_SOURCES,
        'existing_data': questionnaire.questionnaire_data or {},
        'mode': 'edit',
    }
    return render(request, 'companies/questionnaire_form.html', context)


@login_required
@require_POST
def questionnaire_delete(request, id):
    """Delete a questionnaire."""
    questionnaire = get_object_or_404(FundingQuestionnaire, id=id)
    
    if request.user != questionnaire.user and not request.user.admin:
        messages.error(request, 'You do not have permission to delete this questionnaire.')
        return redirect('companies:questionnaires_list')
    
    questionnaire.delete()
    messages.success(request, 'Questionnaire deleted successfully.')
    return redirect('companies:questionnaires_list')


@login_required
def questionnaire_apply(request, id, funding_search_id):
    """Apply a questionnaire to a funding search."""
    questionnaire = get_object_or_404(FundingQuestionnaire, id=id)
    funding_search = get_object_or_404(FundingSearch, id=funding_search_id)
    
    # Check permissions
    if request.user != questionnaire.user and not request.user.admin:
        messages.error(request, 'You do not have permission to use this questionnaire.')
        return redirect('companies:funding_search_detail', id=funding_search_id)
    
    if request.user != funding_search.user and not request.user.admin:
        messages.error(request, 'You do not have permission to edit this funding search.')
        return redirect('companies:funding_search_detail', id=funding_search_id)
    
    # Apply questionnaire to funding search
    questionnaire.apply_to_funding_search(funding_search)
    
    # Link questionnaire to funding search
    funding_search.questionnaire = questionnaire
    funding_search.save()
    
    messages.success(request, f'Questionnaire "{questionnaire.name}" applied successfully.')
    return redirect('companies:funding_search_detail', id=funding_search_id)


@login_required
@require_POST
def questionnaire_unlink(request, funding_search_id):
    """Unlink a questionnaire from a funding search."""
    funding_search = get_object_or_404(FundingSearch, id=funding_search_id)
    
    # Check permissions
    if request.user != funding_search.user and not request.user.admin:
        messages.error(request, 'You do not have permission to edit this funding search.')
        return redirect('companies:funding_search_detail', id=funding_search_id)
    
    # Unlink questionnaire from funding search
    if funding_search.questionnaire:
        questionnaire_name = funding_search.questionnaire.name
        funding_search.questionnaire = None
        funding_search.save()
        messages.success(request, f'Questionnaire "{questionnaire_name}" unlinked successfully.')
    else:
        messages.info(request, 'No questionnaire was linked to this funding search.')
    
    return redirect('companies:funding_search_detail', id=funding_search_id)


@login_required
def company_detail(request, id):
    """Company detail page."""
    from .models import TRL_LEVELS
    
    # SECURITY: Check authorization before loading data
    company = get_object_or_404(Company, id=id)
    
    # Check if user has permission to view (owner or admin)
    if request.user != company.user and not request.user.admin:
        messages.error(request, 'You do not have permission to view this company.')
        return redirect('companies:list')
    
    funding_searches = company.funding_searches.all().order_by('-created_at')
    
    # Check if user can edit (owner or admin)
    can_edit = request.user == company.user or request.user.admin
    
    if request.method == 'POST':
        if not can_edit:
            messages.error(request, 'You do not have permission to edit this company.')
            return redirect('companies:detail', id=id)
        
        # Handle website/notes update
        website = request.POST.get('website', company.website or '').strip()
        # SECURITY: Validate website URL to prevent SSRF
        if website:
            from .security import validate_website_url
            is_valid, error_msg = validate_website_url(website)
            if not is_valid:
                messages.error(request, f'Invalid website URL: {error_msg}')
                return redirect('companies:detail', id=id)
        # SECURITY: Use explicit allowlist to prevent mass assignment
        allowed_fields = []
        
        company.website = website if website else None
        allowed_fields.append('website')
        
        # SECURITY: Only save explicitly allowed fields
        company.save(update_fields=allowed_fields)
        messages.success(request, 'Company updated successfully.')

        return redirect('companies:detail', id=id)
    
    # Tab selection
    allowed_tabs = ['info', 'notes', 'grants', 'filings', 'funding', 'settings']
    current_tab = request.GET.get('tab', 'info')
    if current_tab not in allowed_tabs:
        current_tab = 'info'

    context = {
        'company': company,
        'funding_searches': funding_searches,
        'can_edit': can_edit,
        'trl_levels': TRL_LEVELS,
        'current_tab': current_tab,
        'can_edit_tabs': can_edit,
    }
    return render(request, 'companies/detail.html', context)


@login_required
def company_refresh_grants(request, id):
    """Refresh grants from 360Giving for a company."""
    company = get_object_or_404(Company, id=id)

    if request.user != company.user and not request.user.admin:
        messages.error(request, 'You do not have permission to refresh this company.')
        return redirect('companies:list')

    if not company.company_number:
        messages.error(request, 'Company number is required to refresh grants.')
        return redirect('companies:detail', id=id)

    try:
        grants_received = ThreeSixtyGivingService.fetch_grants_received(company.company_number)
        company.grants_received_360 = grants_received
        company.save(update_fields=['grants_received_360'])
        messages.success(request, 'Grants refreshed successfully.')
    except ThreeSixtyGivingError as e:
        messages.error(request, f'360Giving refresh failed: {e}')
    except Exception as e:
        messages.error(request, f'Unexpected error refreshing grants: {e}')

    return redirect('companies:detail', id=id)


@login_required
def company_refresh_filings(request, id):
    """Refresh filing history from Companies House for a company."""
    company = get_object_or_404(Company, id=id)

    if request.user != company.user and not request.user.admin:
        messages.error(request, 'You do not have permission to refresh this company.')
        return redirect('companies:list')

    if not company.company_number:
        messages.error(request, 'Company number is required to refresh filing history.')
        return redirect('companies:detail', id=id)

    try:
        filing_history = CompaniesHouseService.fetch_filing_history(company.company_number)
        # Replace the filing_history field with fresh data
        company.filing_history = filing_history
        company.save(update_fields=['filing_history'])
        messages.success(request, 'Filing history refreshed successfully.')
    except CompaniesHouseError as e:
        messages.error(request, f'Companies House refresh failed: {e}')
    except Exception as e:
        messages.error(request, f'Unexpected error refreshing filing history: {e}')

    return redirect(f'{reverse("companies:detail", args=[id])}?tab=filings')


@login_required
def company_create(request):
    """Create company from Companies House API or manual entry."""
    if request.method == 'POST':
        creation_mode = request.POST.get('creation_mode', 'registered')
        
        if creation_mode == 'manual':
            # Manual entry for unregistered companies
            name = request.POST.get('name', '').strip()
            
            if not name:
                messages.error(request, 'Company name is required.')
                return render(request, 'companies/create.html', {'mode': 'manual'})
            
            # Check for duplicate names (case-insensitive)
            if Company.objects.filter(name__iexact=name, user=request.user).exists():
                messages.warning(request, f'A company named "{name}" already exists. Continuing anyway...')
            
            # Generate unique company_number for unregistered companies
            import uuid
            from datetime import datetime
            unique_id = f"UNREG-{request.user.id}-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"
            
            # Ensure uniqueness
            while Company.objects.filter(company_number=unique_id).exists():
                unique_id = f"UNREG-{request.user.id}-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"
            
            # Build address from form fields
            address = {}
            if request.POST.get('address_line_1'):
                address = {
                    'address_line_1': request.POST.get('address_line_1', ''),
                    'address_line_2': request.POST.get('address_line_2', ''),
                    'locality': request.POST.get('locality', ''),
                    'postal_code': request.POST.get('postal_code', ''),
                    'country': request.POST.get('country', ''),
                }
            
            # Create unregistered company
            company = Company.objects.create(
                user=request.user,
                company_number=unique_id,
                name=name,
                is_registered=False,
                registration_status='unregistered',
                company_type=request.POST.get('company_type', ''),
                website=request.POST.get('website', '') or None,
                address=address,
                notes=request.POST.get('notes', ''),
            )
            
            messages.success(request, f'Unregistered company "{company.name}" created successfully.')
            return redirect('companies:onboarding', id=company.id)
        
        else:
            # Companies House API lookup (existing flow)
            company_number = request.POST.get('company_number', '').strip()
        
        if not company_number:
            messages.error(request, 'Company number is required.')
            return render(request, 'companies/create.html')
        
        try:
            # Check if company already exists
            if Company.objects.filter(company_number=company_number).exists():
                messages.error(request, f'Company {company_number} already exists.')
                return render(request, 'companies/create.html')
            
            # Fetch from Companies House API
            api_data = CompaniesHouseService.fetch_company(company_number)
            
            # Fetch filing history
            try:
                filing_history = CompaniesHouseService.fetch_filing_history(company_number)
            except CompaniesHouseError as e:
                # Log but don't fail if filing history can't be fetched
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Could not fetch filing history for company {company_number}: {e}")
                filing_history = None
            
            normalized_data = CompaniesHouseService.normalize_company_data(api_data, filing_history)
            
            # Create company with registered status
            company = Company.objects.create(
                user=request.user,
                is_registered=True,
                registration_status='registered',
                **normalized_data
            )

            # Attempt to enrich with historical grants from 360Giving (non-blocking)
            try:
                grants_received = ThreeSixtyGivingService.fetch_grants_received(company.company_number)
                company.grants_received_360 = grants_received
                company.save(update_fields=['grants_received_360'])
            except ThreeSixtyGivingError as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"360Giving lookup skipped for {company.company_number}: {e}")
            
            messages.success(request, f'Company {company.name} created successfully.')
            return redirect('companies:onboarding', id=company.id)
        
        except CompaniesHouseError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f'Error creating company: {str(e)}')
    
    return render(request, 'companies/create.html')


@login_required
@require_POST
def company_delete(request, id):
    """Delete company (owner or admin only)."""
    # SECURITY: Check authorization before loading data
    company = get_object_or_404(Company, id=id)
    
    if request.user != company.user and not request.user.admin:
        messages.error(request, 'You do not have permission to delete this company.')
        return redirect('companies:detail', id=id)
    
    company_name = company.name
    company.delete()
    messages.success(request, f'Company {company_name} deleted successfully.')
    return redirect('companies:list')


@login_required
def funding_search_create(request, company_id):
    """Create funding search for a company."""
    from .models import TRL_LEVELS
    
    # SECURITY: Check authorization before loading data
    company = get_object_or_404(Company, id=company_id)
    
    # Check if user has permission to create funding search for this company
    if request.user != company.user and not request.user.admin:
        messages.error(request, 'You do not have permission to create funding searches for this company.')
        return redirect('companies:detail', id=company_id)
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'Name is required.')
            return render(request, 'companies/funding_search_create.html', {
                'company': company,
                'trl_levels': TRL_LEVELS,
            })
        
        # SECURITY: Validate name length
        if len(name) > 255:
            messages.error(request, 'Name must be 255 characters or less.')
            return render(request, 'companies/funding_search_create.html', {
                'company': company,
                'trl_levels': TRL_LEVELS,
            })
        
        # SECURITY: Validate notes length
        notes = request.POST.get('notes', '').strip()
        if len(notes) > 10000:
            messages.error(request, 'Notes must be 10000 characters or less.')
            return render(request, 'companies/funding_search_create.html', {
                'company': company,
                'trl_levels': TRL_LEVELS,
            })
        
        # Get multiple TRL levels from form
        trl_levels = request.POST.getlist('trl_levels')  # getlist for multiple values
        trl_levels = [level for level in trl_levels if level]  # Remove empty values
        
        # SECURITY: Validate TRL levels against allowed choices
        valid_trl_values = [choice[0] for choice in TRL_LEVELS]
        validated_trl_levels = []
        for level in trl_levels:
            if level in valid_trl_values:
                validated_trl_levels.append(level)
            else:
                messages.error(request, f'Invalid TRL level: {level}')
                return render(request, 'companies/funding_search_create.html', {
                    'company': company,
                    'trl_levels': TRL_LEVELS,
                })
        
        # Get questionnaire if selected
        questionnaire_id = request.POST.get('questionnaire_id')
        questionnaire = None
        if questionnaire_id:
            try:
                questionnaire = FundingQuestionnaire.objects.get(
                    id=questionnaire_id,
                    user=request.user
                )
            except FundingQuestionnaire.DoesNotExist:
                pass
        
        funding_search = FundingSearch.objects.create(
            company=company,
            user=request.user,
            name=name,
            notes=notes,
            trl_level=request.POST.get('trl_level', '') or None,  # Keep for backwards compatibility
            trl_levels=validated_trl_levels,
            questionnaire=questionnaire,
        )
        
        # Apply questionnaire if selected
        if questionnaire:
            questionnaire.apply_to_funding_search(funding_search)
        
        messages.success(request, 'Funding search created successfully.')
        return redirect('companies:funding_search_select_data', id=funding_search.id)
    
    # GET request - show the form
    # Get user's questionnaires
    questionnaires = FundingQuestionnaire.objects.filter(
        user=request.user
    ).order_by('-is_default', '-updated_at')
    
    # Get default questionnaire
    default_questionnaire = questionnaires.filter(is_default=True).first()
    
    context = {
        'company': company,
        'trl_levels': TRL_LEVELS,
        'questionnaires': questionnaires,
        'default_questionnaire': default_questionnaire,
    }
    return render(request, 'companies/funding_search_create.html', context)


@login_required
def funding_search_detail(request, id):
    """Funding search detail page."""
    from .models import TRL_LEVELS
    
    # SECURITY: Check authorization before loading data
    funding_search = get_object_or_404(FundingSearch, id=id)
    
    # Check if user has permission to view (owner or admin)
    if request.user != funding_search.user and not request.user.admin:
        messages.error(request, 'You do not have permission to view this funding search.')
        return redirect('companies:list')
    
    can_edit = request.user == funding_search.user or request.user.admin
    
    if request.method == 'POST':
        if not can_edit:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                from django.http import JsonResponse
                return JsonResponse({'error': 'You do not have permission to edit this funding search.'}, status=403)
            messages.error(request, 'You do not have permission to edit this funding search.')
            return redirect('companies:funding_search_detail', id=id)
        
        # SECURITY: Use explicit allowlist to prevent mass assignment
        # Only allow specific fields to be updated
        allowed_fields = []
        
        # Validate and update name (max 255 chars)
        name = request.POST.get('name', '').strip()
        if name:
            if len(name) > 255:
                messages.error(request, 'Name must be 255 characters or less.')
                return redirect('companies:funding_search_detail', id=id)
            funding_search.name = name
            allowed_fields.append('name')
        
        # Validate and update notes (max 10000 chars)
        notes = request.POST.get('notes', '').strip()
        if notes is not None:  # Allow empty notes
            if len(notes) > 10000:
                messages.error(request, 'Notes must be 10000 characters or less.')
                return redirect('companies:funding_search_detail', id=id)
            funding_search.notes = notes
            allowed_fields.append('notes')
        
        # Get "Let system decide TRL" checkbox
        # Only update if it's in the POST data (preserve existing value if not)
        if 'let_system_decide_trl' in request.POST:
            funding_search.let_system_decide_trl = request.POST.get('let_system_decide_trl') == 'on'
            allowed_fields.append('let_system_decide_trl')
        
        # SECURITY: Validate TRL levels against allowed choices
        # Only update TRL levels if they're in the POST data or if we're updating let_system_decide_trl
        if 'trl_levels' in request.POST or 'let_system_decide_trl' in request.POST:
            if not funding_search.let_system_decide_trl:
                trl_levels = request.POST.getlist('trl_levels')  # getlist for multiple values
                trl_levels = [level for level in trl_levels if level]  # Remove empty values
                
                # Validate each TRL level against allowed choices
                valid_trl_values = [choice[0] for choice in TRL_LEVELS]
                validated_trl_levels = []
                for level in trl_levels:
                    if level in valid_trl_values:
                        validated_trl_levels.append(level)
                    else:
                        messages.error(request, f'Invalid TRL level: {level}')
                        return redirect('companies:funding_search_detail', id=id)
                
                funding_search.trl_levels = validated_trl_levels
            else:
                # Clear TRL levels if letting system decide
                funding_search.trl_levels = []
            allowed_fields.append('trl_levels')
        
        # SECURITY: Validate grant sources against allowed sources
        grant_sources = request.POST.getlist('grant_sources')  # getlist for multiple values
        grant_sources = [source for source in grant_sources if source]  # Remove empty values
        
        # Validate each grant source
        valid_source_codes = [source[0] for source in GRANT_SOURCES]
        validated_grant_sources = []
        for source in grant_sources:
            if source in valid_source_codes:
                validated_grant_sources.append(source)
            else:
                messages.error(request, f'Invalid grant source: {source}')
                return redirect('companies:funding_search_detail', id=id)
        
        funding_search.selected_grant_sources = validated_grant_sources if validated_grant_sources else []
        allowed_fields.append('selected_grant_sources')
        
        # Get "Exclude closed competitions" checkbox
        funding_search.exclude_closed_competitions = request.POST.get('exclude_closed_competitions') == 'on'
        allowed_fields.append('exclude_closed_competitions')
        
        # Get checklist assessment checkboxes
        funding_search.assess_exclusions = request.POST.get('assess_exclusions') == 'on'
        allowed_fields.append('assess_exclusions')
        
        funding_search.assess_eligibility = request.POST.get('assess_eligibility') == 'on'
        allowed_fields.append('assess_eligibility')
        
        funding_search.assess_competitiveness = request.POST.get('assess_competitiveness') == 'on'
        allowed_fields.append('assess_competitiveness')
        
        # SECURITY: Only save explicitly allowed fields
        funding_search.save(update_fields=allowed_fields)
        
        # If AJAX request, return JSON response instead of redirecting
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            from django.http import JsonResponse
            return JsonResponse({'success': True, 'message': 'Funding search updated successfully.'})
        
        messages.success(request, 'Funding search updated successfully.')
        return redirect('companies:funding_search_detail', id=id)
    
    # Get match results (all results, no limit - for debugging and quality assurance)
    match_results = list(GrantMatchResult.objects.filter(
        funding_search=funding_search
    ).select_related('grant').order_by('-match_score', '-matched_at'))
    
    # Separate grants into three groups: excluded, not eligible, and eligible (main results)
    from django.utils import timezone
    excluded_grants = []
    not_eligible_grants = []
    eligible_grants = []
    
    for match in match_results:
        # Check if grant is excluded: exclusions_score < 1.0 means at least one "yes" (exclusion applies)
        # Excluded grants take precedence - they go to excluded section regardless of eligibility
        is_excluded = False
        if match.exclusions_score is not None and match.exclusions_score < 1.0:
            is_excluded = True
        elif match.match_score == 0.0 and match.exclusions_score is not None and match.exclusions_score < 1.0:
            # Also check if match_score is 0 and exclusions were assessed with at least one "yes"
            is_excluded = True
        
        if is_excluded:
            excluded_grants.append(match)
        else:
            # Check if grant has any eligibility "no" items (not eligible)
            match_reasons = match.match_reasons or {}
            eligibility_checklist = match_reasons.get('eligibility_checklist', [])
            has_eligibility_no = any(
                item.get('status') == 'no' 
                for item in eligibility_checklist 
                if isinstance(item, dict)
            )
            
            if has_eligibility_no:
                not_eligible_grants.append(match)
            else:
                eligible_grants.append(match)
    
    # Sort eligible grants by match_score descending
    eligible_grants.sort(key=lambda x: (x.match_score or 0, x.matched_at or timezone.now()), reverse=True)
    
    # Sort not eligible grants by match_score descending
    not_eligible_grants.sort(key=lambda x: (x.match_score or 0, x.matched_at or timezone.now()), reverse=True)
    
    # Sort excluded grants by match_score descending (they'll all be 0, but preserve order)
    excluded_grants.sort(key=lambda x: (x.match_score or 0, x.matched_at or timezone.now()), reverse=True)
    
    # Keep eligible grants as main results
    match_results = eligible_grants
    
    # Convert checklist data to JSON strings for pie charts
    import json
    match_results_with_json = []
    for match in match_results:
        match_reasons = match.match_reasons or {}
        # Get certainty from match_reasons if available, otherwise calculate it
        certainty = match_reasons.get('certainty')
        if certainty is None:
            # Calculate certainty from checklist items
            certainty = match.calculate_certainty() if hasattr(match, 'calculate_certainty') else None
        
        # Determine if this grant is excluded
        # exclusions_score < 1.0 means at least one "yes" (exclusion applies)
        is_excluded = False
        if match.exclusions_score is not None and match.exclusions_score < 1.0:
            is_excluded = True
        elif match.match_score == 0.0 and match.exclusions_score is not None and match.exclusions_score < 1.0:
            is_excluded = True
        
        match_dict = {
            'match': match,
            'eligibility_json': json.dumps(match_reasons.get('eligibility_checklist', [])),
            'competitiveness_json': json.dumps(match_reasons.get('competitiveness_checklist', [])),
            'exclusions_json': json.dumps(match_reasons.get('exclusions_checklist', [])),
            'certainty': certainty,  # Include certainty for frontend use
            'is_excluded': is_excluded,  # Flag for template
        }
        match_results_with_json.append(match_dict)
    
    # Convert not eligible grants to JSON format
    not_eligible_grants_with_json = []
    for match in not_eligible_grants:
        match_reasons = match.match_reasons or {}
        certainty = match_reasons.get('certainty')
        if certainty is None:
            certainty = match.calculate_certainty() if hasattr(match, 'calculate_certainty') else None
        
        match_dict = {
            'match': match,
            'eligibility_json': json.dumps(match_reasons.get('eligibility_checklist', [])),
            'competitiveness_json': json.dumps(match_reasons.get('competitiveness_checklist', [])),
            'exclusions_json': json.dumps(match_reasons.get('exclusions_checklist', [])),
            'certainty': certainty,
            'is_excluded': False,  # Not excluded, but not eligible
        }
        not_eligible_grants_with_json.append(match_dict)
    
    # Convert excluded grants to JSON format
    excluded_grants_with_json = []
    for match in excluded_grants:
        match_reasons = match.match_reasons or {}
        certainty = match_reasons.get('certainty')
        if certainty is None:
            certainty = match.calculate_certainty() if hasattr(match, 'calculate_certainty') else None
        
        match_dict = {
            'match': match,
            'eligibility_json': json.dumps(match_reasons.get('eligibility_checklist', [])),
            'competitiveness_json': json.dumps(match_reasons.get('competitiveness_checklist', [])),
            'exclusions_json': json.dumps(match_reasons.get('exclusions_checklist', [])),
            'certainty': certainty,
            'is_excluded': True,
        }
        excluded_grants_with_json.append(match_dict)
    
    # Get all uploaded files for this funding search
    uploaded_files = funding_search.uploaded_files.all().order_by('-created_at')
    uploaded_files_count = uploaded_files.count()
    
    # Legacy: Extract just the filename from the old uploaded_file field (for backward compatibility)
    uploaded_file_name = None
    has_legacy_file = False
    if funding_search.uploaded_file:
        uploaded_file_name = os.path.basename(funding_search.uploaded_file.name)
        has_legacy_file = True
    
    total_attachments_count = uploaded_files_count + (1 if has_legacy_file else 0)
    
    # Tab selection
    allowed_tabs = ['setup', 'preflight', 'results', 'settings']
    current_tab = request.GET.get('tab', 'setup')
    if current_tab not in allowed_tabs:
        current_tab = 'setup'
    
    # View selection (list or grid) - only for results tab
    allowed_views = ['list', 'grid']
    current_view = request.GET.get('view', 'list')
    if current_view not in allowed_views:
        current_view = 'list'
    
    # Get user's questionnaires for applying to funding search
    questionnaires = []
    if can_edit:
        questionnaires = FundingQuestionnaire.objects.filter(
            user=request.user
        ).order_by('-is_default', '-updated_at')
    
    context = {
        'funding_search': funding_search,
        'can_edit': can_edit,
        'trl_levels': TRL_LEVELS,
        'grant_sources': GRANT_SOURCES,
        'match_results': match_results,
        'match_results_with_json': match_results_with_json,
        'not_eligible_grants_with_json': not_eligible_grants_with_json,
        'excluded_grants_with_json': excluded_grants_with_json,
        'uploaded_files': uploaded_files,
        'uploaded_file_name': uploaded_file_name,
        'total_attachments_count': total_attachments_count,
        'current_tab': current_tab,
        'current_view': current_view,
        'questionnaires': questionnaires,
    }
    return render(request, 'companies/funding_search_detail.html', context)


@login_required
@require_POST
def funding_search_preflight(request, id):
    """
    Run pre-flight checks on the input material for a funding search.
    This does NOT run matching – it only assesses input quality and stores a JSON summary.
    """
    import datetime
    import logging

    logger = logging.getLogger(__name__)
    logger.info(f"Pre-flight check requested for funding search {id} by user {request.user.id}")

    try:
        funding_search = get_object_or_404(FundingSearch, id=id)
        logger.info(f"Funding search {id} found, starting pre-flight checks...")

        # Check permissions (owner or admin)
        if request.user != funding_search.user and not request.user.admin:
            messages.error(request, "You do not have permission to run pre-flight checks for this funding search.")
            return redirect(reverse("companies:funding_search_detail", args=[id]) + "?tab=preflight")

        # Reuse compile_input_sources_text to get combined project text
        try:
            project_text = funding_search.compile_input_sources_text()
        except Exception as e:
            logger.warning(f"Error compiling input sources for funding search {id}: {str(e)}", exc_info=True)
            project_text = ""
        
        total_word_count = len(project_text.split()) if project_text else 0
        
        if not project_text or len(project_text.strip()) == 0:
            logger.warning(f"No input text found for funding search {id}")
            messages.warning(request, "No input sources available to assess. Please add a questionnaire, project description, company notes, or files.")
            return redirect(reverse("companies:funding_search_detail", args=[id]) + "?tab=preflight")

        # Initialize ChatGPT service
        try:
            matcher = ChatGPTMatchingService()
            logger.info("ChatGPTMatchingService initialized for pre-flight check")
        except GrantMatchingError as e:
            logger.error(f"Failed to initialize ChatGPT service: {e}", exc_info=True)
            messages.error(request, "Pre-flight check service is not available. Please check configuration.")
            return redirect(reverse("companies:funding_search_detail", args=[id]) + "?tab=preflight")

        # Create prompt for pre-flight assessment
        preflight_prompt = f"""Analyze the following project input material and provide a comprehensive quality assessment, including Technology Readiness Level (TRL) assessment.

PROJECT INPUT MATERIAL:
{project_text[:15000]}

Please provide a JSON assessment with the following structure:
{{
    "summary": {{
        "overall_score": <0-100>,
        "overall_grade": "<A-F>",
        "readiness_level": "<excellent|good|fair|poor>",
        "readiness_description": "<brief description>",
        "estimated_match_quality": "<high|medium|low>"
    }},
    "dimension_scores": {{
        "coverage": {{"score": <0-100>, "grade": "<A-F>", "description": "<text>"}},
        "clarity": {{"score": <0-100>, "grade": "<A-F>", "description": "<text>"}},
        "specificity": {{"score": <0-100>, "grade": "<A-F>", "description": "<text>"}},
        "completeness": {{"score": <0-100>, "grade": "<A-F>", "description": "<text>"}},
        "relevance": {{"score": <0-100>, "grade": "<A-F>", "description": "<text>"}}
    }},
    "critical_checks": {{
        "has_problem_statement": {{"passed": <true|false>, "severity": "<critical|high|medium>", "message": "<text>"}},
        "has_funding_amount": {{"passed": <true|false>, "severity": "<critical|high|medium>", "message": "<text>"}},
        "has_target_market": {{"passed": <true|false>, "severity": "<critical|high|medium>", "message": "<text>"}}
    }},
    "recommendations": {{
        "critical": [{{"id": "<id>", "priority": "critical", "title": "<text>"}}],
        "high": [{{"id": "<id>", "priority": "high", "title": "<text>"}}]
    }},
    "trl_assessment": {{
        "assessed_trl_level": "<TRL 1|TRL 2|...|TRL 9|unknown>",
        "trl_level_number": <1-9 or null>,
        "confidence": "<high|medium|low>",
        "reasoning": "<brief explanation of why this TRL level was assessed>",
        "is_technology_focused": <true|false>,
        "indicators": ["<indicator1>", "<indicator2>"]
    }},
    "strengths": ["<strength1>", "<strength2>"],
    "warnings": ["<warning1>", "<warning2>"]
}}

Assess:
- Coverage: How well does the material cover key areas (problem, solution, impact, market)?
- Clarity: How clear and understandable is the information?
- Specificity: How specific are the details (funding amounts, timelines, requirements)?
- Completeness: How complete is the information (are critical pieces missing)?
- Relevance: How relevant is the information to grant matching?

TRL Assessment:
Assess the Technology Readiness Level (TRL) of the project based on the input material:
- TRL 1-3 (Early Stage): Basic principles observed, concept formulated, proof of concept. Look for keywords: "concept", "idea", "research", "feasibility", "proof of concept", "early stage", "theoretical", "exploratory", "discovery"
- TRL 4-6 (Prototype Stage): Technology validated in lab, validated in relevant environment, demonstrated in relevant environment. Look for keywords: "prototype", "demonstration", "validation", "laboratory", "testing", "development", "pilot testing", "proof of principle"
- TRL 7-9 (Commercialization): System prototype in operational environment, system complete and qualified, actual system proven in operational environment. Look for keywords: "pilot", "deployment", "commercialization", "market ready", "scale up", "production", "launch", "rollout", "market entry"
- If the project is clearly technology-focused but the TRL level cannot be determined from the material, set assessed_trl_level to "unknown" and provide reasoning.
- If the project is not technology-focused (e.g., pure service, consulting, non-technical), set is_technology_focused to false and assessed_trl_level to "unknown".
- Extract specific indicators from the text that support your TRL assessment (e.g., "prototype developed", "market ready", "proof of concept").

Provide actionable recommendations for improvement. Return only valid JSON."""

        # Call ChatGPT API
        import json
        import asyncio
        
        try:
            async def get_preflight_assessment():
                response = await matcher.async_client.chat.completions.create(
                    model=matcher.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are an expert at assessing grant application materials. Always respond with valid JSON only, no additional text."
                        },
                        {"role": "user", "content": preflight_prompt}
                    ],
                    temperature=0.3,
                    response_format={"type": "json_object"},
                    max_tokens=2500,
                )
                return response.choices[0].message.content
            
            # Run async function
            logger.info(f"Calling ChatGPT API for pre-flight assessment of funding search {id}...")
            response_content = asyncio.run(get_preflight_assessment())
            
            if not response_content:
                raise GrantMatchingError("Empty response from ChatGPT API")
            
            result = json.loads(response_content)
            logger.info(f"ChatGPT API response received for funding search {id}")
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse ChatGPT response for pre-flight check: {e}", exc_info=True)
            logger.error(f"Response content: {response_content[:500] if 'response_content' in locals() else 'N/A'}")
            messages.error(request, "Pre-flight check completed but response format was invalid. Please try again.")
            return redirect(reverse("companies:funding_search_detail", args=[id]) + "?tab=preflight")
        except GrantMatchingError as e:
            logger.error(f"ChatGPT API error during pre-flight check: {e}", exc_info=True)
            messages.error(request, f"Pre-flight check failed: {str(e)}")
            return redirect(reverse("companies:funding_search_detail", args=[id]) + "?tab=preflight")
        except Exception as e:
            logger.error(f"Unexpected error during pre-flight check: {e}", exc_info=True)
            messages.error(request, f"An unexpected error occurred during pre-flight check: {str(e)}")
            return redirect(reverse("companies:funding_search_detail", args=[id]) + "?tab=preflight")

        # Add metadata and statistics
        now_iso = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        questionnaire = funding_search.questionnaire
        
        result["version"] = "1.0"
        result["checked_at"] = now_iso
        result["checked_by"] = request.user.email
        
        # Ensure all required fields exist with defaults
        if "summary" not in result:
            result["summary"] = {
                "overall_score": 0,
                "overall_grade": "F",
                "readiness_level": "poor",
                "readiness_description": "Assessment incomplete",
                "estimated_match_quality": "low"
            }
        if "dimension_scores" not in result:
            result["dimension_scores"] = {
                "coverage": {"score": 0, "grade": "F", "description": "Not assessed"},
                "clarity": {"score": 0, "grade": "F", "description": "Not assessed"},
                "specificity": {"score": 0, "grade": "F", "description": "Not assessed"},
                "completeness": {"score": 0, "grade": "F", "description": "Not assessed"},
                "relevance": {"score": 0, "grade": "F", "description": "Not assessed"}
            }
        if "recommendations" not in result:
            result["recommendations"] = {"critical": [], "high": []}
        if "strengths" not in result:
            result["strengths"] = []
        if "warnings" not in result:
            result["warnings"] = []
        if "critical_checks" not in result:
            result["critical_checks"] = {}
        if "trl_assessment" not in result:
            result["trl_assessment"] = {
                "assessed_trl_level": "unknown",
                "trl_level_number": None,
                "confidence": "low",
                "reasoning": "TRL assessment not available",
                "is_technology_focused": False,
                "indicators": []
            }
        else:
            # Ensure TRL assessment has all required fields
            trl_assessment = result["trl_assessment"]
            if "assessed_trl_level" not in trl_assessment:
                trl_assessment["assessed_trl_level"] = "unknown"
            if "trl_level_number" not in trl_assessment:
                trl_assessment["trl_level_number"] = None
            if "confidence" not in trl_assessment:
                trl_assessment["confidence"] = "low"
            if "reasoning" not in trl_assessment:
                trl_assessment["reasoning"] = "No reasoning provided"
            if "is_technology_focused" not in trl_assessment:
                trl_assessment["is_technology_focused"] = False
            if "indicators" not in trl_assessment:
                trl_assessment["indicators"] = []
        
        # Ensure dimension_scores have all required sub-fields
        for dimension in ["coverage", "clarity", "specificity", "completeness", "relevance"]:
            if dimension not in result["dimension_scores"]:
                result["dimension_scores"][dimension] = {"score": 0, "grade": "F", "description": "Not assessed"}
            else:
                # Ensure each dimension has required fields
                dim = result["dimension_scores"][dimension]
                if "score" not in dim:
                    dim["score"] = 0
                if "grade" not in dim:
                    dim["grade"] = "F"
                if "description" not in dim:
                    dim["description"] = "Not assessed"
        
        result["metadata"] = {
            "assessment_method": "chatgpt_api",
            "model_version": matcher.model,
            "input_sources_analyzed": ["questionnaire", "project_description", "company_website", "company_grant_history"]
        }
        
        # Calculate grant history word count
        grant_history_word_count = 0
        if funding_search.use_company_grant_history and funding_search.company.grants_received_360:
            grants = funding_search.company.grants_received_360.get('grants', [])
            for grant in grants:
                if grant.get('title'):
                    grant_history_word_count += len(grant['title'].split())
                if grant.get('description'):
                    grant_history_word_count += len(grant['description'].split())
        
        result["statistics"] = {
            "total_word_count": total_word_count,
            "total_sources": 4,
            "sources_with_content": sum([
                bool(questionnaire and questionnaire.questionnaire_data),
                bool(funding_search.project_description),
                bool(funding_search.company.website),
                bool(funding_search.use_company_grant_history and funding_search.company.grants_received_360 and funding_search.company.grants_received_360.get('grants')),
            ]),
        }
        
        # Add source breakdown if not present
        if "source_breakdown" not in result:
            questionnaire_data = questionnaire.questionnaire_data if (questionnaire and questionnaire.questionnaire_data) else {}
            questionnaire_word_count = 0
            if questionnaire_data:
                for key, value in questionnaire_data.items():
                    if isinstance(value, str):
                        questionnaire_word_count += len(value.split())
            
            result["source_breakdown"] = {
                "questionnaire": {
                    "present": bool(questionnaire_data),
                    "word_count": questionnaire_word_count,
                },
                "project_description": {
                    "present": bool(funding_search.project_description),
                },
                "company_website": {
                    "present": bool(funding_search.company.website),
                    "enabled": funding_search.use_company_website,
                },
                "company_grant_history": {
                    "present": bool(funding_search.company.grants_received_360 and funding_search.company.grants_received_360.get('grants')),
                    "enabled": funding_search.use_company_grant_history,
                    "count": len(funding_search.company.grants_received_360.get('grants', [])) if funding_search.company.grants_received_360 else 0,
                    "word_count": grant_history_word_count,
                },
            }

        funding_search.preflight_result = result
        funding_search.save(update_fields=["preflight_result"])
        
        overall_score = result.get("summary", {}).get("overall_score", 0)
        logger.info(f"Pre-flight checks completed for funding search {id}. Overall score: {overall_score}")

        messages.success(request, "Pre-flight checks completed.")
        return redirect(reverse("companies:funding_search_detail", args=[id]) + "?tab=preflight")
    
    except Exception as e:
        logger.error(f"Error running pre-flight checks for funding search {id}: {str(e)}", exc_info=True)
        messages.error(request, f"An error occurred while running pre-flight checks: {str(e)}")
        return redirect(reverse("companies:funding_search_detail", args=[id]) + "?tab=preflight")


@login_required
def funding_search_download_report(request, id):
    """Generate and download a PDF report of all grant matches for a funding search."""
    from datetime import datetime
    
    # SECURITY: Check authorization before loading data
    funding_search = get_object_or_404(FundingSearch, id=id)
    
    # Check if user has permission to view (owner or admin)
    if request.user != funding_search.user and not request.user.admin:
        messages.error(request, 'You do not have permission to view this funding search.')
        return redirect('companies:list')
    
    # Get match results (all results, no limit - for debugging and quality assurance)
    match_results = list(GrantMatchResult.objects.filter(
        funding_search=funding_search
    ).select_related('grant').order_by('-match_score', '-matched_at'))
    
    # Explicitly sort by match_score descending as a safety measure
    # This ensures correct ordering even if database query doesn't preserve it
    from django.utils import timezone
    match_results.sort(key=lambda x: (x.match_score or 0, x.matched_at or timezone.now()), reverse=True)
    
    # Create the HttpResponse object with PDF headers
    response = HttpResponse(content_type='application/pdf')
    filename = f"grant_matches_{funding_search.name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    # Create the PDF object
    doc = SimpleDocTemplate(response, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
    
    # Container for the 'Flowable' objects
    elements = []
    
    # Define styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#1e40af'),
        spaceAfter=12,
        alignment=TA_LEFT,
    )
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#1e40af'),
        spaceAfter=8,
        spaceBefore=12,
    )
    normal_style = styles['Normal']
    normal_style.fontSize = 10
    normal_style.leading = 14
    
    # Title
    elements.append(Paragraph(f"Grant Matching Report: {funding_search.name}", title_style))
    elements.append(Spacer(1, 0.2*inch))
    
    # Company and search info
    elements.append(Paragraph(f"<b>Company:</b> {funding_search.company.name}", normal_style))
    elements.append(Paragraph(f"<b>Created:</b> {funding_search.created_at.strftime('%B %d, %Y at %I:%M %p')}", normal_style))
    if funding_search.last_matched_at:
        elements.append(Paragraph(f"<b>Last Matched:</b> {funding_search.last_matched_at.strftime('%B %d, %Y at %I:%M %p')}", normal_style))
    match_results_list = list(match_results)
    elements.append(Paragraph(f"<b>Total Matches:</b> {len(match_results_list)}", normal_style))
    elements.append(Spacer(1, 0.3*inch))
    
    # Grant matches
    if match_results_list:
        for idx, match in enumerate(match_results_list, 1):
            grant = match.grant
            
            # Grant title and score
            elements.append(Paragraph(f"<b>{idx}. {grant.title}</b>", heading_style))
            
            # Score information
            score_info = f"Match Score: {match.match_score:.1%}"
            if match.eligibility_score is not None:
                score_info += f" | Eligibility: {match.eligibility_score:.1%}"
            if match.competitiveness_score is not None:
                score_info += f" | Competitiveness: {match.competitiveness_score:.1%}"
            elements.append(Paragraph(score_info, normal_style))
            
            # Grant details
            grant_details = []
            grant_details.append(f"<b>Source:</b> {grant.get_source_display()}")
            grant_details.append(f"<b>Status:</b> {grant.computed_status.title()}")
            if grant.opening_date:
                grant_details.append(f"<b>Opening Date:</b> {grant.opening_date.strftime('%B %d, %Y')}")
            if grant.deadline:
                grant_details.append(f"<b>Closing Date:</b> {grant.deadline.strftime('%B %d, %Y')}")
            elif grant.deadline is None and grant.computed_status == 'open':
                grant_details.append(f"<b>Closing Date:</b> Open - no closing date")
            
            elements.append(Paragraph(" | ".join(grant_details), normal_style))
            
            # Summary sections
            match_reasons = match.match_reasons or {}
            if match_reasons.get('project_type_and_trl_focus') or match_reasons.get('why_it_matches') or match_reasons.get('key_risks_and_uncertainties'):
                elements.append(Spacer(1, 0.1*inch))
                if match_reasons.get('project_type_and_trl_focus'):
                    elements.append(Paragraph(f"<b>Project type and TRL focus:</b> {match_reasons.get('project_type_and_trl_focus', '')}", normal_style))
                    elements.append(Spacer(1, 0.05*inch))
                if match_reasons.get('why_it_matches'):
                    elements.append(Paragraph(f"<b>Why it matches:</b> {match_reasons.get('why_it_matches', '')}", normal_style))
                    elements.append(Spacer(1, 0.05*inch))
                if match_reasons.get('key_risks_and_uncertainties'):
                    elements.append(Paragraph(f"<b>Key risks and uncertainties:</b> {match_reasons.get('key_risks_and_uncertainties', '')}", normal_style))
            elif match_reasons.get('explanation'):
                # Fallback to old explanation format for backward compatibility
                elements.append(Spacer(1, 0.1*inch))
                elements.append(Paragraph(f"<b>Summary:</b> {match_reasons.get('explanation', '')}", normal_style))
            
            # Checklists
            match_reasons = match.match_reasons or {}
            if match_reasons.get('eligibility_checklist') or match_reasons.get('competitiveness_checklist') or match_reasons.get('exclusions_checklist'):
                elements.append(Spacer(1, 0.15*inch))
                checklist_heading = ParagraphStyle(
                    'ChecklistHeading',
                    parent=styles['Heading3'],
                    fontSize=11,
                    textColor=colors.HexColor('#4b5563'),
                    spaceAfter=6,
                    spaceBefore=8,
                )
                checklist_item_style = ParagraphStyle(
                    'ChecklistItem',
                    parent=normal_style,
                    fontSize=9,
                    leftIndent=20,
                    spaceAfter=4,
                )
                
                # Eligibility Checklist
                if match_reasons.get('eligibility_checklist'):
                    elements.append(Paragraph("<b>Eligibility Checklist</b>", checklist_heading))
                    for item in match_reasons.get('eligibility_checklist', []):
                        status = item.get('status', '')
                        if status == 'yes':
                            status_symbol = '<font color="green">✓</font>'
                        elif status == 'no':
                            status_symbol = '<font color="red">✗</font>'
                        else:
                            status_symbol = '<font color="orange">?</font>'
                        criterion = item.get('criterion', '')
                        reason = item.get('reason', '')
                        checklist_text = f"{status_symbol} {criterion}"
                        if reason:
                            checklist_text += f"<br/><i>{reason}</i>"
                        elements.append(Paragraph(checklist_text, checklist_item_style))
                    elements.append(Spacer(1, 0.1*inch))
                
                # Competitiveness Checklist
                if match_reasons.get('competitiveness_checklist'):
                    elements.append(Paragraph("<b>Competitiveness Checklist</b>", checklist_heading))
                    for item in match_reasons.get('competitiveness_checklist', []):
                        status = item.get('status', '')
                        if status == 'yes':
                            status_symbol = '<font color="green">✓</font>'
                        elif status == 'no':
                            status_symbol = '<font color="red">✗</font>'
                        else:
                            status_symbol = '<font color="orange">?</font>'
                        criterion = item.get('criterion', '')
                        reason = item.get('reason', '')
                        checklist_text = f"{status_symbol} {criterion}"
                        if reason:
                            checklist_text += f"<br/><i>{reason}</i>"
                        elements.append(Paragraph(checklist_text, checklist_item_style))
                    elements.append(Spacer(1, 0.1*inch))
                
                # Exclusions Checklist
                if match_reasons.get('exclusions_checklist'):
                    elements.append(Paragraph("<b>Exclusions Checklist</b>", checklist_heading))
                    for item in match_reasons.get('exclusions_checklist', []):
                        # For exclusions: ✓ means exclusion does NOT apply (good), ✗ means it DOES apply (bad)
                        status = item.get('status', '')
                        if status == 'no':
                            status_symbol = '<font color="green">✓</font>'
                        elif status == 'yes':
                            status_symbol = '<font color="red">✗</font>'
                        else:
                            status_symbol = '<font color="orange">?</font>'
                        criterion = item.get('criterion', '')
                        reason = item.get('reason', '')
                        checklist_text = f"{status_symbol} {criterion}"
                        if reason:
                            checklist_text += f"<br/><i>{reason}</i>"
                        elements.append(Paragraph(checklist_text, checklist_item_style))
            
            # Add spacing between grants
            if idx < len(match_results):
                elements.append(Spacer(1, 0.3*inch))
                elements.append(PageBreak())
    else:
        elements.append(Paragraph("No grant matches found.", normal_style))
    
    # Build PDF
    doc.build(elements)
    
    return response


@login_required
def edit_checklist_item(request, match_id):
    """Edit a checklist item status manually."""
    import json
    
    if request.method != 'POST':
        from django.http import JsonResponse
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    # Get the match result
    match_result = get_object_or_404(GrantMatchResult, id=match_id)
    
    # Check if user has permission (owner of funding search or admin)
    if request.user != match_result.funding_search.user and not request.user.admin:
        from django.http import JsonResponse
        return JsonResponse({'error': 'You do not have permission to edit this checklist.'}, status=403)
    
    # SECURITY: Parse JSON with size limits
    from grants_aggregator.security_utils import safe_json_loads
    data, error_response = safe_json_loads(request)
    if error_response:
        return error_response
    try:
        checklist_type = data.get('checklist_type')  # 'eligibility', 'competitiveness', or 'exclusions'
        item_index = data.get('item_index')
        new_status = data.get('status')  # 'yes', 'no', or 'unknown'
        
        if checklist_type not in ['eligibility', 'competitiveness', 'exclusions']:
            from django.http import JsonResponse
            return JsonResponse({'error': 'Invalid checklist type'}, status=400)
        
        if new_status not in ['yes', 'no', 'unknown']:
            from django.http import JsonResponse
            return JsonResponse({'error': 'Invalid status'}, status=400)
        
        # Get the match_reasons
        match_reasons = match_result.match_reasons or {}
        checklist_key = f'{checklist_type}_checklist'
        checklist = match_reasons.get(checklist_key, [])
        
        if item_index < 0 or item_index >= len(checklist):
            from django.http import JsonResponse
            return JsonResponse({'error': 'Invalid item index'}, status=400)
        
        # Store original values if this is the first time editing
        if not checklist[item_index].get('manually_edited'):
            checklist[item_index]['original_status'] = checklist[item_index].get('status')
            checklist[item_index]['original_reason'] = checklist[item_index].get('reason')
        
        # Update the item
        checklist[item_index]['status'] = new_status
        checklist[item_index]['manually_edited'] = True
        
        # Save back to match_reasons
        match_reasons[checklist_key] = checklist
        match_result.match_reasons = match_reasons
        match_result.save()
        
        from django.http import JsonResponse
        return JsonResponse({'success': True})
        
    except Exception as e:
        from django.http import JsonResponse
        return JsonResponse({'error': str(e)}, status=400)


@login_required
def undo_checklist_item(request, match_id):
    """Undo a manual checklist edit and restore the original AI-generated values."""
    import json
    
    if request.method != 'POST':
        from django.http import JsonResponse
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    # Get the match result
    match_result = get_object_or_404(GrantMatchResult, id=match_id)
    
    # Check if user has permission (owner of funding search or admin)
    if request.user != match_result.funding_search.user and not request.user.admin:
        from django.http import JsonResponse
        return JsonResponse({'error': 'You do not have permission to undo this checklist edit.'}, status=403)
    
    # SECURITY: Parse JSON with size limits
    from grants_aggregator.security_utils import safe_json_loads
    data, error_response = safe_json_loads(request)
    if error_response:
        return error_response
    try:
        checklist_type = data.get('checklist_type')  # 'eligibility', 'competitiveness', or 'exclusions'
        item_index = data.get('item_index')
        
        if checklist_type not in ['eligibility', 'competitiveness', 'exclusions']:
            from django.http import JsonResponse
            return JsonResponse({'error': 'Invalid checklist type'}, status=400)
        
        # Get the match_reasons
        match_reasons = match_result.match_reasons or {}
        checklist_key = f'{checklist_type}_checklist'
        checklist = match_reasons.get(checklist_key, [])
        
        if item_index < 0 or item_index >= len(checklist):
            from django.http import JsonResponse
            return JsonResponse({'error': 'Invalid item index'}, status=400)
        
        # Check if item was manually edited
        if not checklist[item_index].get('manually_edited'):
            from django.http import JsonResponse
            return JsonResponse({'error': 'This item was not manually edited'}, status=400)
        
        # Restore original values
        original_status = checklist[item_index].get('original_status')
        original_reason = checklist[item_index].get('original_reason')
        
        if original_status is not None:
            checklist[item_index]['status'] = original_status
        if original_reason is not None:
            checklist[item_index]['reason'] = original_reason
        
        # Remove manual edit flags
        checklist[item_index]['manually_edited'] = False
        if 'original_status' in checklist[item_index]:
            del checklist[item_index]['original_status']
        if 'original_reason' in checklist[item_index]:
            del checklist[item_index]['original_reason']
        
        # Save back to match_reasons
        match_reasons[checklist_key] = checklist
        match_result.match_reasons = match_reasons
        match_result.save()
        
        from django.http import JsonResponse
        return JsonResponse({'success': True})
        
    except Exception as e:
        from django.http import JsonResponse
        return JsonResponse({'error': str(e)}, status=400)


@login_required
def funding_search_clear_results(request, id):
    """Clear all match results for a funding search."""
    import logging
    logger = logging.getLogger(__name__)
    
    # SECURITY: Check authorization before loading data
    funding_search = get_object_or_404(FundingSearch, id=id)
    
    # Check if user has permission to clear results (owner or admin)
    if request.user != funding_search.user and not request.user.admin:
        messages.error(request, 'You do not have permission to clear results for this funding search.')
        return redirect('companies:funding_search_detail', id=id)
    
    if request.method == 'POST':
        # Clear all match results for this funding search
        count = GrantMatchResult.objects.filter(funding_search=funding_search).delete()[0]
        logger.info(f"Cleared {count} match results for funding search {id}")
        result_text = "result" if count == 1 else "results"
        messages.success(request, f'Cleared {count} matching {result_text} successfully.')
    
    return redirect('companies:funding_search_detail', id=id)


@login_required
def funding_search_select_data(request, id):
    """Second step: Select company data to use for funding search."""
    # SECURITY: Check authorization before loading data
    funding_search = get_object_or_404(FundingSearch, id=id)
    
    # Check if user has permission to edit (owner or admin)
    if request.user != funding_search.user and not request.user.admin:
        messages.error(request, 'You do not have permission to edit this funding search.')
        return redirect('companies:funding_search_detail', id=id)
    
    company = funding_search.company
    
    if request.method == 'POST':
        # Get website selection
        funding_search.use_company_website = request.POST.get('use_company_website') == 'on'
        
        # Get grant history selection
        funding_search.use_company_grant_history = request.POST.get('use_company_grant_history') == 'on'
        
        funding_search.save()
        
        messages.success(request, 'Company data selected successfully.')
        return redirect('companies:funding_search_detail', id=id)
    
    # GET request - show selection form
    # Calculate grants count for display
    grants_count = 0
    if company.grants_received_360:
        grants = company.grants_received_360.get('grants', [])
        grants_count = len(grants) if grants else 0
    
    context = {
        'funding_search': funding_search,
        'company': company,
        'grants_count': grants_count,
    }
    return render(request, 'companies/funding_search_select_data.html', context)


@login_required
@require_POST
def funding_search_delete(request, id):
    """Delete funding search (owner or admin only)."""
    # SECURITY: Check authorization before loading data
    funding_search = get_object_or_404(FundingSearch, id=id)
    
    if request.user != funding_search.user and not request.user.admin:
        messages.error(request, 'You do not have permission to delete this funding search.')
        return redirect('companies:funding_search_detail', id=id)
    
        company_id = funding_search.company.id
        funding_search.delete()
        messages.success(request, 'Funding search deleted successfully.')
        return redirect('companies:detail', id=company_id)
    

@login_required
def funding_search_copy(request, id):
    """Copy funding search (owner or admin only)."""
    from django.core.files.base import ContentFile
    import os
    
    # SECURITY: Check authorization before loading data
    original = get_object_or_404(FundingSearch, id=id)
    
    if request.user != original.user and not request.user.admin:
        messages.error(request, 'You do not have permission to copy this funding search.')
        return redirect('companies:funding_search_detail', id=id)
    
    if request.method == 'POST':
        # Create new funding search with copied data
        new_name = f"{original.name} (copy)"
        
        # Create the new funding search (without file first)
        new_funding_search = FundingSearch.objects.create(
            company=original.company,
            user=original.user,
            name=new_name,
            notes=original.notes,
            trl_level=original.trl_level,
            trl_levels=original.trl_levels.copy() if original.trl_levels else [],
            project_description=original.project_description,
            file_type=original.file_type,
            use_company_website=original.use_company_website,
            use_company_grant_history=original.use_company_grant_history,
            selected_grant_sources=original.selected_grant_sources.copy() if original.selected_grant_sources else [],
            matching_status='pending',
            matching_progress={},
        )
        
        # Copy the uploaded file if it exists
        if original.uploaded_file:
            try:
                # Read the original file content
                original.uploaded_file.open('rb')
                file_content = original.uploaded_file.read()
                original.uploaded_file.close()
                
                # Create a new file with the same name
                new_funding_search.uploaded_file.save(
                    os.path.basename(original.uploaded_file.name),
                    ContentFile(file_content),
                    save=True
                )
            except Exception as e:
                # If file copying fails, continue without the file
                messages.warning(request, f'Funding search copied, but file could not be copied: {str(e)}')
        
        # Copy matching results
        if original.match_results.exists():
            for original_result in original.match_results.all():
                GrantMatchResult.objects.create(
                    funding_search=new_funding_search,
                    grant=original_result.grant,
                    match_score=original_result.match_score,
                    eligibility_score=original_result.eligibility_score,
                    competitiveness_score=original_result.competitiveness_score,
                    exclusions_score=original_result.exclusions_score,
                    match_reasons=original_result.match_reasons.copy() if original_result.match_reasons else {},
                )
            
            # Copy last_matched_at and set status to completed if results were copied
            new_funding_search.last_matched_at = original.last_matched_at
            new_funding_search.matching_status = 'completed'
            new_funding_search.save()
        
        messages.success(request, 'Funding search copied successfully.')
        return redirect('companies:funding_search_detail', id=new_funding_search.id)
    
    # GET request - show confirmation (optional, or just redirect)
    return redirect('companies:funding_search_detail', id=id)


def extract_text_from_file(file, file_type):
    """Extract text from uploaded file."""
    if file_type == 'pdf':
        try:
            import PyPDF2
            pdf_reader = PyPDF2.PdfReader(file)
            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
            return text.strip()
        except Exception as e:
            raise Exception(f"Error reading PDF: {str(e)}")
    
    elif file_type == 'docx':
        try:
            from docx import Document
            doc = Document(file)
            text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            return text.strip()
        except Exception as e:
            raise Exception(f"Error reading DOCX: {str(e)}")
    
    elif file_type == 'txt':
        try:
            file.seek(0)  # Reset file pointer
            text = file.read().decode('utf-8')
            return text.strip()
        except UnicodeDecodeError:
            try:
                file.seek(0)
                text = file.read().decode('latin-1')
                return text.strip()
            except Exception as e:
                raise Exception(f"Error reading text file: {str(e)}")
    
    else:
        raise Exception(f"Unsupported file type: {file_type}")


@login_required
@ratelimit(key='user_or_ip', rate='10/h', method='POST', block=True)
def funding_search_upload(request, id):
    """Handle file upload."""
    # SECURITY: Check authorization before loading data
    funding_search = get_object_or_404(FundingSearch, id=id)
    
    # Check if user has permission to edit (owner or admin)
    if request.user != funding_search.user and not request.user.admin:
        messages.error(request, 'You do not have permission to upload files for this funding search.')
        return redirect('companies:funding_search_detail', id=id)
    
    can_edit = True  # If we got here, user can edit
    
    if not can_edit:
        messages.error(request, 'You do not have permission to edit this funding search.')
        return redirect('companies:funding_search_detail', id=id)
    
    if request.method == 'POST':
        uploaded_file = request.FILES.get('file')
        
        if not uploaded_file:
            messages.error(request, 'No file provided.')
            return redirect('companies:funding_search_detail', id=id)
        
        # Validate file size (10MB max)
        if uploaded_file.size > 10 * 1024 * 1024:
            messages.error(request, 'File size exceeds 10MB limit.')
            return redirect('companies:funding_search_detail', id=id)
        
        # SECURITY: Sanitize filename to prevent path traversal and XSS
        import os
        import re
        original_filename = uploaded_file.name
        # Remove any path components
        safe_filename = os.path.basename(original_filename)
        # Remove any non-alphanumeric characters except dots, hyphens, underscores
        safe_filename = re.sub(r'[^a-zA-Z0-9._-]', '_', safe_filename)
        # Limit filename length
        if len(safe_filename) > 255:
            name, ext = os.path.splitext(safe_filename)
            safe_filename = name[:250] + ext
        
        # SECURITY: Validate file type by extension, MIME type, AND content
        file_name = safe_filename.lower()
        
        # Check extension first
        if file_name.endswith('.pdf'):
            expected_type = 'pdf'
            expected_mime_types = ['application/pdf']
        elif file_name.endswith('.docx'):
            expected_type = 'docx'
            expected_mime_types = ['application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'application/zip']
        elif file_name.endswith('.txt'):
            expected_type = 'txt'
            expected_mime_types = ['text/plain', 'text/plain; charset=utf-8', 'text/plain; charset=us-ascii']
        else:
            messages.error(request, 'Unsupported file type. Please upload PDF, DOCX, or TXT.')
            return redirect('companies:funding_search_detail', id=id)
        
        # SECURITY: Validate MIME type if provided
        content_type = uploaded_file.content_type
        if content_type and content_type not in expected_mime_types:
            # Allow if content_type is empty (some browsers don't send it)
            # But if it's provided and doesn't match, reject it
            messages.error(request, f'Invalid file type. Expected {expected_type.upper()} file.')
            return redirect('companies:funding_search_detail', id=id)
        
        # Validate content type (basic check)
        uploaded_file.seek(0)
        file_content = uploaded_file.read(1024)  # Read first 1KB for validation
        uploaded_file.seek(0)  # Reset for processing
        
        # Basic content validation
        if expected_type == 'pdf':
            # PDF files start with %PDF
            if not file_content.startswith(b'%PDF'):
                messages.error(request, 'Invalid PDF file. File content does not match PDF format.')
                return redirect('companies:funding_search_detail', id=id)
        elif expected_type == 'docx':
            # DOCX files are ZIP archives with specific structure
            if not file_content.startswith(b'PK\x03\x04'):  # ZIP file signature
                messages.error(request, 'Invalid DOCX file. File content does not match DOCX format.')
                return redirect('companies:funding_search_detail', id=id)
        elif expected_type == 'txt':
            # Try to decode as text to validate
            try:
                file_content.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    file_content.decode('latin-1')
                except UnicodeDecodeError:
                    messages.error(request, 'Invalid text file. File contains binary data.')
                    return redirect('companies:funding_search_detail', id=id)
        
        file_type = expected_type
        
        try:
            # SECURITY: Save file with sanitized filename
            # Update the file's name attribute before saving
            uploaded_file.name = safe_filename
            
            # Create FundingSearchFile instance for multiple file support
            funding_search_file = FundingSearchFile.objects.create(
                funding_search=funding_search,
                uploaded_by=request.user,
                file=uploaded_file,
                original_name=original_filename,
                file_type=file_type
            )
            
            messages.success(request, f'File uploaded successfully.')
        except Exception as e:
            messages.error(request, f'Error uploading file: {str(e)}')
    
    return redirect('companies:funding_search_detail', id=id)


@login_required
@require_POST
@ratelimit(key='user_or_ip', rate='20/h', method='POST', block=True)
def funding_search_delete_file(request, id):
    """Delete uploaded file from funding search (owner or admin only)."""
    # SECURITY: Check authorization before loading data
    funding_search = get_object_or_404(FundingSearch, id=id)
    
    # Check if user has permission to edit (owner or admin)
    if request.user != funding_search.user and not request.user.admin:
        messages.error(request, 'You do not have permission to delete files for this funding search.')
        return redirect('companies:funding_search_detail', id=id)
    
    # Get file_id from POST data (for new multiple file system)
    file_id = request.POST.get('file_id')
    
    if file_id:
        # Delete specific FundingSearchFile
        try:
            file_obj = get_object_or_404(FundingSearchFile, id=file_id, funding_search=funding_search)
            file_name = file_obj.original_name or file_obj.file.name
            file_obj.file.delete(save=False)
            file_obj.delete()
            messages.success(request, f'File "{file_name}" deleted successfully.')
        except Exception as e:
            messages.error(request, f'Error deleting file: {str(e)}')
    else:
        # Legacy: Delete old uploaded_file field if it exists
        if funding_search.uploaded_file:
            file_name = funding_search.uploaded_file.name
            funding_search.uploaded_file.delete(save=False)
            funding_search.uploaded_file = None
            funding_search.file_type = None
            funding_search.save()
            messages.success(request, f'File "{file_name}" deleted successfully.')
        else:
            messages.error(request, 'No file to delete.')
    
    return redirect('companies:funding_search_detail', id=id)


@login_required
def funding_search_match(request, id):
    """Trigger matching job."""
    import logging
    logger = logging.getLogger(__name__)
    
    # SECURITY: Check authorization before loading data
    funding_search = get_object_or_404(FundingSearch, id=id)
    
    # Check if user has permission to run matching (owner or admin)
    if request.user != funding_search.user and not request.user.admin:
        messages.error(request, 'You do not have permission to run matching for this funding search.')
        return redirect('companies:funding_search_detail', id=id)
    
    if request.method == 'POST':
        # Check if there are any input sources selected
        has_sources = (
            funding_search.use_company_website or
            funding_search.use_company_grant_history or
            funding_search.uploaded_file or
            funding_search.project_description
        )
        
        if not has_sources:
            logger.warning(f"Funding search {id} has no input sources")
            messages.error(request, 'Please select input sources (website, grant history) or add a project description first.')
            return redirect('companies:funding_search_detail', id=id)
        
        if funding_search.matching_status == 'running':
            logger.info(f"Funding search {id} matching already running")
            messages.info(request, 'Matching job is already running.')
            return redirect('companies:funding_search_detail', id=id)
        
        # Check if Celery is available
        logger.info(f"Checking Celery availability. CELERY_AVAILABLE={CELERY_AVAILABLE}, match_grants_with_chatgpt={match_grants_with_chatgpt}")
        if not CELERY_AVAILABLE or match_grants_with_chatgpt is None:
            logger.error(f"Celery not available for funding search {id}")
            messages.error(request, 'Background task service (Celery) is not available. Please check Redis connection.')
            return redirect('companies:funding_search_detail', id=id)
        
        # Set status to running immediately so progress section shows
        funding_search.matching_status = 'running'
        funding_search.matching_progress = {
            'current': 0,
            'total': 0,
            'percentage': 0,
            'stage': 'processing_sources',
            'stage_message': 'Processing input sources...'
        }
        funding_search.save()
        
        # Trigger Celery task
        try:
            logger.info(f"Triggering matching task for funding search {id}")
            task = match_grants_with_chatgpt.delay(funding_search.id)
            logger.info(f"Matching task queued successfully. Task ID: {task.id}")
            # Store task ID in progress for cancellation
            funding_search.matching_progress['task_id'] = task.id
            funding_search.save()
            messages.info(request, f'Matching job started (Task ID: {task.id}). Processing all grants... This may take 1-2 minutes.')
        except Exception as e:
            logger.error(f"Failed to trigger matching task for funding search {id}: {e}", exc_info=True)
            # Reset status if task failed to start
            funding_search.matching_status = 'pending'
            funding_search.matching_error = f'Failed to start matching job: {str(e)}'
            funding_search.save()
            messages.error(request, f'Failed to start matching job: {str(e)}')
    
    return redirect('companies:funding_search_detail', id=id)


@login_required
def funding_search_match_test(request, id):
    """Trigger test matching job (first 5 grants only)."""
    import logging
    logger = logging.getLogger(__name__)
    
    # SECURITY: Check authorization before loading data
    funding_search = get_object_or_404(FundingSearch, id=id)
    
    # Check if user has permission to run matching (owner or admin)
    if request.user != funding_search.user and not request.user.admin:
        messages.error(request, 'You do not have permission to run matching for this funding search.')
        return redirect('companies:funding_search_detail', id=id)
    
    if request.method == 'POST':
        # Check if there are any input sources selected
        has_sources = (
            funding_search.use_company_website or
            funding_search.use_company_grant_history or
            funding_search.uploaded_file or
            funding_search.project_description
        )
        
        if not has_sources:
            logger.warning(f"Funding search {id} has no input sources")
            messages.error(request, 'Please select input sources (website, grant history) or add a project description first.')
            return redirect('companies:funding_search_detail', id=id)
        
        if funding_search.matching_status == 'running':
            logger.info(f"Funding search {id} matching already running")
            messages.info(request, 'Matching job is already running.')
            return redirect('companies:funding_search_detail', id=id)
        
        # Check if Celery is available
        logger.info(f"Checking Celery availability. CELERY_AVAILABLE={CELERY_AVAILABLE}, match_grants_with_chatgpt={match_grants_with_chatgpt}")
        if not CELERY_AVAILABLE or match_grants_with_chatgpt is None:
            logger.error(f"Celery not available for funding search {id}")
            messages.error(request, 'Background task service (Celery) is not available. Please check Redis connection.')
            return redirect('companies:funding_search_detail', id=id)
        
        # Set status to running immediately so progress section shows
        funding_search.matching_status = 'running'
        funding_search.matching_progress = {
            'current': 0,
            'total': 0,
            'percentage': 0,
            'stage': 'processing_sources',
            'stage_message': 'Processing input sources...',
            'test_mode': True  # Flag to indicate this is a test run
        }
        funding_search.save()
        
        # Trigger Celery task with limit of 5 grants
        try:
            logger.info(f"Triggering test matching task for funding search {id} (5 grants)")
            task = match_grants_with_chatgpt.delay(funding_search.id, limit=5)
            logger.info(f"Test matching task queued successfully. Task ID: {task.id}")
            # Store task ID in progress for cancellation
            funding_search.matching_progress['task_id'] = task.id
            funding_search.save()
            messages.info(request, f'Test matching job started (Task ID: {task.id}). Processing first 5 grants for testing...')
        except Exception as e:
            logger.error(f"Failed to trigger test matching task for funding search {id}: {e}", exc_info=True)
            # Reset status if task failed to start
            funding_search.matching_status = 'pending'
            funding_search.matching_error = f'Failed to start test matching job: {str(e)}'
            funding_search.save()
            messages.error(request, f'Failed to start test matching job: {str(e)}')
    
    return redirect('companies:funding_search_detail', id=id)


@login_required
def funding_search_status(request, id):
    """API endpoint to get matching status and progress (for AJAX polling)."""
    from django.http import JsonResponse
    
    funding_search = get_object_or_404(FundingSearch, id=id)
    
    # Check if user has permission to view this funding search
    if request.user != funding_search.user and not request.user.admin:
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    progress = funding_search.matching_progress or {'current': 0, 'total': 0, 'percentage': 0}
    
    return JsonResponse({
        'status': funding_search.matching_status,
        'progress': progress,
        'error': funding_search.matching_error,
        'last_matched_at': funding_search.last_matched_at.isoformat() if funding_search.last_matched_at else None,
    })


@login_required
def funding_search_cancel(request, id):
    """Cancel a running matching job."""
    import logging
    logger = logging.getLogger(__name__)
    
    # SECURITY: Check authorization before loading data
    funding_search = get_object_or_404(FundingSearch, id=id)
    
    # Check if user has permission to cancel matching (owner or admin)
    if request.user != funding_search.user and not request.user.admin:
        messages.error(request, 'You do not have permission to cancel matching for this funding search.')
        return redirect('companies:funding_search_detail', id=id)
    
    if request.method == 'POST':
        if funding_search.matching_status != 'running':
            messages.info(request, 'No matching job is currently running.')
            return redirect('companies:funding_search_detail', id=id)
        
        # Try to revoke the Celery task if we have the task ID
        try:
            from celery.result import AsyncResult
            progress = funding_search.matching_progress or {}
            task_id = progress.get('task_id')
            
            if task_id:
                task = AsyncResult(task_id)
                task.revoke(terminate=True)
                logger.info(f"Cancelled Celery task {task_id} for funding search {id}")
        except Exception as e:
            logger.warning(f"Could not cancel Celery task for funding search {id}: {e}")
        
        # Update funding search status
        funding_search.matching_status = 'cancelled'
        funding_search.matching_error = 'Matching job cancelled by user.'
        funding_search.save()
        
        logger.info(f"Matching job cancelled for funding search {id}")
        messages.success(request, 'Matching job cancelled successfully.')
    
    return redirect('companies:funding_search_detail', id=id)


@login_required
def funding_search_select_company(request):
    """Select or create a company for a new funding search."""
    if request.method == 'POST':
        creation_mode = request.POST.get('creation_mode', 'registered')
        
        if creation_mode == 'manual':
            # Manual entry for unregistered companies
            name = request.POST.get('name', '').strip()
            
            if not name:
                messages.error(request, 'Company name is required.')
                return render(request, 'companies/funding_search_select_company.html', {'mode': 'manual'})
            
            # Check if company already exists for this user
            existing_company = Company.objects.filter(name__iexact=name, user=request.user).first()
            if existing_company:
                messages.info(request, f'Using existing company "{existing_company.name}".')
                return redirect('companies:funding_search_create', company_id=existing_company.id)
            
            # Generate unique company_number for unregistered companies
            import uuid
            from datetime import datetime
            unique_id = f"UNREG-{request.user.id}-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"
            
            # Ensure uniqueness
            while Company.objects.filter(company_number=unique_id).exists():
                unique_id = f"UNREG-{request.user.id}-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"
            
            # Build address from form fields
            address = {}
            if request.POST.get('address_line_1'):
                address = {
                    'address_line_1': request.POST.get('address_line_1', ''),
                    'address_line_2': request.POST.get('address_line_2', ''),
                    'locality': request.POST.get('locality', ''),
                    'postal_code': request.POST.get('postal_code', ''),
                    'country': request.POST.get('country', ''),
                }
            
            # Create unregistered company
            company = Company.objects.create(
                user=request.user,
                company_number=unique_id,
                name=name,
                is_registered=False,
                registration_status='unregistered',
                company_type=request.POST.get('company_type', ''),
                website=request.POST.get('website', '') or None,
                address=address,
                notes=request.POST.get('notes', ''),
            )
            
            messages.success(request, f'Company "{company.name}" created successfully.')
            return redirect('companies:funding_search_create', company_id=company.id)
        
        else:
            # Companies House API lookup
            company_number = request.POST.get('company_number', '').strip()
        
        if not company_number:
            messages.error(request, 'Company number is required.')
            return render(request, 'companies/funding_search_select_company.html')
        
        try:
            # Check if company already exists for this user
            existing_company = Company.objects.filter(company_number=company_number, user=request.user).first()
            if existing_company:
                messages.info(request, f'Using existing company "{existing_company.name}".')
                return redirect('companies:funding_search_create', company_id=existing_company.id)
            
            # Check if company exists but belongs to another user
            if Company.objects.filter(company_number=company_number).exists():
                messages.error(request, f'Company {company_number} already exists for another user. Please use a different company.')
                return render(request, 'companies/funding_search_select_company.html')
            
            # Fetch from Companies House API
            api_data = CompaniesHouseService.fetch_company(company_number)
            
            # Fetch filing history
            try:
                filing_history = CompaniesHouseService.fetch_filing_history(company_number)
            except CompaniesHouseError as e:
                # Log but don't fail if filing history can't be fetched
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Could not fetch filing history for company {company_number}: {e}")
                filing_history = None
            
            normalized_data = CompaniesHouseService.normalize_company_data(api_data, filing_history)
            
            # Create company with registered status
            company = Company.objects.create(
                user=request.user,
                is_registered=True,
                registration_status='registered',
                **normalized_data
            )

            # Attempt to enrich with historical grants from 360Giving (non-blocking)
            try:
                grants_received = ThreeSixtyGivingService.fetch_grants_received(company.company_number)
                company.grants_received_360 = grants_received
                company.save(update_fields=['grants_received_360'])
            except ThreeSixtyGivingError as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"360Giving lookup skipped for {company.company_number}: {e}")
            
            messages.success(request, f'Company {company.name} created successfully.')
            return redirect('companies:funding_search_create', company_id=company.id)
        
        except CompaniesHouseError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f'Error creating company: {str(e)}')
    
    return render(request, 'companies/funding_search_select_company.html')


@login_required
@ratelimit(key='user_or_ip', rate='30/m', method='GET', block=True)
def company_search(request):
    """API endpoint to search Companies House by company name."""
    from django.http import JsonResponse
    from django.conf import settings
    
    query = request.GET.get('q', '').strip()
    
    if not query or len(query) < 2:
        return JsonResponse({'results': []})
    
    try:
        results = CompaniesHouseService.search_companies(query, items_per_page=20)
        return JsonResponse({'results': results})
    except CompaniesHouseError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        # SECURITY: Don't expose internal error details in production
        if settings.DEBUG:
            error_msg = f'Unexpected error: {str(e)}'
        else:
            error_msg = 'An error occurred processing your request'
        return JsonResponse({'error': error_msg}, status=500)


@login_required
def company_onboarding(request, id):
    """Multi-step onboarding flow after company creation."""
    company = get_object_or_404(Company, id=id)
    
    # Check if user has permission (owner or admin)
    if request.user != company.user and not request.user.admin:
        messages.error(request, 'You do not have permission to access this company.')
        return redirect('companies:list')
    
    if request.method == 'POST':
        step = request.POST.get('step', 'website')
        action = request.POST.get('action', 'next')
        
        # Only save when "Finish" is clicked (step == 'website' and action == 'finish')
        if step == 'website' and action == 'finish':
            # Save all data at once
            saved_items = []
            
            # Save website
            website = request.POST.get('website', '').strip()
            if website:
                # SECURITY: Validate website URL to prevent SSRF
                from .security import validate_website_url
                is_valid, error_msg = validate_website_url(website)
                if not is_valid:
                    messages.error(request, f'Invalid website URL: {error_msg}')
                    return redirect('companies:onboarding', id=id)
                company.website = website
                company.save(update_fields=['website'])
                saved_items.append('website')
            
            if saved_items:
                messages.success(request, f'Company setup completed. Saved: {", ".join(saved_items)}.')
            else:
                messages.info(request, 'Company setup completed.')
            
            # Redirect to detail page
            return redirect('companies:detail', id=id)
    
    # Allow user to manually navigate steps, default to website
    requested_step = request.GET.get('step', 'website')
    if requested_step in ['website']:
        current_step = requested_step
    else:
        current_step = 'website'
    
    context = {
        'company': company,
        'current_step': current_step,
    }
    return render(request, 'companies/onboarding.html', context)

