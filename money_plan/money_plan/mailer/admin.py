from django.contrib import admin

from .models import EmailLog


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "to", "template", "status", "attempts", "sent_at"]
    list_filter = ["status", "template"]
    search_fields = ["to", "message_id", "dedupe_key", "subject"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
