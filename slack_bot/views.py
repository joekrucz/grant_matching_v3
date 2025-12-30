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
from .models import SlackBotLog

logger = logging.getLogger(__name__)

# Cache bot user ID to avoid repeated API calls
_bot_user_id = None

def get_bot_user_id():
    """Get the bot's user ID from Slack API."""
    global _bot_user_id
    if _bot_user_id:
        return _bot_user_id
    
    try:
        slack_service = SlackService()
        auth_response = slack_service.client.auth_test()
        _bot_user_id = auth_response.get('user_id')
        logger.info(f"Bot user ID: {_bot_user_id}")
        return _bot_user_id
    except Exception as e:
        logger.warning(f"Could not get bot user ID: {e}")
        return None


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
            # Also ignore message_changed, message_deleted, etc.
            if event.get('subtype') or event.get('bot_id'):
                logger.debug(f"Ignoring message with subtype={event.get('subtype')} or bot_id={event.get('bot_id')}")
                return JsonResponse({'status': 'ok'})
            
            # Ignore messages from the bot itself
            event_user = event.get('user', '')
            bot_user_id = get_bot_user_id()
            if bot_user_id and event_user == bot_user_id:
                logger.debug(f"Ignoring message from bot user {bot_user_id}")
                return JsonResponse({'status': 'ok'})
            
            # Ignore if message text is empty (might be a file upload or other non-text message)
            message_text = event.get('text', '').strip()
            if not message_text:
                logger.debug("Ignoring empty message text")
                return JsonResponse({'status': 'ok'})
            
            # Log event details for debugging
            logger.info(f"Processing DM event: user={event_user}, channel={channel}, text={message_text[:50]}")
            
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
    
    # Create event-like dict for logging
    event_dict = {
        'text': text,
        'user': user_id,
        'channel': channel_id,
        'username': request.POST.get('user_name', ''),
    }
    
    if not company_number:
        log_bot_message('command', event_dict, status='error', error_message='No company number found')
        return JsonResponse({
            'response_type': 'ephemeral',
            'text': 'Please provide a valid company number.\nUsage: `/company-info 12345678` or `/company-info AB123456`'
        })
    
    # Log the message
    log_bot_message('command', event_dict, company_number=company_number, status='processed')
    
    # Process company lookup (async response via response_url)
    try:
        slack_service = SlackService()
        company_info = CompanyInfoService.get_company_info(company_number, user=None)
        
        if company_info.get('error'):
            error_msg = company_info['error']
            # Update log with error
            try:
                log = SlackBotLog.objects.filter(
                    slack_user_id=user_id,
                    channel=channel_id,
                    company_number=company_number,
                    message_type='command'
                ).order_by('-created_at').first()
                if log:
                    log.status = 'error'
                    log.error_message = error_msg[:500]
                    log.save()
            except:
                pass
            
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
            
            # Update log to indicate response was sent
            try:
                log = SlackBotLog.objects.filter(
                    slack_user_id=user_id,
                    channel=channel_id,
                    company_number=company_number,
                    message_type='command'
                ).order_by('-created_at').first()
                if log:
                    log.response_sent = True
                    log.status = 'processed'
                    log.save()
            except:
                pass
        except Exception as e:
            logger.error(f"Error sending delayed response: {e}")
        
        # Return immediate acknowledgment
        return JsonResponse({
            'response_type': 'ephemeral',
            'text': f'Fetching information for company {company_number}...'
        })
        
    except Exception as e:
        logger.error(f"Error processing command: {e}", exc_info=True)
        # Update log with error
        try:
            log = SlackBotLog.objects.filter(
                slack_user_id=user_id,
                channel=channel_id,
                company_number=company_number,
                message_type='command'
            ).order_by('-created_at').first()
            if log:
                log.status = 'error'
                log.error_message = str(e)[:500]
                log.save()
        except:
            pass
        
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
        log_bot_message('mention', event, status='error', error_message='No company number found')
        try:
            slack_service = SlackService()
            slack_service.send_message(
                channel=channel,
                text=f"Hi! Please provide a company number. For example: `@trellis-bot 12345678`"
            )
        except Exception as e:
            logger.error(f"Error sending message: {e}")
        return JsonResponse({'status': 'ok'})
    
    # Log the message
    log_bot_message('mention', event, company_number=company_number, status='processed')
    
    # Process company lookup
    try:
        slack_service = SlackService()
        company_info = CompanyInfoService.get_company_info(company_number, user=None)
        
        if company_info.get('error'):
            error_msg = company_info['error']
            # Update log with error
            try:
                log = SlackBotLog.objects.filter(
                    slack_user_id=user,
                    channel=channel,
                    company_number=company_number,
                    message_type='mention'
                ).order_by('-created_at').first()
                if log:
                    log.status = 'error'
                    log.error_message = error_msg[:500]
                    log.save()
            except:
                pass
            
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
        
        # Update log to indicate response was sent
        try:
            log = SlackBotLog.objects.filter(
                slack_user_id=user,
                channel=channel,
                company_number=company_number,
                message_type='mention'
            ).order_by('-created_at').first()
            if log:
                log.response_sent = True
                log.status = 'processed'
                log.save()
        except:
            pass
        
    except Exception as e:
        logger.error(f"Error processing mention: {e}", exc_info=True)
        # Update log with error
        try:
            log = SlackBotLog.objects.filter(
                slack_user_id=user,
                channel=channel,
                company_number=company_number,
                message_type='mention'
            ).order_by('-created_at').first()
            if log:
                log.status = 'error'
                log.error_message = str(e)[:500]
                log.save()
        except:
            pass
        
        try:
            slack_service = SlackService()
            slack_service.send_message(
                channel=channel,
                text="An error occurred while processing your request. Please try again later."
            )
        except:
            pass
    
    return JsonResponse({'status': 'ok'})


