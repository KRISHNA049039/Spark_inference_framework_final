import uuid

from django.db import models


class InferenceJob(models.Model):
    """One run of a platform pipeline or plugin as a Spark job."""

    class Kind(models.TextChoices):
        PIPELINE = "pipeline"
        PLUGIN = "plugin"

    class Status(models.TextChoices):
        QUEUED = "queued"
        RUNNING = "running"
        SUCCEEDED = "succeeded"
        FAILED = "failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    target = models.CharField(max_length=128, help_text="pipeline or model name")
    params = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED, db_index=True)
    command = models.TextField(blank=True)
    exit_code = models.IntegerField(null=True, blank=True)
    log = models.TextField(blank=True, help_text="tail of the CLI output")
    error = models.TextField(blank=True)
    result_path = models.CharField(max_length=512, blank=True, help_text="results file, relative to the runner workdir")
    summary = models.JSONField(default=dict, blank=True)
    created_by = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.kind}:{self.target} {self.status} ({self.id})"

    def to_dict(self, include_log=False):
        data = {
            "id": str(self.id), "kind": self.kind, "target": self.target, "status": self.status,
            "params": self.params, "exit_code": self.exit_code, "error": self.error or None,
            "result_path": self.result_path or None, "summary": self.summary or None,
            "created_by": self.created_by or None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }
        if include_log:
            data["command"] = self.command
            data["log"] = self.log
        return data
