class PublicListAuthMixin:
    """
    Allow unauthenticated access to list and retrieve actions.
    All other actions require JWT authentication.
    """
    def get_authentication_classes(self):
        from rest_framework_simplejwt.authentication import JWTAuthentication
        if self.action in ('list', 'retrieve'):
            return []
        return [JWTAuthentication()]
