import logging

from rest_framework import permissions
from rest_framework_simplejwt.authentication import JWTAuthentication

from .signals import accessed

logger = logging.getLogger(__name__)


class LoginRequiredMixin:
    """
    Sets JWT authentication and IsAuthenticated permission on any ViewSet
    that inherits it. Keeps ViewSets self-contained regardless of global
    DEFAULT_AUTHENTICATION_CLASSES / DEFAULT_PERMISSION_CLASSES settings.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]


class LogAccessMixin:
    """
    Fires the `accessed` signal whenever an object is retrieved.
    Attach receivers to `accessed` to build audit logs, analytics, etc.

    Usage:
        from core.signals import accessed

        @receiver(accessed, sender=MyModel)
        def on_my_model_accessed(sender, instance, **kwargs):
            AuditLog.objects.create(...)
    """

    def _fire_accessed(self, obj):
        try:
            accessed.send(sender=obj.__class__, instance=obj)
        except Exception:
            logger.exception(
                "Failed to fire 'accessed' signal for %s pk=%s",
                obj.__class__.__name__,
                getattr(obj, "pk", "?"),
            )
