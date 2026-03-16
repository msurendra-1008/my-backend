from django.db import models
from django.conf import settings
from core.models import BaseModel


class UPATree(BaseModel):
    LEG_CHOICES = [('L', 'Left'), ('M', 'Middle'), ('R', 'Right')]

    user        = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='upa_node')
    parent_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='children_nodes')
    leg         = models.CharField(max_length=1, choices=LEG_CHOICES, null=True, blank=True)
    depth_level = models.PositiveIntegerField(default=0)
    joined_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('parent_user', 'leg')]

    def __str__(self):
        return f"{self.user.upa_id} → {self.parent_user} [{self.leg}]"
