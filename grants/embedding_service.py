"""
Service for generating and using embeddings for grant semantic search.
"""
import numpy as np
from typing import List, Dict, Optional, Tuple
from django.conf import settings
from grants.models import Grant

try:
    from openai import OpenAI
    from openai import PermissionDeniedError, APIError
    OPENAI_ERRORS_AVAILABLE = True
except Exception:
    OpenAI = None
    PermissionDeniedError = Exception  # Fallback to generic Exception
    APIError = Exception
    OPENAI_ERRORS_AVAILABLE = False


class EmbeddingService:
    """Service for generating and using embeddings for grants."""
    
    def __init__(self):
        api_key = getattr(settings, 'OPENAI_API_KEY', None)
        if not api_key or OpenAI is None:
            raise ValueError("OPENAI_API_KEY not configured or OpenAI not available")
        self.client = OpenAI(api_key=api_key)
        # Allow model to be configured via settings, with fallback options
        self.model = getattr(settings, 'EMBEDDING_MODEL', "text-embedding-3-small")
        self.fallback_model = "text-embedding-ada-002"  # Older but more widely available
    
    def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding for a single text with automatic fallback."""
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")
        
        # Try primary model first
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=text.strip()
            )
            return response.data[0].embedding
        except Exception as e:
            # Check if this is a permission/model access error
            should_fallback = False
            error_str = str(e).lower()
            
            # Check for specific error types
            if OPENAI_ERRORS_AVAILABLE:
                if isinstance(e, PermissionDeniedError):
                    should_fallback = True
                elif isinstance(e, APIError):
                    # Check error code or message
                    if hasattr(e, 'status_code') and e.status_code == 403:
                        should_fallback = True
                    elif '403' in error_str or 'permission' in error_str:
                        should_fallback = True
            
            # Also check error message for model access issues (works even if imports failed)
            if ('403' in error_str or 
                'permission' in error_str or
                'model_not_found' in error_str or 
                'does not have access' in error_str or
                'does not have access to model' in error_str):
                should_fallback = True
            
            if should_fallback:
                # Try fallback model
                try:
                    import logging
                    logger = logging.getLogger(__name__)
                    # Only log warning once per service instance to avoid spam
                    if not hasattr(self, '_fallback_warned'):
                        logger.warning(
                            f"Primary embedding model '{self.model}' not available (error: {str(e)[:100]}). "
                            f"Automatically falling back to '{self.fallback_model}' for all subsequent requests. "
                            f"To fix this, either: 1) Enable '{self.model}' in your OpenAI project settings, "
                            f"or 2) Set EMBEDDING_MODEL='{self.fallback_model}' in your environment variables."
                        )
                        self._fallback_warned = True
                    response = self.client.embeddings.create(
                        model=self.fallback_model,
                        input=text.strip()
                    )
                    return response.data[0].embedding
                except Exception as fallback_error:
                    # If fallback also fails, raise the original error with context
                    raise ValueError(
                        f"Failed to generate embedding with both '{self.model}' and "
                        f"'{self.fallback_model}'. Original error: {str(e)}. "
                        f"Fallback error: {str(fallback_error)}. "
                        f"Please check your OpenAI API key and project permissions."
                    ) from e
            else:
                # For other errors, raise as-is
                raise
    
    def generate_grant_embedding_text(self, grant: Grant) -> str:
        """Create a comprehensive text representation of a grant for embedding."""
        parts = []
        
        # Title and summary
        if grant.title:
            parts.append(f"Title: {grant.title}")
        if grant.summary:
            parts.append(f"Summary: {grant.summary}")
        
        # Description (truncate for efficiency)
        if grant.description:
            desc = grant.description[:2000] if len(grant.description) > 2000 else grant.description
            parts.append(f"Description: {desc}")
        
        # Eligibility criteria
        if grant.eligibility_checklist:
            items = grant.eligibility_checklist.get('checklist_items', [])
            if items:
                parts.append(f"Eligibility: {'; '.join(items[:10])}")  # Top 10 items
        
        # Competitiveness criteria
        if grant.competitiveness_checklist:
            items = grant.competitiveness_checklist.get('checklist_items', [])
            if items:
                parts.append(f"Competitiveness: {'; '.join(items[:10])}")
        
        # TRL requirements
        if grant.trl_requirements:
            trl_levels = grant.trl_requirements.get('trl_levels', [])
            if trl_levels:
                parts.append(f"Technology Readiness Levels: {', '.join(trl_levels)}")
        
        # Source and funding amount
        parts.append(f"Source: {grant.get_source_display()}")
        if grant.funding_amount:
            parts.append(f"Funding: {grant.funding_amount}")
        
        return "\n".join(parts)
    
    def cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        vec1 = np.array(vec1)
        vec2 = np.array(vec2)
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(dot_product / (norm1 * norm2))
    
    def find_similar_grants(
        self, 
        grant: Grant,
        limit: int = 10,
        min_similarity: float = 0.5
    ) -> List[Tuple[Grant, float]]:
        """
        Find similar grants to the given grant.
        
        Returns: List of (grant, similarity_score) tuples, sorted by score descending
        """
        if not grant.embedding:
            return []
        
        # Get all grants with embeddings (excluding the current grant)
        grants_with_embeddings = Grant.objects.exclude(
            id=grant.id
        ).exclude(
            embedding__isnull=True
        ).exclude(
            embedding=[]
        )
        
        similarities = []
        grant_embedding = grant.embedding
        
        for other_grant in grants_with_embeddings:
            if not other_grant.embedding:
                continue
            
            try:
                score = self.cosine_similarity(grant_embedding, other_grant.embedding)
                if score >= min_similarity:
                    similarities.append((other_grant, score))
            except Exception:
                # Skip grants with invalid embeddings
                continue
        
        # Sort by similarity (highest first) and return top results
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:limit]
