from rest_framework import status, serializers as s, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import RefreshToken
from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer

from core.mixins import LoginRequiredMixin
from accounts.models import User
from .permissions import IsAdmin
from .serializers import (
    AdminLoginSerializer, UPARegisterSerializer, UPALoginSerializer,
    EmployeeRegisterSerializer, EmployeeUpdateSerializer,
    EmployeeListSerializer, UserSerializer,
)


def _tokens(user):
    refresh = RefreshToken.for_user(user)
    return {'access': str(refresh.access_token), 'refresh': str(refresh)}


_auth_user_response = inline_serializer('AuthUserWithTokens', fields={
    'access':  s.CharField(),
    'refresh': s.CharField(),
    'user':    UserSerializer(),
})


class AuthViewSet(viewsets.ViewSet):
    authentication_classes = [JWTAuthentication]

    @extend_schema(
        tags=['Authentication'],
        request=AdminLoginSerializer,
        responses={200: _auth_user_response},
    )
    @action(detail=False, methods=['post'], url_path='admin/login', permission_classes=[AllowAny])
    def admin_login(self, request):
        serializer = AdminLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        return Response({
            **_tokens(user),
            'user': UserSerializer(user, context={'request': request}).data,
        })

    @extend_schema(
        tags=['Authentication'],
        request=UPARegisterSerializer,
        responses={
            201: inline_serializer('UPARegisterSuccess', fields={
                'success':  s.BooleanField(),
                'access':   s.CharField(),
                'refresh':  s.CharField(),
                'user':     UserSerializer(),
            }),
            200: inline_serializer('UPARegisterNoLeg', fields={
                'success':            s.BooleanField(),
                'suggest_standalone': s.BooleanField(),
                'message':            s.CharField(),
            }),
        },
    )
    @action(detail=False, methods=['post'], url_path='user/register', permission_classes=[AllowAny])
    def upa_register(self, request):
        serializer = UPARegisterSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except Exception as exc:
            detail = getattr(exc, 'detail', {})
            flat = str(detail)
            if 'no_vacant_leg' in flat or 'No vacant leg' in flat:
                return Response({
                    'success': False,
                    'suggest_standalone': True,
                    'message': 'No vacant leg found. Register as standalone user instead.',
                }, status=status.HTTP_200_OK)
            raise
        user = serializer.save()
        return Response({
            'success': True,
            **_tokens(user),
            'user': UserSerializer(user, context={'request': request}).data,
        }, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=['Authentication'],
        request=UPALoginSerializer,
        responses={200: _auth_user_response},
    )
    @action(detail=False, methods=['post'], url_path='user/login', permission_classes=[AllowAny])
    def upa_login(self, request):
        serializer = UPALoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        return Response({**_tokens(user), 'user': UserSerializer(user, context={'request': request}).data})

    @extend_schema(
        tags=['Authentication'],
        request=inline_serializer('LogoutRequest', fields={'refresh': s.CharField()}),
        responses={205: None},
    )
    @action(detail=False, methods=['post'], url_path='logout', permission_classes=[IsAuthenticated])
    def logout(self, request):
        try:
            RefreshToken(request.data.get('refresh', '')).blacklist()
        except Exception:
            pass
        return Response(status=status.HTTP_205_RESET_CONTENT)

    @extend_schema(methods=['GET'], tags=['Authentication'], responses={200: UserSerializer})
    @extend_schema(methods=['PATCH'], tags=['Authentication'],
                   request=EmployeeUpdateSerializer, responses={200: UserSerializer})
    @action(detail=False, methods=['get', 'patch'], url_path='me', permission_classes=[IsAuthenticated])
    def me(self, request):
        if request.method == 'GET':
            return Response(UserSerializer(request.user, context={'request': request}).data)
        # PATCH
        serializer = EmployeeUpdateSerializer(request.user, data=request.data, partial=True, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserSerializer(request.user, context={'request': request}).data)

    @extend_schema(
        tags=['Authentication'],
        request=inline_serializer('PhotoUpload', fields={'photo': s.ImageField()}),
        responses={200: inline_serializer('PhotoResponse', fields={'photo_url': s.URLField()})},
    )
    @action(detail=False, methods=['patch'], url_path='me/photo',
            permission_classes=[IsAuthenticated], parser_classes=[MultiPartParser, FormParser])
    def upload_photo(self, request):
        if 'photo' not in request.FILES:
            return Response({'detail': 'No photo provided.'}, status=status.HTTP_400_BAD_REQUEST)
        request.user.photo = request.FILES['photo']
        request.user.save()
        return Response({'photo_url': request.build_absolute_uri(request.user.photo.url)})


@extend_schema_view(
    list=extend_schema(tags=['Employees']),
    retrieve=extend_schema(tags=['Employees']),
    create=extend_schema(tags=['Employees']),
    partial_update=extend_schema(tags=['Employees']),
    destroy=extend_schema(tags=['Employees']),
)
class EmployeeViewSet(LoginRequiredMixin, viewsets.ModelViewSet):
    permission_classes = [IsAdmin]
    http_method_names  = ['get', 'post', 'patch', 'head', 'options']

    def get_queryset(self):
        return User.objects.filter(role='employee').select_related('employee_profile')

    def get_serializer_class(self):
        if self.action == 'create':
            return EmployeeRegisterSerializer
        if self.action in ('partial_update', 'update'):
            return EmployeeUpdateSerializer
        if self.action == 'list':
            return EmployeeListSerializer
        return UserSerializer

    def get_serializer_context(self):
        return {'request': self.request}

    def create(self, request, *args, **kwargs):
        serializer = EmployeeRegisterSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(EmployeeListSerializer(user, context={'request': request}).data, status=status.HTTP_201_CREATED)
