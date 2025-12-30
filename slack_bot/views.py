"""
Views for handling Slack webhook requests.
"""
import json
import logging
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings

from .utils import verify_slack_signature, extract_company_number
from .services import SlackService, CompanyInfoService

logger = logging.getLogger(__name__)


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
    
    # Extract company number
    company_number = extract_company_number(text) if text else None
    
    if not company_number:
        return JsonResponse({
            'response_type': 'ephemeral',
            'text': 'Please provide a valid company number.\nUsage: `/company-info 12345678` or `/company-info AB123456`'
        })
    
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
    
    # Extract company number
    company_number = extract_company_number(text)
    
    if not company_number:
        try:
            slack_service = SlackService()
            slack_service.send_message(
                channel=channel,
                text=f"Hi! Please provide a company number. For example: `@trellis-bot 12345678`"
            )
        except Exception as e:
            logger.error(f"Error sending message: {e}")
        return JsonResponse({'status': 'ok'})
    
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
    
    # Extract company number
    company_number = extract_company_number(text)
    
    if not company_number:
        try:
            slack_service = SlackService()
            slack_service.send_message(
                channel=channel,
                text="Hi! Please send me a company number and I'll fetch the company information, filings, and previous grants.\n\nExample: `12345678` or `AB123456`"
            )
        except Exception as e:
            logger.error(f"Error sending message: {e}")
        return JsonResponse({'status': 'ok'})
    
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

