from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import User
from apps.wallet.models import Wallet
from apps.upa_tree.models import UPATree
from apps.authentication.utils import generate_upa_id


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_admin(email='admin@tree.com', password='pass1234', role='admin'):
    return User.objects.create_user(
        password=password, email=email,
        first_name='Admin', role=role,
    )


def make_upa(mobile, password='pass1234', parent=None, leg=None):
    u = User.objects.create_user(
        password=password, mobile=mobile,
        first_name=f'User{mobile[-4:]}', role='upa_user',
        upa_id=generate_upa_id(),
    )
    Wallet.objects.create(user=u)
    parent_depth = 0
    if parent:
        try:
            parent_depth = parent.upa_node.depth_level
        except UPATree.DoesNotExist:
            pass
    UPATree.objects.create(
        user=u,
        parent_user=parent,
        leg=leg,
        depth_level=(parent_depth + 1) if parent else 0,
    )
    return u


# ── B6 Tests ─────────────────────────────────────────────────────────────────

class RegistrationTreeTests(TestCase):
    """Register → tree node created correctly."""

    def setUp(self):
        self.client = APIClient()
        self.register_url = '/api/v1/auth/user/register/'

    def test_T1_register_with_valid_ref_creates_node_correct_leg_depth(self):
        parent = make_upa('8000000001')
        r = self.client.post(self.register_url, {
            'name': 'Child', 'mobile': '8000000002',
            'password': 'pass1234', 'upa_ref_id': parent.upa_id,
        }, format='json')
        self.assertEqual(r.status_code, 201)
        child = User.objects.get(mobile='8000000002')
        node  = UPATree.objects.get(user=child)
        self.assertEqual(node.parent_user, parent)
        self.assertEqual(node.leg, 'L')          # first vacant leg
        self.assertEqual(node.depth_level, 1)    # parent is level 0

    def test_T2_register_standalone_creates_node_null_parent_leg(self):
        r = self.client.post(self.register_url, {
            'name': 'Alone', 'mobile': '8000000003', 'password': 'pass1234',
        }, format='json')
        self.assertEqual(r.status_code, 201)
        node = UPATree.objects.get(user__mobile='8000000003')
        self.assertIsNone(node.parent_user)
        self.assertIsNone(node.leg)
        self.assertEqual(node.depth_level, 0)

    def test_T3_three_users_join_same_parent_all_legs_filled(self):
        parent = make_upa('8000000010')
        for i, mobile in enumerate(['8000000011', '8000000012', '8000000013']):
            r = self.client.post(self.register_url, {
                'name': f'Child{i}', 'mobile': mobile,
                'password': 'pass1234', 'upa_ref_id': parent.upa_id,
            }, format='json')
            self.assertEqual(r.status_code, 201)
        legs = set(
            UPATree.objects.filter(parent_user=parent).values_list('leg', flat=True)
        )
        self.assertEqual(legs, {'L', 'M', 'R'})


class MyConnectionsTests(TestCase):
    """GET /api/v1/tree/my-connections/"""

    def setUp(self):
        self.client = APIClient()
        self.url = '/api/v1/tree/my-connections/'

    def _auth_upa(self, user):
        r = self.client.post('/api/v1/auth/user/login/', {
            'mobile': user.mobile, 'password': 'pass1234',
        })
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")

    def test_T4_my_connections_returns_correct_parent_and_legs(self):
        parent = make_upa('9100000001')
        child  = make_upa('9100000002', parent=parent, leg='L')
        # Add a leg node
        make_upa('9100000003', parent=parent, leg='M')

        self._auth_upa(parent)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.data['parent'])
        self.assertIsNotNone(r.data['legs']['L'])
        self.assertIsNotNone(r.data['legs']['M'])
        self.assertIsNone(r.data['legs']['R'])
        self.assertEqual(r.data['legs']['L']['upa_id'], child.upa_id)

    def test_T5_my_connections_standalone_all_nulls(self):
        user = make_upa('9100000010')
        self._auth_upa(user)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.data['parent'])
        self.assertIsNone(r.data['legs']['L'])
        self.assertIsNone(r.data['legs']['M'])
        self.assertIsNone(r.data['legs']['R'])


