from django.dispatch import Signal

# Fired whenever a model instance is retrieved via a ViewSet.
# Receivers receive: sender=ModelClass, instance=obj, user=request.user
accessed = Signal()
