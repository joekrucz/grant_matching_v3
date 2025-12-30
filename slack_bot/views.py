"""
Views for handling Slack webhook requests.
"""
import json
import logging
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings

from .utils import verify_slack_signature, extract_company_number, is_company_number
from .services import SlackService, CompanyInfoService

logger = logging.getLogger(__name__)


def resolve_company_identifier(text: str) -> Dict:
    """
    Resolve company identifier from text (company number or name).
    
    Args:
        text: Company number or company name
        
    Returns:
        dict with keys: company_number, error, matches
    """
    result = {
        'company_number': None,
        'error': None,
        'matches': []
    }
    
    if not text or not text.strip():
        result['error'] = 'Please provide a company number or company name.'
        return result
    
    text = text.strip()
    
    # Check if it's a company number
    if is_company_number(text):
        result['company_number'] = text.upper()
        return result
    
    # Try to extract company number from text
    company_number = extract_company_number(text)
    if company_number:
        result['company_number'] = company_number
        return result
    
    # Search by company name
    search_result = CompanyInfoService.search_company_by_name(text)
    
    if search_result.get('error'):
        result['error'] = search_result['error']
        return result
    
    matches = search_result.get('matches', [])
    result['matches'] = matches
    
    if not matches:
        result['error'] = f"No companies found matching '{text}'. Please try a different search term or provide a company number."
        return result
    
    # If multiple matches, return them for user to choose
    if len(matches) > 1:
        result['error'] = 'multiple_matches'  # Special error code
        return result
    
    # Single match - use it
    result['company_number'] = matches[0]['company_number']
    return result


@csrf_exempt
@require_http_methods(["POST"])
def slack_events(request):
    """
    Handle Slack Events API webhooks.
    
    Handles:
    - URL verification challenge
    - App mentions
    - Direct messages
    """
    # Get request headers
    timestamp = request.META.get('HTTP_X_SLACK_REQUEST_TIMESTAMP', '')
    signature = request.META.get('HTTP_X_SLACK_SIGNATURE', '')
    
    # Read request body
    request_body = request.body
    
    # Verify signature
    if not verify_slack_signature(request_body, timestamp, signature):
        logger.warning("Invalid Slack signature")
        return HttpResponse(status=401)
    
    # Parse request data
    try:
        data = json.loads(request_body.decode('utf-8'))
    except json.JSONDecodeError:
        logger.error("Invalid JSON in Slack request")
        return HttpResponse(status=400)
    
    # Handle URL verification challenge
    if data.get('type') == 'url_verification':
        challenge = data.get('challenge')
        if challenge:
            return JsonResponse({'challenge': challenge})
        return HttpResponse(status=400)
    
    # Handle events
    if data.get('type') == 'event_callback':
        event = data.get('event', {})
        event_type = event.get('type')
        
        # Handle app mentions
        if event_type == 'app_mention':
            return handle_app_mention(event)
        
        # Handle direct messages
        # Check for DMs: channel_type == 'im' or channel starts with 'D' (DM channel ID format)
        channel = event.get('channel', '')
        channel_type = event.get('channel_type')
        is_dm = channel_type == 'im' or (channel and channel.startswith('D'))
        
        if event_type == 'message' and is_dm:
            # Ignore bot messages and message subtypes
            if event.get('subtype') or event.get('bot_id'):
                return JsonResponse({'status': 'ok'})
            return handle_direct_message(event)
    
    # Acknowledge event
    return JsonResponse({'status': 'ok'})


