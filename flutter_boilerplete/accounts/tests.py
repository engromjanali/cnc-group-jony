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

from django.conf import settings  # noqa: E402
from django.test import override_settings  # noqa: E402

from firebase_admin import auth  # noqa: E402

from . import firebase  # noqa: E402

VERIFY = 'accounts.firebase.verify_firebase_token'


def _claims(provider='google.com', **overrides):
    claims = {
        'sub': 'uid-1',
        'email': 'new.person@gmail.com',
        'email_verified': True,
        'name': 'New Person',
        'firebase': {'sign_in_provider': provider},
    }
    claims.update(overrides)
    return claims


class GoogleLoginTests(APITestCase):
    URL = '/api/v1/auth/google'

    def _login(self, claims=None):
        with patch(VERIFY, return_value=claims if claims is not None else _claims()):
            return self.client.post(self.URL, {'id_token': 'tok'})

    def test_a_new_user_is_created_with_no_password(self):
        response = self._login()

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['is_new_user'])
        self.assertFalse(response.data['password_set'])
        self.assertFalse(response.data['user']['password_set'])
        self.assertIn('access', response.data['tokens'])
        self.assertIn('refresh', response.data['tokens'])
        user = User.objects.get(email='new.person@gmail.com')
        self.assertEqual((user.first_name, user.last_name), ('New', 'Person'))
        self.assertEqual(user.firebase_uid, 'uid-1')
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.password_set)
        self.assertFalse(user.is_staff)

    def test_the_second_sign_in_is_the_same_user(self):
        first = self._login().data['user']['id']
        second = self._login()

        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.data['is_new_user'])
        self.assertEqual(second.data['user']['id'], first)
        self.assertEqual(User.objects.count(), 1)

    def test_the_uid_is_the_identity_so_a_changed_email_is_still_the_same_user(self):
        first = self._login().data['user']['id']
        second = self._login(_claims('google.com', email='renamed@gmail.com'))

        self.assertEqual(second.data['user']['id'], first)
        self.assertEqual(User.objects.count(), 1)

    def test_an_existing_account_with_that_verified_email_is_linked(self):
        existing = User.objects.create_user('New.Person@gmail.com', 'pw-1', first_name='Kept')
        response = self._login()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['is_new_user'])
        self.assertTrue(response.data['password_set'])
        self.assertEqual(User.objects.count(), 1)
        existing.refresh_from_db()
        self.assertEqual(existing.firebase_uid, 'uid-1')
        self.assertEqual(existing.first_name, 'Kept')
        self.assertTrue(existing.has_usable_password())

    def test_an_account_linked_to_another_firebase_user_is_refused(self):
        User.objects.create_user('new.person@gmail.com', 'pw-1', firebase_uid='someone-else')
        response = self._login()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.get().firebase_uid, 'someone-else')

    def test_a_disabled_account_is_refused_and_not_linked(self):
        User.objects.create_user('new.person@gmail.com', 'pw-1', is_active=False)
        response = self._login()

        self.assertEqual(response.status_code, 400)
        self.assertIsNone(User.objects.get().firebase_uid)

    def test_a_firebase_email_password_token_is_refused(self):
        # Email + password accounts live in this backend, not in Firebase.
        response = self._login(_claims('password'))

        self.assertEqual(response.status_code, 400)
        self.assertIn('id_token', response.data)
        self.assertEqual(User.objects.count(), 0)

    def test_there_is_no_firebase_email_endpoint(self):
        self.assertEqual(self.client.post('/api/v1/auth/email', {'id_token': 'x'}).status_code, 404)

    def test_an_invalid_token_creates_nothing(self):
        with patch(VERIFY, side_effect=firebase.InvalidFirebaseToken('Invalid or expired sign-in.')):
            response = self.client.post(self.URL, {'id_token': 'tok'})

        self.assertEqual(response.status_code, 400)
        self.assertIn('id_token', response.data)
        self.assertEqual(User.objects.count(), 0)

    def test_the_token_is_required(self):
        self.assertEqual(self.client.post(self.URL, {}).status_code, 400)

    def test_the_issued_jwt_works_for_normal_calls(self):
        access = self._login().data['tokens']['access']

        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        profile = self.client.get('/api/v1/user/profile')
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.data['email'], 'new.person@gmail.com')
        self.assertFalse(profile.data['password_set'])


