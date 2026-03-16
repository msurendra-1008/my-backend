from rest_framework import serializers
from accounts.models import User
from apps.users.models import EmployeeProfile
from apps.wallet.models import Wallet
from apps.upa_tree.models import UPATree
from apps.upa_tree.utils import get_vacant_leg
from core.serializers import BaseModelSerializer
from .utils import generate_upa_id


class AdminLoginSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    password   = serializers.CharField(write_only=True)

    def validate(self, data):
        identifier = data['identifier']
        password   = data['password']

        user = User.objects.filter(email=identifier).first()
        if not user:
            user = User.objects.filter(mobile=identifier).first()

        if not user or not user.check_password(password):
            raise serializers.ValidationError('Invalid credentials.')
        if user.role == 'upa_user':
            raise serializers.ValidationError('Invalid credentials.')
        if not user.is_active:
            raise serializers.ValidationError('Account is disabled.')

        data['user'] = user
        return data


class EmployeeRegisterSerializer(serializers.Serializer):
    name        = serializers.CharField(max_length=150)
    email       = serializers.EmailField(required=False, allow_blank=True)
    mobile      = serializers.CharField(max_length=15, required=False, allow_blank=True)
    password    = serializers.CharField(write_only=True, min_length=8)
    department  = serializers.CharField(max_length=100)
    role        = serializers.ChoiceField(choices=['employee'])
    permissions = serializers.ListField(child=serializers.CharField(), default=list, required=False)

    def validate(self, data):
        email  = data.get('email', '').strip() or None
        mobile = data.get('mobile', '').strip() or None
        if not email and not mobile:
            raise serializers.ValidationError('At least one of email or mobile is required.')
        if email and User.objects.filter(email=email).exists():
            raise serializers.ValidationError({'email': 'Email already in use.'})
        if mobile and User.objects.filter(mobile=mobile).exists():
            raise serializers.ValidationError({'mobile': 'Mobile already in use.'})
        data['email']  = email
        data['mobile'] = mobile
        return data

    def create(self, validated_data):
        name        = validated_data.pop('name')
        password    = validated_data.pop('password')
        department  = validated_data.pop('department')
        permissions = validated_data.pop('permissions', [])
        validated_data.pop('role')
        first_name, *rest = name.split(' ', 1)
        last_name = rest[0] if rest else ''

        user = User.objects.create_user(
            password=password,
            first_name=first_name,
            last_name=last_name,
            role='employee',
            **{k: v for k, v in validated_data.items() if v is not None},
        )
        EmployeeProfile.objects.create(
            user=user,
            department=department,
            permissions=permissions,
            created_by=self.context.get('request').user,
        )
        return user


class EmployeeUpdateSerializer(BaseModelSerializer):
    department  = serializers.CharField(required=False)
    permissions = serializers.ListField(child=serializers.CharField(), required=False)
    is_active   = serializers.BooleanField(required=False)
    photo       = serializers.ImageField(required=False)

    class Meta:
        model  = User
        fields = ['first_name', 'last_name', 'department', 'permissions', 'is_active', 'photo', 'object_permissions']

    def update(self, instance, validated_data):
        department  = validated_data.pop('department', None)
        permissions = validated_data.pop('permissions', None)
        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        instance.save()
        if department is not None or permissions is not None:
            profile, _ = EmployeeProfile.objects.get_or_create(user=instance)
            if department  is not None: profile.department   = department
            if permissions is not None: profile.permissions  = permissions
            profile.save()
        return instance


class UPARegisterSerializer(serializers.Serializer):
    name           = serializers.CharField(max_length=150)
    mobile         = serializers.CharField(max_length=15)
    password       = serializers.CharField(write_only=True, min_length=8)
    upa_ref_id     = serializers.CharField(required=False, allow_blank=True)
    add_standalone = serializers.BooleanField(default=False)

    def validate_mobile(self, value):
        if User.objects.filter(mobile=value).exists():
            raise serializers.ValidationError('Mobile number already in use.')
        return value

    def validate(self, data):
        upa_ref_id     = data.get('upa_ref_id', '').strip() or None
        add_standalone = data.get('add_standalone', False)

        if upa_ref_id and not add_standalone:
            parent = User.objects.filter(upa_id=upa_ref_id).first()
            if not parent:
                raise serializers.ValidationError({'upa_ref_id': 'Invalid referral ID.'})
            leg = get_vacant_leg(parent)
            if leg is None:
                raise serializers.ValidationError({'no_vacant_leg': 'No vacant leg found.'})
            data['_parent'] = parent
            data['_leg']    = leg
        return data

    def create(self, validated_data):
        name           = validated_data['name']
        mobile         = validated_data['mobile']
        password       = validated_data['password']
        parent         = validated_data.get('_parent')
        leg            = validated_data.get('_leg')
        add_standalone = validated_data.get('add_standalone', False)

        first_name, *rest = name.split(' ', 1)
        last_name = rest[0] if rest else ''

        user = User.objects.create_user(
            password=password,
            mobile=mobile,
            first_name=first_name,
            last_name=last_name,
            role='upa_user',
            upa_id=generate_upa_id(),
        )
        Wallet.objects.create(user=user, balance=0.00)

        if parent and not add_standalone:
            UPATree.objects.create(user=user, parent_user=parent, leg=leg,
                                   depth_level=(parent.upa_node.depth_level + 1 if hasattr(parent, 'upa_node') else 1))
        else:
            UPATree.objects.create(user=user, parent_user=None, leg=None, depth_level=0)

        return user


class UPALoginSerializer(serializers.Serializer):
    mobile   = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = User.objects.filter(mobile=data['mobile']).first()
        if not user or not user.check_password(data['password']):
            raise serializers.ValidationError('Invalid credentials.')
        if user.role != 'upa_user':
            raise serializers.ValidationError('Invalid credentials.')
        if not user.is_active:
            raise serializers.ValidationError('Account is disabled.')
        data['user'] = user
        return data


class UserSerializer(BaseModelSerializer):
    full_name      = serializers.ReadOnlyField()
    photo_url      = serializers.SerializerMethodField()
    wallet_balance = serializers.SerializerMethodField()
    department     = serializers.SerializerMethodField()
    permissions    = serializers.SerializerMethodField()

    class Meta:
        model  = User
        fields = [
            'id', 'email', 'mobile', 'first_name', 'last_name', 'full_name',
            'role', 'upa_id', 'photo_url', 'wallet_balance',
            'department', 'permissions', 'date_joined', 'is_active',
            'object_permissions',
        ]
        read_only_fields = ['id', 'date_joined', 'upa_id', 'role']

    def get_photo_url(self, obj):
        request = self.context.get('request')
        if obj.photo and request:
            return request.build_absolute_uri(obj.photo.url)
        return None

    def get_wallet_balance(self, obj):
        try:
            return str(obj.wallet.balance)
        except Exception:
            return None

    def get_department(self, obj):
        try:
            return obj.employee_profile.department
        except Exception:
            return None

    def get_permissions(self, obj):
        try:
            return obj.employee_profile.permissions
        except Exception:
            return None


class EmployeeListSerializer(BaseModelSerializer):
    full_name   = serializers.ReadOnlyField()
    department  = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()

    class Meta:
        model  = User
        fields = ['id', 'email', 'mobile', 'full_name', 'role', 'department', 'permissions', 'is_active', 'date_joined', 'object_permissions']

    def get_department(self, obj):
        try:
            return obj.employee_profile.department
        except Exception:
            return None

    def get_permissions(self, obj):
        try:
            return obj.employee_profile.permissions
        except Exception:
            return None