@csrf_exempt
@require_http_methods(["POST"])
def slack_commands(request):
    """
    Handle Slack slash commands.
    
    Command: /company-info [company_number]
    """
    # Get request headers
    timestamp = request.META.get('HTTP_X_SLACK_REQUEST_TIMESTAMP', '')
    signature = request.META.get('HTTP_X_SLACK_SIGNATURE', '')
    
    # Read request body
    request_body = request.body
    
    # Verify signature
    if not verify_slack_signature(request_body, timestamp, signature):
        logger.warning("Invalid Slack signature for command")
        return HttpResponse(status=401)
    
    # Parse form data
    try:
        text = request.POST.get('text', '').strip()
        user_id = request.POST.get('user_id')
        channel_id = request.POST.get('channel_id')
        response_url = request.POST.get('response_url')
    except Exception as e:
        logger.error(f"Error parsing command data: {e}")
        return JsonResponse({
            'response_type': 'ephemeral',
            'text': 'Error processing command. Please try again.'
        })
    
    # Resolve company identifier (number or name)
    text = text.strip() if text else ""
    resolve_result = resolve_company_identifier(text)
    
    if resolve_result.get('error'):
        error = resolve_result['error']
        
        # Handle multiple matches
        if error == 'multiple_matches':
            matches = resolve_result.get('matches', [])
            matches_text = f"*Found {len(matches)} companies matching '{text}':*\n\n"
            for idx, match in enumerate(matches[:10], 1):  # Show first 10
                matches_text += f"{idx}. {match['title']} ({match['company_number']}) - {match.get('company_status', 'Unknown')}\n"
            
            matches_text += f"\nPlease provide the company number (e.g., {matches[0]['company_number']}) or be more specific with the company name."
            
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': matches_text
            })
        
        return JsonResponse({
            'response_type': 'ephemeral',
            'text': error
        })
    
    company_number = resolve_result['company_number']
    
    # Process company lookup (async response via response_url)
    try:
        slack_service = SlackService()
        company_info = CompanyInfoService.get_company_info(company_number, user=None)
        
        if company_info.get('error'):
            error_msg = company_info['error']
            if 'not found' in error_msg.lower():
                return JsonResponse({
                    'response_type': 'ephemeral',
                    'text': f'Company {company_number} not found in Companies House.'
                })
            return JsonResponse({
                'response_type': 'ephemeral',
                'text': f'Error: {error_msg}'
            })
        
        # Format and send response
        blocks = CompanyInfoService.format_slack_blocks(
            company_info['company_data'],
            company_info['filings'],
            company_info['grants'],
            company_info.get('company_obj')
        )
        
        # Send response via response_url (allows for delayed responses)
        try:
            import requests
            requests.post(response_url, json={
                'response_type': 'in_channel',
                'blocks': blocks
            }, timeout=5)
        except Exception as e:
            logger.error(f"Error sending delayed response: {e}")
        
        # Return immediate acknowledgment
        return JsonResponse({
            'response_type': 'ephemeral',
            'text': f'Fetching information for company {company_number}...'
        })
        
    except Exception as e:
        logger.error(f"Error processing command: {e}", exc_info=True)
        return JsonResponse({
            'response_type': 'ephemeral',
            'text': 'An error occurred while processing your request. Please try again later.'
        })


