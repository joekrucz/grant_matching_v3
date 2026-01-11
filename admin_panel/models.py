"""
Models for the admin panel.

Currently includes:
- AiInteractionLog: simple audit log for admin AI assistant usage.
"""
from django.conf import settings
from django.db import models


class AiInteractionLog(models.Model):
    """Audit log for admin AI assistant interactions."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_interactions",
    )
    endpoint = models.CharField(max_length=100, db_index=True)
    model_name = models.CharField(max_length=100, blank=True, null=True)
    grant = models.ForeignKey(
        "grants.Grant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_interactions",
    )
    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_interactions",
    )
    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, null=True)
    latency_ms = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "admin_ai_interaction_logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["endpoint", "created_at"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.user_id} {self.endpoint} @ {self.created_at}"


class Conversation(models.Model):
    """Stores a conversation session between an admin and the AI assistant."""
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_conversations",
    )
    title = models.CharField(max_length=255, blank=True, null=True)
    # Store page context when conversation started
    initial_page_type = models.CharField(max_length=50, blank=True, null=True)  # 'grant', 'company', 'unknown'
    initial_grant_id = models.IntegerField(blank=True, null=True)
    initial_company_id = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)
    
    class Meta:
        db_table = "admin_ai_conversations"
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["user", "-updated_at"]),
        ]
    
    def __str__(self) -> str:
        return f"{self.user.email} - {self.title or 'Untitled'} @ {self.created_at}"
    
    def get_message_count(self):
        """Return the number of messages in this conversation."""
        return self.messages.count()
    
    def get_first_user_message(self):
        """Return the first user message to use as title if none set."""
        first_msg = self.messages.filter(role="user").first()
        if first_msg:
            # Use first 50 chars as title
            return first_msg.content[:50] + ("..." if len(first_msg.content) > 50 else "")
        return "New Conversation"
    
    def get_default_title(self):
        """Generate a default title based on the initial context (grant/company)."""
        if self.initial_grant_id:
            try:
                from grants.models import Grant
                grant = Grant.objects.get(id=self.initial_grant_id)
                return f"{grant.title} Conversation"
            except Grant.DoesNotExist:
                pass
        if self.initial_company_id:
            try:
                from companies.models import Company
                company = Company.objects.get(id=self.initial_company_id)
                return f"{company.name} Conversation"
            except Company.DoesNotExist:
                pass
        # Fallback to first user message or generic title
        return self.get_first_user_message() or "New Conversation"


class ConversationMessage(models.Model):
    """Stores individual messages within a conversation."""
    
    ROLE_CHOICES = [
        ("user", "User"),
        ("assistant", "Assistant"),
    ]
    
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, db_index=True)
    content = models.TextField()
    # Store metadata for assistant messages (fit scores, used fields, etc.)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        db_table = "admin_ai_conversation_messages"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
        ]
    
    def __str__(self) -> str:
        return f"{self.conversation_id} - {self.role} @ {self.created_at}"


class SystemSettings(models.Model):
    """System-wide settings that can be configured via admin panel."""
    
    # Singleton pattern - only one settings record
    id = models.IntegerField(primary_key=True, default=1, editable=False)
    
    # Grant matching settings
    grant_matching_batch_size = models.IntegerField(
        default=1,
        help_text="Number of parallel ChatGPT API requests to make simultaneously (1-10 recommended)"
    )
    
    # Feature flags
    ai_widget_enabled = models.BooleanField(
        default=False,
        help_text="Enable the AI widget and conversations feature"
    )
    
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="system_settings_updates"
    )
    
    class Meta:
        db_table = "admin_system_settings"
        verbose_name = "System Settings"
        verbose_name_plural = "System Settings"
    
    def __str__(self) -> str:
        return f"System Settings (Batch Size: {self.grant_matching_batch_size})"
    
    def save(self, *args, **kwargs):
        # Enforce singleton pattern
        self.id = 1
        super().save(*args, **kwargs)
    
    @classmethod
    def get_settings(cls):
        """Get or create the singleton settings instance."""
        settings_obj, created = cls.objects.get_or_create(id=1, defaults={
            'grant_matching_batch_size': 1,
            'ai_widget_enabled': False,
        })
        return settings_obj

