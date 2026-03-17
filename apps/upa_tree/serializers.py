from rest_framework import serializers
from .models import UPATree


class MyConnectionsSerializer(serializers.ModelSerializer):
    upa_id      = serializers.CharField(source='user.upa_id')
    depth_level = serializers.IntegerField()
    parent      = serializers.SerializerMethodField()
    legs        = serializers.SerializerMethodField()

    class Meta:
        model  = UPATree
        fields = ['upa_id', 'depth_level', 'parent', 'legs']

    def get_parent(self, obj):
        if not obj.parent_user:
            return None
        return {'upa_id': obj.parent_user.upa_id, 'name': obj.parent_user.full_name}

    def get_legs(self, obj):
        result = {}
        for leg, node in obj.get_children().items():
            result[leg] = {
                'upa_id':    node.user.upa_id,
                'name':      node.user.full_name,
                'joined_at': node.joined_at.isoformat(),
                'is_active': node.user.is_active,
            } if node else None
        return result


class UPANodeSerializer(serializers.ModelSerializer):
    upa_id        = serializers.CharField(source='user.upa_id')
    name          = serializers.CharField(source='user.full_name')
    mobile        = serializers.CharField(source='user.mobile')
    is_active     = serializers.BooleanField(source='user.is_active')
    photo_url     = serializers.SerializerMethodField()
    parent_upa_id = serializers.SerializerMethodField()

    class Meta:
        model  = UPATree
        fields = [
            'id', 'upa_id', 'name', 'mobile', 'is_active',
            'leg', 'depth_level', 'joined_at', 'photo_url', 'parent_upa_id',
        ]

    def get_photo_url(self, obj):
        request = self.context.get('request')
        if obj.user.photo and request:
            return request.build_absolute_uri(obj.user.photo.url)
        return None

    def get_parent_upa_id(self, obj):
        return obj.parent_user.upa_id if obj.parent_user else None


class UPAProfileSerializer(UPANodeSerializer):
    wallet_balance   = serializers.SerializerMethodField()
    children_summary = serializers.SerializerMethodField()
    user_id          = serializers.UUIDField(source='user.id')

    class Meta(UPANodeSerializer.Meta):
        fields = UPANodeSerializer.Meta.fields + ['user_id', 'wallet_balance', 'children_summary']

    def get_wallet_balance(self, obj):
        try:
            return str(obj.user.wallet.balance)
        except Exception:
            return '0.00'

    def get_children_summary(self, obj):
        result = {}
        for leg, node in obj.get_children().items():
            result[leg] = {'upa_id': node.user.upa_id, 'name': node.user.full_name} if node else None
        return result


class UPASearchSerializer(serializers.ModelSerializer):
    upa_id        = serializers.CharField(source='user.upa_id')
    name          = serializers.CharField(source='user.full_name')
    mobile        = serializers.CharField(source='user.mobile')
    is_active     = serializers.BooleanField(source='user.is_active')
    parent_upa_id = serializers.SerializerMethodField()
    legs_filled   = serializers.SerializerMethodField()

    class Meta:
        model  = UPATree
        fields = [
            'id', 'upa_id', 'name', 'mobile', 'is_active',
            'depth_level', 'parent_upa_id', 'legs_filled', 'joined_at',
        ]

    def get_parent_upa_id(self, obj):
        return obj.parent_user.upa_id if obj.parent_user else None

    def get_legs_filled(self, obj):
        return UPATree.objects.filter(parent_user=obj.user).count()
