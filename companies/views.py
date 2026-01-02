"""
Company views.
"""
import os
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models.functions import Lower
from django.db.models import Q
from django.conf import settings
from django.urls import reverse
from .models import Company, FundingSearch, GrantMatchResult, CompanyFile, CompanyNote
from .services import (
    CompaniesHouseService,
    CompaniesHouseError,
    ThreeSixtyGivingService,
    ThreeSixtyGivingError,
)
from grants_aggregator import CELERY_AVAILABLE
from grants.models import Grant, GRANT_SOURCES, GRANT_SOURCES

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
        company.website = request.POST.get('website', company.website)
        company.notes = request.POST.get('notes', company.notes)
        company.save()

        # Handle optional file upload
        uploaded_file = request.FILES.get('company_file')
        if uploaded_file:
            CompanyFile.objects.create(
                company=company,
                uploaded_by=request.user,
                file=uploaded_file,
                original_name=uploaded_file.name,
            )
            messages.success(request, 'Company updated and file uploaded.')
        else:
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
        'company_files': company.files.all(),
        'notes': company.company_notes.all(),
        'current_tab': current_tab,
        'can_edit_tabs': can_edit,
    }
    return render(request, 'companies/detail.html', context)


@login_required
def company_file_delete(request, file_id):
    """Delete a company file (owner or admin)."""
    company_file = get_object_or_404(CompanyFile, id=file_id)
    company = company_file.company

    if request.user != company.user and not request.user.admin:
        messages.error(request, 'You do not have permission to delete this file.')
        return redirect('companies:detail', id=company.id)

    if request.method == 'POST':
        company_file.delete()
        messages.success(request, 'File deleted.')

    return redirect('companies:detail', id=company.id)


@login_required
def company_note_create(request, company_id):
    """Create a new note for a company."""
    company = get_object_or_404(Company, id=company_id)

    if request.user != company.user and not request.user.admin:
        messages.error(request, 'You do not have permission to add notes for this company.')
        return redirect('companies:list')

    if request.method == 'POST':
        body = (request.POST.get('body') or '').strip()
        title = (request.POST.get('title') or '').strip() or None

        if not body:
            messages.error(request, 'Note text cannot be empty.')
        else:
            CompanyNote.objects.create(
                company=company,
                user=request.user,
                title=title,
                body=body,
            )
            messages.success(request, 'Note added.')

    detail_url = reverse('companies:detail', args=[company_id])
    return redirect(f'{detail_url}?tab=notes')


