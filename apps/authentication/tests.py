from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import User
from apps.wallet.models import Wallet
from apps.upa_tree.models import UPATree
from apps.users.models import EmployeeProfile


def make_admin(email='admin@test.com', password='testpass123', role='admin'):
    u = User.objects.create_user(password=password, email=email, first_name='Admin', role=role)
    return u


def make_upa(mobile='9999999999', password='testpass123'):
    from apps.authentication.utils import generate_upa_id
    u = User.objects.create_user(password=password, mobile=mobile, first_name='UPAUser', role='upa_user', upa_id=generate_upa_id())
    Wallet.objects.create(user=u)
    UPATree.objects.create(user=u, parent_user=None, leg=None)
    return u


class AdminLoginTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = '/api/v1/auth/admin/login/'
        self.admin = make_admin(email='a@test.com', password='pass1234')

    def test_B8_1_admin_login_email(self):
        r = self.client.post(self.url, {'identifier': 'a@test.com', 'password': 'pass1234'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('access', r.data)
        self.assertEqual(r.data['user']['role'], 'admin')

    def test_B8_2_admin_login_mobile(self):
        self.admin.mobile = '1234567890'
        self.admin.save()
        r = self.client.post(self.url, {'identifier': '1234567890', 'password': 'pass1234'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('access', r.data)

    def test_B8_3_admin_login_wrong_password(self):
        r = self.client.post(self.url, {'identifier': 'a@test.com', 'password': 'wrong'})
        self.assertEqual(r.status_code, 400)

    def test_B8_4_upa_user_cannot_use_admin_login(self):
        make_upa(mobile='5555555555')
        # upa user has no email so try mobile
        u = User.objects.get(mobile='5555555555')
        u.email = 'upa@test.com'
        u.save()
        r = self.client.post(self.url, {'identifier': 'upa@test.com', 'password': 'testpass123'})
        self.assertEqual(r.status_code, 400)


class EmployeeTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make_admin()
        r = self.client.post('/api/v1/auth/admin/login/', {'identifier': 'admin@test.com', 'password': 'testpass123'})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")

    def test_B8_5_create_employee_with_email(self):
        r = self.client.post('/api/v1/employees/', {
            'name': 'Emp One', 'email': 'emp1@test.com',
            'password': 'pass1234', 'department': 'Sales', 'role': 'employee', 'permissions': [],
        }, format='json')
        self.assertEqual(r.status_code, 201)

    def test_B8_6_create_employee_with_mobile(self):
        r = self.client.post('/api/v1/employees/', {
            'name': 'Emp Two', 'mobile': '9876543210',
            'password': 'pass1234', 'department': 'Tech', 'role': 'employee', 'permissions': [],
        }, format='json')
        self.assertEqual(r.status_code, 201)

    def test_B8_7_employee_creation_fails_without_email_or_mobile(self):
        r = self.client.post('/api/v1/employees/', {
            'name': 'Emp Three', 'password': 'pass1234',
            'department': 'HR', 'role': 'employee',
        }, format='json')
        self.assertEqual(r.status_code, 400)

    def test_B8_8_employee_permissions_stored(self):
        r = self.client.post('/api/v1/employees/', {
            'name': 'Emp Four', 'email': 'emp4@test.com',
            'password': 'pass1234', 'department': 'IT',
            'role': 'employee', 'permissions': ['inventory.view', 'orders.edit'],
        }, format='json')
        self.assertEqual(r.status_code, 201)
        u = User.objects.get(email='emp4@test.com')
        self.assertIn('inventory.view', u.employee_profile.permissions)


class UPARegisterTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = '/api/v1/auth/user/register/'

    def test_B8_9_upa_register_no_ref(self):
        r = self.client.post(self.url, {'name': 'New User', 'mobile': '1111111111', 'password': 'pass1234'}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.data['success'])
        u = User.objects.get(mobile='1111111111')
        self.assertIsNotNone(u.upa_id)
        self.assertTrue(Wallet.objects.filter(user=u).exists())
        self.assertEqual(Wallet.objects.get(user=u).balance, Decimal('0.00'))

    def test_B8_10_upa_register_valid_ref_vacant_leg(self):
        parent = make_upa(mobile='2222222222')
        r = self.client.post(self.url, {
            'name': 'Child User', 'mobile': '3333333333',
            'password': 'pass1234', 'upa_ref_id': parent.upa_id,
        }, format='json')
        self.assertEqual(r.status_code, 201)
        child = User.objects.get(mobile='3333333333')
        tree = UPATree.objects.get(user=child)
        self.assertEqual(tree.parent_user, parent)

    def test_B8_11_upa_register_all_legs_full(self):
        parent = make_upa(mobile='4444444444')
        for i, mobile in enumerate(['5000000001', '5000000002', '5000000003']):
            make_upa(mobile=mobile)
            child = User.objects.get(mobile=mobile)
            leg = ['L', 'M', 'R'][i]
            UPATree.objects.filter(user=child).update(parent_user=parent, leg=leg)
        r = self.client.post(self.url, {
            'name': 'Extra', 'mobile': '6666666666',
            'password': 'pass1234', 'upa_ref_id': parent.upa_id,
        }, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['success'])
        self.assertTrue(r.data['suggest_standalone'])

    def test_B8_12_upa_register_all_legs_full_add_standalone(self):
        parent = make_upa(mobile='7777777777')
        for i, mobile in enumerate(['8000000001', '8000000002', '8000000003']):
            make_upa(mobile=mobile)
            child = User.objects.get(mobile=mobile)
            UPATree.objects.filter(user=child).update(parent_user=parent, leg=['L', 'M', 'R'][i])
        r = self.client.post(self.url, {
            'name': 'Standalone', 'mobile': '9000000001',
            'password': 'pass1234', 'upa_ref_id': parent.upa_id, 'add_standalone': True,
        }, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.data['success'])


class UPALoginTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = '/api/v1/auth/user/login/'
        self.user = make_upa(mobile='9191919191')

    def test_B8_13_upa_login_mobile(self):
        r = self.client.post(self.url, {'mobile': '9191919191', 'password': 'testpass123'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('upa_id', r.data['user'])

    def test_B8_14_upa_login_wrong_password(self):
        r = self.client.post(self.url, {'mobile': '9191919191', 'password': 'wrong'})
        self.assertEqual(r.status_code, 400)


class MeViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make_admin(email='me_admin@test.com')
        r = self.client.post('/api/v1/auth/admin/login/', {'identifier': 'me_admin@test.com', 'password': 'testpass123'})
        self.admin_token = r.data['access']

        self.upa = make_upa(mobile='9292929292')
        r2 = self.client.post('/api/v1/auth/user/login/', {'mobile': '9292929292', 'password': 'testpass123'})
        self.upa_token = r2.data['access']

    def test_B8_15_me_admin_returns_department_permissions(self):
        EmployeeProfile.objects.create(user=self.admin, department='IT', permissions=['reports.view'])
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.admin_token}')
        r = self.client.get('/api/v1/auth/me/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['department'], 'IT')

    def test_B8_16_me_upa_returns_upa_id_wallet(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.upa_token}')
        r = self.client.get('/api/v1/auth/me/')
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(r.data['upa_id'])
        self.assertIsNotNone(r.data['wallet_balance'])

    def test_B8_17_me_no_token_401(self):
        self.client.credentials()
        r = self.client.get('/api/v1/auth/me/')
        self.assertEqual(r.status_code, 401)


class PermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make_admin(email='perm_admin@test.com')
        r = self.client.post('/api/v1/auth/admin/login/', {'identifier': 'perm_admin@test.com', 'password': 'testpass123'})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        emp_r = self.client.post('/api/v1/employees/', {
            'name': 'Perm Emp', 'email': 'perm_emp@test.com',
            'password': 'pass1234', 'department': 'QA', 'role': 'employee', 'permissions': [],
        }, format='json')
        self.emp_user = User.objects.get(email='perm_emp@test.com')
        self.client.credentials()
        r2 = self.client.post('/api/v1/auth/admin/login/', {'identifier': 'perm_emp@test.com', 'password': 'pass1234'})
        self.emp_token = r2.data['access']

    def test_B8_18_employee_accessing_admin_endpoint_403(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.emp_token}')
        r = self.client.post('/api/v1/employees/', {
            'name': 'Another', 'email': 'another@test.com',
            'password': 'pass1234', 'department': 'X', 'role': 'employee',
        }, format='json')
        self.assertEqual(r.status_code, 403)

    def test_B8_19_has_permission_check(self):
        # Employee WITH permission should pass, WITHOUT should fail
        from apps.authentication.permissions import HasPermission
        from unittest.mock import MagicMock

        # With permission
        mock_req = MagicMock()
        mock_req.user.is_authenticated = True
        mock_req.user.role = 'employee'
        mock_req.user.employee_profile.permissions = ['inventory.view']
        perm = HasPermission('inventory.view')
        self.assertTrue(perm.has_permission(mock_req, None))

        # Without permission
        mock_req2 = MagicMock()
        mock_req2.user.is_authenticated = True
        mock_req2.user.role = 'employee'
        mock_req2.user.employee_profile.permissions = []
        perm2 = HasPermission('inventory.view')
        self.assertFalse(perm2.has_permission(mock_req2, None))
