"""
Tests for Company and FundingSearch models.
"""
import pytest
import json
from companies.models import Company, FundingSearch
from companies.tests.factories import CompanyFactory, UnregisteredCompanyFactory, FundingSearchFactory


@pytest.mark.django_db
class TestCompany:
    """Test Company model methods."""
    
    def test_company_str_with_number(self):
        """Test company string representation with company number."""
        company = CompanyFactory(company_number='12345678', name='Test Company')
        assert str(company) == 'Test Company (12345678)'
    
    def test_company_str_unregistered(self):
        """Test company string representation without company number."""
        company = UnregisteredCompanyFactory(name='Unregistered Co')
        assert str(company) == 'Unregistered Co (Unregistered)'
    
    def test_sic_codes_array_from_json(self):
        """Test SIC codes array parsing from JSON format."""
        company = CompanyFactory(sic_codes='["12345", "67890"]')
        codes = company.sic_codes_array()
        assert codes == ['12345', '67890']
    
    def test_sic_codes_array_from_string(self):
        """Test SIC codes array parsing from comma-separated string."""
        company = CompanyFactory(sic_codes='12345, 67890, 11111')
        codes = company.sic_codes_array()
        assert codes == ['12345', '67890', '11111']
    
    def test_sic_codes_array_empty(self):
        """Test SIC codes array with empty value."""
        company = CompanyFactory(sic_codes=None)
        assert company.sic_codes_array() == []
        
        company.sic_codes = ''
        assert company.sic_codes_array() == []
    
    def test_formatted_address(self):
        """Test formatted address generation."""
        company = CompanyFactory(address={
            'address_line_1': '123 Test Street',
            'locality': 'London',
            'postal_code': 'SW1A 1AA',
            'country': 'England'
        })
        address = company.formatted_address()
        assert '123 Test Street' in address
        assert 'London' in address
        assert 'SW1A 1AA' in address
        assert 'England' in address
    
    def test_formatted_address_empty(self):
        """Test formatted address with empty address."""
        company = CompanyFactory(address={})
        assert company.formatted_address() == ''
        
        company.address = None
        assert company.formatted_address() == ''
    
    def test_get_account_filings_empty(self):
        """Test account filings with no filing history."""
        company = CompanyFactory(filing_history={})
        assert company.get_account_filings() == []
        
        company.filing_history = None
        assert company.get_account_filings() == []
    
    def test_get_account_filings_with_data(self):
        """Test account filings extraction."""
        company = CompanyFactory(filing_history={
            'items': [
                {
                    'category': 'accounts',
                    'date': '2024-01-15',
                    'description': 'accounts-with-made-up-date',
                    'description_values': {
                        'made_up_date': '2023-12-31',
                        'account_type': 'small'
                    },
                    'links': {
                        'self': '/filing/123'
                    }
                }
            ]
        })
        filings = company.get_account_filings()
        assert len(filings) == 1
        assert filings[0]['made_up_to_date'] == '2023-12-31'


@pytest.mark.django_db
class TestFundingSearch:
    """Test FundingSearch model."""
    
    def test_funding_search_creation(self):
        """Test funding search creation."""
        search = FundingSearchFactory(name='Test Search')
        assert search.name == 'Test Search'
        assert search.matching_status == 'pending'
        assert search.company is not None
        assert search.user is not None
    
    def test_funding_search_user_relationship(self):
        """Test funding search user relationship."""
        search = FundingSearchFactory()
        assert search.user == search.company.user






