"""
Services for Slack bot functionality.
"""
import logging
from typing import Dict, List, Optional, Tuple
from django.conf import settings
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from companies.services import CompaniesHouseService, CompaniesHouseError, ThreeSixtyGivingService
from companies.models import Company
from grants.models import Grant

logger = logging.getLogger(__name__)


class SlackService:
    """Service to interact with Slack API."""
    
    def __init__(self, bot_token: Optional[str] = None):
        """
        Initialize Slack client.
        
        Args:
            bot_token: Slack bot token (defaults to SLACK_BOT_TOKEN from settings)
        """
        self.bot_token = bot_token or getattr(settings, 'SLACK_BOT_TOKEN', None)
        if not self.bot_token:
            raise ValueError("SLACK_BOT_TOKEN not configured")
        self.client = WebClient(token=self.bot_token)
    
    def send_message(self, channel: str, text: str = None, blocks: List[Dict] = None):
        """
        Send message to Slack channel.
        
        Args:
            channel: Channel ID or channel name
            text: Plain text message (fallback)
            blocks: Slack Block Kit blocks for rich formatting
        """
        try:
            response = self.client.chat_postMessage(
                channel=channel,
                text=text or "Company information",
                blocks=blocks
            )
            return response
        except SlackApiError as e:
            logger.error(f"Slack API error: {e.response['error']}")
            raise
    
    def send_ephemeral(self, channel: str, user: str, text: str):
        """
        Send ephemeral message (only visible to user).
        
        Args:
            channel: Channel ID
            user: User ID
            text: Message text
        """
        try:
            response = self.client.chat_postEphemeral(
                channel=channel,
                user=user,
                text=text
            )
            return response
        except SlackApiError as e:
            logger.error(f"Slack API error: {e.response['error']}")
            raise


