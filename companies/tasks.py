"""
Celery tasks for grant matching.
"""
import logging
from django.utils import timezone
from django.db import transaction
from .models import FundingSearch, GrantMatchResult
from .services import ChatGPTMatchingService, GrantMatchingError
from grants.models import Grant

logger = logging.getLogger(__name__)

# Import Celery safely
try:
    from celery import shared_task
    CELERY_TASKS_AVAILABLE = True
except Exception as e:
    logger.warning(f"Celery tasks not available: {e}")
    CELERY_TASKS_AVAILABLE = False
    # Create a dummy decorator
    def shared_task(*args, **kwargs):
        def decorator(func):
            return func
        return decorator


if CELERY_TASKS_AVAILABLE:
    @shared_task(bind=True)
    def match_grants_with_chatgpt(self, funding_search_id, limit=None):
        """
        Match grants using ChatGPT API with batch processing.
        
        Args:
            funding_search_id: ID of the FundingSearch to match grants for
            limit: Optional limit on number of grants to match (for testing)
        
        Returns:
            dict with status, matches_created, grants_processed
        """
        logger.info(f"match_grants_with_chatgpt task started for funding_search_id: {funding_search_id}, limit: {limit}")
        
        funding_search = FundingSearch.objects.get(id=funding_search_id)
        
        funding_search.matching_status = 'running'
        funding_search.matching_progress = {
            'current': 0, 
            'total': 0, 
            'percentage': 0,
            'stage': 'processing_sources',
            'stage_message': 'Processing input sources...'
        }
        funding_search.save()
        
        # Helper function to check if matching was cancelled
        def is_cancelled():
            try:
                funding_search.refresh_from_db()
                return funding_search.matching_status == 'cancelled'
            except Exception:
                return False
        
        try:
            # Check for cancellation before starting
            if is_cancelled():
                logger.info(f"Matching cancelled before starting for funding search {funding_search_id}")
                return {'status': 'cancelled', 'matches_created': 0, 'grants_processed': 0}
            
            # Compile text from all selected input sources (this includes scraping website if selected)
            logger.info("Compiling input sources (this may include website scraping)...")
            project_text = funding_search.compile_input_sources_text()
            logger.info(f"Found funding search: {funding_search.name}, compiled input sources length: {len(project_text or '')}")
            if not project_text:
                raise ValueError("No input sources available. Please select company files, notes, website, or add a project description.")
            
            logger.info(f"Input sources compiled. Total text length: {len(project_text)} characters")
            
            # Check for cancellation after compiling sources
            if is_cancelled():
                logger.info(f"Matching cancelled after compiling sources for funding search {funding_search_id}")
                return {'status': 'cancelled', 'matches_created': 0, 'grants_processed': 0}
            
            # Update progress to show we're ready to match
            total_grants = len(grants_list) if 'grants_list' in locals() else 0
            funding_search.matching_progress = {
                'current': 0,
                'total': total_grants,
                'percentage': 0,
                'stage': 'ready_to_match',
                'stage_message': f'Input sources processed. Starting grant matching for {total_grants} grants...'
            }
            funding_search.save()
            
            # Check for cancellation before fetching grants
            if is_cancelled():
                logger.info(f"Matching cancelled before fetching grants for funding search {funding_search_id}")
                return {'status': 'cancelled', 'matches_created': 0, 'grants_processed': 0}
            
            # Get grants (with optional limit for testing and source filtering)
            grants = Grant.objects.all().order_by('-created_at')
            
            # Filter by selected grant sources if specified (if empty list, match all sources)
            selected_sources = funding_search.selected_grant_sources
            if selected_sources and len(selected_sources) > 0:
                grants = grants.filter(source__in=selected_sources)
                logger.info(f"Filtering grants by sources: {selected_sources}")
            else:
                logger.info("No source filter applied - matching against all grant sources")
            
            # Filter out closed competitions if option is enabled
            if funding_search.exclude_closed_competitions:
                now = timezone.now()
                # Exclude grants where deadline is in the past
                grants = grants.exclude(deadline__lt=now)
                logger.info("Excluding closed competitions from matching")
            else:
                logger.info("Including all competitions (including closed) in matching")
            
            if limit:
                grants = grants[:limit]
            # Get grants with their checklists
            grants_list = []
            for grant in grants:
                # Check for cancellation during grant list building
                if is_cancelled():
                    logger.info(f"Matching cancelled while building grant list for funding search {funding_search_id}")
                    return {'status': 'cancelled', 'matches_created': 0, 'grants_processed': 0}
                grant_data = {
                    'id': grant.id,
                    'title': grant.title,
                    'source': grant.source,
                    'summary': grant.summary,
                    'description': grant.description,
                    'funding_amount': grant.funding_amount,
                    'deadline': grant.deadline,
                    'status': grant.get_computed_status(),
                    'slug': grant.slug,
                    'eligibility_checklist': grant.eligibility_checklist,
                    'competitiveness_checklist': grant.competitiveness_checklist,
                    'exclusions_checklist': grant.exclusions_checklist,
                }
                grants_list.append(grant_data)
            logger.info(f"Found {len(grants_list)} grants to match against" + (f" (limited to {limit})" if limit else ""))
            
            # Update progress with total grants count
            funding_search.matching_progress = {
                'current': 0,
                'total': len(grants_list),
                'percentage': 0,
                'stage': 'ready_to_match',
                'stage_message': f'Input sources processed. Starting grant matching for {len(grants_list)} grants...'
            }
            funding_search.save()
            
            # Initialize matcher
            try:
                logger.info("Initializing ChatGPTMatchingService...")
                matcher = ChatGPTMatchingService()
                logger.info("ChatGPTMatchingService initialized successfully")
            except GrantMatchingError as e:
                logger.error(f"Failed to initialize matching service: {e}", exc_info=True)
                raise Exception(f"Failed to initialize matching service: {str(e)}")
            
            # Progress tracking function - updates database for real-time progress
            # Split into sync and async parts to handle Celery task context properly
            def update_database_progress(current, total):
                """Update database progress (can be called from async context)."""
                percentage = (current / total) * 100 if total > 0 else 0
                FundingSearch.objects.filter(id=funding_search_id).update(
                    matching_progress={
                        'current': current,
                        'total': total,
                        'percentage': round(percentage, 1),
                        'stage': 'matching',
                        'stage_message': f'Matching grant {current} of {total}...'
                    }
                )
                logger.info(f"Progress update: {current}/{total} ({percentage:.1f}%)")
            
            def progress_callback(current, total):
                percentage = (current / total) * 100 if total > 0 else 0
                # Update Celery task state (must run in original context, not thread pool)
                self.update_state(
                    state='PROGRESS',
                    meta={'current': current, 'total': total, 'progress': f'{percentage:.1f}%'}
                )
                # Update database for real-time frontend polling
                update_database_progress(current, total)
            
            # Check for cancellation before starting matching
            if is_cancelled():
                logger.info(f"Matching cancelled before starting grant matching for funding search {funding_search_id}")
                return {'status': 'cancelled', 'matches_created': 0, 'grants_processed': 0}
            
            # Match all grants (don't delete old results yet - we'll do that atomically after saving new ones)
            logger.info(f"Starting matching for {len(grants_list)} grants...")
            match_results = matcher.match_all_grants(
                project_text,
                grants_list,
                progress_callback=progress_callback,
                let_system_decide_trl=funding_search.let_system_decide_trl,
                funding_search_id=funding_search_id
            )
            
            # Check for cancellation after matching completes
            if is_cancelled():
                logger.info(f"Matching cancelled after completion for funding search {funding_search_id}")
                return {'status': 'cancelled', 'matches_created': 0, 'grants_processed': len(match_results)}
            
            logger.info(f"Matching completed. Got {len(match_results)} results")
            
            # Save results to database and atomically replace old results
            # Use a transaction to ensure we don't lose data if saving fails
            matches_created = 0
            matches_updated = 0
            new_grant_ids = set()  # Track which grants have new results
            
            # OPTIMIZATION: Prefetch all grants to avoid N+1 queries
            # Collect all grant IDs from match results
            grant_ids = []
            for result in match_results:
                grant_idx = result['grant_index']
                if grant_idx < len(grants_list):
                    grant_ids.append(grants_list[grant_idx]['id'])
            
            # Fetch all grants in a single query
            grants_dict = {g.id: g for g in Grant.objects.filter(id__in=grant_ids)}
            logger.info(f"Prefetched {len(grants_dict)} grants for matching results")
            
            with transaction.atomic():
                # First, save all new results (this will update existing ones due to unique constraint)
                for result in match_results:
                    # Check for cancellation while saving results
                    if is_cancelled():
                        logger.info(f"Matching cancelled while saving results for funding search {funding_search_id}")
                        break
                    grant_idx = result['grant_index']
                    if grant_idx < len(grants_list):
                        grant_data = grants_list[grant_idx]
                        grant_id = grant_data['id']
                        
                        # Use prefetched grant instead of querying database
                        grant = grants_dict.get(grant_id)
                        if not grant:
                            # Grant was deleted between matching and saving - skip this result
                            logger.warning(f"Grant {grant_id} not found in prefetched grants, skipping result")
                            continue
                    
                    # Get original checklists from grant to preserve exact criterion text
                    grant_eligibility_checklist = grant_data.get('eligibility_checklist', {})
                    grant_eligibility_items = grant_eligibility_checklist.get('checklist_items', [])
                    
                    grant_competitiveness_checklist = grant_data.get('competitiveness_checklist', {})
                    grant_competitiveness_items = grant_competitiveness_checklist.get('checklist_items', [])
                    
                    grant_exclusions_checklist = grant_data.get('exclusions_checklist', {})
                    grant_exclusions_items = grant_exclusions_checklist.get('checklist_items', [])
                    
                    # Map ChatGPT evaluations to original checklist items
                    # This ensures we preserve the exact criterion text from the grant page
                    eligibility_checklist_result = []
                    if grant_eligibility_items:
                        # Use original items from grant
                        chatgpt_evaluations = result.get('eligibility_checklist', [])
                        
                        # First, try to match by exact text
                        chatgpt_by_text = {item.get('criterion', '').strip(): item for item in chatgpt_evaluations}
                        
                        # Also create index-based mapping in case order is preserved
                        chatgpt_by_index = {i: item for i, item in enumerate(chatgpt_evaluations)}
                        
                        for idx, original_item in enumerate(grant_eligibility_items):
                            original_text = original_item.strip()
                            
                            # Try exact match first
                            evaluation = chatgpt_by_text.get(original_text)
                            
                            # Try by index if same length and no exact match
                            if not evaluation and idx < len(chatgpt_evaluations):
                                evaluation = chatgpt_by_index.get(idx)
                                # Verify it's a reasonable match (at least partial text match)
                                if evaluation:
                                    eval_text = evaluation.get('criterion', '').strip()
                                    if not (original_text.lower() in eval_text.lower() or eval_text.lower() in original_text.lower()):
                                        evaluation = None
                            
                            # Try partial match as fallback
                            if not evaluation:
                                for key, val in chatgpt_by_text.items():
                                    if original_text.lower() in key.lower() or key.lower() in original_text.lower():
                                        evaluation = val
                                        break
                            
                            if evaluation:
                                eligibility_checklist_result.append({
                                    'criterion': original_item,  # Use exact text from grant
                                    'status': evaluation.get('status', 'don\'t know'),
                                    'reason': evaluation.get('reason', '')
                                })
                            else:
                                # If no evaluation found, mark as "don't know"
                                eligibility_checklist_result.append({
                                    'criterion': original_item,
                                    'status': 'don\'t know',
                                    'reason': 'Evaluation not provided'
                                })
                    else:
                        # No pre-generated checklist, use ChatGPT's extracted items
                        eligibility_checklist_result = result.get('eligibility_checklist', [])
                    
                    competitiveness_checklist_result = []
                    if grant_competitiveness_items:
                        # Use original items from grant
                        chatgpt_evaluations = result.get('competitiveness_checklist', [])
                        
                        # First, try to match by exact text
                        chatgpt_by_text = {item.get('criterion', '').strip(): item for item in chatgpt_evaluations}
                        
                        # Also create index-based mapping in case order is preserved
                        chatgpt_by_index = {i: item for i, item in enumerate(chatgpt_evaluations)}
                        
                        for idx, original_item in enumerate(grant_competitiveness_items):
                            original_text = original_item.strip()
                            
                            # Try exact match first
                            evaluation = chatgpt_by_text.get(original_text)
                            
                            # Try by index if same length and no exact match
                            if not evaluation and idx < len(chatgpt_evaluations):
                                evaluation = chatgpt_by_index.get(idx)
                                # Verify it's a reasonable match (at least partial text match)
                                if evaluation:
                                    eval_text = evaluation.get('criterion', '').strip()
                                    if not (original_text.lower() in eval_text.lower() or eval_text.lower() in original_text.lower()):
                                        evaluation = None
                            
                            # Try partial match as fallback
                            if not evaluation:
                                for key, val in chatgpt_by_text.items():
                                    if original_text.lower() in key.lower() or key.lower() in original_text.lower():
                                        evaluation = val
                                        break
                            
                            if evaluation:
                                competitiveness_checklist_result.append({
                                    'criterion': original_item,  # Use exact text from grant
                                    'status': evaluation.get('status', 'don\'t know'),
                                    'reason': evaluation.get('reason', '')
                                })
                            else:
                                # If no evaluation found, mark as "don't know"
                                competitiveness_checklist_result.append({
                                    'criterion': original_item,
                                    'status': 'don\'t know',
                                    'reason': 'Evaluation not provided'
                                })
                    else:
                        # No pre-generated checklist, use ChatGPT's extracted items
                        competitiveness_checklist_result = result.get('competitiveness_checklist', [])
                    
                    exclusions_checklist_result = []
                    if grant_exclusions_items:
                        # Use original items from grant
                        chatgpt_evaluations = result.get('exclusions_checklist', [])
                        
                        # First, try to match by exact text
                        chatgpt_by_text = {item.get('criterion', '').strip(): item for item in chatgpt_evaluations}
                        
                        # Also create index-based mapping in case order is preserved
                        chatgpt_by_index = {i: item for i, item in enumerate(chatgpt_evaluations)}
                        
                        for idx, original_item in enumerate(grant_exclusions_items):
                            original_text = original_item.strip()
                            
                            # Try exact match first
                            evaluation = chatgpt_by_text.get(original_text)
                            
                            # Try by index if same length and no exact match
                            if not evaluation and idx < len(chatgpt_evaluations):
                                evaluation = chatgpt_by_index.get(idx)
                                # Verify it's a reasonable match (at least partial text match)
                                if evaluation:
                                    eval_text = evaluation.get('criterion', '').strip()
                                    if not (original_text.lower() in eval_text.lower() or eval_text.lower() in original_text.lower()):
                                        evaluation = None
                            
                            # Try partial match as fallback
                            if not evaluation:
                                for key, val in chatgpt_by_text.items():
                                    if original_text.lower() in key.lower() or key.lower() in original_text.lower():
                                        evaluation = val
                                        break
                            
                            if evaluation:
                                exclusions_checklist_result.append({
                                    'criterion': original_item,  # Use exact text from grant
                                    'status': evaluation.get('status', 'don\'t know'),
                                    'reason': evaluation.get('reason', '')
                                })
                            else:
                                # If no evaluation found, mark as "don't know"
                                exclusions_checklist_result.append({
                                    'criterion': original_item,
                                    'status': 'don\'t know',
                                    'reason': 'Evaluation not provided'
                                })
                    else:
                        # No pre-generated checklist, use ChatGPT's extracted items
                        exclusions_checklist_result = result.get('exclusions_checklist', [])
                    
                    # Recalculate scores from checklist items to ensure accuracy
                    # This is more reliable than trusting ChatGPT's calculation
                    eligibility_yes_count = sum(1 for item in eligibility_checklist_result if item.get('status') == 'yes')
                    eligibility_total_count = len(eligibility_checklist_result) if eligibility_checklist_result else 0
                    eligibility_score = (eligibility_yes_count / eligibility_total_count) if eligibility_total_count > 0 else 0.0
                    
                    competitiveness_yes_count = sum(1 for item in competitiveness_checklist_result if item.get('status') == 'yes')
                    competitiveness_total_count = len(competitiveness_checklist_result) if competitiveness_checklist_result else 0
                    competitiveness_score = (competitiveness_yes_count / competitiveness_total_count) if competitiveness_total_count > 0 else 0.0
                    
                    # For exclusions: "no" means NOT excluded (good), "yes" means IS excluded (bad)
                    # So exclusions_score = percentage of "no" answers
                    exclusions_no_count = sum(1 for item in exclusions_checklist_result if item.get('status') == 'no')
                    exclusions_total_count = len(exclusions_checklist_result) if exclusions_checklist_result else 0
                    exclusions_score = (exclusions_no_count / exclusions_total_count) if exclusions_total_count > 0 else 1.0  # Default to 1.0 if no exclusions checklist
                    
                    # Calculate overall score from components
                    # Include exclusions_score in the average if available
                    score_components = []
                    if eligibility_score is not None:
                        score_components.append(eligibility_score)
                    if competitiveness_score is not None:
                        score_components.append(competitiveness_score)
                    if exclusions_total_count > 0:  # Only include if exclusions checklist exists
                        score_components.append(exclusions_score)
                    
                    if score_components:
                        calculated_score = sum(score_components) / len(score_components)
                    else:
                        # Fallback to ChatGPT's score if we couldn't calculate
                        overall_score = result.get('score')
                        calculated_score = overall_score if overall_score is not None else 0.0
                    
                    # Log if scores differ significantly from ChatGPT's calculation (for debugging)
                    chatgpt_eligibility = result.get('eligibility_score')
                    chatgpt_competitiveness = result.get('competitiveness_score')
                    chatgpt_exclusions = result.get('exclusions_score')
                    if chatgpt_eligibility is not None and abs(chatgpt_eligibility - eligibility_score) > 0.1:
                        logger.warning(f"Score mismatch for grant {grant_data.get('id')}: ChatGPT eligibility={chatgpt_eligibility}, Recalculated={eligibility_score}")
                    if chatgpt_competitiveness is not None and abs(chatgpt_competitiveness - competitiveness_score) > 0.1:
                        logger.warning(f"Score mismatch for grant {grant_data.get('id')}: ChatGPT competitiveness={chatgpt_competitiveness}, Recalculated={competitiveness_score}")
                    if chatgpt_exclusions is not None and exclusions_total_count > 0 and abs(chatgpt_exclusions - exclusions_score) > 0.1:
                        logger.warning(f"Score mismatch for grant {grant_data.get('id')}: ChatGPT exclusions={chatgpt_exclusions}, Recalculated={exclusions_score}")
                    
                    # Save all matches regardless of score (no threshold)
                    # Use update_or_create to handle duplicates gracefully
                    match_obj, created = GrantMatchResult.objects.update_or_create(
                        funding_search=funding_search,
                        grant=grant,
                        defaults={
                            'match_score': calculated_score,
                            'eligibility_score': eligibility_score,
                            'competitiveness_score': competitiveness_score,
                            'match_reasons': {
                                'explanation': result.get('explanation', ''),  # Keep for backward compatibility
                                'project_type_and_trl_focus': result.get('project_type_and_trl_focus', ''),
                                'why_it_matches': result.get('why_it_matches', ''),
                                'key_risks_and_uncertainties': result.get('key_risks_and_uncertainties', ''),
                                'eligibility_checklist': eligibility_checklist_result,
                                'competitiveness_checklist': competitiveness_checklist_result,
                                'exclusions_checklist': exclusions_checklist_result,
                                'alignment_points': result.get('alignment_points', []),  # Keep for backward compatibility
                                'concerns': result.get('concerns', []),  # Keep for backward compatibility
                                'matched_via': 'chatgpt',
                                'batch_processed': True,
                            }
                        }
                    )
                    new_grant_ids.add(grant.id)  # Track this grant as having a new result
                    if created:
                        matches_created += 1
                    else:
                        matches_updated += 1
                
                # Now safely delete any old results that weren't in the new matching run
                # This handles the case where a grant was previously matched but is no longer in the results
                deleted_count = GrantMatchResult.objects.filter(
                    funding_search=funding_search
                ).exclude(
                    grant_id__in=new_grant_ids
                ).delete()[0]
                
                if deleted_count > 0:
                    logger.info(f"Deleted {deleted_count} old match results that are no longer in the new results")
            
            # Update funding search
            funding_search.matching_status = 'completed'
            funding_search.last_matched_at = timezone.now()
            funding_search.matching_progress = {
                'current': len(grants_list), 
                'total': len(grants_list), 
                'percentage': 100,
                'stage': 'completed',
                'stage_message': 'Matching completed!'
            }
            funding_search.save()
            
            result_summary = {
                'status': 'success',
                'matches_created': matches_created,
                'matches_updated': matches_updated,
                'grants_processed': len(grants_list),
                'total_results': len(match_results),
            }
            logger.info(f"Matching completed successfully: {result_summary}")
            return result_summary
        
        except Exception as e:
            import traceback
            error_traceback = traceback.format_exc()
            # SECURITY: Store sanitized error message (no internal details)
            # Log full traceback server-side only
            logger.error(f"Matching failed for funding_search_id {funding_search_id}: {e}", exc_info=True)
            
            # Create user-friendly error message without exposing internals
            if "OPENAI_API_KEY" in str(e) or "API" in str(e):
                user_error = "Matching service configuration error. Please contact support."
            elif "RateLimitError" in str(type(e).__name__):
                user_error = "Matching service rate limit exceeded. Please try again later."
            elif "Timeout" in str(e) or "timeout" in str(e).lower():
                user_error = "Matching request timed out. Please try again."
            else:
                user_error = "Matching failed due to an unexpected error. Please try again or contact support."
            
            funding_search.matching_status = 'error'
            funding_search.matching_error = user_error  # Store sanitized error message
            # Keep progress as-is so user can see how far it got
            funding_search.save()
            raise Exception(f"Matching failed: {str(e)}")
else:
    # Dummy function if Celery is not available
    def match_grants_with_chatgpt(funding_search_id):
        raise Exception("Celery is not available")

