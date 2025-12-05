"""
Company views.
"""
import os
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.conf import settings
from .models import Company, FundingSearch, GrantMatchResult
from .services import CompaniesHouseService, CompaniesHouseError
from grants_aggregator import CELERY_AVAILABLE
from grants.models import Grant

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
        companies = Company.objects.all().select_related('user').order_by('-created_at')
    else:
        # Regular users only see their own companies
        companies = Company.objects.filter(user=request.user).select_related('user').order_by('-created_at')
    
    # Pagination
    paginator = Paginator(companies, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'companies/list.html', {'page_obj': page_obj})


@login_required
def company_detail(request, id):
    """Company detail page."""
    from .models import TRL_LEVELS
    
    company = get_object_or_404(Company, id=id)
    funding_searches = company.funding_searches.all().order_by('-created_at')
    
    # Check if user can edit (owner or admin)
    can_edit = request.user == company.user or request.user.admin
    
    if request.method == 'POST':
        if not can_edit:
            messages.error(request, 'You do not have permission to edit this company.')
            return redirect('companies:detail', id=id)
        
        # Update editable fields
        company.website = request.POST.get('website', company.website)
        company.notes = request.POST.get('notes', company.notes)
        company.save()
        messages.success(request, 'Company updated successfully.')
        return redirect('companies:detail', id=id)
    
    context = {
        'company': company,
        'funding_searches': funding_searches,
        'can_edit': can_edit,
        'trl_levels': TRL_LEVELS,
    }
    return render(request, 'companies/detail.html', context)


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
            return redirect('companies:detail', id=company.id)
        
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
                normalized_data = CompaniesHouseService.normalize_company_data(api_data)
                
                # Create company with registered status
                company = Company.objects.create(
                    user=request.user,
                    is_registered=True,
                    registration_status='registered',
                    **normalized_data
                )
                
                messages.success(request, f'Company {company.name} created successfully.')
                return redirect('companies:detail', id=company.id)
            
            except CompaniesHouseError as e:
                messages.error(request, str(e))
            except Exception as e:
                messages.error(request, f'Error creating company: {str(e)}')
    
    return render(request, 'companies/create.html')


@login_required
def company_delete(request, id):
    """Delete company (owner or admin only)."""
    company = get_object_or_404(Company, id=id)
    
    if request.user != company.user and not request.user.admin:
        messages.error(request, 'You do not have permission to delete this company.')
        return redirect('companies:detail', id=id)
    
    if request.method == 'POST':
        company_name = company.name
        company.delete()
        messages.success(request, f'Company {company_name} deleted successfully.')
        return redirect('companies:list')
    
    return render(request, 'companies/delete.html', {'company': company})


@login_required
def funding_search_create(request, company_id):
    """Create funding search for a company."""
    company = get_object_or_404(Company, id=company_id)
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'Name is required.')
            return redirect('companies:detail', id=company_id)
        
        funding_search = FundingSearch.objects.create(
            company=company,
            user=request.user,
            name=name,
            notes=request.POST.get('notes', ''),
            trl_level=request.POST.get('trl_level', '') or None,
        )
        
        messages.success(request, 'Funding search created successfully.')
        return redirect('companies:detail', id=company_id)
    
    return redirect('companies:detail', id=company_id)


@login_required
def funding_search_detail(request, id):
    """Funding search detail page."""
    from .models import TRL_LEVELS
    
    funding_search = get_object_or_404(FundingSearch, id=id)
    can_edit = request.user == funding_search.user or request.user.admin
    
    if request.method == 'POST':
        if not can_edit:
            messages.error(request, 'You do not have permission to edit this funding search.')
            return redirect('companies:funding_search_detail', id=id)
        
        # Handle regular form submission (name, notes, trl_level, project_description)
        funding_search.name = request.POST.get('name', funding_search.name)
        funding_search.notes = request.POST.get('notes', funding_search.notes)
        funding_search.trl_level = request.POST.get('trl_level', '') or None
        funding_search.project_description = request.POST.get('project_description', funding_search.project_description)
        funding_search.save()
        
        messages.success(request, 'Funding search updated successfully.')
        return redirect('companies:funding_search_detail', id=id)
    
    # Get match results
    match_results = GrantMatchResult.objects.filter(
        funding_search=funding_search
    ).select_related('grant').order_by('-match_score')[:50]
    
    context = {
        'funding_search': funding_search,
        'can_edit': can_edit,
        'trl_levels': TRL_LEVELS,
        'match_results': match_results,
    }
    return render(request, 'companies/funding_search_detail.html', context)