class CompanyInfoService:
    """Service to fetch and format company information."""
    
    @staticmethod
    def get_company_info(company_number: str, user=None) -> Dict:
        """
        Get comprehensive company information.
        Creates company in database if it doesn't exist.
        
        Args:
            company_number: Companies House company number
            user: Optional user to associate with the company (for Slack bot, can be None)
            
        Returns:
            dict with keys: company_data, filings, grants, company_obj, error
        """
        result = {
            'company_data': None,
            'filings': None,
            'grants': [],
            'company_obj': None,
            'error': None
        }
        
        try:
            # Check if company exists in database
            company_obj = None
            try:
                company_obj = Company.objects.get(company_number=company_number)
                logger.info(f"Company {company_number} already exists in database")
            except Company.DoesNotExist:
                # Company doesn't exist - create it
                logger.info(f"Company {company_number} not found, creating new company")
                
                # Fetch company data from Companies House
                api_data = CompaniesHouseService.fetch_company(company_number)
                
                # Fetch filing history
                try:
                    filing_history = CompaniesHouseService.fetch_filing_history(company_number)
                except CompaniesHouseError as e:
                    logger.warning(f"Could not fetch filing history for {company_number}: {e}")
                    filing_history = None
                
                # Normalize data
                normalized_data = CompaniesHouseService.normalize_company_data(api_data, filing_history)
                
                # Create company - use first admin user if no user provided
                if not user:
                    from users.models import User
                    admin_user = User.objects.filter(admin=True).first()
                    if admin_user:
                        user = admin_user
                    else:
                        # Fallback to first user
                        user = User.objects.first()
                
                if not user:
                    raise ValueError("No user available to create company")
                
                # Create company with registered status
                company_obj = Company.objects.create(
                    user=user,
                    is_registered=True,
                    registration_status='registered',
                    **normalized_data
                )
                logger.info(f"Created new company {company_number} in database")
                
                # Attempt to enrich with historical grants from 360Giving (non-blocking)
                try:
                    grants_received = ThreeSixtyGivingService.fetch_grants_received(company_obj.company_number)
                    company_obj.grants_received_360 = grants_received
                    company_obj.save(update_fields=['grants_received_360'])
                except Exception as e:
                    logger.info(f"360Giving lookup skipped for {company_number}: {e}")
            
            # Use company object data
            result['company_obj'] = company_obj
            result['company_data'] = company_obj.raw_data if company_obj.raw_data else {
                'company_name': company_obj.name,
                'company_number': company_obj.company_number,
                'company_status': company_obj.status,
                'company_type': company_obj.company_type,
                'date_of_creation': str(company_obj.date_of_creation) if company_obj.date_of_creation else None,
                'sic_codes': company_obj.sic_codes_array() if company_obj.sic_codes else [],
                'registered_office_address': company_obj.address if company_obj.address else {},
            }
            
            # Get account filings using the company's method
            account_filings = company_obj.get_account_filings()
            result['filings'] = {
                'account_filings': account_filings,
                'total_count': len(account_filings)
            }
            
            # Get grants - check both 360Giving and CompanyGrant relationships
            grants_360 = company_obj.grants_received_360.get('grants', []) if company_obj.grants_received_360 else []
            
            # Get grants from CompanyGrant relationships (all grants, not limited)
            company_grants = Grant.objects.filter(
                company_grants__company=company_obj
            ).select_related().order_by('-created_at')
            
            # Combine grants (360Giving grants are dicts, CompanyGrant grants are objects)
            result['grants'] = {
                'grants_360': grants_360,  # All 360Giving grants
                'company_grants': list(company_grants),  # All grants linked via CompanyGrant
            }
            
        except CompaniesHouseError as e:
            result['error'] = str(e)
            logger.error(f"Error fetching company {company_number}: {e}")
        except Exception as e:
            result['error'] = f"Unexpected error: {str(e)}"
            logger.error(f"Unexpected error fetching company {company_number}: {e}", exc_info=True)
        
        return result
    
    
    @staticmethod
    def format_slack_blocks(company_data: Dict, filings: Dict, grants: Dict, company_obj: Company = None) -> List[Dict]:
        """
        Format company information as Slack Block Kit blocks.
        
        Args:
            company_data: Company data from Companies House API
            filings: Filing history data
            grants: List of Grant objects
            
        Returns:
            List of Slack Block Kit blocks
        """
        blocks = []
        
        # Header
        company_name = company_data.get('company_name', 'Unknown')
        company_number = company_data.get('company_number', '')
        blocks.append({
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{company_name} ({company_number})"
            }
        })
        
        # Company details section
        fields = []
        if company_data.get('company_status'):
            fields.append({
                "type": "mrkdwn",
                "text": f"*Status:* {company_data['company_status']}"
            })
        if company_data.get('company_type'):
            fields.append({
                "type": "mrkdwn",
                "text": f"*Type:* {company_data['company_type']}"
            })
        if company_data.get('date_of_creation'):
            fields.append({
                "type": "mrkdwn",
                "text": f"*Created:* {company_data['date_of_creation']}"
            })
        if company_data.get('sic_codes'):
            from companies.sic_codes import get_sic_description
            sic_codes_list = company_data['sic_codes'][:3]  # First 3 SIC codes
            sic_codes_formatted = ', '.join([
                f"{code} ({get_sic_description(code)})" 
                for code in sic_codes_list
            ])
            fields.append({
                "type": "mrkdwn",
                "text": f"*SIC Codes:* {sic_codes_formatted}"
            })
        
        if fields:
            blocks.append({
                "type": "section",
                "fields": fields
            })
        
        # Address (if available)
        if company_data.get('registered_office_address'):
            addr = company_data['registered_office_address']
            address_parts = [
                addr.get('address_line_1', ''),
                addr.get('address_line_2', ''),
                addr.get('locality', ''),
                addr.get('postal_code', ''),
            ]
            address = ', '.join([p for p in address_parts if p])
            if address:
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Address:* {address}"
                    }
                })
        
        blocks.append({"type": "divider"})
        
        # Account filings (using get_account_filings format)
        account_filings = filings.get('account_filings', []) if filings else []
        if account_filings:
            filing_text = "*Recent Account Filings:*\n"
            for filing in account_filings[:5]:  # Last 5 account filings
                financial_year = filing.get('financial_year', 'N/A')
                made_up_to = filing.get('made_up_to_date', 'N/A')
                account_type = filing.get('account_type', 'Unknown')
                filing_status = filing.get('filing_status', '')
                
                filing_text += f"• *{financial_year}* - Made up to: {made_up_to}\n"
                filing_text += f"  Type: {account_type}, Status: {filing_status}\n"
            
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": filing_text
                }
            })
        else:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Recent Account Filings:* No account filings found"
                }
            })
        
        blocks.append({"type": "divider"})
        
        # Grants - show both 360Giving and linked grants (all grants, not limited)
        grants_360 = grants.get('grants_360', []) if grants else []
        company_grants = grants.get('company_grants', []) if grants else []
        
        grants_text = ""
        has_grants = False
        
        # 360Giving grants (all grants)
        if grants_360:
            has_grants = True
            grants_text += f"*Historic Grants (360Giving) - {len(grants_360)} total:*\n"
            for grant in grants_360:
                title = grant.get('title', grant.get('grant_title', 'Unknown'))
                amount = grant.get('amountAwarded', grant.get('amount_awarded', grant.get('amount', '')))
                award_date = grant.get('awardDate', grant.get('award_date', grant.get('date', '')))
                
                grant_line = f"• {title}"
                if amount:
                    if isinstance(amount, (int, float)):
                        grant_line += f" - £{amount:,.0f}"
                    else:
                        grant_line += f" - {amount}"
                if award_date:
                    grant_line += f" (Awarded: {award_date})"
                grants_text += grant_line + "\n"
        
        # CompanyGrant linked grants (all grants)
        if company_grants:
            has_grants = True
            if grants_text:
                grants_text += "\n"
            grants_text += f"*Linked Grants - {len(company_grants)} total:*\n"
            for grant in company_grants:
                grant_line = f"• {grant.title} ({grant.source})"
                # Add deadline if available (closest thing to grant date for these)
                if grant.deadline:
                    from django.utils import dateformat
                    grant_line += f" - Deadline: {dateformat.format(grant.deadline, 'M d, Y')}"
                elif grant.created_at:
                    from django.utils import dateformat
                    grant_line += f" - Added: {dateformat.format(grant.created_at, 'M d, Y')}"
                grants_text += grant_line + "\n"
        
        if has_grants:
            # Split into multiple blocks if text is too long (Slack has limits)
            # Slack block text limit is 3000 characters, but we'll split at 2000 to be safe
            if len(grants_text) > 2000:
                # Split into chunks
                chunks = []
                current_chunk = ""
                for line in grants_text.split('\n'):
                    if len(current_chunk) + len(line) + 1 > 2000:
                        if current_chunk:
                            chunks.append(current_chunk)
                        current_chunk = line + "\n"
                    else:
                        current_chunk += line + "\n"
                if current_chunk:
                    chunks.append(current_chunk)
                
                for chunk in chunks:
                    blocks.append({
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": chunk
                        }
                    })
            else:
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": grants_text
                    }
                })
        else:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Grants:* No grants found for this company"
                }
            })
        
        return blocks