def _fake_service_account(project='cncgroupjony'):
    """A well-formed service account key (a throwaway RSA key, not a real one)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return {
        'type': 'service_account',
        'project_id': project,
        'private_key_id': 'test-key-id',
        'private_key': pem,
        'client_email': f'firebase-adminsdk@{project}.iam.gserviceaccount.com',
        'client_id': '1234567890',
        'token_uri': 'https://oauth2.googleapis.com/token',
    }


class _FirebaseModuleState(APITestCase):
    """Each test starts with no Admin SDK app, and leaves none behind."""

    def setUp(self):
        self._reset_app()

    def tearDown(self):
        self._reset_app()

    @staticmethod
    def _reset_app():
        import firebase_admin
        if firebase._app is not None:
            try:
                firebase_admin.delete_app(firebase._app)
            except ValueError:
                pass
        firebase._app = None


class VerifyFirebaseTokenTests(_FirebaseModuleState):
    """The verifier, with the Admin SDK's own network call stubbed out."""

    def _verify(self, claims=None, error=None):
        with patch.object(firebase, '_firebase_app', return_value='the-app'), \
             patch('accounts.firebase.auth.verify_id_token', return_value=claims, side_effect=error) as verify:
            return firebase.verify_firebase_token('tok'), verify

    def _fails_with(self, exception, **kwargs):
        with self.assertRaises(exception):
            self._verify(**kwargs)

    def test_it_uses_the_admin_sdk_and_asks_firebase_whether_it_was_revoked(self):
        _, verify = self._verify(_claims())

        self.assertEqual(verify.call_args.args, ('tok',))
        self.assertEqual(verify.call_args.kwargs['app'], 'the-app')
        self.assertIs(verify.call_args.kwargs['check_revoked'], True)

    def test_a_google_sign_in_is_accepted(self):
        claims, _ = self._verify(_claims('google.com'))

        self.assertEqual(firebase.provider_of(claims), 'google.com')

    def test_any_other_provider_is_rejected(self):
        for provider in ('password', 'facebook.com', 'phone', 'anonymous', 'custom', None):
            with self.assertRaises(firebase.InvalidFirebaseToken, msg=provider):
                self._verify(_claims(provider))
        self._fails_with(firebase.InvalidFirebaseToken, claims=_claims(firebase={}))

    def test_every_way_the_sdk_calls_a_token_bad_is_an_invalid_token(self):
        for error in (
            auth.InvalidIdTokenError('forged'),
            auth.ExpiredIdTokenError('expired', ValueError()),
            auth.RevokedIdTokenError('revoked'),
            auth.UserDisabledError('the Firebase user is disabled'),
            auth.UserNotFoundError('the Firebase user was deleted'),
            ValueError('not a JWT'),
        ):
            with self.assertRaises(firebase.InvalidFirebaseToken, msg=type(error).__name__):
                self._verify(error=error)

    def test_firebase_being_unreachable_is_our_problem_not_an_invalid_token(self):
        with self.assertLogs('accounts.firebase', level='ERROR'):
            for error in (auth.CertificateFetchError('no network', ValueError()), OSError('boom')):
                with self.assertRaises(firebase.FirebaseUnavailable):
                    self._verify(error=error)

    def test_a_service_account_that_cannot_read_users_is_a_setup_problem_with_a_clear_message(self):
        from firebase_admin import _auth_utils
        error = _auth_utils.InsufficientPermissionError('INSUFFICIENT_PERMISSION', None, None)
        with override_settings(FIREBASE_SERVICE_ACCOUNT_JSON='', FIREBASE_SERVICE_ACCOUNT_FILE=''):
            with self.assertLogs('accounts.firebase', level='ERROR') as logged:
                with self.assertRaises(firebase.FirebaseNotConfigured):
                    self._verify(error=error)

        # Says what to do - and is one line, not a stack trace on every attempt.
        self.assertIn('Firebase Authentication Admin', logged.output[0])
        self.assertNotIn('Traceback', logged.output[0])

    def test_the_revocation_check_can_be_turned_off_knowingly(self):
        with override_settings(FIREBASE_CHECK_REVOKED=False):
            _, verify = self._verify(_claims())
        self.assertIs(verify.call_args.kwargs['check_revoked'], False)

        # ...and everything else is still checked.
        with override_settings(FIREBASE_CHECK_REVOKED=False):
            with self.assertRaises(firebase.InvalidFirebaseToken):
                self._verify(_claims('password'))
            with self.assertRaises(firebase.InvalidFirebaseToken):
                self._verify(error=auth.InvalidIdTokenError('forged'))

    def test_it_is_on_by_default(self):
        self.assertIs(settings.FIREBASE_CHECK_REVOKED, True)

    def test_an_unverified_or_missing_email_is_rejected(self):
        self._fails_with(firebase.InvalidFirebaseToken, claims=_claims(email_verified=False))
        self._fails_with(firebase.InvalidFirebaseToken, claims=_claims(email=''))

    def test_a_token_with_no_firebase_user_id_is_rejected(self):
        self._fails_with(firebase.InvalidFirebaseToken, claims=_claims(sub=''))


