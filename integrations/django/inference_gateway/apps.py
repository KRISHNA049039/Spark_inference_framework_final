from django.apps import AppConfig


class InferenceGatewayConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "inference_gateway"
    verbose_name = "Inference gateway (Spark platform)"
