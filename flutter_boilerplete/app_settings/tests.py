from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from .limits import MAX_URL_LENGTH
from .models import AppSetting

User = get_user_model()

PLAY = 'https://play.google.com/store/apps/details?id=com.jony.cncgroupjony&hl=en'
APPSTORE = 'https://apps.apple.com/app/cnc-design/id1234567890'

# Every option added: blank value or default, until an admin sets it.
HELP_SUPPORT_DEFAULTS = {
    'maintenance_mode': False,
    'app_version': '1.0.0',
    'min_supported_version': '1.0.0',
    'registration_enabled': True,
    'google_login_enabled': True,
    'help_support_email': '', 'help_support_email_enabled': True,
    'help_support_whatsapp': '', 'help_support_whatsapp_enabled': True,
    'help_support_telegram': '', 'help_support_telegram_enabled': True,
    'help_support_phone': '', 'help_support_phone_enabled': True,
}


class SettingTestCase(APITestCase):
    """An admin, a customer, and the two endpoints - what every test here
    starts from. Has no tests itself."""

    def setUp(self):
        AppSetting.objects.all().delete()
        self.admin = User.objects.create_user('admin@example.com', 'pw-1', is_staff=True)
        self.customer = User.objects.create_user('customer@example.com', 'pw-2')
        self.client.force_authenticate(self.admin)

    def _get(self):
        return self.client.get(reverse('app-setting'))

    def _patch(self, data=None, **fields):
        body = fields if data is None else data
        return self.client.patch(reverse('admin-app-setting'), body, format='json')

    def _saved(self, **fields):
        response = self._patch(**fields)
        self.assertEqual(response.status_code, 200, response.data)
        return AppSetting.current()


class AccessTests(SettingTestCase):
    def test_anyone_can_read_it_without_signing_in(self):
        self.client.force_authenticate(None)

        response = self._get()

        self.assertEqual(response.status_code, 200)

    def test_a_signed_in_user_can_read_it_too(self):
        for user in (self.customer, self.admin):
            self.client.force_authenticate(user)
            self.assertEqual(self._get().status_code, 200)

    def test_a_stale_token_does_not_break_the_public_read(self):
        # The app sends whatever token it still holds - even an expired one -
        # and the footer on the login page needs this before anyone signs in.
        self.client.force_authenticate(None)

        for header in ('Bearer not.a.real.token', 'Bearer ', 'Token abc', 'garbage'):
            with self.subTest(header=header):
                response = self.client.get(reverse('app-setting'), HTTP_AUTHORIZATION=header)
                self.assertEqual(response.status_code, 200)

    def test_writing_needs_a_login(self):
        self.client.force_authenticate(None)

        self.assertEqual(self._patch(android_app_url=PLAY).status_code, 401)
        self.assertFalse(AppSetting.objects.exists())

    def test_a_customer_cannot_write_it(self):
        self.client.force_authenticate(self.customer)

        self.assertEqual(self._patch(android_app_url=PLAY).status_code, 403)
        self.assertFalse(AppSetting.objects.exists())

    def test_a_customer_cannot_change_what_an_admin_set(self):
        self._saved(android_app_url=PLAY)
        self.client.force_authenticate(self.customer)

        self.assertEqual(self._patch(android_app_url='https://evil.example').status_code, 403)
        self.assertEqual(AppSetting.current().android_app_url, PLAY)

    def test_the_public_url_only_reads(self):
        self.client.force_authenticate(None)
        for method in ('post', 'put', 'patch', 'delete'):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    reverse('app-setting'), {'android_app_url': PLAY}, format='json',
                )
                self.assertEqual(response.status_code, 405)
        self.assertFalse(AppSetting.objects.exists())

    def test_the_admin_url_supports_get_and_patch(self):
        self.assertEqual(self.client.get(reverse('admin-app-setting')).status_code, 200)
        for method in ('post', 'put', 'delete'):
            with self.subTest(method=method):
                response = getattr(self.client, method)(reverse('admin-app-setting'))
                self.assertEqual(response.status_code, 405)

    def test_the_paths_are_the_ones_the_app_calls(self):
        self.assertEqual(reverse('admin-app-setting'), '/api/v1/admin/app-setting')


