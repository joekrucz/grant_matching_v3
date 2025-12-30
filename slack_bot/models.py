"""
Slack bot models for workspace and user management.
"""
from django.db import models
from django.conf import settings


class SlackWorkspace(models.Model):
    """Store Slack workspace/team information."""
    team_id = models.CharField(max_length=50, unique=True, db_index=True)
    team_name = models.CharField(max_length=255)
    access_token = models.CharField(max_length=255)  # Bot token
    bot_user_id = models.CharField(max_length=50)
    installed_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        db_table = 'slack_workspaces'
        verbose_name = 'Slack Workspace'
        verbose_name_plural = 'Slack Workspaces'
    
    def __str__(self):
        return f"{self.team_name} ({self.team_id})"


class SlackUser(models.Model):
    """Link Slack users to app users (optional)."""
    slack_user_id = models.CharField(max_length=50, unique=True, db_index=True)
    workspace = models.ForeignKey(SlackWorkspace, on_delete=models.CASCADE, related_name='users')
    app_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        related_name='slack_users'
    )
    slack_username = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'slack_users'
        verbose_name = 'Slack User'
        verbose_name_plural = 'Slack Users'
        unique_together = [['slack_user_id', 'workspace']]
    
    def __str__(self):
        return f"{self.slack_username} ({self.slack_user_id})"


class SlackBotLog(models.Model):
    """Log of messages sent to the Slack bot."""
    
    MESSAGE_TYPES = [
        ('dm', 'Direct Message'),
        ('mention', 'App Mention'),
        ('command', 'Slash Command'),
    ]
    
    STATUS_CHOICES = [
        ('received', 'Received'),
        ('processed', 'Processed'),
        ('error', 'Error'),
    ]
    
    message_type = models.CharField(max_length=20, choices=MESSAGE_TYPES, db_index=True)
    slack_user_id = models.CharField(max_length=50, db_index=True)
    slack_username = models.CharField(max_length=100, blank=True)
    channel = models.CharField(max_length=50, db_index=True)
    message_text = models.TextField()
    company_number = models.CharField(max_length=20, blank=True, null=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='received', db_index=True)
    error_message = models.TextField(blank=True, null=True)
    response_sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        db_table = 'slack_bot_logs'
        verbose_name = 'Slack Bot Log'
        verbose_name_plural = 'Slack Bot Logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['message_type', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.message_type} from {self.slack_username or self.slack_user_id} at {self.created_at}"

