from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender="masters.Client")
def client_creates_ledger(sender, instance, **kwargs):
    from core.feature_flags import accounts_module_enabled

    if not accounts_module_enabled():
        return
    from .services import sync_client_account

    sync_client_account(instance)
