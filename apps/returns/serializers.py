from decimal import Decimal

from django.shortcuts import get_object_or_404
from rest_framework import serializers

from apps.orders.models import OrderItem
from apps.orders.serializers import OrderItemSerializer
from apps.products.models import ProductVariant
from .models import ReturnPhoto, ReturnRequest, ReturnSettings
from .utils import is_return_eligible


# ── Settings ──────────────────────────────────────────────────────────────────

class ReturnSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ReturnSettings
        fields = ["return_window_days", "predefined_reasons"]


# ── Photo ─────────────────────────────────────────────────────────────────────

class ReturnPhotoSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ReturnPhoto
        fields = ["id", "photo", "created_at"]


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

        exchange_variant_id = data.get("exchange_variant_id")
        if data["request_type"] == "exchange":
            if not exchange_variant_id:
                raise serializers.ValidationError(
                    {"exchange_variant_id": "Exchange variant is required for exchange requests."}
                )
            exv = get_object_or_404(ProductVariant, pk=exchange_variant_id)

            if not order_item.variant_id:
                raise serializers.ValidationError(
                    {"exchange_variant_id": "Original variant not found on this order item."}
                )
            if exv.product_id != order_item.variant.product_id:
                raise serializers.ValidationError(
                    {"exchange_variant_id": "Exchange variant must be a variant of the same product."}
                )
            if exv.pk == order_item.variant_id:
                raise serializers.ValidationError(
                    {"exchange_variant_id": "Exchange variant must differ from the ordered variant."}
                )
            if exv.stock_quantity < data["return_qty"]:
                raise serializers.ValidationError(
                    {"exchange_variant_id": "Selected exchange variant does not have sufficient stock."}
                )
            data["_exchange_variant"] = exv
        else:
            data["_exchange_variant"] = None

        data["_order_item"] = order_item
        return data

    def create(self, validated_data):
        order_item      = validated_data.pop("_order_item")
        exchange_variant = validated_data.pop("_exchange_variant")
        validated_data.pop("order_item_id")
        validated_data.pop("exchange_variant_id", None)

        request_type = validated_data["request_type"]

        rr = ReturnRequest.objects.create(
            order_item=order_item,
            exchange_variant=exchange_variant,
            raised_by=self.context["request"].user,
            **validated_data,
        )

        # Update item status
        new_status = "return_requested" if request_type == "return" else "exchange_requested"
        order_item.status = new_status
        order_item.save(update_fields=["status"])

        return rr


# ── Request — read (user + admin) ─────────────────────────────────────────────

class ReturnRequestSerializer(serializers.ModelSerializer):
    photos                = ReturnPhotoSerializer(many=True, read_only=True)
    order_item            = OrderItemSerializer(read_only=True)
    exchange_variant_name = serializers.SerializerMethodField()
    raised_by_name        = serializers.SerializerMethodField()
    raised_at             = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model  = ReturnRequest
        fields = [
            "id", "order_item", "request_type", "return_qty",
            "exchange_variant", "exchange_variant_name",
            "reason", "notes", "status",
            "refund_amount", "refund_mode", "admin_notes",
            "user_reply_count",
            "raised_at", "reviewed_at", "completed_at",
            "raised_by", "raised_by_name",
            "photos", "updated_at",
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
