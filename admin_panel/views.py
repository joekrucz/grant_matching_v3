"""
Admin panel views.
"""
import json

from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.urls import reverse
from django.utils import timezone
from django_ratelimit.decorators import ratelimit

from grants.models import Grant, ScrapeLog, GRANT_SOURCES
from users.models import User
from companies.models import Company
from grants_aggregator import CELERY_AVAILABLE

# Import SlackBotLog conditionally - may not be available in local dev
try:
    from slack_bot.models import SlackBotLog
    SLACK_BOT_AVAILABLE = True
except (ImportError, Exception):
    SlackBotLog = None
    SLACK_BOT_AVAILABLE = False
from .ai_client import (
    AiAssistantClient,
    AiAssistantError,
    build_company_context,
    build_grant_context,
    prepare_conversation_history,
)
from .models import AiInteractionLog, Conversation, ConversationMessage

# Import tasks only if Celery is available
if CELERY_AVAILABLE:
    from .tasks import (
        trigger_ukri_scrape,
        trigger_nihr_scrape,
        trigger_catapult_scrape,
        trigger_innovate_uk_scrape,
        refresh_companies_house_data,
        generate_checklists_for_all_grants,
    )
else:
    trigger_ukri_scrape = None
    trigger_nihr_scrape = None
    trigger_catapult_scrape = None
    trigger_innovate_uk_scrape = None
    refresh_companies_house_data = None
    generate_checklists_for_all_grants = None


def admin_required(view_func):
    """Decorator to require admin access."""
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.admin:
            messages.error(request, 'Admin access required.')
            return redirect('/')
        return view_func(request, *args, **kwargs)
    return wrapper


def _json_bad_request(message, status=400):
    return JsonResponse({"error": message}, status=status)


def _get_ai_client():
    try:
        return AiAssistantClient()
    except AiAssistantError as exc:
        return str(exc)


@login_required
@admin_required
def dashboard(request):
    """Admin dashboard."""
    total_grants = Grant.objects.count()
    # Count open grants using computed status (deadline in future or null, and opening_date null or in past)
    from django.utils import timezone
    now = timezone.now()
    from django.db.models import Q
    open_grants = Grant.objects.filter(
        Q(deadline__isnull=True) | Q(deadline__gt=now)
    ).exclude(
        Q(opening_date__isnull=False) & Q(opening_date__gt=now)
    ).count()
    last_scrape = ScrapeLog.objects.filter(status='success').order_by('-completed_at').first()
    
    # Check for recent Companies House refresh task
    last_refresh_task = None
    if CELERY_AVAILABLE:
        try:
            from celery.result import AsyncResult
            from django.core.cache import cache
            
            # Try to get last task ID from cache or URL
            task_id = request.GET.get('task_id') or cache.get('last_companies_refresh_task_id')
            if task_id:
                task_result = AsyncResult(task_id)
                if task_result.ready():
                    if task_result.state == 'SUCCESS':
                        last_refresh_task = {
                            'task_id': task_id,
                            'status': 'completed',
                            'result': task_result.result,
                            'completed': True
                        }
                    elif task_result.state == 'FAILURE':
                        last_refresh_task = {
                            'task_id': task_id,
                            'status': 'error',
                            'error': str(task_result.info),
                            'completed': True
                        }
                else:
                    last_refresh_task = {
                        'task_id': task_id,
                        'status': 'running',
                        'completed': False
                    }
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Error checking refresh task status: {e}")
    
    # Check Celery worker status
    celery_status = "Unknown"
    celery_details = ""
    if CELERY_AVAILABLE:
        try:
            from celery import current_app
            inspect = current_app.control.inspect()
            active_workers = inspect.active()
            if active_workers:
                celery_status = f"Active ({len(active_workers)} worker(s))"
                celery_details = f"Workers: {', '.join(active_workers.keys())}"
            else:
                celery_status = "No active workers"
                celery_details = "Tasks are queued but no workers are processing them. Check Celery service is running."
        except Exception as e:
            celery_status = f"Error checking: {str(e)}"
            celery_details = "Cannot connect to Celery workers. They may not be running or Redis connection failed."
    else:
        celery_status = "Celery not available"
        celery_details = "Celery is not initialized. Check Redis connection and web service logs."
    
    # Calculate checklist statistics
    # Count grants that have non-empty eligibility checklists
    # Using JSONField lookups to check if checklist_items array exists and is not empty
    grants_with_eligibility = Grant.objects.filter(
        eligibility_checklist__checklist_items__0__isnull=False
    ).count()
    
    grants_with_competitiveness = Grant.objects.filter(
        competitiveness_checklist__checklist_items__0__isnull=False
    ).count()
    
    grants_with_exclusions = Grant.objects.filter(
        exclusions_checklist__checklist_items__0__isnull=False
    ).count()
    
    grants_with_both = Grant.objects.filter(
        eligibility_checklist__checklist_items__0__isnull=False,
        competitiveness_checklist__checklist_items__0__isnull=False
    ).count()
    
    grants_with_all_three = Grant.objects.filter(
        eligibility_checklist__checklist_items__0__isnull=False,
        competitiveness_checklist__checklist_items__0__isnull=False,
        exclusions_checklist__checklist_items__0__isnull=False
    ).count()
    
    # Calculate user statistics
    total_users = User.objects.count()
    admin_users = User.objects.filter(admin=True).count()
    active_users = User.objects.filter(is_active=True).count()
    
    # Calculate Companies House statistics
    from datetime import timedelta
    from django.db.models import Q
    total_companies = Company.objects.count()
    registered_companies = Company.objects.filter(is_registered=True, company_number__isnull=False).count()
    companies_with_filing_history = Company.objects.exclude(filing_history={}).exclude(filing_history__isnull=True).count()
    companies_with_360_grants = Company.objects.exclude(grants_received_360={}).exclude(grants_received_360__isnull=True).count()
    # Companies updated in last 7 days
    seven_days_ago = timezone.now() - timedelta(days=7)
    companies_updated_recently = Company.objects.filter(updated_at__gte=seven_days_ago).count()
    # Companies not updated in last 30 days (may need refresh)
    thirty_days_ago = timezone.now() - timedelta(days=30)
    companies_needing_refresh = Company.objects.filter(
        is_registered=True,
        company_number__isnull=False
    ).filter(
        Q(updated_at__lt=thirty_days_ago) | Q(updated_at__isnull=True)
    ).count()
    
    # Get recent bot logs (last 20) - handle gracefully if Slack bot isn't configured
    recent_bot_logs = []
    total_bot_messages = 0
    bot_messages_today = 0
    if SLACK_BOT_AVAILABLE and SlackBotLog is not None:
        try:
            recent_bot_logs = list(SlackBotLog.objects.all()[:20])
            total_bot_messages = SlackBotLog.objects.count()
            bot_messages_today = SlackBotLog.objects.filter(
                created_at__date=timezone.now().date()
            ).count()
        except Exception as e:
            # Handle case where table doesn't exist (migrations not run) or other DB errors
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Slack bot logs not available (likely not configured for local dev): {e}")
            # Use default values already set above
    
    context = {
        'total_grants': total_grants,
        'open_grants': open_grants,
        'last_scrape': last_scrape,
        'celery_status': celery_status,
        'celery_details': celery_details,
        'last_refresh_task': last_refresh_task,
        'grants_with_eligibility': grants_with_eligibility,
        'grants_with_competitiveness': grants_with_competitiveness,
        'grants_with_exclusions': grants_with_exclusions,
        'grants_with_both': grants_with_both,
        'grants_with_all_three': grants_with_all_three,
        'total_users': total_users,
        'admin_users': admin_users,
        'active_users': active_users,
        'recent_bot_logs': recent_bot_logs,
        'total_bot_messages': total_bot_messages,
        'bot_messages_today': bot_messages_today,
        'total_companies': total_companies,
        'registered_companies': registered_companies,
        'companies_with_filing_history': companies_with_filing_history,
        'companies_with_360_grants': companies_with_360_grants,
        'companies_updated_recently': companies_updated_recently,
        'companies_needing_refresh': companies_needing_refresh,
    }
    return render(request, 'admin_panel/dashboard.html', context)