class FirebaseServiceAccountTests(_FirebaseModuleState):
    """Where the service account comes from, and that nothing works without one."""

    def test_with_none_configured_it_refuses_rather_than_falling_back(self):
        with override_settings(FIREBASE_SERVICE_ACCOUNT_JSON='', FIREBASE_SERVICE_ACCOUNT_FILE=''):
            with self.assertRaises(firebase.FirebaseNotConfigured):
                firebase.verify_firebase_token('anything')

    def test_json_in_the_environment_is_used(self):
        import json
        with override_settings(
            FIREBASE_SERVICE_ACCOUNT_JSON=json.dumps(_fake_service_account()),
            FIREBASE_SERVICE_ACCOUNT_FILE='', FIREBASE_PROJECT_ID='cncgroupjony',
        ):
            _, project = firebase._credential()

        self.assertEqual(project, 'cncgroupjony')

    def test_the_same_value_works_as_json_or_as_base64(self):
        import base64
        import json
        key = json.dumps(_fake_service_account())
        for value in (key, base64.b64encode(key.encode()).decode()):
            with override_settings(
                FIREBASE_SERVICE_ACCOUNT_JSON=value, FIREBASE_SERVICE_ACCOUNT_FILE='',
                FIREBASE_PROJECT_ID='cncgroupjony',
            ):
                _, project = firebase._credential()
            self.assertEqual(project, 'cncgroupjony')

    def test_a_double_quoted_env_value_with_real_line_breaks_still_loads(self):
        import json
        # What a .env parser hands over when the key's \n escapes were turned
        # into actual line breaks by double quotes.
        mangled = json.dumps(_fake_service_account()).replace('\\n', '\n')
        with self.assertRaises(ValueError):
            json.loads(mangled)  # strict JSON really would refuse this
        with override_settings(
            FIREBASE_SERVICE_ACCOUNT_JSON=mangled, FIREBASE_SERVICE_ACCOUNT_FILE='',
            FIREBASE_PROJECT_ID='cncgroupjony',
        ):
            _, project = firebase._credential()

        self.assertEqual(project, 'cncgroupjony')

    def test_something_that_is_neither_json_nor_base64_is_reported(self):
        with override_settings(
            FIREBASE_SERVICE_ACCOUNT_JSON='this is !! not a key', FIREBASE_SERVICE_ACCOUNT_FILE='',
        ):
            with self.assertRaisesMessage(firebase.FirebaseNotConfigured, 'neither JSON nor base64'):
                firebase._credential()

    def test_the_example_key_from_env_example_is_reported_not_used(self):
        import json
        example = dict(_fake_service_account(), private_key_id=firebase.EXAMPLE_KEY_ID)
        with override_settings(
            FIREBASE_SERVICE_ACCOUNT_JSON=json.dumps(example), FIREBASE_SERVICE_ACCOUNT_FILE='',
            FIREBASE_PROJECT_ID='',
        ):
            with self.assertRaisesMessage(firebase.FirebaseNotConfigured, 'EXAMPLE key'):
                firebase._credential()

    def test_the_example_in_env_example_is_well_formed_but_refused(self):
        """The shipped example must look real (valid base64, JSON, PEM) so it shows
        the format - and still never be mistaken for a working key."""
        import base64
        import json
        import pathlib
        from firebase_admin import credentials

        env_example = pathlib.Path(__file__).resolve().parents[2] / '.env.example'
        line = next(
            ln for ln in env_example.read_text().splitlines()
            if ln.startswith('FIREBASE_SERVICE_ACCOUNT_JSON=')
        )
        value = line.split('=', 1)[1]
        info = json.loads(base64.b64decode(value, validate=True))

        self.assertEqual(info['type'], 'service_account')
        self.assertTrue(info['client_email'].startswith('firebase-adminsdk-'))
        credentials.Certificate(info)  # a real-shaped key: the SDK accepts its format
        with override_settings(FIREBASE_SERVICE_ACCOUNT_JSON=value, FIREBASE_SERVICE_ACCOUNT_FILE=''):
            with self.assertRaisesMessage(firebase.FirebaseNotConfigured, 'EXAMPLE key'):
                firebase._credential()

    def test_a_key_file_is_used_too(self):
        import json
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as key_file:
            json.dump(_fake_service_account(), key_file)
        with override_settings(
            FIREBASE_SERVICE_ACCOUNT_JSON='', FIREBASE_SERVICE_ACCOUNT_FILE=key_file.name,
            FIREBASE_PROJECT_ID='',
        ):
            _, project = firebase._credential()

        self.assertEqual(project, 'cncgroupjony')

    def test_the_project_comes_from_the_key_when_none_is_set(self):
        import json
        with override_settings(
            FIREBASE_SERVICE_ACCOUNT_JSON=json.dumps(_fake_service_account('other-project')),
            FIREBASE_SERVICE_ACCOUNT_FILE='', FIREBASE_PROJECT_ID='',
        ):
            _, project = firebase._credential()

        self.assertEqual(project, 'other-project')

    def test_a_key_for_another_project_is_refused(self):
        import json
        with override_settings(
            FIREBASE_SERVICE_ACCOUNT_JSON=json.dumps(_fake_service_account('other-project')),
            FIREBASE_SERVICE_ACCOUNT_FILE='', FIREBASE_PROJECT_ID='cncgroupjony',
        ):
            with self.assertRaisesMessage(firebase.FirebaseNotConfigured, 'other-project'):
                firebase._credential()

    def test_broken_configuration_is_reported_not_crashed_on(self):
        for json_value, path in (
            ('{not json', ''),  # garbled
            ('', '/no/such/key.json'),  # unreadable file
            ('{"project_id": "cncgroupjony"}', ''),  # not a service account
            ('{"type": "service_account"}', ''),  # no project
        ):
            with override_settings(
                FIREBASE_SERVICE_ACCOUNT_JSON=json_value, FIREBASE_SERVICE_ACCOUNT_FILE=path,
                FIREBASE_PROJECT_ID='',
            ):
                with self.assertRaises(firebase.FirebaseNotConfigured, msg=json_value or path):
                    firebase._credential()

    def test_the_sdk_app_is_created_once_and_reused(self):
        import json
        with override_settings(
            FIREBASE_SERVICE_ACCOUNT_JSON=json.dumps(_fake_service_account()),
            FIREBASE_SERVICE_ACCOUNT_FILE='', FIREBASE_PROJECT_ID='cncgroupjony',
        ):
            first = firebase._firebase_app()
            second = firebase._firebase_app()

        self.assertIs(first, second)
        self.assertEqual(first.project_id, 'cncgroupjony')

    def test_garbage_is_rejected_by_the_real_sdk(self):
        import json
        with override_settings(
            FIREBASE_SERVICE_ACCOUNT_JSON=json.dumps(_fake_service_account()),
            FIREBASE_SERVICE_ACCOUNT_FILE='', FIREBASE_PROJECT_ID='cncgroupjony',
        ):
            for token in ('garbage', 'a.b.c', 'eyJhbGciOiJSUzI1NiJ9.eyJhdWQiOiJ4In0.c2ln'):
                with self.assertRaises(firebase.InvalidFirebaseToken, msg=token):
                    firebase.verify_firebase_token(token)