class AdminTreeTests(TestCase):
    """Admin-only endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.admin  = make_admin()
        r = self.client.post('/api/v1/auth/admin/login/', {
            'identifier': 'admin@tree.com', 'password': 'pass1234',
        })
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")

        # Create some UPA users for testing
        self.root1 = make_upa('7000000001')
        self.root2 = make_upa('7000000002')
        self.child  = make_upa('7000000003', parent=self.root1, leg='L')

    def test_T6_stats_as_admin_returns_correct_counts(self):
        r = self.client.get('/api/v1/tree/stats/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['total_upa_users'], 3)
        self.assertEqual(r.data['standalone'], 2)    # root1 and root2
        self.assertEqual(r.data['placed_in_tree'], 1) # child

    def test_T7_stats_as_upa_user_returns_403(self):
        upa = make_upa('7000000099')
        r2  = self.client.post('/api/v1/auth/user/login/', {
            'mobile': '7000000099', 'password': 'pass1234',
        })
        upa_client = APIClient()
        upa_client.credentials(HTTP_AUTHORIZATION=f"Bearer {r2.data['access']}")
        r = upa_client.get('/api/v1/tree/stats/')
        self.assertEqual(r.status_code, 403)

    def test_T8_search_by_upa_id(self):
        r = self.client.get(f'/api/v1/tree/search/?q={self.root1.upa_id}')
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(r.data['count'], 1)
        upa_ids = [item['upa_id'] for item in r.data['results']]
        self.assertIn(self.root1.upa_id, upa_ids)

    def test_T8b_search_by_name(self):
        # first_name is f'User{mobile[-4:]}' — e.g. 'User0001' for mobile 7000000001
        r = self.client.get('/api/v1/tree/search/?q=User0001')
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(r.data['count'], 1)

    def test_T9_browse_returns_root_nodes_with_children(self):
        r = self.client.get('/api/v1/tree/browse/')
        self.assertEqual(r.status_code, 200)
        # Both standalone root nodes should appear
        self.assertGreaterEqual(r.data['count'], 2)
        result = r.data['results']
        self.assertIn('children', result[0])

    def test_T10_subtree_returns_nested_dict(self):
        r = self.client.get(f'/api/v1/tree/{self.root1.upa_id}/subtree/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['upa_id'], self.root1.upa_id)
        self.assertIn('children', r.data)
        # child should appear in L leg
        self.assertIsNotNone(r.data['children']['L'])
        self.assertEqual(r.data['children']['L']['upa_id'], self.child.upa_id)

    def test_T11_profile_returns_full_profile_with_wallet(self):
        r = self.client.get(f'/api/v1/tree/{self.root1.upa_id}/profile/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['upa_id'], self.root1.upa_id)
        self.assertIn('wallet_balance', r.data)
        self.assertIn('children_summary', r.data)

    def test_T12_toggle_active_flips_status(self):
        self.assertTrue(self.root2.is_active)
        r = self.client.patch(f'/api/v1/tree/{self.root2.upa_id}/toggle-active/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['is_active'])
        self.root2.refresh_from_db()
        self.assertFalse(self.root2.is_active)

        # Deactivated user cannot login
        r2 = self.client.post('/api/v1/auth/user/login/', {
            'mobile': '7000000002', 'password': 'pass1234',
        })
        self.assertEqual(r2.status_code, 400)

    def test_T13_toggle_active_as_upa_user_returns_403(self):
        upa = make_upa('7000000098')
        r2  = self.client.post('/api/v1/auth/user/login/', {
            'mobile': '7000000098', 'password': 'pass1234',
        })
        upa_client = APIClient()
        upa_client.credentials(HTTP_AUTHORIZATION=f"Bearer {r2.data['access']}")
        r = upa_client.patch(f'/api/v1/tree/{self.root1.upa_id}/toggle-active/')
        self.assertEqual(r.status_code, 403)
