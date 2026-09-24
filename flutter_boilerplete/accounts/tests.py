from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

User = get_user_model()


class AdminUserManagementTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user('admin@example.com', 'pw-1', is_staff=True)
        self.jane = User.objects.create_user(
            'jane@example.com', 'pw-2', first_name='Jane', last_name='Doe',
        )
        self.bob = User.objects.create_user('bob@example.com', 'pw-3', first_name='Bob')

    # --- access ---------------------------------------------------------------

    def test_needs_admin(self):
        self.client.force_authenticate(self.jane)
        self.assertEqual(self.client.get('/api/v1/admin/users/list').status_code, 403)
        url = f'/api/v1/admin/users/update/{self.bob.pk}'
        self.assertEqual(self.client.patch(url, {'phone': '123'}).status_code, 403)

    def test_needs_sign_in(self):
        self.assertEqual(self.client.get('/api/v1/admin/users/list').status_code, 401)

    # --- list -------------------------------------------------------------------

    def test_list_search_and_filter(self):
        self.bob.is_active = False
        self.bob.save()
        self.client.force_authenticate(self.admin)

        everyone = self.client.get('/api/v1/admin/users/list')
        self.assertEqual(everyone.data['count'], 3)

        by_name = self.client.get('/api/v1/admin/users/list', {'search': 'jane'})
        self.assertEqual([u['email'] for u in by_name.data['results']], ['jane@example.com'])

        by_email = self.client.get('/api/v1/admin/users/list', {'search': 'BOB@example'})
        self.assertEqual([u['email'] for u in by_email.data['results']], ['bob@example.com'])

        disabled = self.client.get('/api/v1/admin/users/list', {'is_active': 'false'})
        self.assertEqual([u['email'] for u in disabled.data['results']], ['bob@example.com'])

        enabled = self.client.get('/api/v1/admin/users/list', {'is_active': 'true'})
        self.assertEqual(len(enabled.data['results']), 2)

    # --- edit ---------------------------------------------------------------

    def test_edit_name_and_phone(self):
        self.client.force_authenticate(self.admin)
        url = f'/api/v1/admin/users/update/{self.jane.pk}'
        response = self.client.patch(url, {'first_name': 'Janet', 'phone': '01700000000'})

        self.assertEqual(response.status_code, 200)
        self.jane.refresh_from_db()
        self.assertEqual(self.jane.first_name, 'Janet')
        self.assertEqual(self.jane.phone, '01700000000')

    def test_email_and_wallet_balance_cannot_be_edited_here(self):
        self.client.force_authenticate(self.admin)
        url = f'/api/v1/admin/users/update/{self.jane.pk}'
        response = self.client.patch(
            url, {'email': 'new@example.com', 'wallet_balance': '999.00'}, format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.jane.refresh_from_db()
        self.assertEqual(self.jane.email, 'jane@example.com')
        self.assertEqual(self.jane.wallet_balance, 0)

    # --- disable / enable -----------------------------------------------------

    def test_disable_blocks_sign_in_and_re_enabling_restores_it(self):
        self.client.force_authenticate(self.admin)
        url = f'/api/v1/admin/users/update/{self.jane.pk}'

        off = self.client.patch(url, {'is_active': False})
        self.assertEqual(off.status_code, 200)
        self.assertFalse(off.data['is_active'])

        login = self.client.post(
            '/api/v1/auth/login', {'email': 'jane@example.com', 'password': 'pw-2'},
        )
        self.assertEqual(login.status_code, 400)

        on = self.client.patch(url, {'is_active': True})
        self.assertTrue(on.data['is_active'])
        login = self.client.post(
            '/api/v1/auth/login', {'email': 'jane@example.com', 'password': 'pw-2'},
        )
        self.assertEqual(login.status_code, 200)

    def test_disabling_revokes_an_already_issued_token(self):
        # A real bearer token, not force_authenticate: that helper sets
        # request.user directly and never runs JWTAuthentication.get_user(),
        # which is where a disabled account's requests are actually refused.
        login = self.client.post(
            '/api/v1/auth/login', {'email': 'jane@example.com', 'password': 'pw-2'},
        )
        access = login.data['tokens']['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        self.assertEqual(self.client.get('/api/v1/user/profile').status_code, 200)

        self.client.credentials()
        self.client.force_authenticate(self.admin)
        self.client.patch(f'/api/v1/admin/users/update/{self.jane.pk}', {'is_active': False})
        # force_authenticate stays in effect across requests until cleared -
        # otherwise it would override the bearer token below too.
        self.client.force_authenticate(user=None)

        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        self.assertEqual(self.client.get('/api/v1/user/profile').status_code, 401)

    def test_an_admin_cannot_disable_their_own_account(self):
        self.client.force_authenticate(self.admin)
        url = f'/api/v1/admin/users/update/{self.admin.pk}'
        response = self.client.patch(url, {'is_active': False})

        self.assertEqual(response.status_code, 400)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