class ReadingTests(SettingTestCase):
    def test_before_any_is_saved_every_option_reads_blank_not_an_error(self):
        response = self._get()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {
                'android_app_url': '', 'ios_app_url': '',
                **HELP_SUPPORT_DEFAULTS,
                'updated_at': None,
            },
        )

    def test_it_reads_back_what_was_saved(self):
        self._saved(android_app_url=PLAY, ios_app_url=APPSTORE)

        data = self._get().data

        self.assertEqual(data['android_app_url'], PLAY)
        self.assertEqual(data['ios_app_url'], APPSTORE)
        self.assertIsNotNone(data['updated_at'])

    def test_it_carries_only_what_the_app_uses(self):
        self._saved(android_app_url=PLAY)

        self.assertEqual(
            set(self._get().data),
            {'android_app_url', 'ios_app_url', 'updated_at', *HELP_SUPPORT_DEFAULTS},
        )

    def test_an_option_that_was_never_set_reads_blank_beside_one_that_was(self):
        self._saved(android_app_url=PLAY)

        data = self._get().data

        self.assertEqual(data['android_app_url'], PLAY)
        self.assertEqual(data['ios_app_url'], '')

    def test_it_is_one_query(self):
        self._saved(android_app_url=PLAY)

        with CaptureQueriesContext(connection) as captured:
            self.assertEqual(self._get().status_code, 200)

        self.assertEqual(len(captured), 1)

    def test_a_blank_read_costs_one_query_too(self):
        with CaptureQueriesContext(connection) as captured:
            self._get()

        self.assertEqual(len(captured), 1)


