from rest_framework import status, serializers as s, viewsets, generics
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import RefreshToken
from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer
from django.db.models import Q

from core.mixins import LoginRequiredMixin
from accounts.models import User
from .permissions import IsAdmin, IsAdminOrEmployee
from .serializers import (
    AdminLoginSerializer, UPARegisterSerializer, UPALoginSerializer,
    EmployeeRegisterSerializer, EmployeeUpdateSerializer,
    EmployeeListSerializer, UserSerializer, UPAUserListSerializer,
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


@extend_schema_view(
    list=extend_schema(tags=['UPA Users'], summary='List all UPA users'),
    retrieve=extend_schema(tags=['UPA Users'], summary='Retrieve a UPA user'),
)
class UPAUserViewSet(LoginRequiredMixin, viewsets.ReadOnlyModelViewSet):
    """Read-only list/retrieve of UPA users. Admin & superadmin only."""
    permission_classes = [IsAdmin]
    serializer_class   = UPAUserListSerializer

    def get_queryset(self):
        return (
            User.objects
            .filter(role='upa_user')
            .select_related('upa_node__parent_user', 'wallet')
            .order_by('-date_joined')
        )

    @extend_schema(
        tags=['UPA Users'],
        summary='UPA user stats (total count)',
        responses={200: inline_serializer('UPAStats', fields={
            'total':      s.IntegerField(),
            'standalone': s.IntegerField(),
            'networked':  s.IntegerField(),
        })},
    )
    @action(detail=False, methods=['get'], url_path='stats')
    def stats(self, request):
        from apps.upa_tree.models import UPATree
        total      = User.objects.filter(role='upa_user').count()
        standalone = UPATree.objects.filter(parent_user=None).count()
        return Response({
            'total':      total,
            'standalone': standalone,
            'networked':  total - standalone,
        })


class UserSearchView(generics.ListAPIView):
    """Search all users by name/email/mobile. Admin only. Used for HR employee linking."""
    permission_classes = [IsAdmin]
    serializer_class   = EmployeeListSerializer
    pagination_class   = None

    def get_queryset(self):
        qs     = User.objects.all().order_by('first_name', 'last_name')
        search = self.request.query_params.get('search', '').strip()
        role   = self.request.query_params.get('role', '').strip()
        if search:
            qs = qs.filter(
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search)  |
                Q(email__icontains=search)       |
                Q(mobile__icontains=search)
            )
        if role:
            qs = qs.filter(role=role)
        return qs[:20]


class QuickUserCreateView(generics.CreateAPIView):
    """Create a user account for HR linking. Admin only. Accepts password and role."""
    permission_classes = [IsAdmin]

    VALID_ROLES = ['employee', 'delivery_partner', 'admin']

    def create(self, request, *args, **kwargs):
        name     = (request.data.get('name') or '').strip()
        email    = (request.data.get('email') or '').strip() or None
        mobile   = (request.data.get('mobile') or '').strip() or None
        password = (request.data.get('password') or '').strip()
        role     = (request.data.get('role') or 'employee').strip()

        if not name:
            return Response({'error': 'name is required'}, status=400)
        if not email and not mobile:
            return Response({'error': 'email or mobile is required'}, status=400)
        if not password or len(password) < 8:
            return Response({'error': 'Password must be at least 8 characters'}, status=400)
        if role not in self.VALID_ROLES:
            return Response({'error': f'role must be one of: {", ".join(self.VALID_ROLES)}'}, status=400)
        if email and User.objects.filter(email=email).exists():
            return Response({'email': ['Email already in use.']}, status=400)
        if mobile and User.objects.filter(mobile=mobile).exists():
            return Response({'mobile': ['Mobile already in use.']}, status=400)

        first_name, *rest = name.split(' ', 1)
        last_name = rest[0] if rest else ''
        kwargs_create = {'first_name': first_name, 'last_name': last_name, 'role': role}
        if email:
            kwargs_create['email'] = email
        if mobile:
            kwargs_create['mobile'] = mobile

        user = User.objects.create_user(password=password, **kwargs_create)
        return Response(EmployeeListSerializer(user, context={'request': request}).data, status=201)
