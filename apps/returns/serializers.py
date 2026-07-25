from decimal import Decimal

from django.shortcuts import get_object_or_404
from rest_framework import serializers

from apps.orders.models import OrderItem
from apps.orders.serializers import OrderItemSerializer
from apps.products.models import ProductVariant
from .models import ReturnPhoto, ReturnRequest, ReturnRequestLog, ReturnSettings
from .utils import is_return_eligible


# ── Settings ──────────────────────────────────────────────────────────────────

class ReturnSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ReturnSettings
        fields = ["return_window_days", "exchange_buffer_days", "max_attempts", "predefined_reasons"]

    def validate_return_window_days(self, value):
        if value < 1 or value > 90:
            raise serializers.ValidationError("Return window must be between 1 and 90 days.")
        return value

    def validate_exchange_buffer_days(self, value):
        if value < 1 or value > 30:
            raise serializers.ValidationError("Exchange buffer must be between 1 and 30 days.")
        return value

    def validate_max_attempts(self, value):
        if value < 1 or value > 5:
            raise serializers.ValidationError("Max attempts must be between 1 and 5.")
        return value


# ── Photo ─────────────────────────────────────────────────────────────────────

class ReturnPhotoSerializer(serializers.ModelSerializer):
    photo_url = serializers.SerializerMethodField()

    class Meta:
        model  = ReturnPhoto
        fields = ["id", "photo", "photo_url", "log", "created_at"]

    def get_photo_url(self, obj):
        request = self.context.get("request")
        if request and obj.photo:
            return request.build_absolute_uri(obj.photo.url)
        return obj.photo.url if obj.photo else None


# ── Request Log ───────────────────────────────────────────────────────────────

class ReturnRequestLogSerializer(serializers.ModelSerializer):
    photos     = ReturnPhotoSerializer(many=True, read_only=True)
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model  = ReturnRequestLog
        fields = [
            "id", "action", "actor", "actor_name", "actor_role",
            "notes", "photos", "created_at",
        ]

    def get_actor_name(self, obj):
        if obj.actor:
            return getattr(obj.actor, "full_name", None) or obj.actor.first_name or str(obj.actor)
        return ""


# ── Request — create (user) ───────────────────────────────────────────────────

class ReturnRequestCreateSerializer(serializers.ModelSerializer):
    order_item_id      = serializers.UUIDField(write_only=True)
    exchange_variant_id = serializers.UUIDField(required=False, allow_null=True, write_only=True)

    class Meta:
        model  = ReturnRequest
        fields = [
            "order_item_id", "request_type", "return_qty",
            "exchange_variant_id", "reason", "notes",
        ]

    def validate(self, data):
        order_item = get_object_or_404(OrderItem, pk=data["order_item_id"])

        eligible, reason = is_return_eligible(order_item)
        if not eligible:
            raise serializers.ValidationError({"order_item_id": reason})

        if data["return_qty"] > order_item.quantity:
            raise serializers.ValidationError(
                {"return_qty": "Return quantity cannot exceed ordered quantity."}
            )

        if data["request_type"] == "exchange":
            if not order_item.variant_id:
                raise serializers.ValidationError(
                    {"order_item_id": "Cannot raise an exchange — variant not recorded on this order item."}
                )
            # Exchange is always same-variant replacement; ignore any client-supplied exchange_variant_id
            exv = get_object_or_404(ProductVariant, pk=order_item.variant_id)
            data["_exchange_variant"] = exv
        else:
            data["_exchange_variant"] = None

        data["_order_item"] = order_item
        return data

    def create(self, validated_data):
        from .utils import create_log

        order_item      = validated_data.pop("_order_item")
        exchange_variant = validated_data.pop("_exchange_variant")
        validated_data.pop("order_item_id")
        validated_data.pop("exchange_variant_id", None)

        request_type = validated_data["request_type"]

        # Compute attempt_count from rejection count
        attempt_count = order_item.return_rejection_count + 1

        rr = ReturnRequest.objects.create(
            order_item=order_item,
            exchange_variant=exchange_variant,
            raised_by=self.context["request"].user,
            waiting_for="admin",
            attempt_count=attempt_count,
            **validated_data,
        )

        # Update item status
        new_status = "return_requested" if request_type == "return" else "exchange_requested"
        order_item.status = new_status
        order_item.save(update_fields=["status"])

        # Create initial log
        action = "raised" if attempt_count == 1 else "re_raised"
        create_log(rr, action, actor=self.context["request"].user,
                   notes=validated_data.get("notes", ""))

        return rr


# ── Request — read (user + admin) ─────────────────────────────────────────────

class ReturnRequestSerializer(serializers.ModelSerializer):
    photos                = ReturnPhotoSerializer(many=True, read_only=True)
    logs                  = ReturnRequestLogSerializer(many=True, read_only=True)
    order_item            = OrderItemSerializer(read_only=True)
    exchange_variant_name = serializers.SerializerMethodField()
    raised_by_name        = serializers.SerializerMethodField()
    raised_at             = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model  = ReturnRequest
        fields = [
            "id", "order_item", "request_type", "return_qty",
            "exchange_variant", "exchange_variant_name",
            "reason", "notes", "status", "waiting_for", "attempt_count",
            "refund_amount", "refund_mode", "admin_notes",
            "user_reply_count",
            "raised_at", "reviewed_at", "completed_at",
            "raised_by", "raised_by_name",
            "photos", "logs", "updated_at",
        ]

    def get_exchange_variant_name(self, obj):
        return obj.exchange_variant.name if obj.exchange_variant else None

    def get_raised_by_name(self, obj):
        return obj.raised_by.full_name if obj.raised_by else ""


# ── Request — admin update ────────────────────────────────────────────────────

class ReturnRequestAdminSerializer(ReturnRequestSerializer):
    admin_notes = serializers.CharField(required=False, allow_blank=True)

    class Meta(ReturnRequestSerializer.Meta):
        pass