@login_required
@admin_required
@ratelimit(key='user_or_ip', rate='30/h', block=True)
def ai_summarise_grant(request):
    """API endpoint: summarise a single grant for an admin."""
    if request.method != "POST":
        return _json_bad_request("Method not allowed", status=405)
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return _json_bad_request("Invalid JSON payload")
    grant_id = payload.get("grant_id")
    conversation_id = payload.get("conversation_id")
    page_type = payload.get("page_type", "grant")
    company_id = payload.get("company_id")
    
    if not grant_id:
        return _json_bad_request("grant_id is required")

    # Get or create conversation
    conversation = None
    if conversation_id:
        conversation = Conversation.objects.filter(id=conversation_id, user=request.user).first()
        if not conversation:
            return _json_bad_request("Conversation not found", status=404)
    else:
        # Create new conversation for this action
        grant = get_object_or_404(Grant, id=grant_id)
        conversation = Conversation.objects.create(
            user=request.user,
            title=f"{grant.title} Conversation",
            initial_page_type=page_type,
            initial_grant_id=grant_id,
            initial_company_id=company_id,
        )

    grant = get_object_or_404(Grant, id=grant_id) if not grant else grant
    client = _get_ai_client()
    if isinstance(client, str):
        return _json_bad_request(client, status=503)

    grant_ctx = build_grant_context(grant)
    parsed, raw_meta, latency_ms = client.summarise_grant(grant_ctx)

    bullets = parsed.get("bullets") or []
    risks = parsed.get("risks") or []
    
    # Format response for conversation
    summary_text = "Grant Summary:\n\n" + "\n".join([f"• {b}" for b in bullets])
    if risks:
        summary_text += "\n\nRisks:\n" + "\n".join([f"⚠ {r}" for r in risks])

    # Save to conversation
    ConversationMessage.objects.create(
        conversation=conversation,
        role="user",
        content=f"Summarise grant: {grant.title}",
        metadata={"action": "summarise_grant", "grant_id": grant_id},
    )
    ConversationMessage.objects.create(
        conversation=conversation,
        role="assistant",
        content=summary_text,
        metadata={
            "action": "summarise_grant",
            "grant_id": grant_id,
            "grant_slug": grant.slug,  # Store slug for link generation
            "grant_title": grant.title,  # Store title for matching
            "bullets": bullets,
            "risks": risks,
            "model": raw_meta.get("model"),
            "latency_ms": latency_ms,
        },
    )
    # Update conversation timestamp
    conversation.save(update_fields=['updated_at'])

    log = AiInteractionLog.objects.create(
        user=request.user,
        endpoint="summarise_grant",
        model_name=raw_meta.get("model"),
        grant=grant,
        company=None,
        request_payload={"grant_id": grant_id, "conversation_id": conversation.id},
        response_payload={"bullets": bullets, "risks": risks},
        latency_ms=latency_ms,
    )

    return JsonResponse(
        {
            "bullets": bullets,
            "risks": risks,
            "conversation_id": conversation.id,
            "grant_title": grant.title,  # Include for link generation
            "grant_slug": grant.slug,  # Include for link generation
            "meta": {
                "model": raw_meta.get("model"),
                "input_tokens": (raw_meta.get("usage") or {}).get("input_tokens"),
                "output_tokens": (raw_meta.get("usage") or {}).get("output_tokens"),
                "latency_ms": latency_ms,
                "log_id": log.id,
            },
        }
    )


@login_required
@admin_required
@ratelimit(key='user_or_ip', rate='30/h', block=True)
def ai_summarise_company(request):
    """API endpoint: summarise a single company for an admin."""
    if request.method != "POST":
        return _json_bad_request("Method not allowed", status=405)
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return _json_bad_request("Invalid JSON payload")
    company_id = payload.get("company_id")
    conversation_id = payload.get("conversation_id")
    page_type = payload.get("page_type", "company")
    grant_id = payload.get("grant_id")
    
    if not company_id:
        return _json_bad_request("company_id is required")

    # Get or create conversation
    conversation = None
    if conversation_id:
        conversation = Conversation.objects.filter(id=conversation_id, user=request.user).first()
        if not conversation:
            return _json_bad_request("Conversation not found", status=404)
    else:
        # Create new conversation for this action
        company = get_object_or_404(Company, id=company_id)
        conversation = Conversation.objects.create(
            user=request.user,
            title=f"{company.name} Conversation",
            initial_page_type=page_type,
            initial_grant_id=grant_id,
            initial_company_id=company_id,
        )

    company = get_object_or_404(Company, id=company_id) if not company else company
    client = _get_ai_client()
    if isinstance(client, str):
        return _json_bad_request(client, status=503)

    company_ctx = build_company_context(company)
    parsed, raw_meta, latency_ms = client.summarise_company(company_ctx)

    bullets = parsed.get("bullets") or []
    highlights = parsed.get("highlights") or []
    gaps = parsed.get("gaps") or []
    
    # Format response for conversation
    summary_text = "Company Summary:\n\n" + "\n".join([f"• {b}" for b in bullets])
    if highlights:
        summary_text += "\n\nHighlights:\n" + "\n".join([f"✓ {h}" for h in highlights])
    if gaps:
        summary_text += "\n\nGaps:\n" + "\n".join([f"⚠ {g}" for g in gaps])

    # Save to conversation
    ConversationMessage.objects.create(
        conversation=conversation,
        role="user",
        content=f"Summarise company: {company.name}",
        metadata={"action": "summarise_company", "company_id": company_id},
    )
    ConversationMessage.objects.create(
        conversation=conversation,
        role="assistant",
        content=summary_text,
        metadata={
            "action": "summarise_company",
            "bullets": bullets,
            "highlights": highlights,
            "gaps": gaps,
            "model": raw_meta.get("model"),
            "latency_ms": latency_ms,
        },
    )
    # Update conversation timestamp
    conversation.save(update_fields=['updated_at'])

    log = AiInteractionLog.objects.create(
        user=request.user,
        endpoint="summarise_company",
        model_name=raw_meta.get("model"),
        grant=None,
        company=company,
        request_payload={"company_id": company_id, "conversation_id": conversation.id},
        response_payload={"bullets": bullets, "highlights": highlights, "gaps": gaps},
        latency_ms=latency_ms,
    )

    return JsonResponse(
        {
            "bullets": bullets,
            "highlights": highlights,
            "gaps": gaps,
            "conversation_id": conversation.id,
            "meta": {
                "model": raw_meta.get("model"),
                "input_tokens": (raw_meta.get("usage") or {}).get("input_tokens"),
                "output_tokens": (raw_meta.get("usage") or {}).get("output_tokens"),
                "latency_ms": latency_ms,
                "log_id": log.id,
            },
        }
    )


