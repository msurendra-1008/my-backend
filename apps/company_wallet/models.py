from django.conf import settings
from django.db import models
from core.models import BaseModel


class CompanyWallet(BaseModel):
    """Singleton — one row tracks the running company balance."""
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        verbose_name = 'Company Wallet'

    def __str__(self):
        return f'Company Wallet — ₹{self.balance}'

    def save(self, *args, **kwargs):
        if not self.pk and CompanyWallet.objects.exists():
            raise ValueError('Only one CompanyWallet instance is allowed.')
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        wallet, _ = cls.objects.get_or_create()
        return wallet


class CompanyTransaction(BaseModel):
    TYPE_CHOICES = [
        ('order_received',     'Order Received'),
        ('commission_paid',    'Commission Paid'),
        ('refund_paid',        'Refund Paid'),
        ('gst_collected',      'GST Collected'),
        ('gst_paid',           'GST Paid'),
        ('manual_credit',      'Manual Credit'),
        ('manual_debit',       'Manual Debit'),
        ('salary_paid',        'Salary Paid'),
    ]

    wallet           = models.ForeignKey(CompanyWallet, on_delete=models.PROTECT, related_name='transactions')
    transaction_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    amount           = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after    = models.DecimalField(max_digits=14, decimal_places=2)
    description      = models.CharField(max_length=255, blank=True)
    order            = models.ForeignKey(
        'orders.Order', null=True, blank=True, on_delete=models.SET_NULL, related_name='company_transactions'
    )
    order_item       = models.ForeignKey(
        'orders.OrderItem', null=True, blank=True, on_delete=models.SET_NULL, related_name='company_transactions'
    )
    commission_entry = models.ForeignKey(
        'commissions.CommissionEntry', null=True, blank=True, on_delete=models.SET_NULL, related_name='company_transactions'
    )
    triggered_by     = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='company_transactions'
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Company Transaction'

    def __str__(self):
        return f'{self.get_transaction_type_display()} ₹{self.amount}'


class GSTLedgerEntry(BaseModel):
    TYPE_CHOICES = [
        ('collected', 'GST Collected (from customer)'),
        ('paid',      'GST Paid (to govt)'),
    ]

    gst_type    = models.CharField(max_length=10, choices=TYPE_CHOICES)
    amount      = models.DecimalField(max_digits=12, decimal_places=2)
    order_item  = models.ForeignKey(
        'orders.OrderItem', null=True, blank=True, on_delete=models.SET_NULL, related_name='gst_ledger_entries'
    )
    description = models.CharField(max_length=255, blank=True)
    reference   = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'GST Ledger Entry'

    def __str__(self):
        return f'{self.get_gst_type_display()} ₹{self.amount}'