class GoogleSignInUnavailableTests(APITestCase):
    """A server-side problem is a 503 the app can show as "try again later",
    never a 400 that blames the user's sign-in - and never a way in."""

    URL = '/api/v1/auth/google'

    def _login(self, error):
        with patch(VERIFY, side_effect=error):
            return self.client.post(self.URL, {'id_token': 'tok'})

    def test_no_service_account_is_a_503_and_creates_nothing(self):
        with self.assertLogs('accounts.serializers', level='ERROR'):
            response = self._login(firebase.FirebaseNotConfigured('No Firebase service account'))

        self.assertEqual(response.status_code, 503)
        self.assertIn('not available', response.data['detail'])
        self.assertEqual(User.objects.count(), 0)

    def test_the_reason_is_not_leaked_to_the_caller(self):
        with self.assertLogs('accounts.serializers', level='ERROR'):
            response = self._login(firebase.FirebaseNotConfigured('the key file is at /secret/path'))

        self.assertNotIn('/secret/path', str(response.data))

    def test_firebase_being_unreachable_is_a_503_too(self):
        response = self._login(firebase.FirebaseUnavailable('no network'))

        self.assertEqual(response.status_code, 503)
        self.assertEqual(User.objects.count(), 0)


class SetPasswordTests(APITestCase):
    URL = '/api/v1/auth/set-password'
    GOOD = 'Correct-Horse-Battery-9'

    def setUp(self):
        with patch(VERIFY, return_value=_claims('google.com')):
            login = self.client.post('/api/v1/auth/google', {'id_token': 'tok'})
        self.access = login.data['tokens']['access']
        self.user = User.objects.get(email='new.person@gmail.com')

    def _set(self, password=None, confirmation=None, token=True):
        password = self.GOOD if password is None else password
        self.client.credentials(**({'HTTP_AUTHORIZATION': f'Bearer {self.access}'} if token else {}))
        return self.client.post(
            self.URL, {'password': password, 'password_confirmation': confirmation or password},
        )

    def test_it_needs_the_backend_token(self):
        response = self._set(token=False)

        self.assertEqual(response.status_code, 401)
        self.user.refresh_from_db()
        self.assertFalse(self.user.password_set)

    def test_a_google_user_can_set_one(self):
        response = self._set()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['password_set'])
        self.user.refresh_from_db()
        self.assertTrue(self.user.password_set)
        self.assertTrue(self.user.check_password(self.GOOD))

    def test_the_password_is_never_sent_back(self):
        response = self._set()

        self.assertNotIn(self.GOOD, str(response.data))
        self.assertNotIn('password', {k for k in response.data if k != 'password_set'})

    def test_the_new_password_then_works_for_the_password_login(self):
        self._set()
        self.client.credentials()

        login = self.client.post(
            '/api/v1/auth/login', {'email': 'new.person@gmail.com', 'password': self.GOOD},
        )
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.data['user']['password_set'])

    def test_passwords_must_match(self):
        response = self._set(confirmation='Something-Else-99')

        self.assertEqual(response.status_code, 400)
        self.assertIn('password_confirmation', response.data)
        self.user.refresh_from_db()
        self.assertFalse(self.user.password_set)

    def test_a_weak_password_is_refused(self):
        for weak in ('short', '12345678', 'password'):
            response = self._set(weak)
            self.assertEqual(response.status_code, 400, weak)

        self.user.refresh_from_db()
        self.assertFalse(self.user.password_set)

    def test_a_password_like_the_email_is_refused(self):
        self.assertEqual(self._set('new.person@gmail.com').status_code, 400)

    def test_it_cannot_replace_an_existing_password(self):
        self._set()
        response = self._set('Another-Strong-Pass-7')

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.GOOD))

    def test_an_account_made_with_a_password_already_has_one(self):
        jane = User.objects.create_user('jane@example.com', 'Sup3r-secret-pw')
        self.assertTrue(jane.password_set)
        self.client.force_authenticate(jane)

        response = self.client.post(
            self.URL, {'password': self.GOOD, 'password_confirmation': self.GOOD},
        )
        self.assertEqual(response.status_code, 400)


