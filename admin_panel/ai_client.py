"""
Lightweight AI assistant client and context builders for the admin panel.

This provides:
- build_grant_context / build_company_context: safe, truncated views of models
- AiAssistantClient: thin wrapper around the OpenAI Chat Completions API
"""
import json
import time
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings

from grants.models import Grant
from companies.models import Company

try:
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover - import guard for environments without openai
    OpenAI = None  # type: ignore


def _truncate(value: Optional[str], max_length: int = 2000) -> str:
    if not value:
        return ""
    value_str = str(value)
    if len(value_str) <= max_length:
        return value_str
    return value_str[: max_length - 3] + "..."


def build_grant_context(grant: Grant) -> Dict[str, Any]:
    """Return a sanitised, truncated context dict for a Grant."""
    raw_data = grant.raw_data or {}
    
    # Extract eligibility from multiple possible locations
    eligibility = ""
    # Try direct eligibility field first
    if raw_data.get("eligibility"):
        eligibility = str(raw_data["eligibility"])
    # Try sections structure (for Innovate UK, Catapult, NIHR, etc.)
    elif raw_data.get("sections"):
        sections = raw_data["sections"]
        if isinstance(sections, dict):
            # Most common case: sections is a dict with "eligibility" as a key with string value
            if sections.get("eligibility"):
                eligibility = str(sections["eligibility"])
            # Check for nested sections (tabs structure like Catapult)
            else:
                for key, value in sections.items():
                    if isinstance(value, dict):
                        # Check if this is a tab with nested sections
                        if value.get("is_tab") and value.get("sections"):
                            for nested_section in value.get("sections", []):
                                if isinstance(nested_section, dict):
                                    section_key = nested_section.get("key", "").lower()
                                    if "eligibility" in section_key or "who_can_apply" in section_key:
                                        eligibility = str(nested_section.get("content", ""))
                                        break
                        # Check if this section itself is eligibility (by key name)
                        elif "eligibility" in key.lower() or "who_can_apply" in key.lower():
                            # Value might be a dict with "content" or just a string
                            if isinstance(value, str):
                                eligibility = value
                            else:
                                eligibility = str(value.get("content", value.get("title", "")))
    
    return {
        "id": grant.id,
        "slug": grant.slug,  # Include slug for generating links
        "title": _truncate(grant.title, 500),
        "summary": _truncate(grant.summary, 1000),
        "description": _truncate(grant.description, 2000),
        "eligibility": _truncate(eligibility, 2000),  # Increased to capture more eligibility info
        "deadline": grant.deadline.isoformat() if grant.deadline else None,
        "funding_amount": _truncate(grant.funding_amount, 255),
        "status": grant.status,
        "source": grant.source,
        "url": grant.url,
    }


def build_company_context(company: Company) -> Dict[str, Any]:
    """Return a sanitised, truncated context dict for a Company."""
    address = company.address or {}
    return {
        "id": company.id,
        "name": _truncate(company.name, 500),
        "company_type": _truncate(company.company_type, 100),
        "status": _truncate(company.status, 100),
        "country": _truncate(address.get("country") or "", 100),
        "sic_codes": company.sic_codes_array(),
        "website": company.website,
        "notes": _truncate(company.notes, 1000) if company.notes else "",
        # Explicitly exclude raw_data, user, and contact details
    }


def prepare_conversation_history(
    messages: list,
    max_messages: int = 20,
    max_total_chars: int = 8000,
) -> List[Dict[str, str]]:
    """
    Prepare conversation history for AI, with context window management.
    
    Args:
        messages: List of ConversationMessage objects (ordered by created_at)
        max_messages: Maximum number of messages to include
        max_total_chars: Maximum total characters across all messages
    
    Returns:
        List of message dicts in format [{"role": "user", "content": "..."}, ...]
    """
    if not messages:
        return []
    
    # Convert to list of dicts
    history = []
    total_chars = 0
    
    # Start from the most recent messages and work backwards
    # We'll include the most recent messages up to the limits
    recent_messages = list(messages)[-max_messages:] if len(messages) > max_messages else list(messages)
    
    for msg in recent_messages:
        content = (msg.content or "").strip()
        if not content:
            continue
        
        # Estimate character count (rough approximation: 1 token ≈ 4 chars)
        content_chars = len(content)
        
        # If adding this message would exceed the limit, truncate it
        if total_chars + content_chars > max_total_chars:
            remaining_chars = max_total_chars - total_chars
            if remaining_chars > 100:  # Only include if we have meaningful space
                content = content[:remaining_chars] + "..."
                history.append({
                    "role": msg.role,
                    "content": content,
                })
            break
        
        history.append({
            "role": msg.role,
            "content": content,
        })
        total_chars += content_chars
    
    return history


