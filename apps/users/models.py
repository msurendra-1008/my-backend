from django.db import models
from django.conf import settings
from core.models import BaseModel


class EmployeeProfile(BaseModel):
    user        = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='employee_profile')
    department  = models.CharField(max_length=100, blank=True)
    permissions = models.JSONField(default=list, blank=True)
    created_by  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='created_employees')

    def __str__(self):
        return f"{self.user} — {self.department}"
