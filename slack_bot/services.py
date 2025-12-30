"""
Services for Slack bot functionality.
"""
import logging
from typing import Dict, List, Optional, Tuple
from django.conf import settings
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from companies.services import CompaniesHouseService, CompaniesHouseError
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
    def get_company_info(company_number: str) -> Dict:
        """
        Get comprehensive company information.
        
        Args:
            company_number: Companies House company number
            
        Returns:
            dict with keys: company_data, filings, grants, error
        """
        result = {
            'company_data': None,
            'filings': None,
            'grants': [],
            'error': None
        }
        
        try:
            # Fetch company data from Companies House
            company_data = CompaniesHouseService.fetch_company(company_number)
            result['company_data'] = company_data
            
            # Fetch filing history
            try:
                filings = CompaniesHouseService.fetch_filing_history(company_number)
                result['filings'] = filings
            except CompaniesHouseError as e:
                logger.warning(f"Could not fetch filing history for {company_number}: {e}")
                result['filings'] = {'items': [], 'total_count': 0}
            
            # Get grants from database
            result['grants'] = CompanyInfoService.get_company_grants(company_number)
            
        except CompaniesHouseError as e:
            result['error'] = str(e)
            logger.error(f"Error fetching company {company_number}: {e}")
        except Exception as e:
            result['error'] = f"Unexpected error: {str(e)}"
            logger.error(f"Unexpected error fetching company {company_number}: {e}", exc_info=True)
        
        return result
    
    @staticmethod
    def get_company_grants(company_number: str) -> List[Grant]:
        """
        Get grants associated with a company.
        
        Args:
            company_number: Companies House company number
            
        Returns:
            List of Grant objects
        """
        try:
            company = Company.objects.get(company_number=company_number)
            grants = Grant.objects.filter(
                company_grants__company=company
            ).select_related().order_by('-created_at')[:10]
            return list(grants)
        except Company.DoesNotExist:
            return []
        except Exception as e:
            logger.error(f"Error fetching grants for company {company_number}: {e}")
            return []
    
    @staticmethod
    def format_slack_blocks(company_data: Dict, filings: Dict, grants: List[Grant]) -> List[Dict]:
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
            sic_codes = ', '.join(company_data['sic_codes'][:3])  # First 3 SIC codes
            fields.append({
                "type": "mrkdwn",
                "text": f"*SIC Codes:* {sic_codes}"
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
        
        # Recent filings
        if filings and filings.get('items'):
            filing_items = filings['items'][:5]  # Last 5 filings
            filing_text = "*Recent Filings:*\n"
            for filing in filing_items:
                description = filing.get('description', 'Unknown')
                date = filing.get('date', '')
                filing_text += f"• {description} ({date})\n"
            
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
                    "text": "*Recent Filings:* No filings found"
                }
            })
        
        blocks.append({"type": "divider"})
        
        # Previous grants
        if grants:
            grants_text = "*Previous Grants:*\n"
            for grant in grants[:5]:  # Last 5 grants
                grants_text += f"• {grant.title} ({grant.source})\n"
            
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
                    "text": "*Previous Grants:* No grants found for this company"
                }
            })
        
        return blocks