class PasswordSetFlagTests(APITestCase):
    def test_register_marks_the_password_as_set(self):
        response = self.client.post('/api/v1/auth/register', {
            'email': 'reg@example.com', 'password': 'Correct-Horse-Battery-9',
            'password_confirm': 'Correct-Horse-Battery-9',
        })

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['user']['password_set'])

    def test_an_account_made_without_a_password_is_not_marked(self):
        self.assertFalse(User.objects.create_user('nopw@example.com').password_set)
        self.assertTrue(User.objects.create_user('pw@example.com', 'x-1').password_set)

    def test_the_token_refresh_alias_works(self):
        user = User.objects.create_user('r@example.com', 'pw-9')
        refresh = self.client.post(
            '/api/v1/auth/login', {'email': 'r@example.com', 'password': 'pw-9'},
        ).data['tokens']['refresh']

        for path in ('/api/v1/auth/refresh', '/api/v1/auth/token/refresh'):
            response = self.client.post(path, {'refresh': refresh})
            self.assertEqual(response.status_code, 200, path)
            refresh = response.data['refresh']
        self.assertEqual(user.pk, User.objects.get(email='r@example.com').pk)


import re  # noqa: E402
from datetime import timedelta  # noqa: E402

from django.core import mail  # noqa: E402
from django.core.cache import cache  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken  # noqa: E402

