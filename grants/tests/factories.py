"""
Test factories for grants app.
"""
import factory
from django.utils import timezone
from datetime import timedelta
from grants.models import Grant, ScrapeLog
import hashlib


class GrantFactory(factory.django.DjangoModelFactory):
    """Factory for creating test grants."""
    
    class Meta:
        model = Grant
    
    title = factory.Faker('sentence', nb_words=6)
    slug = factory.Sequence(lambda n: f"test-grant-{n}")
    source = 'ukri'
    summary = factory.Faker('text', max_nb_chars=200)
    description = factory.Faker('text', max_nb_chars=1000)
    url = factory.Faker('url')
    funding_amount = '£100,000 - £500,000'
    deadline = factory.LazyFunction(lambda: timezone.now() + timedelta(days=30))
    status = 'open'
    hash_checksum = factory.LazyAttribute(lambda obj: hashlib.sha256(
        f"{obj.title}{obj.source}{obj.url}".encode()
    ).hexdigest())
    raw_data = factory.LazyFunction(lambda: {
        'title': 'Test Grant',
        'source': 'ukri'
    })


class ClosedGrantFactory(GrantFactory):
    """Factory for creating closed grants."""
    deadline = factory.LazyFunction(lambda: timezone.now() - timedelta(days=1))
    status = 'closed'


class ScrapeLogFactory(factory.django.DjangoModelFactory):
    """Factory for creating scrape logs."""
    
    class Meta:
        model = ScrapeLog
    
    source = 'ukri'
    status = 'success'
    grants_created = 10
    grants_updated = 5
    grants_skipped = 2

