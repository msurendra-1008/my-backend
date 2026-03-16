from django.db import models
from django.conf import settings
from core.models import BaseModel


class Wallet(BaseModel):
    user    = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    def __str__(self):
        return f"Wallet({self.user}, ₹{self.balance})"
