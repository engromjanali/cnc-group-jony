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


from unittest.mock import patch  # noqa: E402

from django.test import override_settings  # noqa: E402

from . import google  # noqa: E402


def _claims(**overrides):
    claims = {
        'email': 'new.person@gmail.com',
        'email_verified': True,
        'name': 'New Person',
        'firebase': {'sign_in_provider': 'google.com'},
    }
    claims.update(overrides)
    return claims


class GoogleLoginTests(APITestCase):
    URL = '/api/v1/auth/google'

    def _login(self, token='a-firebase-id-token'):
        return self.client.post(self.URL, {'id_token': token})

    def test_a_new_google_user_is_created_and_signed_in(self):
        with patch('accounts.google.verify_google_id_token', return_value=_claims()):
            response = self._login()

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['is_new_user'])
        self.assertIn('access', response.data['tokens'])
        self.assertIn('refresh', response.data['tokens'])
        user = User.objects.get(email='new.person@gmail.com')
        self.assertEqual((user.first_name, user.last_name), ('New', 'Person'))
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.is_staff)

    def test_an_existing_user_signs_in_without_a_duplicate(self):
        existing = User.objects.create_user('New.Person@gmail.com', 'pw-1', first_name='Kept')
        with patch('accounts.google.verify_google_id_token', return_value=_claims()):
            response = self._login()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['is_new_user'])
        self.assertEqual(response.data['user']['id'], existing.pk)
        self.assertEqual(User.objects.count(), 1)
        existing.refresh_from_db()
        self.assertEqual(existing.first_name, 'Kept')
        self.assertTrue(existing.has_usable_password())

    def test_the_issued_token_works(self):
        with patch('accounts.google.verify_google_id_token', return_value=_claims()):
            access = self._login().data['tokens']['access']

        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        profile = self.client.get('/api/v1/user/profile')
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.data['email'], 'new.person@gmail.com')

    def test_a_disabled_account_is_refused(self):
        User.objects.create_user('new.person@gmail.com', 'pw-1', is_active=False)
        with patch('accounts.google.verify_google_id_token', return_value=_claims()):
            response = self._login()

        self.assertEqual(response.status_code, 400)

    def test_an_invalid_token_is_a_400_and_creates_nothing(self):
        with patch(
            'accounts.google.verify_google_id_token',
            side_effect=google.InvalidGoogleToken('Invalid or expired Google sign-in.'),
        ):
            response = self._login()

        self.assertEqual(response.status_code, 400)
        self.assertIn('id_token', response.data)
        self.assertEqual(User.objects.count(), 0)

    def test_the_token_is_required(self):
        self.assertEqual(self.client.post(self.URL, {}).status_code, 400)


@override_settings(FIREBASE_PROJECT_ID='cncgroupjony')
class VerifyGoogleTokenTests(APITestCase):
    """The verifier itself, with google-auth's signature check stubbed out."""

    def _verify(self, claims=None, error=None):
        target = 'accounts.google.id_token.verify_firebase_token'
        with patch(target, return_value=claims, side_effect=error) as verify:
            return google.verify_google_id_token('tok'), verify

    def test_it_checks_the_token_against_this_firebase_project(self):
        _, verify = self._verify(_claims())

        self.assertEqual(verify.call_args.kwargs['audience'], 'cncgroupjony')

    def test_a_bad_signature_or_expired_token_is_rejected(self):
        with self.assertRaises(google.InvalidGoogleToken):
            self._verify(error=ValueError('Token expired'))
        with self.assertRaises(google.InvalidGoogleToken):
            self._verify(claims=None)

    def test_only_a_google_sign_in_is_accepted(self):
        with self.assertRaises(google.InvalidGoogleToken):
            self._verify(_claims(firebase={'sign_in_provider': 'password'}))
        with self.assertRaises(google.InvalidGoogleToken):
            self._verify(_claims(firebase={}))

    def test_an_unverified_or_missing_email_is_rejected(self):
        with self.assertRaises(google.InvalidGoogleToken):
            self._verify(_claims(email_verified=False))
        with self.assertRaises(google.InvalidGoogleToken):
            self._verify(_claims(email=''))