@login_required
@admin_required
@ratelimit(key='user_or_ip', rate='30/h', block=True)
def ai_contextual_qa(request):
    """API endpoint: contextual Q&A for an admin based on current page context."""
    if request.method != "POST":
        return _json_bad_request("Method not allowed", status=405)
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return _json_bad_request("Invalid JSON payload")

    question = (payload.get("message") or "").strip()
    page_type = (payload.get("page_type") or "unknown").strip()
    grant_id = payload.get("grant_id")
    company_id = payload.get("company_id")
    conversation_id = payload.get("conversation_id")

    if not question:
        return _json_bad_request("message is required")

    # Get or create conversation
    conversation = None
    if conversation_id:
        conversation = Conversation.objects.filter(id=conversation_id, user=request.user).first()
        if not conversation:
            return _json_bad_request("Conversation not found", status=404)
    else:
        # Create new conversation if none provided
        grant = get_object_or_404(Grant, id=grant_id) if grant_id else None
        company = get_object_or_404(Company, id=company_id) if company_id else None
        
        # Generate title based on context
        title = None
        if grant:
            title = f"{grant.title} Conversation"
        elif company:
            title = f"{company.name} Conversation"
        
        conversation = Conversation.objects.create(
            user=request.user,
            title=title,
            initial_page_type=page_type,
            initial_grant_id=grant_id,
            initial_company_id=company_id,
        )

    grant = grant if 'grant' in locals() else (get_object_or_404(Grant, id=grant_id) if grant_id else None)
    company = company if 'company' in locals() else (get_object_or_404(Company, id=company_id) if company_id else None)

    # Load previous messages from conversation for context
    previous_messages = []
    referenced_grant_contexts = {}  # Grants mentioned in previous messages
    conversation_history = None
    
    if conversation:
        # Get all messages except the one we're about to create
        previous_messages = list(conversation.messages.all().order_by("created_at"))
        # Prepare conversation history with context window management
        conversation_history = prepare_conversation_history(previous_messages)
        
        # Extract grant IDs from previous messages' metadata
        # This allows us to load full grant context for grants mentioned in conversation
        referenced_grants = []
        for msg in previous_messages:
            metadata = msg.metadata or {}
            # Check for grant_ids in metadata (from search results, fit analysis, etc.)
            if "grant_ids" in metadata:
                referenced_grants.extend(metadata["grant_ids"])
            # Also check for single grant_id
            if "grant_id" in metadata and metadata["grant_id"]:
                referenced_grants.append(metadata["grant_id"])
        
        # Remove duplicates and load grant contexts
        referenced_grant_ids = list(set(referenced_grants))
        if referenced_grant_ids:
            # Load grant contexts for referenced grants
            referenced_grant_objects = Grant.objects.filter(id__in=referenced_grant_ids)
            # Store in a dict for easy access
            referenced_grant_contexts = {
                g.id: build_grant_context(g) for g in referenced_grant_objects
            }

    # Save user message
    ConversationMessage.objects.create(
        conversation=conversation,
        role="user",
        content=question,
        metadata={"page_type": page_type, "grant_id": grant_id, "company_id": company_id},
    )

    client = _get_ai_client()
    if isinstance(client, str):
        return _json_bad_request(client, status=503)

    # Use current grant context if provided, otherwise None
    grant_ctx = build_grant_context(grant) if grant else None
    company_ctx = build_company_context(company) if company else None
    
    # Pass conversation history and referenced grants to AI
    parsed, raw_meta, latency_ms = client.contextual_qa(
        question=question,
        page_type=page_type,
        grant_ctx=grant_ctx,
        company_ctx=company_ctx,
        conversation_history=conversation_history,
        referenced_grants=referenced_grant_contexts if referenced_grant_contexts else None,
    )

    answer = parsed.get("answer") or ""
    used_fields = parsed.get("used_fields") or []
    caveats = parsed.get("caveats") or []

    # Build grant mapping for link generation (from referenced grants)
    grant_mapping = {}
    if referenced_grant_contexts:
        # Get grant objects to access slugs
        referenced_grant_objects = Grant.objects.filter(id__in=referenced_grant_contexts.keys())
        for grant_obj in referenced_grant_objects:
            grant_ctx = referenced_grant_contexts.get(grant_obj.id)
            if grant_ctx and grant_obj.slug:
                grant_mapping[grant_obj.id] = {
                    "title": grant_ctx.get("title", grant_obj.title),
                    "slug": grant_obj.slug,
                }

    # Save assistant response
    ConversationMessage.objects.create(
        conversation=conversation,
        role="assistant",
        content=answer,
        metadata={
            "used_fields": used_fields,
            "caveats": caveats,
            "grant_mapping": grant_mapping,  # Store grant title -> slug mapping for link generation
            "model": raw_meta.get("model"),
            "latency_ms": latency_ms,
        },
    )
    
    # Update conversation timestamp and potentially extract topics
    # For now, we'll just update the timestamp. Topic extraction can be added later
    # if we want to track what topics were discussed in the conversation.
    conversation.save(update_fields=['updated_at'])

    log = AiInteractionLog.objects.create(
        user=request.user,
        endpoint="contextual_qa",
        model_name=raw_meta.get("model"),
        grant=grant,
        company=company,
        request_payload={
            "message": question,
            "page_type": page_type,
            "grant_id": grant_id,
            "company_id": company_id,
            "conversation_id": conversation.id,
        },
        response_payload={
            "answer": answer,
            "used_fields": used_fields,
            "caveats": caveats,
        },
        latency_ms=latency_ms,
    )

    # Convert grant_mapping from {grant_id: {...}} to {title: slug} format for frontend
    grant_mapping_list = {}
    for grant_id, grant_info in grant_mapping.items():
        if grant_info.get("slug"):
            grant_mapping_list[grant_info["title"]] = grant_info["slug"]
    
    return JsonResponse(
        {
            "answer": answer,
            "used_fields": used_fields,
            "caveats": caveats,
            "conversation_id": conversation.id,
            "grant_mapping": grant_mapping_list,  # Include grant mapping for link generation
            "meta": {
                "model": raw_meta.get("model"),
                "input_tokens": (raw_meta.get("usage") or {}).get("input_tokens"),
                "output_tokens": (raw_meta.get("usage") or {}).get("output_tokens"),
                "latency_ms": latency_ms,
                "log_id": log.id,
            },
        }
    )


@login_required
@admin_required
def ai_search_companies(request):
    """API endpoint: search companies by name for AI assistant dropdowns."""
    if request.method != "GET":
        return _json_bad_request("Method not allowed", status=405)
    
    query = request.GET.get("q", "").strip()
    
    # If no query, return all companies (for dropdown population)
    # If query provided, filter by name
    if query:
        companies = Company.objects.filter(name__icontains=query)[:20]
    else:
        companies = Company.objects.all()[:50]  # Limit to 50 for dropdown
    
    results = [
        {"id": c.id, "name": c.name, "company_type": c.company_type or "", "status": c.status or ""}
        for c in companies
    ]
    
    return JsonResponse({"companies": results})


