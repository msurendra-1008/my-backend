from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from core.mixins import LoginRequiredMixin
from apps.authentication.permissions import IsAdmin, IsAdminOrEmployee, IsUPAUser
from .models import ReturnPhoto, ReturnRequest, ReturnSettings, ACTIVE_REQUEST_STATUSES
from .serializers import (
    ReturnRequestAdminSerializer,
    ReturnRequestCreateSerializer,
    ReturnRequestSerializer,
    ReturnSettingsSerializer,
)
from .utils import process_approved_exchange, process_approved_return


class _ReturnPagination(PageNumberPagination):
    page_size = 20


# ── ReturnSettings ────────────────────────────────────────────────────────────

class ReturnSettingsViewSet(LoginRequiredMixin, viewsets.ViewSet):

    def get_permissions(self):
        return [IsAdmin()]

    def list(self, request):
        return Response(ReturnSettingsSerializer(ReturnSettings.get()).data)

    @action(detail=False, methods=["patch"], url_path="update")
    def update_settings(self, request):
        settings_obj = ReturnSettings.get()
        ser = ReturnSettingsSerializer(settings_obj, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save(updated_by=request.user)
        return Response(ser.data)


# ── ReturnRequest ─────────────────────────────────────────────────────────────

class ReturnRequestViewSet(LoginRequiredMixin, viewsets.GenericViewSet):
    pagination_class = _ReturnPagination

    def get_queryset(self):
        user = self.request.user
        qs   = ReturnRequest.objects.select_related(
            "order_item__variant__product", "exchange_variant",
            "raised_by", "reviewed_by",
        ).prefetch_related("photos")
        if user.role in ("superadmin", "admin", "employee"):
            return qs
        return qs.filter(raised_by=user)

    def get_permissions(self):
        admin_actions = {"admin_list", "admin_detail", "approve", "reject", "request_info"}
        if self.action in admin_actions:
            return [IsAdminOrEmployee()]
        if self.action in {"approve", "reject"}:
            return [IsAdmin()]
        return [IsUPAUser()]

    # ── User: list own requests ───────────────────────────────────────────────

    @action(detail=False, methods=["get"], url_path="my-requests")
    def my_requests(self, request):
        qs     = ReturnRequest.objects.filter(raised_by=request.user).select_related(
            "order_item__variant__product", "exchange_variant",
        ).prefetch_related("photos").order_by("-created_at")
        page   = self.paginate_queryset(qs)
        ser    = ReturnRequestSerializer(page if page is not None else qs, many=True)
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)

    # ── User: raise request ───────────────────────────────────────────────────

    def create(self, request):
        if not (request.user and request.user.is_authenticated and request.user.role == "upa_user"):
            return Response({"detail": "Forbidden."}, status=403)
        ser = ReturnRequestCreateSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        rr  = ser.save()
        return Response(ReturnRequestSerializer(rr).data, status=status.HTTP_201_CREATED)

    # ── User: retrieve own request ────────────────────────────────────────────

    def retrieve(self, request, pk=None):
        rr = get_object_or_404(self.get_queryset(), pk=pk)
        return Response(ReturnRequestSerializer(rr).data)

    # ── User: upload photo ────────────────────────────────────────────────────

    @action(detail=True, methods=["post"], url_path="upload-photo")
    def upload_photo(self, request, pk=None):
        if not (request.user and request.user.is_authenticated and request.user.role == "upa_user"):
            return Response({"detail": "Forbidden."}, status=403)
        rr    = get_object_or_404(ReturnRequest, pk=pk, raised_by=request.user)
        photo = request.FILES.get("photo")
        if not photo:
            return Response({"detail": "No photo uploaded."}, status=400)
        if rr.photos.count() >= 3:
            return Response({"detail": "Maximum 3 photos allowed per request."}, status=400)
        p = ReturnPhoto.objects.create(return_request=rr, photo=photo)
        from .serializers import ReturnPhotoSerializer
        return Response(ReturnPhotoSerializer(p).data, status=status.HTTP_201_CREATED)

    # ── Admin: list all requests ──────────────────────────────────────────────

    @action(detail=False, methods=["get"], url_path="admin",
            permission_classes=[IsAdminOrEmployee])
    def admin_list(self, request):
        qs = ReturnRequest.objects.select_related(
            "order_item__variant__product", "exchange_variant", "raised_by",
        ).prefetch_related("photos")

        search = request.query_params.get("search", "").strip()
        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(order_item__order__order_number__icontains=search) |
                Q(raised_by__mobile__icontains=search) |
                Q(raised_by__first_name__icontains=search)
            )

        req_type = request.query_params.get("request_type", "")
        if req_type:
            qs = qs.filter(request_type=req_type)

        req_status = request.query_params.get("status", "")
        if req_status:
            qs = qs.filter(status=req_status)

        date_from = request.query_params.get("date_from", "")
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)

        date_to = request.query_params.get("date_to", "")
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        page = self.paginate_queryset(qs)
        ser  = ReturnRequestAdminSerializer(page if page is not None else qs, many=True)
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)

    # ── Admin: single request detail ──────────────────────────────────────────

    @action(detail=True, methods=["get"], url_path="admin",
            permission_classes=[IsAdminOrEmployee])
    def admin_detail(self, request, pk=None):
        rr = get_object_or_404(
            ReturnRequest.objects.select_related(
                "order_item__variant__product", "exchange_variant", "raised_by", "reviewed_by",
            ).prefetch_related("photos"),
            pk=pk,
        )
        return Response(ReturnRequestAdminSerializer(rr).data)

    # ── Admin: approve ────────────────────────────────────────────────────────

    @action(detail=True, methods=["patch"], url_path="approve",
            permission_classes=[IsAdmin])
    def approve(self, request, pk=None):
        rr = get_object_or_404(ReturnRequest, pk=pk)
        if rr.status not in ACTIVE_REQUEST_STATUSES:
            return Response(
                {"detail": f"Cannot approve a request with status '{rr.status}'."},
                status=400,
            )
        rr.reviewed_by = request.user
        rr.reviewed_at = timezone.now()
        rr.status      = "approved"
        rr.save(update_fields=["reviewed_by", "reviewed_at", "status"])

        try:
            if rr.request_type == "return":
                process_approved_return(rr)
            else:
                process_approved_exchange(rr)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)

        rr.refresh_from_db()
        return Response(ReturnRequestAdminSerializer(rr).data)

    # ── Admin: reject ─────────────────────────────────────────────────────────

    @action(detail=True, methods=["patch"], url_path="reject",
            permission_classes=[IsAdmin])
    def reject(self, request, pk=None):
        rr = get_object_or_404(ReturnRequest, pk=pk)
        if rr.status not in ACTIVE_REQUEST_STATUSES:
            return Response(
                {"detail": f"Cannot reject a request with status '{rr.status}'."},
                status=400,
            )
        rr.reviewed_by  = request.user
        rr.reviewed_at  = timezone.now()
        rr.status       = "rejected"
        rr.admin_notes  = request.data.get("admin_notes", rr.admin_notes)
        rr.save(update_fields=["reviewed_by", "reviewed_at", "status", "admin_notes"])

        # Revert OrderItem status back to delivered
        rr.order_item.status = "delivered"
        rr.order_item.save(update_fields=["status"])

        rr.refresh_from_db()
        return Response(ReturnRequestAdminSerializer(rr).data)

    # ── Admin: request more info ──────────────────────────────────────────────

    @action(detail=True, methods=["patch"], url_path="request-info",
            permission_classes=[IsAdminOrEmployee])
    def request_info(self, request, pk=None):
        rr = get_object_or_404(ReturnRequest, pk=pk)
        if rr.status not in ACTIVE_REQUEST_STATUSES:
            return Response(
                {"detail": f"Cannot update a request with status '{rr.status}'."},
                status=400,
            )
        rr.status      = "under_review"
        rr.admin_notes = request.data.get("admin_notes", rr.admin_notes)
        rr.reviewed_by = request.user
        rr.reviewed_at = timezone.now()
        rr.save(update_fields=["status", "admin_notes", "reviewed_by", "reviewed_at"])

        rr.refresh_from_db()
        return Response(ReturnRequestAdminSerializer(rr).data)
