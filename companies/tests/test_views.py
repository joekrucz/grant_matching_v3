"""
Tests for company views (authorization, CRUD operations).
"""
import pytest
from django.urls import reverse
from companies.tests.factories import CompanyFactory, FundingSearchFactory
from users.tests.factories import UserFactory


@pytest.mark.django_db
class TestCompanyList:
    """Test company list view."""
    
    def test_company_list_requires_login(self, client):
        """Test company list requires authentication."""
        response = client.get(reverse('companies:list'))
        assert response.status_code == 302  # Redirect to login
    
    def test_company_list_shows_user_companies(self, client, user):
        """Test company list shows only user's companies."""
        company = CompanyFactory(user=user)
        other_company = CompanyFactory()  # Different user
        
        client.force_login(user)
        response = client.get(reverse('companies:list'))
        
        assert response.status_code == 200
        content = response.content.decode()
        assert company.name in content
        # Non-admin users should only see their own companies
        if not user.admin:
            assert other_company.name not in content


@pytest.mark.django_db
class TestCompanyDetail:
    """Test company detail view."""
    
    def test_company_detail_requires_login(self, client):
        """Test company detail requires authentication."""
        company = CompanyFactory()
        response = client.get(reverse('companies:detail', args=[company.id]))
        assert response.status_code == 302  # Redirect to login
    
    def test_company_detail_owner_can_access(self, client, user):
        """Test company owner can access detail page."""
        company = CompanyFactory(user=user)
        client.force_login(user)
        response = client.get(reverse('companies:detail', args=[company.id]))
        assert response.status_code == 200
    
    def test_company_detail_other_user_cannot_access(self, client):
        """Test other users cannot access company detail."""
        owner = UserFactory()
        other_user = UserFactory()
        company = CompanyFactory(user=owner)
        
        client.force_login(other_user)
        response = client.get(reverse('companies:detail', args=[company.id]))
        # Should redirect or show error
        assert response.status_code in [302, 403, 404]
    
    def test_company_detail_admin_can_access(self, client, admin_user):
        """Test admin can access any company detail."""
        owner = UserFactory()
        company = CompanyFactory(user=owner)
        
        client.force_login(admin_user)
        response = client.get(reverse('companies:detail', args=[company.id]))
        assert response.status_code == 200


@pytest.mark.django_db
class TestCompanyCreate:
    """Test company creation."""
    
    def test_company_create_requires_login(self, client):
        """Test company create requires authentication."""
        response = client.get(reverse('companies:create'))
        assert response.status_code == 302  # Redirect to login
    
    def test_company_create_get(self, client, user):
        """Test company create page loads."""
        client.force_login(user)
        response = client.get(reverse('companies:create'))
        assert response.status_code == 200
    
    def test_company_create_post(self, client, user):
        """Test company creation via POST."""
        client.force_login(user)
        response = client.post(reverse('companies:create'), {
            'company_number': '12345678',
            'name': 'New Company',
        })
        # Should redirect after creation
        assert response.status_code == 302
        assert user.companies.filter(company_number='12345678').exists()


@pytest.mark.django_db
class TestCompanyDelete:
    """Test company deletion."""
    
    def test_company_delete_requires_login(self, client):
        """Test company delete requires authentication."""
        company = CompanyFactory()
        response = client.post(reverse('companies:delete', args=[company.id]))
        assert response.status_code == 302  # Redirect to login
    
    def test_company_delete_owner_can_delete(self, client, user):
        """Test company owner can delete."""
        company = CompanyFactory(user=user)
        client.force_login(user)
        response = client.post(reverse('companies:delete', args=[company.id]))
        assert response.status_code == 302  # Redirect after deletion
        assert not CompanyFactory._meta.model.objects.filter(id=company.id).exists()
    
    def test_company_delete_other_user_cannot_delete(self, client):
        """Test other users cannot delete company."""
        owner = UserFactory()
        other_user = UserFactory()
        company = CompanyFactory(user=owner)
        
        client.force_login(other_user)
        response = client.post(reverse('companies:delete', args=[company.id]))
        # Should not allow deletion
        assert response.status_code in [302, 403, 404]
        assert CompanyFactory._meta.model.objects.filter(id=company.id).exists()


@pytest.mark.django_db
class TestFundingSearch:
    """Test funding search views."""
    
    def test_funding_search_list_requires_login(self, client):
        """Test funding search list requires authentication."""
        response = client.get(reverse('companies:funding_searches_list'))
        assert response.status_code == 302  # Redirect to login
    
    def test_funding_search_detail_requires_login(self, client):
        """Test funding search detail requires authentication."""
        search = FundingSearchFactory()
        response = client.get(reverse('companies:funding_search_detail', args=[search.id]))
        assert response.status_code == 302  # Redirect to login
    
    def test_funding_search_detail_owner_can_access(self, client, user):
        """Test funding search owner can access detail."""
        company = CompanyFactory(user=user)
        search = FundingSearchFactory(company=company, user=user)
        client.force_login(user)
        response = client.get(reverse('companies:funding_search_detail', args=[search.id]))
        assert response.status_code == 200