def handle_app_mention(event):
    """Handle app mention events."""
    text = event.get('text', '')
    channel = event.get('channel')
    user = event.get('user')
    
    # Remove bot mention from text
    # Slack mentions look like <@U123456> or similar
    import re
    text = re.sub(r'<@[A-Z0-9]+>', '', text).strip()
    
    # Resolve company identifier (number or name)
    resolve_result = resolve_company_identifier(text)
    
    if resolve_result.get('error'):
        error = resolve_result['error']
        
        # Handle multiple matches
        if error == 'multiple_matches':
            matches = resolve_result.get('matches', [])
            matches_text = f"*Found {len(matches)} companies matching '{text}':*\n\n"
            for idx, match in enumerate(matches[:10], 1):
                matches_text += f"{idx}. {match['title']} ({match['company_number']}) - {match.get('company_status', 'Unknown')}\n"
            
            matches_text += f"\nPlease provide the company number (e.g., {matches[0]['company_number']}) or be more specific."
            
            try:
                slack_service = SlackService()
                slack_service.send_message(channel=channel, text=matches_text)
            except Exception as e:
                logger.error(f"Error sending message: {e}")
            return JsonResponse({'status': 'ok'})
        
        # Other errors
        try:
            slack_service = SlackService()
            slack_service.send_message(
                channel=channel,
                text=f"Hi! {error}\n\nYou can search by company number (e.g., `12345678`) or company name (e.g., `Acme Corp Ltd`)."
            )
        except Exception as e:
            logger.error(f"Error sending message: {e}")
        return JsonResponse({'status': 'ok'})
    
    company_number = resolve_result['company_number']
    
    # Process company lookup
    try:
        slack_service = SlackService()
        company_info = CompanyInfoService.get_company_info(company_number, user=None)
        
        if company_info.get('error'):
            error_msg = company_info['error']
            if 'not found' in error_msg.lower():
                slack_service.send_message(
                    channel=channel,
                    text=f"Company {company_number} not found in Companies House."
                )
            else:
                slack_service.send_message(
                    channel=channel,
                    text=f"Error: {error_msg}"
                )
            return JsonResponse({'status': 'ok'})
        
        # Format and send response
        blocks = CompanyInfoService.format_slack_blocks(
            company_info['company_data'],
            company_info['filings'],
            company_info['grants'],
            company_info.get('company_obj')
        )
        
        slack_service.send_message(
            channel=channel,
            blocks=blocks
        )
        
    except Exception as e:
        logger.error(f"Error processing mention: {e}", exc_info=True)
        try:
            slack_service = SlackService()
            slack_service.send_message(
                channel=channel,
                text="An error occurred while processing your request. Please try again later."
            )
        except:
            pass
    
    return JsonResponse({'status': 'ok'})


def handle_direct_message(event):
    """Handle direct message events."""
    text = event.get('text', '')
    channel = event.get('channel')
    user = event.get('user')
    
    # Resolve company identifier (number or name)
    resolve_result = resolve_company_identifier(text)
    
    if resolve_result.get('error'):
        error = resolve_result['error']
        
        # Handle multiple matches
        if error == 'multiple_matches':
            matches = resolve_result.get('matches', [])
            matches_text = f"*Found {len(matches)} companies matching '{text}':*\n\n"
            for idx, match in enumerate(matches[:10], 1):
                matches_text += f"{idx}. {match['title']} ({match['company_number']}) - {match.get('company_status', 'Unknown')}\n"
            
            matches_text += f"\nPlease provide the company number (e.g., {matches[0]['company_number']}) or be more specific with the company name."
            
            try:
                slack_service = SlackService()
                slack_service.send_message(channel=channel, text=matches_text)
            except Exception as e:
                logger.error(f"Error sending message: {e}")
            return JsonResponse({'status': 'ok'})
        
        # Other errors
        try:
            slack_service = SlackService()
            slack_service.send_message(
                channel=channel,
                text=f"Hi! {error}\n\nYou can search by company number (e.g., `12345678`) or company name (e.g., `Acme Corp Ltd`)."
            )
        except Exception as e:
            logger.error(f"Error sending message: {e}")
        return JsonResponse({'status': 'ok'})
    
    company_number = resolve_result['company_number']
    
    # Process company lookup
    try:
        slack_service = SlackService()
        company_info = CompanyInfoService.get_company_info(company_number, user=None)
        
        if company_info.get('error'):
            error_msg = company_info['error']
            if 'not found' in error_msg.lower():
                slack_service.send_message(
                    channel=channel,
                    text=f"Company {company_number} not found in Companies House."
                )
            else:
                slack_service.send_message(
                    channel=channel,
                    text=f"Error: {error_msg}"
                )
            return JsonResponse({'status': 'ok'})
        
        # Format and send response
        blocks = CompanyInfoService.format_slack_blocks(
            company_info['company_data'],
            company_info['filings'],
            company_info['grants'],
            company_info.get('company_obj')
        )
        
        slack_service.send_message(
            channel=channel,
            blocks=blocks
        )
        
    except Exception as e:
        logger.error(f"Error processing DM: {e}", exc_info=True)
        try:
            slack_service = SlackService()
            slack_service.send_message(
                channel=channel,
                text="An error occurred while processing your request. Please try again later."
            )
        except:
            pass
    
    return JsonResponse({'status': 'ok'})

