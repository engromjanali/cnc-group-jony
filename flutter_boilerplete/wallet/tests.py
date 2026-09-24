from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from .models import WalletTransaction

User = get_user_model()


class WalletTestCase(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user('admin@example.com', 'pw-1', is_staff=True)
        self.user = User.objects.create_user('user@example.com', 'pw-2')

    def _add(self, tnx='123456', amount='50.00'):
        self.client.force_authenticate(self.user)
        return self.client.post('/api/v1/wallet/add', {'transaction_id': tnx, 'amount': amount, 'sender_number': '01700000000'})

    def test_add_is_pending_and_balance_untouched(self):
        response = self._add()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'pending')
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, 0)

    def test_add_validation(self):
        self._add()
        self.assertEqual(self._add().status_code, 400)  # duplicate id
        self.assertEqual(self._add('TXN-abc9').status_code, 201)  # letters are fine
        self.assertEqual(self._add('   ').status_code, 400)  # blank
        self.assertEqual(self._add('999', '0').status_code, 400)  # bad amount

    def test_sender_number_required(self):
        self.client.force_authenticate(self.user)
        response = self.client.post('/api/v1/wallet/add', {'transaction_id': '1', 'amount': '5'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('sender_number', response.data)

    def test_payment_methods(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.post('/api/v1/admin/wallet/payment-method/add', {}).status_code, 403)
        self.client.force_authenticate(self.admin)
        add = '/api/v1/admin/wallet/payment-method/add'
        made = self.client.post(add, {'name': 'bKash', 'number': '01779852361'})
        self.assertEqual(made.status_code, 201)
        hidden = self.client.post(add, {'name': 'Nagad', 'number': '01', 'is_active': 'false'})
        self.assertEqual(hidden.status_code, 201)
        self.assertEqual(len(self.client.get('/api/v1/admin/wallet/payment-method/list').data), 2)
        self.client.force_authenticate(self.user)
        shown = self.client.get('/api/v1/wallet/payment-methods').data
        self.assertEqual([m['name'] for m in shown], ['bKash'])
        self.client.force_authenticate(self.admin)
        url = f"/api/v1/admin/wallet/payment-method/update/{made.data['id']}"
        self.assertEqual(self.client.patch(url, {'number': '019'}).data['number'], '019')
        self.assertEqual(
            self.client.delete(f"/api/v1/admin/wallet/payment-method/delete/{made.data['id']}").status_code, 204,
        )

    def test_approve_credits_once(self):
        tnx_id = self._add().data['id']
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(f'/api/v1/admin/wallet/approve/{tnx_id}').status_code, 200)
        self.assertEqual(self.client.post(f'/api/v1/admin/wallet/approve/{tnx_id}').status_code, 409)
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('50.00'))
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get('/api/v1/user/profile').data['wallet_balance'], '50.00')

    def test_deny_does_not_credit(self):
        tnx_id = self._add().data['id']
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(f'/api/v1/admin/wallet/deny/{tnx_id}').status_code, 200)
        self.assertEqual(self.client.post(f'/api/v1/admin/wallet/approve/{tnx_id}').status_code, 409)
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, 0)
        self.assertEqual(WalletTransaction.objects.get().status, 'denied')

    def test_admin_credit_adds_at_once_and_is_recorded(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            f'/api/v1/admin/wallet/credit/{self.user.pk}',
            {'amount': '25.00', 'note': 'goodwill credit'},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'approved')
        self.assertEqual(response.data['source'], 'admin')
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('25.00'))

        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get('/api/v1/user/profile').data['wallet_balance'], '25.00')

    def test_admin_credit_needs_admin_and_a_positive_amount(self):
        self.client.force_authenticate(self.user)
        url = f'/api/v1/admin/wallet/credit/{self.user.pk}'
        self.assertEqual(self.client.post(url, {'amount': '10'}).status_code, 403)

        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(url, {'amount': '0'}).status_code, 400)
        self.assertEqual(self.client.post('/api/v1/admin/wallet/credit/9999', {'amount': '10'}).status_code, 404)

    def test_admin_only_and_list_filter(self):
        tnx_id = self._add().data['id']
        self.assertEqual(self.client.get('/api/v1/admin/wallet/list').status_code, 403)
        self.assertEqual(self.client.post(f'/api/v1/admin/wallet/approve/{tnx_id}').status_code, 403)
        self.client.force_authenticate(self.admin)
        pending = self.client.get('/api/v1/admin/wallet/list?status=pending')
        approved = self.client.get('/api/v1/admin/wallet/list?status=approved')
        self.assertEqual((len(pending.data), len(approved.data)), (1, 0))
