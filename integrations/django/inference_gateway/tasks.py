"""Celery task - used only when INFERENCE_GATEWAY["EXECUTOR"] = "celery"."""
from celery import shared_task

from .runner import run_job


@shared_task(name="inference_gateway.run_job")
def run_job_task(job_id):
    run_job(job_id)
