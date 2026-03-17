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

    def get_children(self):
        """Returns dict of all 3 legs with their UPATree node or None."""
        children = {
            c.leg: c
            for c in UPATree.objects.filter(parent_user=self.user).select_related('user')
        }
        return {leg: children.get(leg) for leg in ('L', 'M', 'R')}

    def get_ancestors(self):
        """Returns list of ancestor nodes from root to parent (closest last)."""
        ancestors = []
        current = self
        while current.parent_user is not None:
            try:
                parent_node = UPATree.objects.select_related('user', 'parent_user').get(user=current.parent_user)
                ancestors.insert(0, parent_node)
                current = parent_node
            except UPATree.DoesNotExist:
                break
        return ancestors
