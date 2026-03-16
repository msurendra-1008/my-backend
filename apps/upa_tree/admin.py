from django.contrib import admin
from django.utils.html import mark_safe
from .models import UPATree


@admin.register(UPATree)
class UPATreeAdmin(admin.ModelAdmin):
    list_display    = ('upa_id_col', 'full_name_col', 'mobile_col', 'parent_col', 'leg', 'depth_level', 'joined_at')
    list_filter     = ('leg', 'depth_level')
    search_fields   = (
        'user__upa_id', 'user__first_name', 'user__last_name',
        'user__mobile', 'parent_user__upa_id', 'parent_user__first_name',
    )
    ordering        = ('depth_level', 'joined_at')
    readonly_fields = ('user', 'parent_user', 'leg', 'depth_level', 'joined_at', 'parent_panel', 'leg_status_panel')

    fieldsets = (
        ('Node Info', {
            'fields': ('user', 'leg', 'depth_level', 'joined_at'),
            'description': 'Basic information about this UPA tree node.',
        }),
        ('Parent Details', {
            'fields': ('parent_panel',),
            'description': 'Who referred this user and where they are placed.',
        }),
        ('Leg Occupancy', {
            'fields': ('leg_status_panel',),
            'description': "Shows which of this user's 3 legs (L/M/R) are filled and which are vacant.",
        }),
    )

    # ── List display helpers ──────────────────────────────────────────────────

    def upa_id_col(self, obj):
        return mark_safe(f'<span style="font-family:monospace;font-weight:600;color:#7c3aed">{obj.user.upa_id or "—"}</span>')
    upa_id_col.short_description = 'UPA ID'

    def full_name_col(self, obj):
        return obj.user.full_name or '—'
    full_name_col.short_description = 'Name'

    def mobile_col(self, obj):
        return obj.user.mobile or '—'
    mobile_col.short_description = 'Mobile'

    def parent_col(self, obj):
        if not obj.parent_user:
            return mark_safe('<span style="color:#999;font-style:italic">Root / Standalone</span>')
        p = obj.parent_user
        return mark_safe(
            f'{p.full_name or p.mobile}'
            f'<br><span style="font-family:monospace;font-size:11px;color:#7c3aed">{p.upa_id or "—"}</span>'
        )
    parent_col.short_description = 'Parent'

    # ── Detail panel: parent info ─────────────────────────────────────────────

    def parent_panel(self, obj):
        if not obj.parent_user:
            return mark_safe(
                '<div style="padding:12px;background:#f9fafb;border-radius:6px;color:#6b7280">'
                '<strong>No parent</strong> — this is a root or standalone node.'
                '</div>'
            )
        p = obj.parent_user
        leg_color = {'L': '#dbeafe', 'M': '#dcfce7', 'R': '#fef9c3'}.get(obj.leg or '', '#f3f4f6')
        leg_text  = {'L': 'Left', 'M': 'Middle', 'R': 'Right'}.get(obj.leg or '', obj.leg or '—')

        rows = (
            ('Name',      p.full_name or '—'),
            ('UPA ID',    f'<span style="font-family:monospace;color:#7c3aed">{p.upa_id or "—"}</span>'),
            ('Mobile',    p.mobile or '—'),
            ('Placed in', f'<span style="background:{leg_color};padding:2px 10px;border-radius:12px;font-weight:600">{leg_text}</span>'),
        )

        html = '<table style="border-collapse:collapse;font-size:13px;min-width:360px">'
        for label, value in rows:
            html += (
                f'<tr>'
                f'<td style="padding:6px 12px 6px 0;color:#6b7280;white-space:nowrap">{label}</td>'
                f'<td style="padding:6px 0 6px 12px">{value}</td>'
                f'</tr>'
            )
        html += '</table>'
        return mark_safe(html)
    parent_panel.short_description = 'Parent'

    # ── Detail panel: leg occupancy ───────────────────────────────────────────

    def leg_status_panel(self, obj):
        """Shows L / M / R legs of this node and who occupies them."""
        children = {
            c.leg: c
            for c in UPATree.objects.filter(parent_user=obj.user).select_related('user')
        }

        leg_configs = [
            ('L', 'Left',   '#dbeafe', '#1d4ed8'),
            ('M', 'Middle', '#dcfce7', '#15803d'),
            ('R', 'Right',  '#fef9c3', '#a16207'),
        ]

        cards = []
        for leg_key, leg_label, bg, fg in leg_configs:
            child = children.get(leg_key)
            if child:
                name   = child.user.full_name or '—'
                upa_id = child.user.upa_id or '—'
                mobile = child.user.mobile or '—'
                card = (
                    f'<div style="border:1px solid {fg}40;border-radius:8px;padding:12px;background:{bg};min-width:130px">'
                    f'  <div style="font-size:10px;font-weight:700;text-transform:uppercase;color:{fg};margin-bottom:6px">{leg_label}</div>'
                    f'  <div style="font-weight:600;font-size:13px">{name}</div>'
                    f'  <div style="font-family:monospace;font-size:11px;color:{fg}">{upa_id}</div>'
                    f'  <div style="font-size:11px;color:#6b7280">{mobile}</div>'
                    f'</div>'
                )
            else:
                card = (
                    f'<div style="border:2px dashed #d1d5db;border-radius:8px;padding:12px;background:#fafafa;min-width:130px">'
                    f'  <div style="font-size:10px;font-weight:700;text-transform:uppercase;color:#9ca3af;margin-bottom:6px">{leg_label}</div>'
                    f'  <div style="color:#9ca3af;font-style:italic;font-size:13px">Vacant</div>'
                    f'</div>'
                )
            cards.append(card)

        html = (
            '<div style="display:flex;gap:12px;flex-wrap:wrap">'
            + ''.join(cards)
            + '</div>'
        )
        return mark_safe(html)
    leg_status_panel.short_description = 'Leg Occupancy'
