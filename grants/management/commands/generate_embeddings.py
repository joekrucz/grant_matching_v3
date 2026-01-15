"""
Management command to generate embeddings for grants.
"""
from django.core.management.base import BaseCommand
from django.db import models
from django.utils import timezone
from grants.models import Grant
from grants.embedding_service import EmbeddingService
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Generate embeddings for grants (all grants or specific ones)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--grant-id',
            type=int,
            help='Generate embedding for a specific grant ID',
        )
        parser.add_argument(
            '--grant-slug',
            type=str,
            help='Generate embedding for a specific grant slug',
        )
        parser.add_argument(
            '--source',
            type=str,
            help='Generate embeddings for all grants from a specific source',
        )
        parser.add_argument(
            '--missing-only',
            action='store_true',
            help='Only generate embeddings for grants that don\'t have one yet',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Limit the number of grants to process',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Regenerate embeddings even if they already exist',
        )

    def handle(self, *args, **options):
        try:
            embedding_service = EmbeddingService()
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Failed to initialize embedding service: {e}')
            )
            return

        # Determine which grants to process
        grants = Grant.objects.all()

        if options['grant_id']:
            grants = grants.filter(id=options['grant_id'])
        elif options['grant_slug']:
            grants = grants.filter(slug=options['grant_slug'])
        elif options['source']:
            grants = grants.filter(source=options['source'])

        if options['missing_only']:
            grants = grants.filter(
                models.Q(embedding__isnull=True) | models.Q(embedding=[])
            )

        if options['limit']:
            grants = grants[:options['limit']]

        total_grants = grants.count()
        self.stdout.write(f'Processing {total_grants} grant(s)...')

        if total_grants == 0:
            self.stdout.write(self.style.WARNING('No grants found to process.'))
            return

        success_count = 0
        error_count = 0
        skipped_count = 0

        for idx, grant in enumerate(grants, 1):
            # Skip if embedding exists and not forcing
            if not options['force'] and grant.embedding:
                skipped_count += 1
                if idx % 10 == 0:
                    self.stdout.write(f'  Processed {idx}/{total_grants}... (skipped: {skipped_count})')
                continue

            try:
                # Generate embedding text
                embedding_text = embedding_service.generate_grant_embedding_text(grant)
                
                if not embedding_text or not embedding_text.strip():
                    self.stdout.write(
                        self.style.WARNING(f'  Grant {grant.id} ({grant.slug}): No content to embed, skipping')
                    )
                    skipped_count += 1
                    continue

                # Generate embedding
                embedding = embedding_service.generate_embedding(embedding_text)

                # Save to grant
                grant.embedding = embedding
                grant.embedding_updated_at = timezone.now()
                grant.save(update_fields=['embedding', 'embedding_updated_at'])

                success_count += 1

                if idx % 10 == 0:
                    self.stdout.write(
                        f'  Processed {idx}/{total_grants}... '
                        f'(success: {success_count}, errors: {error_count}, skipped: {skipped_count})'
                    )

            except Exception as e:
                error_count += 1
                logger.error(f'Error generating embedding for grant {grant.id} ({grant.slug}): {e}', exc_info=True)
                self.stdout.write(
                    self.style.ERROR(f'  Grant {grant.id} ({grant.slug}): {e}')
                )

        # Summary
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Completed!'))
        self.stdout.write(f'  Success: {success_count}')
        self.stdout.write(f'  Errors: {error_count}')
        self.stdout.write(f'  Skipped: {skipped_count}')
        self.stdout.write(f'  Total: {total_grants}')
