from django.urls import path

from . import views

app_name = "inference_gateway"

urlpatterns = [
    path("catalog/", views.catalog_view, name="catalog"),
    path("jobs/", views.jobs_view, name="jobs"),
    path("jobs/<uuid:job_id>/", views.job_detail_view, name="job-detail"),
    path("jobs/<uuid:job_id>/results/", views.job_results_view, name="job-results"),
    path("pipelines/<str:name>/predict/", views.predict_view, name="predict"),
    path("pipelines/<str:name>/health/", views.health_view, name="health"),
]