@login_required
def funding_search_delete(request, id):
    """Delete funding search (owner or admin only)."""
    funding_search = get_object_or_404(FundingSearch, id=id)
    
    if request.user != funding_search.user and not request.user.admin:
        messages.error(request, 'You do not have permission to delete this funding search.')
        return redirect('companies:funding_search_detail', id=id)
    
    if request.method == 'POST':
        company_id = funding_search.company.id
        funding_search.delete()
        messages.success(request, 'Funding search deleted successfully.')
        return redirect('companies:detail', id=company_id)
    
    return render(request, 'companies/funding_search_delete.html', {'funding_search': funding_search})


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
    """Handle file upload and text extraction."""
    funding_search = get_object_or_404(FundingSearch, id=id)
    can_edit = request.user == funding_search.user or request.user.admin
    
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
        
        # Determine file type
        file_name = uploaded_file.name.lower()
        if file_name.endswith('.pdf'):
            file_type = 'pdf'
        elif file_name.endswith('.docx'):
            file_type = 'docx'
        elif file_name.endswith('.txt'):
            file_type = 'txt'
        else:
            messages.error(request, 'Unsupported file type. Please upload PDF, DOCX, or TXT.')
            return redirect('companies:funding_search_detail', id=id)
        
        try:
            # Extract text from file
            extracted_text = extract_text_from_file(uploaded_file, file_type)
            
            if not extracted_text:
                messages.error(request, 'Could not extract text from file. File may be empty or corrupted.')
                return redirect('companies:funding_search_detail', id=id)
            
            # Save file and extracted text
            funding_search.uploaded_file = uploaded_file
            funding_search.file_type = file_type
            funding_search.project_description = extracted_text
            funding_search.save()
            
            messages.success(request, f'File uploaded and text extracted successfully. ({len(extracted_text)} characters)')
        except Exception as e:
            messages.error(request, f'Error processing file: {str(e)}')
    
    return redirect('companies:funding_search_detail', id=id)


@login_required
def funding_search_match(request, id):
    """Trigger matching job."""
    import logging
    logger = logging.getLogger(__name__)
    
    funding_search = get_object_or_404(FundingSearch, id=id)
    can_edit = request.user == funding_search.user or request.user.admin
    
    logger.info(f"Funding search match requested for ID: {id}, user: {request.user.email}, can_edit: {can_edit}")
    
    if not can_edit:
        messages.error(request, 'You do not have permission to run matching for this funding search.')
        return redirect('companies:funding_search_detail', id=id)
    
    if request.method == 'POST':
        if not funding_search.project_description:
            logger.warning(f"Funding search {id} has no project description")
            messages.error(request, 'Please provide project description or upload a file first.')
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
        
        # Trigger Celery task
        try:
            logger.info(f"Triggering matching task for funding search {id}")
            task = match_grants_with_chatgpt.delay(funding_search.id)
            logger.info(f"Matching task queued successfully. Task ID: {task.id}")
            messages.info(request, f'Matching job started (Task ID: {task.id}). Processing all grants... This may take 1-2 minutes.')
        except Exception as e:
            logger.error(f"Failed to trigger matching task for funding search {id}: {e}", exc_info=True)
            messages.error(request, f'Failed to start matching job: {str(e)}')
    
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