class WritingTests(SettingTestCase):
    def test_the_first_save_creates_it_and_says_what_is_set(self):
        response = self._patch(android_app_url=PLAY, ios_app_url=APPSTORE)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['android_app_url'], PLAY)
        self.assertEqual(response.data['ios_app_url'], APPSTORE)
        self.assertIsNotNone(response.data['updated_at'])
        self.assertEqual(AppSetting.objects.count(), 1)

    def test_the_answer_is_what_a_later_read_returns(self):
        answer = self._patch(android_app_url=PLAY).data

        self.assertEqual(answer, self._get().data)

    def test_only_the_options_sent_are_changed(self):
        self._saved(android_app_url=PLAY, ios_app_url=APPSTORE)

        self._saved(ios_app_url='https://apps.apple.com/app/new/id999')

        setting = AppSetting.current()
        self.assertEqual(setting.android_app_url, PLAY)
        self.assertEqual(setting.ios_app_url, 'https://apps.apple.com/app/new/id999')

    def test_setting_one_option_first_leaves_the_other_blank(self):
        self._saved(ios_app_url=APPSTORE)

        setting = AppSetting.current()
        self.assertEqual(setting.android_app_url, '')
        self.assertEqual(setting.ios_app_url, APPSTORE)

    def test_a_blank_value_switches_an_option_off(self):
        self._saved(android_app_url=PLAY, ios_app_url=APPSTORE)

        self._saved(android_app_url='')

        setting = AppSetting.current()
        self.assertEqual(setting.android_app_url, '')
        self.assertEqual(setting.ios_app_url, APPSTORE, 'the other one stays')

    def test_null_switches_an_option_off_too(self):
        self._saved(android_app_url=PLAY)

        self._saved(android_app_url=None)

        self.assertEqual(AppSetting.current().android_app_url, '')
        self.assertEqual(self._get().data['android_app_url'], '')

    def test_a_blank_of_only_whitespace_switches_it_off(self):
        self._saved(android_app_url=PLAY)

        self._saved(android_app_url='   \n ')

        self.assertEqual(AppSetting.current().android_app_url, '')

    def test_both_options_can_be_switched_off_at_once(self):
        self._saved(android_app_url=PLAY, ios_app_url=APPSTORE)

        self._saved(android_app_url='', ios_app_url='')

        self.assertEqual(self._get().data['android_app_url'], '')
        self.assertEqual(self._get().data['ios_app_url'], '')

    def test_whitespace_around_a_link_is_trimmed(self):
        self._saved(android_app_url=f'  {PLAY}\n')

        self.assertEqual(AppSetting.current().android_app_url, PLAY)

    def test_a_link_is_kept_exactly_as_written(self):
        link = 'https://example.com/get?app=cnc&utm_source=web&utm_campaign=Eid%20sale#install'

        self._saved(android_app_url=link)

        self.assertEqual(self._get().data['android_app_url'], link)

    def test_http_and_https_in_any_case_are_accepted(self):
        for link in (
            'http://example.com/app.apk',
            'https://example.com/app.apk',
            'HTTPS://Example.com/App',
            'https://192.168.1.10:8080/app.apk',
            'https://sub.example.co.uk/a/b/c?d=e',
            'https://xn--mgbh0fb.example/app',
        ):
            with self.subTest(link=link):
                self.assertEqual(self._patch(android_app_url=link).status_code, 200)

    def test_the_longest_allowed_link_is_accepted(self):
        prefix = 'https://example.com/'
        link = prefix + 'a' * (MAX_URL_LENGTH - len(prefix))

        response = self._patch(android_app_url=link)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(AppSetting.current().android_app_url), MAX_URL_LENGTH)

    def test_a_save_moves_the_last_saved_time_on(self):
        first = self._saved(android_app_url=PLAY)
        AppSetting.objects.filter(pk=first.pk).update(updated_at=timezone.now() - timedelta(days=30))
        old = AppSetting.current().updated_at

        self._saved(ios_app_url=APPSTORE)

        self.assertGreater(AppSetting.current().updated_at, old)

    def test_it_records_who_saved_it_last(self):
        self._saved(android_app_url=PLAY)
        self.assertEqual(AppSetting.current().updated_by, self.admin)

        other = User.objects.create_user('other@example.com', 'pw-4', is_staff=True)
        self.client.force_authenticate(other)
        self._saved(ios_app_url=APPSTORE)

        self.assertEqual(AppSetting.current().updated_by, other)

    def test_a_client_cannot_choose_the_time_or_the_editor(self):
        someone = User.objects.create_user('someone@example.com', 'pw-5')

        response = self._patch(
            android_app_url=PLAY, updated_at='2001-01-01T00:00:00Z', updated_by=someone.pk,
        )

        self.assertEqual(response.status_code, 200)
        setting = AppSetting.current()
        self.assertGreater(setting.updated_at.year, 2001)
        self.assertEqual(setting.updated_by, self.admin)

    def test_options_it_does_not_know_are_ignored(self):
        response = self._patch(android_app_url=PLAY, windows_app_url='https://example.com/w')

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('windows_app_url', response.data)

    def test_other_languages_in_a_link_survive(self):
        link = 'https://example.com/অ্যাপ?নাম=সিএনসি'

        response = self._patch(android_app_url=link)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._get().data['android_app_url'], link)

    def test_nothing_sent_changes_nothing_and_creates_nothing(self):
        response = self._patch({})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['android_app_url'], '')
        self.assertFalse(AppSetting.objects.exists())

    def test_nothing_sent_leaves_what_is_saved_and_when_alone(self):
        first = self._saved(android_app_url=PLAY)
        AppSetting.objects.filter(pk=first.pk).update(updated_at=timezone.now() - timedelta(days=30))
        before = AppSetting.current()

        response = self._patch({})

        after = AppSetting.current()
        self.assertEqual(response.data['android_app_url'], PLAY)
        self.assertEqual(after.updated_at, before.updated_at)
        self.assertEqual(after.updated_by, before.updated_by)


