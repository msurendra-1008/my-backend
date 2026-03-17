from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from apps.wallet.models import Wallet, WalletTransaction

User = get_user_model()


def make_upa_user(mobile, name='Test User', password='pass1234'):
    """Create a UPA user with a wallet (mirrors registration flow)."""
    first, *rest = name.split(' ', 1)
    last = rest[0] if rest else ''
    user = User.objects.create_user(
        password=password,
        mobile=mobile,
        first_name=first,
        last_name=last,
        role='upa_user',
        upa_id=f'UPA-{mobile[-4:]}',
    )
    Wallet.objects.create(user=user, balance=Decimal('0.00'))
    return user


def make_admin(email='admin@test.com', password='admin1234'):
    """Create an admin user."""
    return User.objects.create_user(
        password=password,
        email=email,
        first_name='Admin',
        role='admin',
    )


class WalletAutoCreationTest(APITestCase):
    """Wallet auto-created with balance 0 on UPA registration."""

    def test_wallet_created_on_registration(self):
        """POST /api/v1/auth/user/register/ should create wallet with 0 balance."""
        resp = self.client.post('/api/v1/auth/user/register/', {
            'name':     'New User',
            'mobile':   '9000000001',
            'password': 'pass1234',
        })
        # 201 created or 200 (standalone suggested) — either way user + wallet created
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_201_CREATED])
        user = User.objects.get(mobile='9000000001')
        self.assertTrue(hasattr(user, 'wallet'))
        self.assertEqual(user.wallet.balance, Decimal('0.00'))


class MyWalletTest(APITestCase):
    """GET /api/v1/wallet/my-wallet/"""

    def setUp(self):
        self.user = make_upa_user('9000000002')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_returns_balance_and_transactions(self):
        WalletTransaction.objects.create(
            wallet=self.user.wallet, type='credit',
            amount=Decimal('100.00'), reason='Test credit',
        )
        resp = self.client.get('/api/v1/wallet/my-wallet/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('balance', resp.data)
        self.assertIn('transactions', resp.data)
        self.assertEqual(len(resp.data['transactions']), 1)

    def test_admin_gets_403(self):
        admin = make_admin()
        self.client.force_authenticate(user=admin)
        resp = self.client.get('/api/v1/wallet/my-wallet/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class MyTransactionsTest(APITestCase):
    """GET /api/v1/wallet/my-transactions/"""

    def setUp(self):
        self.user = make_upa_user('9000000003')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_paginated_history(self):
        # Create 25 transactions
        for i in range(25):
            WalletTransaction.objects.create(
                wallet=self.user.wallet, type='credit',
                amount=Decimal('10.00'), reason=f'Txn {i}',
            )
        resp = self.client.get('/api/v1/wallet/my-transactions/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 25)
        self.assertEqual(len(resp.data['results']), 20)  # page_size = 20
        self.assertIsNotNone(resp.data['next'])           # has next page


class ManualAdjustTest(APITestCase):
    """POST /api/v1/wallet/{user_id}/manual-adjust/"""

    def setUp(self):
        self.admin   = make_admin()
        self.upa     = make_upa_user('9000000004')
        self.wallet  = self.upa.wallet
        self.client  = APIClient()
        self.client.force_authenticate(user=self.admin)
        self.url = f'/api/v1/wallet/{self.upa.id}/manual-adjust/'

    def test_credit_increases_balance(self):
        resp = self.client.post(self.url, {'type': 'credit', 'amount': '500.00', 'reason': 'Bonus'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('500.00'))
        self.assertEqual(WalletTransaction.objects.filter(wallet=self.wallet, type='credit').count(), 1)

    def test_debit_decreases_balance(self):
        self.wallet.balance = Decimal('1000.00')
        self.wallet.save()
        resp = self.client.post(self.url, {'type': 'debit', 'amount': '300.00', 'reason': 'Withdrawal'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('700.00'))
        self.assertEqual(WalletTransaction.objects.filter(wallet=self.wallet, type='debit').count(), 1)

    def test_debit_beyond_balance_returns_400(self):
        resp = self.client.post(self.url, {'type': 'debit', 'amount': '999.00', 'reason': 'Too much'})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Insufficient', resp.data['detail'])
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('0.00'))  # unchanged

    def test_upa_user_cannot_manual_adjust(self):
        other_upa = make_upa_user('9000000005')
        self.client.force_authenticate(user=other_upa)
        resp = self.client.post(self.url, {'type': 'credit', 'amount': '100.00', 'reason': 'Hack'})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class AdminOverviewTest(APITestCase):
    """GET /api/v1/wallet/admin-overview/"""

    def setUp(self):
        self.admin  = make_admin()
        self.upa    = make_upa_user('9000000006')
        self.wallet = self.upa.wallet
        self.wallet.balance = Decimal('250.00')
        self.wallet.save()
        WalletTransaction.objects.create(
            wallet=self.wallet, type='credit',
            amount=Decimal('250.00'), reason='Initial credit',
        )
        self.client = APIClient()

    def test_admin_gets_correct_totals(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get('/api/v1/wallet/admin-overview/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('total_balance', resp.data)
        self.assertIn('credited_this_month', resp.data)
        self.assertIn('total_wallets', resp.data)
        self.assertEqual(Decimal(resp.data['total_balance']), Decimal('250.00'))
        self.assertEqual(Decimal(resp.data['credited_this_month']), Decimal('250.00'))

    def test_upa_user_gets_403(self):
        self.client.force_authenticate(user=self.upa)
        resp = self.client.get('/api/v1/wallet/admin-overview/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
