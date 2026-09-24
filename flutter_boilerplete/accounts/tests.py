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


@override_settings(FIREBASE_PROJECT_ID='cncgroupjony')
class VerifyFirebaseTokenTests(APITestCase):
    """The verifier itself, with google-auth's signature check stubbed out."""

    def _verify(self, claims=None, error=None):
        target = 'accounts.firebase.id_token.verify_firebase_token'
        with patch(target, return_value=claims, side_effect=error) as verify:
            return firebase.verify_firebase_token('tok'), verify

    def test_it_checks_the_token_against_this_firebase_project(self):
        _, verify = self._verify(_claims())

        self.assertEqual(verify.call_args.kwargs['audience'], 'cncgroupjony')

    def test_a_google_sign_in_is_accepted(self):
        claims, _ = self._verify(_claims('google.com'))

        self.assertEqual(firebase.provider_of(claims), 'google.com')

    def test_any_other_provider_is_rejected(self):
        for provider in ('password', 'facebook.com', 'phone', 'anonymous', 'custom', None):
            with self.assertRaises(firebase.InvalidFirebaseToken, msg=provider):
                self._verify(_claims(provider))
        with self.assertRaises(firebase.InvalidFirebaseToken):
            self._verify(_claims(firebase={}))

    def test_a_bad_signature_or_expired_token_is_rejected(self):
        with self.assertRaises(firebase.InvalidFirebaseToken):
            self._verify(error=ValueError('Token expired'))
        with self.assertRaises(firebase.InvalidFirebaseToken):
            self._verify(claims=None)

    def test_an_unverified_or_missing_email_is_rejected(self):
        with self.assertRaises(firebase.InvalidFirebaseToken):
            self._verify(_claims(email_verified=False))
        with self.assertRaises(firebase.InvalidFirebaseToken):
            self._verify(_claims(email=''))

    def test_a_token_with_no_firebase_user_id_is_rejected(self):
        with self.assertRaises(firebase.InvalidFirebaseToken):
            self._verify(_claims(sub=''))

    def test_garbage_is_rejected_by_the_real_library(self):
        for token in ('garbage', 'a.b.c'):
            with self.assertRaises(firebase.InvalidFirebaseToken):
                firebase.verify_firebase_token(token)


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
