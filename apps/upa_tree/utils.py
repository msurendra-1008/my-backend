from .models import UPATree


def get_vacant_leg(parent_user):
    """Returns first vacant leg 'L','M','R' or None if all 3 are occupied."""
    occupied = UPATree.objects.filter(parent_user=parent_user).values_list('leg', flat=True)
    for leg in ['L', 'M', 'R']:
        if leg not in occupied:
            return leg
    return None