@login_required
@admin_required
def ai_search_grants(request):
    """API endpoint: search grants by title for AI assistant dropdowns."""
    if request.method != "GET":
        return _json_bad_request("Method not allowed", status=405)
    
    query = request.GET.get("q", "").strip()
    
    # If no query, return all grants (for dropdown population)
    # If query provided, filter by title
    if query:
        grants = Grant.objects.filter(title__icontains=query)[:20]
    else:
        grants = Grant.objects.all()[:50]  # Limit to 50 for dropdown
    
    results = [
        {"id": g.id, "title": g.title, "source": g.get_source_display(), "status": g.get_status_display()}
        for g in grants
    ]
    
    return JsonResponse({"grants": results})


@login_required
@admin_required
@ratelimit(key='user_or_ip', rate='30/h', block=True)
def ai_grant_company_fit(request):
    """API endpoint: analyze how well a grant fits a company."""
    if request.method != "POST":
        return _json_bad_request("Method not allowed", status=405)
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return _json_bad_request("Invalid JSON payload")
    
    grant_id = payload.get("grant_id")
    company_id = payload.get("company_id")
    conversation_id = payload.get("conversation_id")
    page_type = payload.get("page_type", "mixed")
    
    if not grant_id or not company_id:
        return _json_bad_request("Both grant_id and company_id are required")
    
    # Get or create conversation
    conversation = None
    if conversation_id:
        conversation = Conversation.objects.filter(id=conversation_id, user=request.user).first()
        if not conversation:
            return _json_bad_request("Conversation not found", status=404)
    else:
        # Create new conversation for this action
        grant = get_object_or_404(Grant, id=grant_id)
        company = get_object_or_404(Company, id=company_id)
        conversation = Conversation.objects.create(
            user=request.user,
            title=f"{company.name} & {grant.title} Conversation",
            initial_page_type=page_type,
            initial_grant_id=grant_id,
            initial_company_id=company_id,
        )
    
    grant = grant if 'grant' in locals() else get_object_or_404(Grant, id=grant_id)
    company = company if 'company' in locals() else get_object_or_404(Company, id=company_id)
    
    client = _get_ai_client()
    if isinstance(client, str):
        return _json_bad_request(client, status=503)
    
    grant_ctx = build_grant_context(grant)
    company_ctx = build_company_context(company)
    parsed, raw_meta, latency_ms = client.grant_company_fit(grant_ctx, company_ctx)
    
    fit_score = parsed.get("fit_score", 0.0)
    explanation = parsed.get("explanation", "")
    alignment_points = parsed.get("alignment_points", [])
    concerns = parsed.get("concerns", [])
    recommendations = parsed.get("recommendations", [])
    
    # Format response for conversation
    score_percent = int(fit_score * 100)
    fit_text = f"Fit Analysis: {company.name} ↔ {grant.title}\n\n"
    fit_text += f"Fit Score: {score_percent}% ({fit_score:.2f}/1.0)\n\n"
    fit_text += f"{explanation}\n\n"
    if alignment_points:
        fit_text += "Alignment Points:\n" + "\n".join([f"✓ {a}" for a in alignment_points]) + "\n\n"
    if concerns:
        fit_text += "Concerns:\n" + "\n".join([f"⚠ {c}" for c in concerns]) + "\n\n"
    if recommendations:
        fit_text += "Recommendations:\n" + "\n".join([f"💡 {r}" for r in recommendations])

    # Save to conversation
    ConversationMessage.objects.create(
        conversation=conversation,
        role="user",
        content=f"Check fit: {grant.title} with {company.name}",
        metadata={"action": "grant_company_fit", "grant_id": grant_id, "company_id": company_id},
    )
    ConversationMessage.objects.create(
        conversation=conversation,
        role="assistant",
        content=fit_text,
        metadata={
            "action": "grant_company_fit",
            "grant_id": grant_id,
            "grant_slug": grant.slug,  # Store slug for link generation
            "grant_title": grant.title,  # Store title for matching
            "fit_score": fit_score,
            "explanation": explanation,
            "alignment_points": alignment_points,
            "concerns": concerns,
            "recommendations": recommendations,
            "model": raw_meta.get("model"),
            "latency_ms": latency_ms,
        },
    )
    # Update conversation timestamp
    conversation.save(update_fields=['updated_at'])
    
    log = AiInteractionLog.objects.create(
        user=request.user,
        endpoint="grant_company_fit",
        model_name=raw_meta.get("model"),
        grant=grant,
        company=company,
        request_payload={"grant_id": grant_id, "company_id": company_id, "conversation_id": conversation.id},
        response_payload={
            "fit_score": fit_score,
            "explanation": explanation,
            "alignment_points": alignment_points,
            "concerns": concerns,
        },
        latency_ms=latency_ms,
    )
    
    return JsonResponse(
        {
            "fit_score": fit_score,
            "explanation": explanation,
            "alignment_points": alignment_points,
            "concerns": concerns,
            "recommendations": recommendations,
            "conversation_id": conversation.id,
            "grant_title": grant.title,  # Include for link generation
            "grant_slug": grant.slug,  # Include for link generation
            "meta": {
                "model": raw_meta.get("model"),
                "input_tokens": (raw_meta.get("usage") or {}).get("input_tokens"),
                "output_tokens": (raw_meta.get("usage") or {}).get("output_tokens"),
                "latency_ms": latency_ms,
                "log_id": log.id,
            },
        }
    )