class HelpSupportFieldTests(SettingTestCase):
    """Each contact channel has its own value and its own switch, saved and
    read the same way as android/iOS but independent of one another."""

    def test_every_channel_defaults_to_blank_and_switched_on(self):
        self.assertEqual(self._get().data, {
            'android_app_url': '', 'ios_app_url': '',
            **HELP_SUPPORT_DEFAULTS,
            'updated_at': None,
        })

    def test_a_channel_s_value_and_switch_are_saved_together(self):
        self._saved(help_support_email='support@cncgroupjony.com', help_support_email_enabled=False)

        data = self._get().data
        self.assertEqual(data['help_support_email'], 'support@cncgroupjony.com')
        self.assertFalse(data['help_support_email_enabled'])

    def test_each_channel_is_independent_of_the_others(self):
        self._saved(help_support_whatsapp='8801000000000', help_support_telegram='cncgroupjony')

        setting = AppSetting.current()
        self.assertEqual(setting.help_support_whatsapp, '8801000000000')
        self.assertEqual(setting.help_support_telegram, 'cncgroupjony')
        self.assertEqual(setting.help_support_email, '')
        self.assertTrue(setting.help_support_whatsapp_enabled, 'untouched switches stay on')

    def test_a_blank_value_switches_a_channel_off_without_touching_its_switch(self):
        self._saved(help_support_phone='+8801000000000', help_support_phone_enabled=False)

        self._saved(help_support_phone='')

        setting = AppSetting.current()
        self.assertEqual(setting.help_support_phone, '')
        self.assertFalse(setting.help_support_phone_enabled, 'the switch is a separate field')

    def test_null_clears_a_channel_s_value_too(self):
        self._saved(help_support_whatsapp='+8801000000000')

        self._saved(help_support_whatsapp=None)

        self.assertEqual(AppSetting.current().help_support_whatsapp, '')

    def test_the_switch_can_be_changed_without_sending_the_value(self):
        self._saved(help_support_email='support@cncgroupjony.com')

        self._saved(help_support_email_enabled=False)

        setting = AppSetting.current()
        self.assertEqual(setting.help_support_email, 'support@cncgroupjony.com', 'the value stays')
        self.assertFalse(setting.help_support_email_enabled)

    def test_an_invalid_email_is_refused(self):
        response = self._patch(help_support_email='not-an-email')

        self.assertEqual(response.status_code, 400)
        self.assertIn('help_support_email', response.data)
        self.assertFalse(AppSetting.objects.exists())

    def test_a_valid_email_is_accepted(self):
        response = self._patch(help_support_email='support@cncgroupjony.com')

        self.assertEqual(response.status_code, 200, response.data)

    def test_whatsapp_telegram_and_phone_are_not_validated_as_email(self):
        response = self._patch(
            help_support_whatsapp='+880 1000-000000',
            help_support_telegram='@cncgroupjony',
            help_support_phone='+880 1000-000000',
        )

        self.assertEqual(response.status_code, 200, response.data)

    def test_it_carries_the_help_support_fields_and_nothing_extra(self):
        self._saved(help_support_email='support@cncgroupjony.com')

        self.assertEqual(
            set(self._get().data),
            {'android_app_url', 'ios_app_url', 'updated_at', *HELP_SUPPORT_DEFAULTS},
        )