@login_required
def company_note_delete(request, note_id):
    """Delete a note for a company."""
    note = get_object_or_404(CompanyNote, id=note_id)
    company = note.company

    if request.user != company.user and not request.user.admin:
        messages.error(request, 'You do not have permission to delete notes for this company.')
        return redirect('companies:list')

    if request.method == 'POST':
        note.delete()
        messages.success(request, 'Note deleted.')

    detail_url = reverse('companies:detail', args=[company.id])
    return redirect(f'{detail_url}?tab=notes')


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
        
        # Get multiple TRL levels from form
        trl_levels = request.POST.getlist('trl_levels')  # getlist for multiple values
        trl_levels = [level for level in trl_levels if level]  # Remove empty values
        
        funding_search = FundingSearch.objects.create(
            company=company,
            user=request.user,
            name=name,
            notes=request.POST.get('notes', ''),
            trl_level=request.POST.get('trl_level', '') or None,  # Keep for backwards compatibility
            trl_levels=trl_levels,
        )
        
        messages.success(request, 'Funding search created successfully.')
        return redirect('companies:funding_search_select_data', id=funding_search.id)
    
    # GET request - show the form
    context = {
        'company': company,
        'trl_levels': TRL_LEVELS,
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
        
        # Handle regular form submission (name, notes, trl_levels, grant_sources)
        funding_search.name = request.POST.get('name', funding_search.name)
        funding_search.notes = request.POST.get('notes', funding_search.notes)
        # Get multiple TRL levels from form
        trl_levels = request.POST.getlist('trl_levels')  # getlist for multiple values
        trl_levels = [level for level in trl_levels if level]  # Remove empty values
        funding_search.trl_levels = trl_levels
        # Get selected grant sources from form
        grant_sources = request.POST.getlist('grant_sources')  # getlist for multiple values
        grant_sources = [source for source in grant_sources if source]  # Remove empty values
        funding_search.selected_grant_sources = grant_sources if grant_sources else []  # Default to empty list if none selected
        funding_search.save()
        
        # If AJAX request, return JSON response instead of redirecting
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            from django.http import JsonResponse
            return JsonResponse({'success': True, 'message': 'Funding search updated successfully.'})
        
        messages.success(request, 'Funding search updated successfully.')
        return redirect('companies:funding_search_detail', id=id)
    
    # Get match results
    match_results = GrantMatchResult.objects.filter(
        funding_search=funding_search
    ).select_related('grant').order_by('-match_score')[:50]
    
    # Get selected sources (company files and notes)
    selected_files = funding_search.selected_company_files.all().order_by('-created_at')
    selected_notes = funding_search.selected_company_notes.all().order_by('-created_at')
    
    context = {
        'funding_search': funding_search,
        'can_edit': can_edit,
        'trl_levels': TRL_LEVELS,
        'grant_sources': GRANT_SOURCES,
        'match_results': match_results,
        'selected_files': selected_files,
        'selected_notes': selected_notes,
    }
    return render(request, 'companies/funding_search_detail.html', context)


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
    from .models import CompanyFile, CompanyNote
    
    # SECURITY: Check authorization before loading data
    funding_search = get_object_or_404(FundingSearch, id=id)
    
    # Check if user has permission to edit (owner or admin)
    if request.user != funding_search.user and not request.user.admin:
        messages.error(request, 'You do not have permission to edit this funding search.')
        return redirect('companies:funding_search_detail', id=id)
    
    company = funding_search.company
    
    if request.method == 'POST':
        # Get selected company files
        selected_file_ids = request.POST.getlist('company_files')
        selected_files = CompanyFile.objects.filter(
            id__in=selected_file_ids,
            company=company
        )
        funding_search.selected_company_files.set(selected_files)
        
        # Get selected company notes
        selected_note_ids = request.POST.getlist('company_notes')
        selected_notes = CompanyNote.objects.filter(
            id__in=selected_note_ids,
            company=company
        )
        funding_search.selected_company_notes.set(selected_notes)
        
        # Get website selection
        funding_search.use_company_website = request.POST.get('use_company_website') == 'on'
        
        funding_search.save()
        
        messages.success(request, 'Company data selected successfully.')
        return redirect('companies:funding_search_detail', id=id)
    
    # GET request - show selection form
    company_files = company.files.all().order_by('-created_at')
    company_notes = company.company_notes.all().order_by('-created_at')
    
    # Get currently selected items
    selected_file_ids = set(funding_search.selected_company_files.values_list('id', flat=True))
    selected_note_ids = set(funding_search.selected_company_notes.values_list('id', flat=True))
    
    context = {
        'funding_search': funding_search,
        'company': company,
        'company_files': company_files,
        'company_notes': company_notes,
        'selected_file_ids': selected_file_ids,
        'selected_note_ids': selected_note_ids,
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
        
        # Copy ManyToMany relationships
        new_funding_search.selected_company_files.set(original.selected_company_files.all())
        new_funding_search.selected_company_notes.set(original.selected_company_notes.all())
        
        # Copy matching results
        if original.match_results.exists():
            for original_result in original.match_results.all():
                GrantMatchResult.objects.create(
                    funding_search=new_funding_search,
                    grant=original_result.grant,
                    match_score=original_result.match_score,
                    eligibility_score=original_result.eligibility_score,
                    competitiveness_score=original_result.competitiveness_score,
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
        
        # SECURITY: Validate file type by extension AND content
        file_name = uploaded_file.name.lower()
        
        # Check extension first
        if file_name.endswith('.pdf'):
            expected_type = 'pdf'
        elif file_name.endswith('.docx'):
            expected_type = 'docx'
        elif file_name.endswith('.txt'):
            expected_type = 'txt'
        else:
            messages.error(request, 'Unsupported file type. Please upload PDF, DOCX, or TXT.')
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
            # Save file without extracting text
            funding_search.uploaded_file = uploaded_file
            funding_search.file_type = file_type
            funding_search.save()
            
            messages.success(request, f'File uploaded successfully.')
        except Exception as e:
            messages.error(request, f'Error uploading file: {str(e)}')
    
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
            funding_search.selected_company_files.exists() or
            funding_search.selected_company_notes.exists() or
            funding_search.use_company_website or
            funding_search.uploaded_file or
            funding_search.project_description
        )
        
        if not has_sources:
            logger.warning(f"Funding search {id} has no input sources")
            messages.error(request, 'Please select input sources (company files, notes, website) or add a project description first.')
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
            funding_search.selected_company_files.exists() or
            funding_search.selected_company_notes.exists() or
            funding_search.use_company_website or
            funding_search.uploaded_file or
            funding_search.project_description
        )
        
        if not has_sources:
            logger.warning(f"Funding search {id} has no input sources")
            messages.error(request, 'Please select input sources (company files, notes, website) or add a project description first.')
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
def company_search(request):
    """API endpoint to search Companies House by company name."""
    from django.http import JsonResponse
    
    query = request.GET.get('q', '').strip()
    
    if not query or len(query) < 2:
        return JsonResponse({'results': []})
    
    try:
        results = CompaniesHouseService.search_companies(query, items_per_page=20)
        return JsonResponse({'results': results})
    except CompaniesHouseError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Unexpected error: {str(e)}'}, status=500)


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
        
        # Only save when "Finish" is clicked (step == 'files' and action == 'finish')
        if step == 'files' and action == 'finish':
            # Save all data at once
            saved_items = []
            
            # Save website
            website = request.POST.get('website', '').strip()
            if website:
                company.website = website
                company.save(update_fields=['website'])
                saved_items.append('website')
            
            # Save note
            note_title = request.POST.get('note_title', '').strip()
            note_body = request.POST.get('note_body', '').strip()
            if note_body:
                CompanyNote.objects.create(
                    company=company,
                    user=request.user,
                    title=note_title or None,
                    body=note_body
                )
                saved_items.append('note')
            
            # Save file
            uploaded_file = request.FILES.get('company_file')
            if uploaded_file:
                CompanyFile.objects.create(
                    company=company,
                    uploaded_by=request.user,
                    file=uploaded_file,
                    original_name=uploaded_file.name,
                )
                saved_items.append('file')
            
            if saved_items:
                messages.success(request, f'Company setup completed. Saved: {", ".join(saved_items)}.')
            else:
                messages.info(request, 'Company setup completed.')
            
            # Redirect to detail page
            return redirect('companies:detail', id=id)
    
    # Allow user to manually navigate steps, default to website
    requested_step = request.GET.get('step', 'website')
    if requested_step in ['website', 'notes', 'files']:
        current_step = requested_step
    else:
        current_step = 'website'
    
    context = {
        'company': company,
        'current_step': current_step,
    }
    return render(request, 'companies/onboarding.html', context)