@login_required
@admin_required
@ratelimit(key='user_or_ip', rate='20/h', block=True)
def ai_search_grants_for_company(request):
    """API endpoint: search grants in DB that match a company."""
    if request.method != "POST":
        return _json_bad_request("Method not allowed", status=405)
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return _json_bad_request("Invalid JSON payload")
    
    company_id = payload.get("company_id")
    conversation_id = payload.get("conversation_id")
    page_type = payload.get("page_type", "company")
    limit = payload.get("limit", 50)  # Max grants to analyze
    
    if not company_id:
        return _json_bad_request("company_id is required")
    
    # Get or create conversation
    conversation = None
    if conversation_id:
        conversation = Conversation.objects.filter(id=conversation_id, user=request.user).first()
        if not conversation:
            return _json_bad_request("Conversation not found", status=404)
    else:
        # Create new conversation for this action
        company = get_object_or_404(Company, id=company_id)
        conversation = Conversation.objects.create(
            user=request.user,
            title=f"{company.name} Conversation",
            initial_page_type=page_type,
            initial_company_id=company_id,
        )
    
    company = company if 'company' in locals() else get_object_or_404(Company, id=company_id)
    
    # Fetch a reasonable set of grants to analyze
    # Prioritize active/open grants, then recent ones
    active_grant_ids = list(Grant.objects.filter(
        status__in=['open', 'upcoming', 'active']
    ).order_by('-deadline', '-created_at').values_list('id', flat=True)[:limit])
    
    # If not enough active grants, include some closed ones
    if len(active_grant_ids) < 20:
        additional_ids = list(Grant.objects.exclude(
            id__in=active_grant_ids
        ).order_by('-deadline', '-created_at').values_list('id', flat=True)[:limit - len(active_grant_ids)])
        all_grant_ids = active_grant_ids + additional_ids
    else:
        all_grant_ids = active_grant_ids
    
    grants_qs = Grant.objects.filter(id__in=all_grant_ids).order_by('-deadline', '-created_at')
    
    # Build grant contexts for AI
    grants_list = [build_grant_context(g) for g in grants_qs]
    
    if not grants_list:
        return JsonResponse({
            "matched_grants": [],
            "search_summary": "No grants found in database to analyze.",
            "conversation_id": conversation.id,
        })
    
    client = _get_ai_client()
    if isinstance(client, str):
        return _json_bad_request(client, status=503)
    
    company_ctx = build_company_context(company)
    parsed, raw_meta, latency_ms = client.search_grants_for_company(company_ctx, grants_list)
    
    matched_grants = parsed.get("matched_grants", [])
    search_summary = parsed.get("search_summary", "")
    
    # Fetch full grant objects for matched grants
    grant_ids = [m.get("grant_id") for m in matched_grants if m.get("grant_id")]
    grants_dict = {g.id: g for g in Grant.objects.filter(id__in=grant_ids)}
    
    # Build response with grant details
    results = []
    for match in matched_grants:
        grant_id = match.get("grant_id")
        if grant_id and grant_id in grants_dict:
            grant = grants_dict[grant_id]
            results.append({
                "grant_id": grant_id,
                "title": grant.title,
                "summary": grant.summary,
                "deadline": grant.deadline.isoformat() if grant.deadline else None,
                "funding_amount": grant.funding_amount,
                "status": grant.get_computed_status(),
                "source": grant.source,
                "url": grant.url,
                "relevance_score": match.get("relevance_score", 0.0),
                "explanation": match.get("explanation", ""),
            })
    
    # Format response for conversation
    if results:
        search_text = f"Grant Search for {company.name}\n\n"
        search_text += f"{search_summary}\n\n" if search_summary else ""
        search_text += f"Found {len(results)} matching grants:\n\n"
        for i, result in enumerate(results[:10], 1):  # Show top 10 in conversation
            score_percent = int(result["relevance_score"] * 100)
            search_text += f"{i}. {result['title']} ({score_percent}% match)\n"
            search_text += f"   {result['explanation']}\n"
            if result.get("deadline"):
                search_text += f"   Deadline: {result['deadline']}\n"
            search_text += "\n"
    else:
        search_text = f"Grant Search for {company.name}\n\n"
        search_text += f"{search_summary}\n\n" if search_summary else ""
        search_text += "No matching grants found."
    
    # Extract grant IDs and slugs from results for metadata
    grant_ids_from_search = [r["grant_id"] for r in results]
    # Also store grant title -> slug mapping for link generation
    grant_mapping = {r["grant_id"]: {"title": r["title"], "slug": grants_dict.get(r["grant_id"]).slug if r["grant_id"] in grants_dict else None} for r in results if r["grant_id"] in grants_dict}
    
    # Save to conversation
    ConversationMessage.objects.create(
        conversation=conversation,
        role="user",
        content=f"Search grants for: {company.name}",
        metadata={"action": "search_grants_for_company", "company_id": company_id},
    )
    ConversationMessage.objects.create(
        conversation=conversation,
        role="assistant",
        content=search_text,
        metadata={
            "action": "search_grants_for_company",
            "matched_count": len(results),
            "grant_ids": grant_ids_from_search,  # Store grant IDs for later reference
            "grant_mapping": grant_mapping,  # Store title -> slug mapping for link generation
            "search_summary": search_summary,
            "model": raw_meta.get("model"),
            "latency_ms": latency_ms,
        },
    )
    # Update conversation timestamp
    conversation.save(update_fields=['updated_at'])
    
    log = AiInteractionLog.objects.create(
        user=request.user,
        endpoint="search_grants_for_company",
        model_name=raw_meta.get("model"),
        grant=None,
        company=company,
        request_payload={"company_id": company_id, "conversation_id": conversation.id, "limit": limit},
        response_payload={
            "matched_count": len(results),
            "search_summary": search_summary,
        },
        latency_ms=latency_ms,
    )
    
    # Convert grant_mapping from {grant_id: {...}} to {title: slug} format for frontend
    grant_mapping_list = {}
    for grant_id, grant_info in grant_mapping.items():
        if grant_info.get("slug"):
            grant_mapping_list[grant_info["title"]] = grant_info["slug"]
    
    return JsonResponse({
        "matched_grants": results,
        "search_summary": search_summary,
        "conversation_id": conversation.id,
        "grant_mapping": grant_mapping_list,  # Include grant mapping for link generation
        "meta": {
            "model": raw_meta.get("model"),
            "input_tokens": (raw_meta.get("usage") or {}).get("input_tokens"),
            "output_tokens": (raw_meta.get("usage") or {}).get("output_tokens"),
            "latency_ms": latency_ms,
            "log_id": log.id,
        },
    })


@login_required
@admin_required
def ai_conversations_list(request):
    """API endpoint: list all conversations for the current user."""
    if request.method != "GET":
        return _json_bad_request("Method not allowed", status=405)
    
    conversations = Conversation.objects.filter(user=request.user).order_by("-updated_at")[:50]
    
    results = [
        {
            "id": c.id,
            "title": c.title or c.get_default_title(),
            "message_count": c.get_message_count(),
            "created_at": c.created_at.isoformat(),
            "updated_at": c.updated_at.isoformat(),
            "initial_page_type": c.initial_page_type,
            "initial_grant_id": c.initial_grant_id,
            "initial_company_id": c.initial_company_id,
        }
        for c in conversations
    ]
    
    return JsonResponse({"conversations": results})


@login_required
@admin_required
def ai_conversation_detail(request, conversation_id):
    """API endpoint: get a conversation with all its messages."""
    if request.method != "GET":
        return _json_bad_request("Method not allowed", status=405)
    
    conversation = get_object_or_404(Conversation, id=conversation_id, user=request.user)
    
    messages = conversation.messages.all().order_by("created_at")
    
    return JsonResponse(
        {
            "id": conversation.id,
            "title": conversation.title or conversation.get_default_title(),
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
            "initial_page_type": conversation.initial_page_type,
            "initial_grant_id": conversation.initial_grant_id,
            "initial_company_id": conversation.initial_company_id,
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "metadata": m.metadata,
                    "created_at": m.created_at.isoformat(),
                }
                for m in messages
            ],
        }
    )


@login_required
@admin_required
def ai_conversation_create(request):
    """API endpoint: create a new conversation."""
    if request.method != "POST":
        return _json_bad_request("Method not allowed", status=405)
    
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return _json_bad_request("Invalid JSON payload")
    
    conversation = Conversation.objects.create(
        user=request.user,
        title=payload.get("title"),
        initial_page_type=payload.get("page_type"),
        initial_grant_id=payload.get("grant_id"),
        initial_company_id=payload.get("company_id"),
    )
    
    return JsonResponse(
        {
            "id": conversation.id,
            "title": conversation.title or conversation.get_default_title(),
            "created_at": conversation.created_at.isoformat(),
        }
    )


@login_required
@admin_required
def ai_conversation_add_message(request, conversation_id):
    """API endpoint: add a message to a conversation."""
    if request.method != "POST":
        return _json_bad_request("Method not allowed", status=405)
    
    conversation = get_object_or_404(Conversation, id=conversation_id, user=request.user)
    
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return _json_bad_request("Invalid JSON payload")
    
    role = payload.get("role")  # "user" or "assistant"
    content = payload.get("content", "").strip()
    metadata = payload.get("metadata", {})
    
    if role not in ["user", "assistant"]:
        return _json_bad_request("role must be 'user' or 'assistant'")
    
    if not content:
        return _json_bad_request("content is required")
    
    message = ConversationMessage.objects.create(
        conversation=conversation,
        role=role,
        content=content,
        metadata=metadata,
    )
    
    # Update conversation's updated_at
    conversation.save(update_fields=["updated_at"])
    
    # Auto-generate title from first user message if not set
    if not conversation.title and role == "user":
        conversation.title = content[:50] + ("..." if len(content) > 50 else "")
        conversation.save(update_fields=["title", "updated_at"])
    
    return JsonResponse(
        {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "created_at": message.created_at.isoformat(),
        }
    )