class ValidationTests(SettingTestCase):
    def _refused(self, response, *fields):
        self.assertEqual(response.status_code, 400, response.data)
        for field in fields:
            self.assertIn(field, response.data)

    def test_a_link_that_is_not_a_web_address_is_refused(self):
        for bad in (
            'not a url',
            'example.com',
            'www.example.com/app',
            '//example.com/app',
            'https://',
            'http://',
            'https:///path',
            'https://exa mple.com',
            'https://example.com/a b',
            'https://example',
            'https://.com',
        ):
            with self.subTest(link=bad):
                self._refused(self._patch(android_app_url=bad), 'android_app_url')

    def test_a_link_that_would_run_something_is_refused(self):
        # Opened in a new tab, these would execute or expose instead of opening
        # a page - only web addresses are links.
        for bad in (
            'javascript:alert(1)',
            'JAVASCRIPT:alert(1)',
            ' javascript:alert(document.cookie)',
            'data:text/html,<script>alert(1)</script>',
            'vbscript:msgbox(1)',
            'file:///etc/passwd',
            'blob:https://example.com/1234',
            'about:blank',
        ):
            with self.subTest(link=bad):
                self._refused(self._patch(ios_app_url=bad), 'ios_app_url')
                self.assertFalse(AppSetting.objects.exists())

    def test_other_schemes_are_refused_even_when_they_are_real_links(self):
        for bad in (
            'ftp://example.com/app.apk',
            'ftps://example.com/app.apk',
            'market://details?id=com.jony.cncgroupjony',
            'itms-apps://apps.apple.com/app/id1234567890',
            'intent://details?id=x#Intent;scheme=market;end',
            'mailto:someone@example.com',
            'tel:+8801700000000',
        ):
            with self.subTest(link=bad):
                self._refused(self._patch(android_app_url=bad), 'android_app_url')

    def test_a_link_with_control_characters_is_refused(self):
        for bad in ('https://example.com/\napp', 'https://example.com/\tapp', 'https://exa\x00mple.com'):
            with self.subTest(link=repr(bad)):
                self._refused(self._patch(android_app_url=bad), 'android_app_url')

    def test_a_link_that_is_too_long_is_refused(self):
        prefix = 'https://example.com/'
        link = prefix + 'a' * (MAX_URL_LENGTH - len(prefix) + 1)

        self._refused(self._patch(android_app_url=link), 'android_app_url')

    def test_something_that_is_not_text_is_refused(self):
        for bad in (5, 1.5, True, ['https://example.com'], {'url': 'https://example.com'}):
            with self.subTest(value=bad):
                self._refused(self._patch(android_app_url=bad), 'android_app_url')

    def test_each_option_is_checked_on_its_own(self):
        response = self._patch(android_app_url='nope', ios_app_url='also nope')

        self._refused(response, 'android_app_url', 'ios_app_url')

    def test_only_the_bad_option_is_named(self):
        response = self._patch(android_app_url=PLAY, ios_app_url='nope')

        self._refused(response, 'ios_app_url')
        self.assertNotIn('android_app_url', response.data)

    def test_a_refused_save_changes_nothing_not_even_the_good_option(self):
        self._saved(android_app_url=PLAY, ios_app_url=APPSTORE)

        response = self._patch(android_app_url='https://new.example/app', ios_app_url='javascript:alert(1)')

        self._refused(response, 'ios_app_url')
        setting = AppSetting.current()
        self.assertEqual(setting.android_app_url, PLAY)
        self.assertEqual(setting.ios_app_url, APPSTORE)

    def test_a_body_that_is_not_json_is_refused(self):
        response = self.client.patch(
            reverse('admin-app-setting'), 'android_app_url=https://example.com',
            content_type='application/x-www-form-urlencoded',
        )

        self.assertEqual(response.status_code, 415)
        self.assertFalse(AppSetting.objects.exists())

    def test_json_that_is_not_an_object_is_a_400_not_a_500(self):
        for body in ('[]', '"text"', '5', 'null'):
            with self.subTest(body=body):
                response = self.client.patch(
                    reverse('admin-app-setting'), body, content_type='application/json',
                )
                self.assertEqual(response.status_code, 400)


class OneDocumentTests(SettingTestCase):
    def test_the_document_always_has_the_same_id(self):
        AppSetting(android_app_url=PLAY).save()

        self.assertEqual(list(AppSetting.objects.values_list('pk', flat=True)), [1])

    def test_saving_a_new_instance_edits_the_one_document(self):
        AppSetting(android_app_url=PLAY).save()

        AppSetting(android_app_url='https://example.com/two').save()

        self.assertEqual(AppSetting.objects.count(), 1)
        self.assertEqual(AppSetting.current().android_app_url, 'https://example.com/two')

    def test_the_database_refuses_a_second_row(self):
        AppSetting(android_app_url=PLAY).save()

        with self.assertRaises(IntegrityError), transaction.atomic():
            AppSetting.objects.bulk_create([AppSetting(pk=2)])

        self.assertEqual(AppSetting.objects.count(), 1)

    def test_current_is_none_until_one_is_saved(self):
        self.assertIsNone(AppSetting.current())

        self._saved(android_app_url=PLAY)

        self.assertEqual(AppSetting.current().android_app_url, PLAY)

    def test_every_option_starts_blank(self):
        setting = AppSetting.objects.create()

        self.assertEqual(setting.android_app_url, '')
        self.assertEqual(setting.ios_app_url, '')

    def test_deleting_the_account_that_saved_it_keeps_the_settings(self):
        self._saved(android_app_url=PLAY)

        self.admin.delete()

        setting = AppSetting.current()
        self.assertIsNotNone(setting)
        self.assertIsNone(setting.updated_by)
        self.client.force_authenticate(None)
        self.assertEqual(self._get().data['android_app_url'], PLAY)


