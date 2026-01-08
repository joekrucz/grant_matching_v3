"""
Tests for company services (CompaniesHouseService, ChatGPTMatchingService).
"""
import json
import pytest
import responses
from unittest.mock import patch, MagicMock
from companies.services import CompaniesHouseService, CompaniesHouseError
from companies.tests.factories import CompanyFactory
from grants.tests.factories import GrantFactory


@pytest.mark.django_db
class TestCompaniesHouseService:
    """Test CompaniesHouseService."""
    
    @responses.activate
    def test_search_companies_success(self):
        """Test successful company search."""
        responses.add(
            responses.GET,
            'https://api.company-information.service.gov.uk/search/companies',
            json={
                'items': [
                    {
                        'company_number': '12345678',
                        'title': 'Test Company Ltd',
                        'company_status': 'active'
                    }
                ],
                'total_results': 1
            },
            status=200
        )
        
        results = CompaniesHouseService.search_companies('Test Company')
        assert len(results) == 1
        assert results[0]['company_number'] == '12345678'
        assert results[0]['title'] == 'Test Company Ltd'
    
    @responses.activate
    def test_search_companies_api_error(self):
        """Test company search with API error."""
        responses.add(
            responses.GET,
            'https://api.company-information.service.gov.uk/search/companies',
            status=500
        )
        
        with pytest.raises(CompaniesHouseError):
            CompaniesHouseService.search_companies('Test')
    
    @responses.activate
    def test_search_companies_no_results(self):
        """Test company search with no results."""
        responses.add(
            responses.GET,
            'https://api.company-information.service.gov.uk/search/companies',
            json={
                'items': [],
                'total_results': 0
            },
            status=200
        )
        
        results = CompaniesHouseService.search_companies('Nonexistent Company')
        assert len(results) == 0
    
    @responses.activate
    def test_get_company_details_success(self):
        """Test successful company details fetch."""
        responses.add(
            responses.GET,
            'https://api.company-information.service.gov.uk/company/12345678',
            json={
                'company_name': 'Test Company Ltd',
                'company_number': '12345678',
                'company_status': 'active',
                'company_type': 'ltd',
                'date_of_creation': '2020-01-01',
                'registered_office_address': {
                    'address_line_1': '123 Test St',
                    'locality': 'London',
                    'postal_code': 'SW1A 1AA'
                }
            },
            status=200
        )
        
        details = CompaniesHouseService.get_company_details('12345678')
        assert details['company_name'] == 'Test Company Ltd'
        assert details['company_number'] == '12345678'
    
    @responses.activate
    def test_get_company_details_not_found(self):
        """Test company details fetch for non-existent company."""
        responses.add(
            responses.GET,
            'https://api.company-information.service.gov.uk/company/99999999',
            status=404
        )
        
        with pytest.raises(CompaniesHouseError):
            CompaniesHouseService.get_company_details('99999999')


@pytest.mark.django_db
class TestChatGPTMatchingService:
    """Test ChatGPTMatchingService (with mocking)."""
    
    @patch('companies.services.OpenAI')
    def test_match_single_grant_success(self, mock_openai_class):
        """Test successful grant matching."""
        # Mock OpenAI client
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        
        # Mock API response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            'eligibility_score': 0.85,
            'competitiveness_score': 0.75,
            'explanation': 'Good match for the project',
            'eligibility_checklist': ['Requirement 1', 'Requirement 2'],
            'competitiveness_checklist': ['Strength 1'],
            'alignment_points': ['Alignment 1'],
            'concerns': []
        })
        mock_client.chat.completions.create.return_value = mock_response
        
        from companies.services import ChatGPTMatchingService
        service = ChatGPTMatchingService()
        
        grant_data = {
            'title': 'Test Grant',
            'description': 'Grant description',
            'eligibility_checklist': ['Requirement 1', 'Requirement 2']
        }
        
        result = service.match_single_grant('Test project description', grant_data)
        
        assert result['eligibility_score'] == 0.85
        assert result['competitiveness_score'] == 0.75
        assert 'explanation' in result
        mock_client.chat.completions.create.assert_called_once()
    
    @patch('companies.services.OpenAI')
    def test_match_single_grant_api_error(self, mock_openai_class):
        """Test grant matching with API error."""
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception('API Error')
        
        from companies.services import ChatGPTMatchingService
        service = ChatGPTMatchingService()
        
        grant_data = {'title': 'Test Grant', 'description': 'Grant description'}
        
        with pytest.raises(Exception):
            service.match_single_grant('Test project', grant_data)