@login_required
@admin_required
def ai_conversation_update(request, conversation_id):
    """API endpoint: update a conversation (e.g., rename title)."""
    if request.method not in ["PUT", "PATCH"]:
        return _json_bad_request("Method not allowed", status=405)
    
    conversation = get_object_or_404(Conversation, id=conversation_id, user=request.user)
    
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return _json_bad_request("Invalid JSON payload")
    
    # Update title if provided
    if "title" in payload:
        title = payload.get("title", "").strip()
        conversation.title = title if title else None
        conversation.save(update_fields=["title", "updated_at"])
    
    return JsonResponse(
        {
            "id": conversation.id,
            "title": conversation.title or conversation.get_default_title(),
            "updated_at": conversation.updated_at.isoformat(),
        }
    )


@login_required
@admin_required
def ai_conversation_delete(request, conversation_id):
    """API endpoint: delete a conversation."""
    if request.method != "DELETE":
        return _json_bad_request("Method not allowed", status=405)
    
    conversation = get_object_or_404(Conversation, id=conversation_id, user=request.user)
    conversation_id_value = conversation.id
    conversation.delete()
    
    return JsonResponse({"success": True, "deleted_id": conversation_id_value})


@login_required
@admin_required
def ai_conversations_page(request):
    """Dedicated page for viewing and managing AI conversations."""
    conversations = Conversation.objects.filter(user=request.user).order_by("-updated_at")
    
    # Get selected conversation ID from query param or use most recent
    selected_id = request.GET.get("conversation_id")
    selected_conversation = None
    
    if selected_id:
        try:
            selected_conversation = Conversation.objects.get(id=selected_id, user=request.user)
        except Conversation.DoesNotExist:
            pass
    
    # If no selection and conversations exist, use most recent
    if not selected_conversation and conversations.exists():
        selected_conversation = conversations.first()
    
    # Get messages for selected conversation
    conversation_messages = []
    if selected_conversation:
        conversation_messages = selected_conversation.messages.all().order_by("created_at")
    
    context = {
        "conversations": conversations,
        "selected_conversation": selected_conversation,
        "conversation_messages": conversation_messages,
    }
    return render(request, "admin_panel/conversations.html", context)


@login_required
@admin_required
def run_scrapers(request):
    """Trigger scraper workers."""
    if request.method == 'POST':
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"Run scrapers button clicked. CELERY_AVAILABLE={CELERY_AVAILABLE}, trigger_ukri_scrape={trigger_ukri_scrape}")
        
        if not CELERY_AVAILABLE or trigger_ukri_scrape is None:
            error_msg = 'Background task service (Celery) is not available. Please check Redis connection.'
            logger.error(error_msg)
            messages.error(request, error_msg)
            return redirect('admin_panel:dashboard')
        
        try:
            # Trigger the scraper chain
            logger.info("Calling trigger_ukri_scrape.delay()...")
            logger.info(f"trigger_ukri_scrape function: {trigger_ukri_scrape}")
            logger.info(f"Has delay method: {hasattr(trigger_ukri_scrape, 'delay')}")
            
            if not hasattr(trigger_ukri_scrape, 'delay'):
                error_msg = 'trigger_ukri_scrape is not a Celery task. Check Celery configuration.'
                logger.error(error_msg)
                messages.error(request, error_msg)
                return redirect('admin_panel:dashboard')
            
            result = trigger_ukri_scrape.delay()
            logger.info(f"Task queued successfully. Task ID: {result.id}")
            logger.info(f"Task state: {result.state}")
            # Store task_id in the most recent ScrapeLog
            try:
                from grants.models import ScrapeLog
                scrape_log = ScrapeLog.objects.filter(source='ukri').order_by('-started_at').first()
                if scrape_log and scrape_log.status == 'running':
                    if scrape_log.metadata is None:
                        scrape_log.metadata = {}
                    scrape_log.metadata['task_id'] = result.id
                    scrape_log.save(update_fields=['metadata'])
            except Exception as e:
                logger.warning(f"Could not store task_id in ScrapeLog: {e}")
            messages.success(request, f'Scrapers triggered (Task ID: {result.id}).')
        except Exception as e:
            error_msg = f'Failed to trigger scrapers: {str(e)}'
            logger.error(f"Error triggering scrapers: {e}", exc_info=True)
            messages.error(request, error_msg)
        return redirect('admin_panel:dashboard')
    
    return redirect('admin_panel:dashboard')


def _queue_single_scraper(request, task, source_label):
    """Helper to enqueue a single scraper task with messaging."""
    import logging
    logger = logging.getLogger(__name__)
    if request.method != 'POST':
        return redirect('admin_panel:dashboard')
    if not CELERY_AVAILABLE or task is None or not hasattr(task, 'delay'):
        messages.error(request, f'Celery not available or task missing for {source_label}.')
        return redirect('admin_panel:dashboard')
    try:
        result = task.delay(None, False)  # chain_started_at_str=None, continue_chain=False
        # Store task_id in the most recent ScrapeLog for this source
        try:
            from grants.models import ScrapeLog
            scrape_log = ScrapeLog.objects.filter(source=source_label.lower()).order_by('-started_at').first()
            if scrape_log and scrape_log.status == 'running':
                if scrape_log.metadata is None:
                    scrape_log.metadata = {}
                scrape_log.metadata['task_id'] = result.id
                scrape_log.save(update_fields=['metadata'])
        except Exception as e:
            logger.warning(f"Could not store task_id in ScrapeLog: {e}")
        messages.success(request, f'{source_label} scraper triggered (Task ID: {result.id}).')
    except Exception as e:
        logger.error(f"Error triggering {source_label} scraper: {e}", exc_info=True)
        messages.error(request, f'Failed to trigger {source_label} scraper: {e}')
    return redirect('admin_panel:dashboard')


@login_required
@admin_required
def run_ukri_scraper(request):
    return _queue_single_scraper(request, trigger_ukri_scrape, "UKRI")


@login_required
@admin_required
def run_nihr_scraper(request):
    return _queue_single_scraper(request, trigger_nihr_scrape, "NIHR")


@login_required
@admin_required
def run_catapult_scraper(request):
    return _queue_single_scraper(request, trigger_catapult_scrape, "Catapult")


@login_required
@admin_required
def run_innovate_uk_scraper(request):
    return _queue_single_scraper(request, trigger_innovate_uk_scrape, "Innovate UK")


@login_required
@admin_required
def wipe_grants(request):
    """Delete all grants (admin only)."""
    if request.method == 'POST':
        count = Grant.objects.count()
        Grant.objects.all().delete()
        messages.success(request, f'Deleted {count} grants.')
        return redirect('admin_panel:dashboard')
    
    return render(request, 'admin_panel/wipe_grants.html')