class AdminSiteTests(SettingTestCase):
    """The Django admin screen - a second way to change the same document."""

    def setUp(self):
        super().setUp()
        self.superuser = User.objects.create_superuser('root@example.com', 'pw-9')
        self.client.force_login(self.superuser)

    def test_it_can_be_added_when_there_is_none(self):
        self.assertEqual(self.client.get('/admin/app_settings/appsetting/add/').status_code, 200)

    def test_it_cannot_be_added_once_there_is_one(self):
        self._saved(android_app_url=PLAY)

        self.assertEqual(self.client.get('/admin/app_settings/appsetting/add/').status_code, 403)

    def test_it_cannot_be_deleted(self):
        setting = self._saved(android_app_url=PLAY)

        response = self.client.post(
            f'/admin/app_settings/appsetting/{setting.pk}/delete/', {'post': 'yes'},
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(AppSetting.objects.exists())

    def test_it_lists_and_opens(self):
        setting = self._saved(android_app_url=PLAY)

        self.assertEqual(self.client.get('/admin/app_settings/appsetting/').status_code, 200)
        self.assertEqual(
            self.client.get(f'/admin/app_settings/appsetting/{setting.pk}/change/').status_code, 200,
        )

    def test_an_edit_there_records_who_made_it(self):
        setting = self._saved(android_app_url=PLAY)

        response = self.client.post(
            f'/admin/app_settings/appsetting/{setting.pk}/change/',
            {'android_app_url': 'https://example.com/from-admin', 'ios_app_url': ''},
        )

        self.assertEqual(response.status_code, 302)
        setting = AppSetting.current()
        self.assertEqual(setting.android_app_url, 'https://example.com/from-admin')
        self.assertEqual(setting.updated_by, self.superuser)


class AppControlTests(SettingTestCase):
    def test_maintenance_mode_can_be_enabled_and_disabled(self):
        self._saved(maintenance_mode=True)
        self.assertTrue(AppSetting.current().maintenance_mode)

        self._saved(maintenance_mode=False)
        self.assertFalse(AppSetting.current().maintenance_mode)

    def test_version_and_min_version_can_be_configured(self):
        self._saved(app_version='2.1.0', min_supported_version='2.0.0')
        setting = AppSetting.current()
        self.assertEqual(setting.app_version, '2.1.0')
        self.assertEqual(setting.min_supported_version, '2.0.0')

    def test_registration_enabled_can_be_toggled(self):
        self._saved(registration_enabled=False)
        self.assertFalse(AppSetting.current().registration_enabled)

        self._saved(registration_enabled=True)
        self.assertTrue(AppSetting.current().registration_enabled)

    def test_google_login_enabled_can_be_toggled(self):
        self._saved(google_login_enabled=False)
        self.assertFalse(AppSetting.current().google_login_enabled)

        self._saved(google_login_enabled=True)
        self.assertTrue(AppSetting.current().google_login_enabled)

    def test_config_endpoint_reflects_app_settings(self):
        self._saved(
            maintenance_mode=True,
            app_version='3.0.0',
            min_supported_version='2.5.0',
            registration_enabled=False,
            google_login_enabled=False,
            help_support_email='admin@cncgroupjony.com',
            help_support_whatsapp='+8801999999999',
            android_app_url='https://play.google.com/store/apps/details?id=com.cnc',
            ios_app_url='https://apps.apple.com/app/id123456789',
        )

        self.client.force_authenticate(None)
        response = self.client.get(reverse('config'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['maintenance_mode'])
        self.assertEqual(response.data['version'], '3.0.0')
        self.assertEqual(response.data['min_supported_version'], '2.5.0')
        self.assertFalse(response.data['features']['registration_enabled'])
        self.assertFalse(response.data['features']['social_login_enabled'])
        self.assertFalse(response.data['features']['google_login_enabled'])
        self.assertEqual(response.data['support_email'], 'admin@cncgroupjony.com')
        self.assertEqual(response.data['help_support_email'], 'admin@cncgroupjony.com')
        self.assertEqual(response.data['help_support_whatsapp'], '+8801999999999')
        self.assertEqual(response.data['android_app_url'], 'https://play.google.com/store/apps/details?id=com.cnc')
        self.assertEqual(response.data['ios_app_url'], 'https://apps.apple.com/app/id123456789')

