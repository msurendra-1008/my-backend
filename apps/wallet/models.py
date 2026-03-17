from django.db import models
from django.conf import settings
from core.models import BaseModel


class Wallet(BaseModel):
    user    = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    def __str__(self):
        return f"Wallet({self.user}, ₹{self.balance})"


class WalletTransaction(BaseModel):
    TYPE_CHOICES = [('credit', 'Credit'), ('debit', 'Debit')]

    wallet       = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    type         = models.CharField(max_length=6, choices=TYPE_CHOICES)
    amount       = models.DecimalField(max_digits=12, decimal_places=2)
    reason       = models.CharField(max_length=255)
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='triggered_transactions',
    )
    reference    = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.type.upper()} ₹{self.amount} → {self.wallet.user}"
