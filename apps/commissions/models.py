from decimal import Decimal
from django.db import models
from django.conf import settings
from core.models import BaseModel

DEFAULT_LEVEL_PERCENTAGES = [40, 25, 15, 10, 5, 3, 2]


class CommissionSettings(BaseModel):
    DIRECTION_CHOICES = [
        ('direct_first',   'Direct parent gets most'),
        ('ancestor_first', 'Top ancestor gets most'),
    ]
    TRIGGER_CHOICES = [
        ('auto',   'Auto after return window expires'),
        ('manual', 'Manual by admin'),
    ]
    network_commission_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('7.00'))
    team_commission_pct    = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('3.00'))
    social_work_pct        = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text="% of profit for social work fund")
    company_pct            = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text="% of profit for company")
    max_upline_levels      = models.PositiveIntegerField(default=7)
    use_max_levels         = models.BooleanField(default=False)
    direction              = models.CharField(max_length=20, choices=DIRECTION_CHOICES, default='direct_first')
    level_percentages      = models.JSONField(default=list)
    left_leg_pct           = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('40.00'))
    middle_leg_pct         = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('30.00'))
    right_leg_pct          = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('30.00'))
    self_commission_enabled = models.BooleanField(default=False)
    self_commission_pct     = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    delivery_packaging_pct  = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    trigger_mode           = models.CharField(max_length=6, choices=TRIGGER_CHOICES, default='auto')
    updated_by             = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True,
    )

    class Meta:
        verbose_name        = 'Commission Settings'
        verbose_name_plural = 'Commission Settings'

    def save(self, *args, **kwargs):
        if not self.pk:
            existing = CommissionSettings.objects.first()
            if existing:
                self.pk = existing.pk
        if not self.level_percentages:
            self.level_percentages = DEFAULT_LEVEL_PERCENTAGES
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        obj = cls.objects.first()
        if not obj:
            obj = cls.objects.create(level_percentages=DEFAULT_LEVEL_PERCENTAGES)
        return obj


class ProductCommissionRule(BaseModel):
    DIRECTION_CHOICES = CommissionSettings.DIRECTION_CHOICES

    product                = models.OneToOneField('app_products.Product', on_delete=models.CASCADE, related_name='commission_rule')
    is_active              = models.BooleanField(default=True)
    network_commission_pct = models.DecimalField(max_digits=5, decimal_places=2)
    team_commission_pct    = models.DecimalField(max_digits=5, decimal_places=2)
    social_work_pct        = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    company_pct            = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    max_upline_levels      = models.PositiveIntegerField(default=7)
    use_max_levels         = models.BooleanField(default=False)
    direction              = models.CharField(max_length=20, choices=DIRECTION_CHOICES, default='direct_first')
    level_percentages      = models.JSONField(default=list)
    left_leg_pct            = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('40.00'))
    middle_leg_pct          = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('30.00'))
    right_leg_pct           = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('30.00'))
    self_commission_enabled = models.BooleanField(default=False)
    self_commission_pct     = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    delivery_packaging_pct  = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    created_by             = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='created_commission_rules',
    )

    def __str__(self):
        return f"CommissionRule({self.product.name})"


class CommissionBreakup(BaseModel):
    STATUS_CHOICES = [
        ('pending_window', 'Waiting for return window'),
        ('processing',     'Being processed'),
        ('completed',      'All credits done'),
        ('partial',        'Some pending'),
    ]
    order_item            = models.OneToOneField('orders.OrderItem', on_delete=models.CASCADE, related_name='commission_breakup')
    total_base_amount     = models.DecimalField(max_digits=12, decimal_places=2)
    network_pool          = models.DecimalField(max_digits=12, decimal_places=2)
    team_pool             = models.DecimalField(max_digits=12, decimal_places=2)
    status                = models.CharField(max_length=15, choices=STATUS_CHOICES, default='pending_window')
    return_window_expires = models.DateTimeField(null=True, blank=True)
    processed_at          = models.DateTimeField(null=True, blank=True)
    rule_snapshot         = models.JSONField(default=dict, help_text="Snapshot of commission rule at calculation time")

    def __str__(self):
        return f"Breakup({self.order_item})"


class CommissionEntry(BaseModel):
    ENTRY_TYPE_CHOICES = [
        ('network_upline',  'Network (upline)'),
        ('team_downline',   'Team (downline)'),
        ('social_work',     'Social Work'),
        ('company',         'Company'),
        ('self_commission', 'Self Commission'),
    ]
    STATUS_CHOICES = [
        ('pending_window', 'Pending return window'),
        ('credited',       'Credited to wallet'),
        ('pending',        'Pending — user inactive'),
        ('vacant',         'Vacant leg — skipped'),
    ]
    LEG_CHOICES = [
        ('left', 'Left'), ('middle', 'Middle'), ('right', 'Right'),
    ]

    breakup            = models.ForeignKey(CommissionBreakup, on_delete=models.CASCADE, related_name='entries')
    recipient          = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='commission_entries',
    )
    recipient_upa_id   = models.CharField(max_length=20, blank=True)
    recipient_name     = models.CharField(max_length=255, blank=True)
    recipient_mobile   = models.CharField(max_length=20, blank=True)
    entry_type         = models.CharField(max_length=20, choices=ENTRY_TYPE_CHOICES)
    level              = models.PositiveIntegerField(null=True, blank=True)
    leg_position       = models.CharField(max_length=6, choices=LEG_CHOICES, blank=True)
    amount             = models.DecimalField(max_digits=12, decimal_places=2)
    percentage_applied = models.DecimalField(max_digits=6, decimal_places=2)
    status             = models.CharField(max_length=14, choices=STATUS_CHOICES)
    credited_at        = models.DateTimeField(null=True, blank=True)
    wallet_transaction = models.ForeignKey(
        'app_wallet.WalletTransaction', on_delete=models.SET_NULL,
        null=True, blank=True,
    )

    def __str__(self):
        return f"{self.entry_type} L{self.level} ₹{self.amount} → {self.recipient_name}"