def log_bot_message(message_type, event, company_number=None, status='received', error_message=None, response_sent=False):
    """Helper function to log bot messages."""
    try:
        text = event.get('text', '').strip()
        channel = event.get('channel', '')
        user_id = event.get('user', '')
        username = event.get('username', '') or event.get('user_name', '')
        
        SlackBotLog.objects.create(
            message_type=message_type,
            slack_user_id=user_id,
            slack_username=username,
            channel=channel,
            message_text=text[:500],  # Limit text length
            company_number=company_number,
            status=status,
            error_message=error_message[:500] if error_message else None,
            response_sent=response_sent,
        )
    except Exception as e:
        logger.error(f"Error logging bot message: {e}", exc_info=True)


def handle_direct_message(event):
    """Handle direct message events."""
    text = event.get('text', '').strip()
    channel = event.get('channel')
    user = event.get('user')
    
    # Skip if message is empty
    if not text:
        logger.debug("Empty message text, skipping")
        return JsonResponse({'status': 'ok'})
    
    # Log the message for debugging
    logger.info(f"Processing DM from user {user} in channel {channel}: {text[:50]}")
    
    # Extract company number
    company_number = extract_company_number(text)
    
    if not company_number:
        logger.info(f"No company number found in message: {text[:50]}")
        # Log the message
        log_bot_message('dm', event, status='error', error_message='No company number found')
        
        # Only send help message if text doesn't look like it might contain a company number
        # (avoid sending help for empty messages or messages that were already processed)
        try:
            slack_service = SlackService()
            slack_service.send_message(
                channel=channel,
                text="Hi! Please send me a company number and I'll fetch the company information, filings, and previous grants.\n\nExample: `12345678` or `AB123456`"
            )
            # Update log to indicate response was sent
            try:
                log = SlackBotLog.objects.filter(
                    slack_user_id=user,
                    channel=channel,
                    message_text__startswith=text[:50]
                ).order_by('-created_at').first()
                if log:
                    log.response_sent = True
                    log.save()
            except:
                pass
        except Exception as e:
            logger.error(f"Error sending message: {e}")
        return JsonResponse({'status': 'ok'})
    
    logger.info(f"Found company number: {company_number}, processing...")
    
    # Log the message
    log_bot_message('dm', event, company_number=company_number, status='processed')
    
    # Process company lookup
    try:
        slack_service = SlackService()
        company_info = CompanyInfoService.get_company_info(company_number, user=None)
        
        if company_info.get('error'):
            error_msg = company_info['error']
            # Update log with error
            try:
                log = SlackBotLog.objects.filter(
                    slack_user_id=user,
                    channel=channel,
                    company_number=company_number
                ).order_by('-created_at').first()
                if log:
                    log.status = 'error'
                    log.error_message = error_msg[:500]
                    log.save()
            except:
                pass
            
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
        
        # Update log to indicate response was sent
        try:
            log = SlackBotLog.objects.filter(
                slack_user_id=user,
                channel=channel,
                company_number=company_number
            ).order_by('-created_at').first()
            if log:
                log.response_sent = True
                log.status = 'processed'
                log.save()
        except:
            pass
        
    except Exception as e:
        logger.error(f"Error processing DM: {e}", exc_info=True)
        # Update log with error
        try:
            log = SlackBotLog.objects.filter(
                slack_user_id=user,
                channel=channel,
                company_number=company_number
            ).order_by('-created_at').first()
            if log:
                log.status = 'error'
                log.error_message = str(e)[:500]
                log.save()
        except:
            pass
        
        try:
            slack_service = SlackService()
            slack_service.send_message(
                channel=channel,
                text="An error occurred while processing your request. Please try again later."
            )
        except:
            pass
    
    return JsonResponse({'status': 'ok'})