class AiAssistantError(Exception):
    """Raised when the AI assistant cannot be used."""


class AiAssistantClient:
    """
    Thin wrapper around OpenAI's chat completions for the admin assistant.

    All methods return (parsed_json, raw_response_dict, latency_ms).
    """

    def __init__(self) -> None:
        api_key = getattr(settings, "OPENAI_API_KEY", "") or ""
        if not api_key or OpenAI is None:
            raise AiAssistantError("AI assistant is not configured (missing OpenAI client or API key).")
        self.client = OpenAI(api_key=api_key)
        # Allow overriding via env/settings; default to a cost-effective model
        self.model = getattr(settings, "ADMIN_AI_MODEL", "gpt-4.1-mini")

    def _call_json_model(
        self,
        system_prompt: str,
        user_payload: Dict[str, Any],
        max_tokens: int = 400,
        temperature: float = 0.3,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any], int]:
        """Call the model and return parsed JSON, raw response, and latency in ms.
        
        Args:
            system_prompt: System prompt for the model
            user_payload: User payload (will be JSON stringified)
            max_tokens: Maximum tokens for response
            temperature: Temperature for generation
            conversation_history: Optional list of previous messages in format [{"role": "user", "content": "..."}, ...]
        """
        start = time.time()
        
        # Build messages array
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add conversation history if provided
        if conversation_history:
            messages.extend(conversation_history)
        
        # Add current user message
        messages.append({
            "role": "user",
            "content": json.dumps(user_payload),
        })
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        latency_ms = int((time.time() - start) * 1000)
        content = response.choices[0].message.content or "{}"
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            # Fallback: wrap raw content
            parsed = {"answer": content}
        raw = {
            "id": response.id,
            "model": response.model,
            "usage": {
                "input_tokens": getattr(response.usage, "prompt_tokens", None),
                "output_tokens": getattr(response.usage, "completion_tokens", None),
            },
        }
        return parsed, raw, latency_ms

    # Public helpers for specific tasks

    def summarise_grant(self, grant_ctx: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], int]:
        system_prompt = (
            "You are an assistant for grant administrators.\n"
            "You receive a single grant object with fields such as "
            "`title`, `summary`, `description`, `eligibility`, `deadline`, "
            "`funding_amount`, `status`, `source`, `url`.\n"
            "Your task is to:\n"
            "- Produce 3–5 concise bullet points summarising what the grant is about, "
            "who it is for, and key conditions.\n"
            "- Produce up to 3 risks or caveats.\n"
            "Rules:\n"
            "- Use only the information in the provided grant object.\n"
            "- If important information is missing, explicitly mention that instead of guessing.\n"
            "- Keep language clear and non-technical.\n"
            "- Do not invent amounts, dates, or sectors.\n"
            "Always respond with a single JSON object: "
            '{"bullets": [string], "risks": [string]}.'
        )
        payload = {
            "task": "summarise_grant",
            "grant": grant_ctx,
        }
        return self._call_json_model(system_prompt, payload)

    def summarise_company(self, company_ctx: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], int]:
        system_prompt = (
            "You are an assistant for grant administrators.\n"
            "You receive a single company object with fields such as "
            "`name`, `company_type`, `status`, `country`, `sic_codes`, `website`, `notes`.\n"
            "Your task is to:\n"
            "- Produce 3–5 concise bullet points summarising what the company does "
            "and its context (sector/industry if inferable from SIC, stage/status, geography).\n"
            "- Use the `notes` field if available to provide additional context about the company.\n"
            "- Optionally, list up to 3 highlights.\n"
            "- Optionally, list up to 3 gaps in the information that might matter for grant matching.\n"
            "Rules:\n"
            "- Use only the information in the provided company object.\n"
            "- If information is missing, say so; do not guess.\n"
            "- Avoid any discussion of specific grants unless explicitly provided.\n"
            "Always respond with a single JSON object: "
            '{"bullets": [string], "highlights": [string], "gaps": [string]}.'
        )
        payload = {
            "task": "summarise_company",
            "company": company_ctx,
        }
        return self._call_json_model(system_prompt, payload)

    def contextual_qa(
        self,
        question: str,
        page_type: str,
        grant_ctx: Optional[Dict[str, Any]] = None,
        company_ctx: Optional[Dict[str, Any]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        referenced_grants: Optional[Dict[int, Dict[str, Any]]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any], int]:
        """Contextual Q&A with conversation history support.
        
        Args:
            question: Current question from the user
            page_type: Type of page (grant, company, mixed)
            grant_ctx: Optional grant context
            company_ctx: Optional company context
            conversation_history: Optional list of previous messages [{"role": "user", "content": "..."}, ...]
            referenced_grants: Optional dict of grant_id -> grant_context for grants mentioned in conversation
        """
        system_prompt = (
            "You are an assistant for grant administrators.\n"
            "You will receive:\n"
            "- A `page_type` indicating whether the admin is viewing a `grant`, a `company`, or `mixed`.\n"
            "- A grant object and/or a company object (for the current page context).\n"
            "- A natural-language question from the admin.\n"
            "- Previous conversation history (if this is a continuing conversation).\n"
            "- Referenced grants: If grants were mentioned in previous messages (e.g., from a search), "
            "you will receive their COMPLETE details in the 'referenced_grants' array. "
            "Each grant object includes ALL of these fields: grant_id, title, summary, description, eligibility, deadline, funding_amount, status, source, url.\n"
            "You have access to ALL this information for each grant - use it comprehensively when answering questions.\n"
            "Your task is to:\n"
            "- Answer the question using ALL available information: provided objects, conversation history, AND referenced grants.\n"
            "- When answering questions about grants mentioned in the conversation, you MUST:\n"
            "  1. Identify which specific grant is being referenced by matching the grant title/name from the conversation\n"
            "  2. Find that grant in the referenced_grants array\n"
            "  3. Use ALL available information from that grant (title, summary, description, eligibility, deadline, funding_amount, etc.)\n"
            "  4. If eligibility criteria is provided, use it. If not, use other available fields (description, summary, etc.) to infer eligibility\n"
            "- When the user asks about 'that grant', 'the grant', 'it', or references a grant by name/number, "
            "match it to the appropriate grant in referenced_grants by comparing titles.\n"
            "- For example, if the conversation mentions 'Freight Innovation Cluster', find the grant with that title in referenced_grants.\n"
            "- IMPORTANT: Even if a grant's eligibility field is empty, use the description, summary, and other fields to answer questions.\n"
            "- When answering eligibility questions, check the eligibility field first, but also consider:\n"
            "  - Grant description and summary (may contain eligibility information)\n"
            "  - Grant source (e.g., UKRI grants often have specific eligibility requirements)\n"
            "  - Funding amount and status (may indicate company size requirements)\n"
            "- Provide specific, detailed answers using the grant's full context, not generic responses.\n"
            "- If the answer is not clearly supported by the data, say you cannot answer "
            "based on the available information and suggest what is missing.\n"
            "- Be concise (ideally under 150 words) unless the question requires detailed explanation.\n"
            "- Maintain context from previous messages - you can reference earlier parts of the conversation.\n"
            "You must also return a list of the fields you relied on in your reasoning.\n"
            "Rules:\n"
            "- Do not fabricate dates, amounts, or eligibility criteria.\n"
            "- Do not speculate about private information or internal details not present in the context.\n"
            "- If the user asks about something outside the provided context, say that is outside your scope.\n"
            "- When answering questions about grants, you MUST:\n"
            "  1. First identify which specific grant is being referenced (by matching title/name from conversation)\n"
            "  2. Then use that grant's COMPLETE details from referenced_grants - check ALL fields (title, summary, description, eligibility, deadline, funding_amount, status, source, url)\n"
            "  3. Provide a specific, detailed answer about THAT grant using all available information\n"
            "  4. If eligibility field is empty, extract eligibility information from description/summary if available\n"
            "- If you cannot identify which specific grant is being referenced, say so clearly.\n"
            "- Never say 'eligibility criteria are not provided' if you have access to the grant's description, summary, or other fields that might contain eligibility information.\n"
            "Always respond with a single JSON object: "
            '{"answer": string, "used_fields": [string], "caveats": [string]}.'
        )
        payload = {
            "task": "contextual_qa",
            "page_type": page_type,
            "question": question,
            "grant": grant_ctx,
            "company": company_ctx,
        }
        
        # Add referenced grants to payload if provided
        # Format as a list with all grant details for easy access
        if referenced_grants:
            # Create a structured list format with all grant details
            grants_list = []
            for grant_id, grant_data in referenced_grants.items():
                # Ensure all fields are included and clearly labeled
                grant_entry = {
                    "grant_id": grant_id,
                    "title": grant_data.get("title", ""),
                    "summary": grant_data.get("summary", ""),
                    "description": grant_data.get("description", ""),
                    "eligibility": grant_data.get("eligibility", ""),
                    "deadline": grant_data.get("deadline"),
                    "funding_amount": grant_data.get("funding_amount", ""),
                    "status": grant_data.get("status", ""),
                    "source": grant_data.get("source", ""),
                    "url": grant_data.get("url", ""),
                }
                grants_list.append(grant_entry)
            payload["referenced_grants"] = grants_list
            # Also add a note about how many grants are available
            payload["referenced_grants_count"] = len(grants_list)
        
        return self._call_json_model(system_prompt, payload, max_tokens=800, conversation_history=conversation_history)

    def grant_company_fit(
        self,
        grant_ctx: Dict[str, Any],
        company_ctx: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any], int]:
        """Analyze how well a grant fits a company."""
        system_prompt = (
            "You are an expert grant matching assistant for grant administrators.\n"
            "You will receive:\n"
            "- A grant object with fields: title, summary, description, eligibility, deadline, funding_amount, status, source, url.\n"
            "- A company object with fields: name, company_type, status, country, sic_codes, website, notes.\n"
            "Your task is to:\n"
            "- Analyze how well the grant aligns with the company.\n"
            "- Provide a fit score from 0.0 to 1.0 (1.0 = perfect match, 0.0 = no match).\n"
            "- List 3-5 alignment points (what matches well).\n"
            "- List 2-4 concerns or mismatches (potential issues).\n"
            "- Provide a brief explanation (2-3 sentences) of the overall fit.\n"
            "- Suggest what the company might need to do to improve their chances (if applicable).\n"
            "Rules:\n"
            "- Base your analysis only on the provided grant and company data.\n"
            "- Consider: sector alignment (SIC codes vs grant focus), company type, eligibility criteria, funding requirements.\n"
            "- Be honest about mismatches - don't inflate scores.\n"
            "- If critical information is missing, mention it in concerns.\n"
            "Always respond with a single JSON object: "
            '{"fit_score": float, "explanation": string, "alignment_points": [string], "concerns": [string], "recommendations": [string]}.'
        )
        payload = {
            "task": "grant_company_fit",
            "grant": grant_ctx,
            "company": company_ctx,
        }
        return self._call_json_model(system_prompt, payload, max_tokens=600)

    def search_grants_for_company(
        self,
        company_ctx: Dict[str, Any],
        grants_list: list[Dict[str, Any]],
    ) -> Tuple[Dict[str, Any], Dict[str, Any], int]:
        """Search and rank grants for a company based on company characteristics."""
        system_prompt = (
            "You are an expert grant matching assistant for grant administrators.\n"
            "You will receive:\n"
            "- A company object with fields: name, company_type, status, country, sic_codes, website, notes.\n"
            "- A list of grant objects, each with: id, title, summary, description, eligibility, deadline, funding_amount, status, source.\n"
            "Your task is to:\n"
            "- Analyze the company's characteristics (sector, type, location, notes).\n"
            "- Match grants from the list that are relevant to this company.\n"
            "- Rank grants by relevance/fit (best matches first).\n"
            "- For each grant, provide a brief explanation (1-2 sentences) of why it might be relevant.\n"
            "- Return only grants that have at least some potential relevance (don't include completely irrelevant grants).\n"
            "Rules:\n"
            "- Consider: sector alignment (SIC codes), company type, eligibility criteria, geographic requirements.\n"
            "- Be realistic - not every grant will be a perfect match.\n"
            "- If a grant has strict eligibility that clearly doesn't match, exclude it.\n"
            "- Prioritize grants with active/open status.\n"
            "Always respond with a single JSON object: "
            '{"matched_grants": [{"grant_id": int, "relevance_score": float (0.0-1.0), "explanation": string}], '
            '"search_summary": string (brief summary of what you searched for)}.'
        )
        payload = {
            "task": "search_grants_for_company",
            "company": company_ctx,
            "grants": grants_list,
        }
        return self._call_json_model(system_prompt, payload, max_tokens=1200)


