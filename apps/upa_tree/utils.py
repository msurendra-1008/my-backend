from .models import UPATree


def get_vacant_leg(parent_user):
    """Returns first vacant leg 'L','M','R' or None if all 3 are occupied."""
    occupied = UPATree.objects.filter(parent_user=parent_user).values_list('leg', flat=True)
    for leg in ['L', 'M', 'R']:
        if leg not in occupied:
            return leg
    return None


def get_tree_stats():
    """Returns counts: total UPA users, active, inactive, standalone, placed in tree."""
    from accounts.models import User
    total      = User.objects.filter(role='upa_user').count()
    active     = User.objects.filter(role='upa_user', is_active=True).count()
    inactive   = User.objects.filter(role='upa_user', is_active=False).count()
    standalone = UPATree.objects.filter(parent_user__isnull=True).count()
    placed     = UPATree.objects.filter(parent_user__isnull=False).count()
    return {
        'total_upa_users': total,
        'active':          active,
        'inactive':        inactive,
        'standalone':      standalone,
        'placed_in_tree':  placed,
    }


def get_subtree(user, max_depth=5):
    """Returns nested dict of the full subtree rooted at user, capped at max_depth levels."""
    try:
        root = UPATree.objects.select_related('user').get(user=user)
    except UPATree.DoesNotExist:
        return None

    def _build(node, depth):
        result = {
            'upa_id':      node.user.upa_id,
            'name':        node.user.full_name,
            'is_active':   node.user.is_active,
            'leg':         node.leg,
            'depth_level': node.depth_level,
            'joined_at':   node.joined_at.isoformat(),
            'children':    {},
        }
        if depth < max_depth:
            for leg, child in node.get_children().items():
                result['children'][leg] = _build(child, depth + 1) if child else None
        return result

    return _build(root, 0)
