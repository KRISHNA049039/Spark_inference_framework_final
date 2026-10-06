"""
inference_gateway - Django app that triggers the PyTorch-Spark inference platform.

A client selects a *pipeline* (file pipelines such as ner_translate, run with
submit_pipeline_job.py) or a *plugin* (tensor models - built-in or BYOM plugins,
run with submit_job.py); the app turns the selection into the platform's own CLI
command, runs it on the Spark driver host (locally, via docker exec or via ssh),
tracks it as a job and returns the results. Pipelines that have a model server
("kitchen") can also be called synchronously for small requests.

See README.md for settings and endpoints.
"""