from . import password_reset  # noqa: E402
from .models import PasswordResetCode  # noqa: E402

FORGOT = '/api/v1/auth/forgot-password'
RESET = '/api/v1/auth/reset-password'
NEW_PASSWORD = 'Correct-Horse-Battery-9'


class PasswordResetTests(APITestCase):
    def setUp(self):
        cache.clear()  # the per-IP throttle counts in the cache, across tests
        self.jane = User.objects.create_user('jane@example.com', 'Old-Password-42')

    def _forgot(self, email='jane@example.com'):
        return self.client.post(FORGOT, {'email': email})

    def _code(self, index=-1):
        return re.search(r'\b(\d{6})\b', mail.outbox[index].body).group(1)

    def _reset(self, code, password=NEW_PASSWORD, confirmation=None, email='jane@example.com'):
        return self.client.post(RESET, {
            'email': email, 'code': code, 'password': password,
            'password_confirmation': confirmation if confirmation is not None else password,
        })

    def _age_codes(self, **fields):
        PasswordResetCode.objects.update(**fields)

    # --- asking for a code -------------------------------------------------------

    def test_a_known_email_gets_one_email_with_a_six_digit_code(self):
        response = self._forgot()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['jane@example.com'])
        self.assertRegex(mail.outbox[0].body, r'\b\d{6}\b')
        self.assertIn('10 minutes', mail.outbox[0].body)
        self.assertTrue(mail.outbox[0].alternatives)  # the HTML version

    def test_an_unknown_email_looks_exactly_the_same_and_sends_nothing(self):
        known = self._forgot()
        unknown = self._forgot('nobody@example.com')

        self.assertEqual(unknown.status_code, known.status_code)
        self.assertEqual(unknown.data, known.data)
        self.assertEqual(len(mail.outbox), 1)  # only jane's

    def test_email_matching_ignores_case(self):
        self._forgot('JANE@Example.com')

        self.assertEqual(len(mail.outbox), 1)

    def test_a_disabled_account_gets_nothing(self):
        self.jane.is_active = False
        self.jane.save()

        self.assertEqual(self._forgot().status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_a_google_sign_up_with_no_password_can_ask_too(self):
        google = User.objects.create_user('g@gmail.com', firebase_uid='uid-g')
        self.assertFalse(google.password_set)

        self._forgot('g@gmail.com')

        self.assertEqual(len(mail.outbox), 1)

    def test_a_second_request_within_a_minute_sends_nothing_more(self):
        self._forgot()
        again = self._forgot()

        self.assertEqual(again.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

    def test_after_the_cooldown_a_new_code_retires_the_old_one(self):
        self._forgot()
        old = self._code()
        self._age_codes(created_at=timezone.now() - timedelta(minutes=2))

        self._forgot()
        new = self._code()

        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(self._reset(old).status_code, 400)
        self.assertEqual(self._reset(new).status_code, 200)

    def test_no_more_than_five_an_hour(self):
        for _ in range(7):
            self._forgot()
            self._age_codes(created_at=timezone.now() - timedelta(minutes=2))

        self.assertEqual(len(mail.outbox), 5)

    def test_only_a_hash_of_the_code_is_stored(self):
        self._forgot()
        code = self._code()
        row = PasswordResetCode.objects.get()

        self.assertNotIn(code, row.code_hash)
        self.assertEqual(row.code_hash, password_reset.hash_code(code))

    def test_a_mail_failure_does_not_show_and_does_not_break_the_request(self):
        with patch('accounts.password_reset.send_mail', side_effect=OSError('smtp down')):
            with self.assertLogs('accounts.password_reset', level='ERROR'):
                response = self._forgot()

        self.assertEqual(response.status_code, 200)

    def test_a_stale_token_in_the_header_does_not_turn_it_into_a_401(self):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer not-a-real-token')

        self.assertEqual(self._forgot().status_code, 200)

    def test_an_invalid_email_is_a_400(self):
        self.assertEqual(self.client.post(FORGOT, {'email': 'nope'}).status_code, 400)
        self.assertEqual(self.client.post(FORGOT, {}).status_code, 400)

    # --- using the code ----------------------------------------------------------

    def test_the_code_sets_the_password_and_the_old_one_stops_working(self):
        self._forgot()

        response = self._reset(self._code())

        self.assertEqual(response.status_code, 200)
        login = lambda pw: self.client.post(  # noqa: E731
            '/api/v1/auth/login', {'email': 'jane@example.com', 'password': pw},
        ).status_code
        self.assertEqual(login(NEW_PASSWORD), 200)
        self.assertEqual(login('Old-Password-42'), 400)

    def test_a_google_sign_up_can_set_its_first_password_this_way(self):
        google = User.objects.create_user('g@gmail.com', firebase_uid='uid-g')
        self._forgot('g@gmail.com')

        response = self._reset(self._code(), email='g@gmail.com')

        self.assertEqual(response.status_code, 200)
        google.refresh_from_db()
        self.assertTrue(google.password_set)
        self.assertTrue(google.check_password(NEW_PASSWORD))
        self.assertEqual(google.firebase_uid, 'uid-g')
        login = self.client.post(
            '/api/v1/auth/login', {'email': 'g@gmail.com', 'password': NEW_PASSWORD},
        )
        self.assertEqual(login.status_code, 200)

    def test_a_code_works_once(self):
        self._forgot()
        code = self._code()

        self.assertEqual(self._reset(code).status_code, 200)
        self.assertEqual(self._reset(code, 'Another-Strong-Pass-7').status_code, 400)
        self.jane.refresh_from_db()
        self.assertTrue(self.jane.check_password(NEW_PASSWORD))

    def test_a_wrong_code_is_refused_and_the_password_untouched(self):
        self._forgot()
        wrong = '000000' if self._code() != '000000' else '111111'

        response = self._reset(wrong)

        self.assertEqual(response.status_code, 400)
        self.assertIn('code', response.data)
        self.jane.refresh_from_db()
        self.assertTrue(self.jane.check_password('Old-Password-42'))

    def test_five_wrong_guesses_kill_the_code_even_for_the_right_one(self):
        self._forgot()
        real = self._code()
        wrong = '000000' if real != '000000' else '111111'

        for _ in range(password_reset.MAX_ATTEMPTS):
            self.assertEqual(self._reset(wrong).status_code, 400)

        self.assertEqual(self._reset(real).status_code, 400)
        self.jane.refresh_from_db()
        self.assertTrue(self.jane.check_password('Old-Password-42'))

    def test_an_expired_code_is_refused(self):
        self._forgot()
        self._age_codes(expires_at=timezone.now() - timedelta(seconds=1))

        self.assertEqual(self._reset(self._code()).status_code, 400)

    def test_every_way_of_being_wrong_gives_the_same_answer(self):
        self._forgot()
        real = self._code()
        wrong_code = self._reset('000000' if real != '000000' else '111111')
        no_such_account = self._reset(real, email='nobody@example.com')
        no_code_at_all = self._reset(real, email='nobody-else@example.com')

        self.assertEqual(wrong_code.data, no_such_account.data)
        self.assertEqual(wrong_code.data, no_code_at_all.data)

    def test_a_code_cannot_be_used_on_someone_elses_account(self):
        User.objects.create_user('bob@example.com', 'Bobs-Password-42')
        self._forgot()

        response = self._reset(self._code(), email='bob@example.com')

        self.assertEqual(response.status_code, 400)

    def test_a_weak_password_is_refused_without_using_up_the_code(self):
        self._forgot()
        code = self._code()

        for weak in ('short', '12345678', 'password'):
            self.assertEqual(self._reset(code, weak).status_code, 400, weak)
        self.assertEqual(self._reset(code, confirmation='Different-Pass-99').status_code, 400)

        # None of that spent the code or counted as a wrong guess.
        row = PasswordResetCode.objects.get()
        self.assertIsNone(row.used_at)
        self.assertEqual(row.attempts, 0)
        self.assertEqual(self._reset(code).status_code, 200)

    def test_a_password_like_the_email_is_refused(self):
        self._forgot()

        self.assertEqual(self._reset(self._code(), 'jane@example.com').status_code, 400)

    def test_the_accounts_sessions_are_signed_out(self):
        login = self.client.post(
            '/api/v1/auth/login', {'email': 'jane@example.com', 'password': 'Old-Password-42'},
        )
        refresh = login.data['tokens']['refresh']
        self._forgot()

        self._reset(self._code())

        self.assertTrue(BlacklistedToken.objects.exists())
        renewed = self.client.post('/api/v1/auth/refresh', {'refresh': refresh})
        self.assertEqual(renewed.status_code, 401)

    def test_it_needs_all_the_fields(self):
        for body in ({}, {'email': 'jane@example.com'}, {'email': 'jane@example.com', 'code': '123456'}):
            self.assertEqual(self.client.post(RESET, body).status_code, 400)

    def test_the_per_ip_throttle_eventually_says_slow_down(self):
        codes = [self._forgot().status_code for _ in range(25)]

        self.assertIn(429, codes)
        self.assertEqual(codes[0], 200)
