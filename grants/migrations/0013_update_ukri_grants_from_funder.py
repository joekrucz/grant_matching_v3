# Generated manually to update existing UKRI grants based on funder data

from django.db import migrations


def map_funder_to_source(funder_text):
    """
    Map UKRI funder name to source code.
    Returns the source code or 'ukri' as fallback.
    """
    if not funder_text:
        return 'ukri'
    
    funder_lower = funder_text.lower()
    
    # Map common UKRI council names to source codes
    council_mappings = {
        'bbsrc': 'bbsrc',
        'biotechnology and biological sciences research council': 'bbsrc',
        'epsrc': 'epsrc',
        'engineering and physical sciences research council': 'epsrc',
        'mrc': 'mrc',
        'medical research council': 'mrc',
        'stfc': 'stfc',
        'science and technology facilities council': 'stfc',
        'ahrc': 'ahrc',
        'arts and humanities research council': 'ahrc',
        'esrc': 'esrc',
        'economic and social research council': 'esrc',
        'nerc': 'nerc',
        'natural environment research council': 'nerc',
        'innovate uk': 'innovate_uk',
    }
    
    # Check for exact matches or partial matches
    for key, source_code in council_mappings.items():
        if key in funder_lower:
            return source_code
    
    # Fallback to 'ukri' if no match
    return 'ukri'


def update_ukri_grants_from_funder(apps, schema_editor):
    """
    Update existing UKRI grants to use specific council sources based on funder data.
    Only updates grants that:
    1. Currently have source='ukri'
    2. Have funder information in raw_data
    """
    Grant = apps.get_model('grants', 'Grant')
    
    # Get all grants with source='ukri'
    ukri_grants = Grant.objects.filter(source='ukri')
    
    updated_count = 0
    skipped_count = 0
    
    for grant in ukri_grants:
        # Try to extract funder from raw_data
        funder = None
        raw_data = grant.raw_data or {}
        
        # Check opportunity_summary for funder
        opportunity_summary = raw_data.get('opportunity_summary', {})
        if isinstance(opportunity_summary, dict):
            # Look for "Funders:" key (with or without colon)
            funder = opportunity_summary.get('Funders:') or opportunity_summary.get('Funders')
        
        # If not found, try other possible locations
        if not funder:
            # Check if funder is stored directly in raw_data
            funder = raw_data.get('funder')
        
        if funder:
            # Map funder to source
            new_source = map_funder_to_source(funder)
            
            if new_source != 'ukri':
                grant.source = new_source
                grant.save(update_fields=['source'])
                updated_count += 1
            else:
                skipped_count += 1
        else:
            skipped_count += 1
    
    print(f"Updated {updated_count} UKRI grants to specific council sources")
    print(f"Skipped {skipped_count} UKRI grants (no funder data or couldn't map)")


def reverse_update_ukri_grants(apps, schema_editor):
    """
    Reverse migration: set all UKRI council grants back to 'ukri'.
    """
    Grant = apps.get_model('grants', 'Grant')
    
    ukri_council_sources = ['bbsrc', 'epsrc', 'mrc', 'stfc', 'ahrc', 'esrc', 'nerc']
    
    # Set all UKRI council grants back to 'ukri'
    updated = Grant.objects.filter(source__in=ukri_council_sources).update(source='ukri')
    print(f"Reverted {updated} grants back to source='ukri'")


class Migration(migrations.Migration):

    dependencies = [
        ('grants', '0012_add_ukri_council_sources'),
    ]

    operations = [
        migrations.RunPython(
            update_ukri_grants_from_funder,
            reverse_update_ukri_grants,
        ),
    ]