@login_required
@admin_required
def wipe_grants_by_source(request, source):
    """Delete grants from a specific source (admin only)."""
    if request.method == 'POST':
        # Validate source
        valid_sources = ['ukri', 'nihr', 'catapult', 'innovate_uk']
        if source not in valid_sources:
            messages.error(request, f'Invalid source: {source}')
            return redirect('admin_panel:dashboard')
        
        # Get count before deletion
        count = Grant.objects.filter(source=source).count()
        
        # Delete grants from this source
        Grant.objects.filter(source=source).delete()
        
        # Get display name for the source
        source_display = dict(GRANT_SOURCES).get(source, source)
        messages.success(request, f'Deleted {count} {source_display} grants.')
        return redirect('admin_panel:dashboard')
    
    return redirect('admin_panel:dashboard')


@login_required
@admin_required
def scrape_logs(request):
    """List scrape logs."""
    logs = ScrapeLog.objects.all().order_by('-started_at')
    
    # Pagination
    paginator = Paginator(logs, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'admin_panel/scrape_logs.html', {'page_obj': page_obj})


@login_required
@admin_required
def cancel_scraper_job(request, log_id):
    """Cancel a running scraper job by revoking its Celery task."""
    if request.method != 'POST':
        messages.error(request, 'Invalid request method.')
        return redirect('admin_panel:scrape_logs')
    
    if not CELERY_AVAILABLE:
        messages.error(request, 'Celery is not available.')
        return redirect('admin_panel:scrape_logs')
    
    try:
        from grants.models import ScrapeLog
        from celery import current_app
        
        scrape_log = get_object_or_404(ScrapeLog, id=log_id)
        
        if scrape_log.status != 'running':
            messages.warning(request, f'Scraper job is not running (status: {scrape_log.get_status_display()}).')
            return redirect('admin_panel:scrape_logs')
        
        # Get task_id from metadata
        task_id = scrape_log.metadata.get('task_id') if scrape_log.metadata else None
        
        if not task_id:
            messages.error(request, 'No task ID found for this scraper job.')
            return redirect('admin_panel:scrape_logs')
        
        # Revoke the task
        current_app.control.revoke(task_id, terminate=True)
        
        # Update scrape log
        scrape_log.status = 'cancelled'
        scrape_log.completed_at = timezone.now()
        scrape_log.error_message = 'Cancelled by administrator'
        scrape_log.save()
        
        messages.success(request, f'Scraper job cancelled successfully.')
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error cancelling scraper job: {e}", exc_info=True)
        messages.error(request, f'Failed to cancel scraper job: {str(e)}')
    
    return redirect('admin_panel:scrape_logs')


@login_required
@admin_required
def scraper_status(request):
    """API endpoint to get scraper chain status and progress (for AJAX polling)."""
    from django.http import JsonResponse
    from django.utils import timezone
    from datetime import timedelta
    
    # Get the most recent chain (scrapers started in the last 10 minutes)
    recent_time = timezone.now() - timedelta(minutes=10)
    recent_logs = ScrapeLog.objects.filter(
        started_at__gte=recent_time
    ).order_by('-started_at')[:3]
    
    # Group by chain_started_at from metadata
    chains = {}
    for log in recent_logs:
        chain_started_at = log.metadata.get('chain_started_at') if log.metadata else None
        if chain_started_at:
            if chain_started_at not in chains:
                chains[chain_started_at] = []
            chains[chain_started_at].append(log)
    
    # Get the most recent chain
    if not chains:
        return JsonResponse({
            'status': 'idle',
            'progress': {'current': 0, 'total': 3, 'percentage': 0},
            'scrapers': []
        })
    
    # Get the most recent chain
    most_recent_chain_time = max(chains.keys())
    chain_logs = chains[most_recent_chain_time]
    
    # Sort by chain_position
    chain_logs.sort(key=lambda x: x.metadata.get('chain_position', 0) if x.metadata else 0)
    
    # Build scraper statuses
    scrapers = []
    completed_count = 0
    running_count = 0
    error_count = 0
    total_grants = 0
    
    for log in chain_logs:
        scraper_status = log.status
        if scraper_status == 'success':
            completed_count += 1
        elif scraper_status == 'running':
            running_count += 1
        elif scraper_status == 'error':
            error_count += 1
        
        total_grants += log.total_grants_processed()
        
        scrapers.append({
            'source': log.source,
            'status': scraper_status,
            'log_id': log.id,
            'grants_found': log.grants_found,
            'grants_created': log.grants_created,
            'grants_updated': log.grants_updated,
            'grants_skipped': log.grants_skipped,
            'error_message': log.error_message,
            'started_at': log.started_at.isoformat() if log.started_at else None,
            'completed_at': log.completed_at.isoformat() if log.completed_at else None,
        })
    
    # Determine overall status
    if error_count > 0:
        overall_status = 'error'
    elif running_count > 0:
        overall_status = 'running'
    elif completed_count == 3:
        overall_status = 'completed'
    else:
        overall_status = 'idle'
    
    # Calculate progress
    progress_percentage = (completed_count / 3) * 100
    
    return JsonResponse({
        'status': overall_status,
        'progress': {
            'current': completed_count,
            'total': 3,
            'percentage': round(progress_percentage, 1)
        },
        'scrapers': scrapers,
        'total_grants_processed': total_grants,
    })


@login_required
@admin_required
def users_list(request):
    """List all users."""
    users = User.objects.all().order_by('-date_joined')
    
    # Pagination
    paginator = Paginator(users, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'admin_panel/users_list.html', {'page_obj': page_obj})


@login_required
@admin_required
def user_detail(request, id):
    """User detail page."""
    # SECURITY: get_object_or_404 provides better error handling
    user = get_object_or_404(User, id=id)
    
    if request.method == 'POST':
        user.name = request.POST.get('name', user.name)
        user.email = request.POST.get('email', user.email)
        user.admin = request.POST.get('admin') == 'on'
        user.is_active = request.POST.get('is_active') == 'on'
        user.save()
        messages.success(request, 'User updated successfully.')
        return redirect('admin_panel:user_detail', id=id)
    
    context = {
        'target_user': user,
    }
    return render(request, 'admin_panel/user_detail.html', context)


@login_required
@admin_required
def user_delete(request, id):
    """Delete user (admin only)."""
    # SECURITY: get_object_or_404 provides better error handling
    user = get_object_or_404(User, id=id)
    
    if request.method == 'POST':
        if user == request.user:
            messages.error(request, 'You cannot delete your own account.')
            return redirect('admin_panel:user_detail', id=id)
        
        user_email = user.email
        user.delete()
        messages.success(request, f'User {user_email} deleted successfully.')
        return redirect('admin_panel:users_list')
    
    return render(request, 'admin_panel/user_delete.html', {'target_user': user})


@login_required
@admin_required
def refresh_companies(request):
    """Trigger Companies House data refresh for all companies."""
    if request.method == 'POST':
        import logging
        logger = logging.getLogger(__name__)
        
        if not CELERY_AVAILABLE or refresh_companies_house_data is None:
            error_msg = 'Background task service (Celery) is not available. Please check Redis connection.'
            logger.error(error_msg)
            messages.error(request, error_msg)
            return redirect('admin_panel:dashboard')
        
        try:
            # Trigger the refresh task
            logger.info("Calling refresh_companies_house_data.delay()...")
            result = refresh_companies_house_data.delay()
            logger.info(f"Task queued successfully. Task ID: {result.id}")
            messages.success(request, f'Companies House data refresh started (Task ID: {result.id}).')
            
            # Store task ID in cache for later retrieval
            from django.core.cache import cache
            cache.set('last_companies_refresh_task_id', result.id, timeout=3600)  # 1 hour
            
            # Return JSON response with task ID for AJAX handling
            from django.http import JsonResponse
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'task_id': result.id, 'status': 'started'})
            
            # Redirect with task ID for non-AJAX requests
            return redirect(f"{reverse('admin_panel:dashboard')}?task_id={result.id}")
        except Exception as e:
            error_msg = f'Failed to start refresh: {str(e)}'
            logger.error(f"Error triggering refresh: {e}", exc_info=True)
            messages.error(request, error_msg)
        
        return redirect('admin_panel:dashboard')
    
    return redirect('admin_panel:dashboard')


