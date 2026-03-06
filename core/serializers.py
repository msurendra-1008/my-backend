from rest_framework import serializers


class BaseModelSerializer(serializers.ModelSerializer):
    """
    Base serializer for all app serializers.

    Features:
    - object_permissions: returns object-level permission map for the
      current user. Returns {} until django-guardian is installed.
      Models can expose permissions via an `object_permissions` property
      to override the default empty dict.

    TODO: Wire up django-guardian here when added to the project.

    Usage:
        class ProductSerializer(BaseModelSerializer):
            class Meta:
                model = Product
                fields = ['id', 'name', ..., 'object_permissions']
    """

    object_permissions = serializers.SerializerMethodField(read_only=True)

    def get_object_permissions(self, obj):
        """
        Returns object-level permissions for the current user.
        If the model exposes an `object_permissions` property, that is
        used. Otherwise returns an empty dict (safe default).
        """
        if hasattr(obj, "object_permissions"):
            return obj.object_permissions
        return {}
