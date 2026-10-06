from django.contrib import admin

from .models import InferenceJob


@admin.register(InferenceJob)
class InferenceJobAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "target", "status", "created_by", "created_at", "finished_at")
    list_filter = ("kind", "status", "target")
    search_fields = ("id", "target", "created_by")
    readonly_fields = [f.name for f in InferenceJob._meta.fields]
