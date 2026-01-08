"""
Test factories for companies app.
"""
import factory
from companies.models import Company, FundingSearch
from users.tests.factories import UserFactory


class CompanyFactory(factory.django.DjangoModelFactory):
    """Factory for creating test companies."""
    
    class Meta:
        model = Company
    
    name = factory.Faker('company')
    company_number = factory.Sequence(lambda n: f'{n:08d}')
    user = factory.SubFactory(UserFactory)
    is_registered = True
    registration_status = 'registered'
    company_type = 'ltd'
    status = 'active'
    address = factory.LazyFunction(lambda: {
        'address_line_1': '123 Test Street',
        'locality': 'London',
        'postal_code': 'SW1A 1AA',
        'country': 'England'
    })
    sic_codes = '12345, 67890'
    raw_data = factory.LazyFunction(lambda: {
        'company_name': 'Test Company Ltd',
        'company_number': '12345678'
    })


class UnregisteredCompanyFactory(CompanyFactory):
    """Factory for creating unregistered companies."""
    company_number = None
    is_registered = False
    registration_status = 'unregistered'


class FundingSearchFactory(factory.django.DjangoModelFactory):
    """Factory for creating funding searches."""
    
    class Meta:
        model = FundingSearch
    
    name = factory.Faker('sentence', nb_words=3)
    company = factory.SubFactory(CompanyFactory)
    user = factory.LazyAttribute(lambda obj: obj.company.user)
    project_description = factory.Faker('text', max_nb_chars=500)
    matching_status = 'pending'