@login_required
@admin_required
def companies_refresh_status(request):
    """API endpoint to get Companies House refresh status and progress (for AJAX polling)."""
    from django.http import JsonResponse
    from celery.result import AsyncResult
    
    # Get task ID from request
    task_id = request.GET.get('task_id')
    if not task_id:
        return JsonResponse({
            'status': 'idle',
            'progress': {'current': 0, 'total': 0, 'percentage': 0}
        })
    
    try:
        task_result = AsyncResult(task_id)
        
        if task_result.state == 'PENDING':
            status = 'running'
            progress = {'current': 0, 'total': 0, 'percentage': 0}
        elif task_result.state == 'PROGRESS':
            status = 'running'
            meta = task_result.info or {}
            progress = {
                'current': meta.get('current', 0),
                'total': meta.get('total', 0),
                'percentage': meta.get('percentage', 0),
                'updated': meta.get('updated', 0),
                'errors': meta.get('errors', 0)
            }
        elif task_result.state == 'SUCCESS':
            status = 'completed'
            result = task_result.result or {}
            progress = {
                'current': result.get('total', 0),
                'total': result.get('total', 0),
                'percentage': 100,
                'updated': result.get('updated', 0),
                'errors': result.get('errors', 0),
                'error_messages': result.get('error_messages', [])
            }
        elif task_result.state == 'FAILURE':
            status = 'error'
            progress = {
                'current': 0,
                'total': 0,
                'percentage': 0,
                'error': str(task_result.info)
            }
        else:
            status = 'unknown'
            progress = {'current': 0, 'total': 0, 'percentage': 0}
        
        return JsonResponse({
            'status': status,
            'progress': progress,
            'task_id': task_id
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'progress': {'current': 0, 'total': 0, 'percentage': 0},
            'error': str(e)
        }, status=500)


@login_required
@admin_required
def generate_checklists(request):
    """Trigger checklist generation for all grants."""
    if request.method == 'POST':
        import logging
        logger = logging.getLogger(__name__)
        
        checklist_type = request.POST.get('checklist_type', 'both')  # 'eligibility', 'competitiveness', 'exclusions', 'both', or 'all'
        
        if not CELERY_AVAILABLE or generate_checklists_for_all_grants is None:
            error_msg = 'Background task service (Celery) is not available. Please check Redis connection.'
            logger.error(error_msg)
            messages.error(request, error_msg)
            return redirect('admin_panel:dashboard')
        
        try:
            # Trigger the checklist generation task
            logger.info(f"Calling generate_checklists_for_all_grants.delay() with type: {checklist_type}...")
            result = generate_checklists_for_all_grants.delay(checklist_type)
            logger.info(f"Task queued successfully. Task ID: {result.id}")
            messages.success(request, f'Checklist generation started (Task ID: {result.id}).')
            
            # Store task ID in cache for later retrieval
            from django.core.cache import cache
            cache_key = f'last_checklist_generation_task_id_{checklist_type}'
            cache.set(cache_key, result.id, timeout=3600)  # 1 hour
            
            # Return JSON response with task ID for AJAX handling
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'task_id': result.id, 'status': 'started', 'checklist_type': checklist_type})
            
            # Redirect with task ID for non-AJAX requests
            return redirect(f"{reverse('admin_panel:dashboard')}?checklist_task_id={result.id}&checklist_type={checklist_type}")
        except Exception as e:
            error_msg = f'Failed to start checklist generation: {str(e)}'
            logger.error(f"Error triggering checklist generation: {e}", exc_info=True)
            messages.error(request, error_msg)
        
        return redirect('admin_panel:dashboard')
    
    return redirect('admin_panel:dashboard')


@login_required
@admin_required
def checklist_generation_status(request):
    """API endpoint to get checklist generation status and progress (for AJAX polling)."""
    from celery.result import AsyncResult
    
    # Get task ID from request
    task_id = request.GET.get('task_id')
    if not task_id:
        return JsonResponse({
            'status': 'idle',
            'progress': {'current': 0, 'total': 0, 'percentage': 0}
        })
    
    try:
        task_result = AsyncResult(task_id)
        
        if task_result.state == 'PENDING':
            status = 'running'
            progress = {'current': 0, 'total': 0, 'percentage': 0}
        elif task_result.state == 'PROGRESS':
            status = 'running'
            meta = task_result.info or {}
            progress = {
                'current': meta.get('current', 0),
                'total': meta.get('total', 0),
                'percentage': meta.get('percentage', 0),
                'processed': meta.get('processed', 0),
                'success': meta.get('success', 0),
                'skipped': meta.get('skipped', 0),
                'errors': meta.get('errors', 0)
            }
        elif task_result.state == 'SUCCESS':
            status = 'completed'
            result = task_result.result or {}
            progress = {
                'current': result.get('total', 0),
                'total': result.get('total', 0),
                'percentage': 100,
                'processed': result.get('processed', 0),
                'success': result.get('success', 0),
                'skipped': result.get('skipped', 0),
                'errors': result.get('errors', 0),
                'error_messages': result.get('error_messages', [])
            }
        elif task_result.state == 'FAILURE':
            status = 'error'
            progress = {
                'current': 0,
                'total': 0,
                'percentage': 0,
                'error': str(task_result.info)
            }
        else:
            status = 'unknown'
            progress = {'current': 0, 'total': 0, 'percentage': 0}
        
        return JsonResponse({
            'status': status,
            'progress': progress,
            'task_id': task_id
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'progress': {'current': 0, 'total': 0, 'percentage': 0},
            'error': str(e)
        }, status=500)


@login_required
@admin_required
def cancel_checklist_generation(request):
    """Cancel a running checklist generation job."""
    import logging
    logger = logging.getLogger(__name__)
    
    if request.method == 'POST':
        # Get task ID from request
        task_id = request.POST.get('task_id') or request.GET.get('task_id')
        if not task_id:
            # Try to get from cache
            from django.core.cache import cache
            checklist_type = request.POST.get('checklist_type', 'both')
            cache_key = f'last_checklist_generation_task_id_{checklist_type}'
            task_id = cache.get(cache_key)
        
        if not task_id:
            messages.error(request, 'No checklist generation job found to cancel.')
            return redirect('admin_panel:dashboard')
        
        try:
            from celery.result import AsyncResult
            task = AsyncResult(task_id)
            
            # Check if task is still running
            if task.state in ['PENDING', 'PROGRESS']:
                task.revoke(terminate=True)
                logger.info(f"Cancelled checklist generation task {task_id}")
                messages.success(request, 'Checklist generation job cancelled successfully.')
            else:
                messages.info(request, 'Checklist generation job is not running.')
        except Exception as e:
            logger.warning(f"Could not cancel checklist generation task {task_id}: {e}")
            messages.error(request, f'Failed to cancel checklist generation job: {str(e)}')
    
    return redirect('admin_panel:dashboard')

