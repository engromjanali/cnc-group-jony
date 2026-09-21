from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from .limits import MAX_CONTENT_LENGTH, MAX_TITLE_LENGTH
from .models import PrivacyPolicy
from .serializers import visible_text

User = get_user_model()

BODY = {
    'title': 'Privacy Policy',
    'content': '<h2>What we collect</h2><p>Your <b>email</b> and designs.</p>',
}


class PolicyTestCase(APITestCase):
    """An admin, a customer, and the two endpoints - what every test here
    starts from. Has no tests itself."""

    def setUp(self):
        self.admin = User.objects.create_user('admin@example.com', 'pw-1', is_staff=True)
        self.customer = User.objects.create_user('customer@example.com', 'pw-2')
        self.client.force_authenticate(self.admin)

    def _get(self):
        return self.client.get(reverse('privacy-policy'))

    def _put(self, data=None, **fields):
        body = {**BODY, **fields} if data is None else data
        return self.client.put(reverse('admin-privacy-policy'), body, format='json')

    def _written(self, **fields):
        response = self._put(**fields)
        self.assertEqual(response.status_code, 200, response.data)
        return PrivacyPolicy.current()


class AccessTests(PolicyTestCase):
    def test_reading_needs_a_login(self):
        self.client.force_authenticate(None)
        self.assertEqual(self._get().status_code, 401)

    def test_any_signed_in_user_can_read_it_not_only_admins(self):
        self._written()

        for user in (self.customer, self.admin):
            self.client.force_authenticate(user)
            self.assertEqual(self._get().status_code, 200)

    def test_writing_needs_a_login(self):
        self.client.force_authenticate(None)
        self.assertEqual(self._put().status_code, 401)
        self.assertFalse(PrivacyPolicy.objects.exists())

    def test_a_customer_cannot_write_it(self):
        self.client.force_authenticate(self.customer)

        self.assertEqual(self._put().status_code, 403)
        self.assertFalse(PrivacyPolicy.objects.exists())

    def test_a_customer_cannot_overwrite_what_an_admin_wrote(self):
        self._written(title='The real policy')
        self.client.force_authenticate(self.customer)

        self.assertEqual(self._put(title='Defaced').status_code, 403)
        self.assertEqual(PrivacyPolicy.current().title, 'The real policy')

    def test_the_public_url_only_reads(self):
        for method in ('post', 'put', 'patch', 'delete'):
            with self.subTest(method=method):
                response = getattr(self.client, method)(reverse('privacy-policy'), BODY, format='json')
                self.assertEqual(response.status_code, 405)
        self.assertFalse(PrivacyPolicy.objects.exists())

    def test_the_admin_url_only_writes_with_put(self):
        for method in ('get', 'post', 'patch', 'delete'):
            with self.subTest(method=method):
                response = getattr(self.client, method)(reverse('admin-privacy-policy'))
                self.assertEqual(response.status_code, 405)

    def test_the_paths_are_the_ones_the_app_calls(self):
        self.assertEqual(reverse('privacy-policy'), '/api/v1/privacy-policy')
        self.assertEqual(reverse('admin-privacy-policy'), '/api/v1/admin/privacy-policy')


class ReadingTests(PolicyTestCase):
    def test_before_one_is_written_it_reads_as_a_blank_one_not_an_error(self):
        response = self._get()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'title': '', 'content': '', 'updated_at': None})

    def test_it_reads_back_what_was_written(self):
        self._written()

        response = self._get()

        self.assertEqual(response.data['title'], BODY['title'])
        self.assertEqual(response.data['content'], BODY['content'])
        self.assertIsNotNone(response.data['updated_at'])

    def test_it_carries_only_what_the_app_shows(self):
        self._written()

        self.assertEqual(set(self._get().data), {'title', 'content', 'updated_at'})

    def test_it_says_when_it_was_last_saved(self):
        before = timezone.now()
        self._written()

        saved = PrivacyPolicy.current().updated_at

        self.assertGreaterEqual(saved, before)
        self.assertIn(saved.isoformat().replace('+00:00', ''), self._get().content.decode())

    def test_it_is_one_query_however_long_it_is(self):
        self._written(content='<p>' + 'word ' * 5000 + '</p>')

        with CaptureQueriesContext(connection) as captured:
            self.assertEqual(self._get().status_code, 200)

        # The login itself is forced in these tests, so this is just the row.
        self.assertEqual(len(captured), 1)


class WritingTests(PolicyTestCase):
    def test_the_first_write_creates_it_and_says_what_was_saved(self):
        response = self._put()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['title'], BODY['title'])
        self.assertEqual(response.data['content'], BODY['content'])
        self.assertIsNotNone(response.data['updated_at'])
        self.assertEqual(PrivacyPolicy.objects.count(), 1)

    def test_the_answer_is_what_a_later_read_returns(self):
        answer = self._put().data

        self.assertEqual(answer, self._get().data)

    def test_a_later_write_replaces_it_and_there_is_still_one(self):
        self._written(title='Version one', content='<p>One</p>')

        self._written(title='Version two', content='<p>Two</p>')

        self.assertEqual(PrivacyPolicy.objects.count(), 1)
        self.assertEqual(self._get().data['title'], 'Version two')
        self.assertEqual(self._get().data['content'], '<p>Two</p>')

    def test_a_later_write_moves_the_last_saved_time_on(self):
        first = self._written()
        PrivacyPolicy.objects.filter(pk=first.pk).update(
            updated_at=timezone.now() - timedelta(days=30),
        )
        old = PrivacyPolicy.current().updated_at

        self._written(title='Version two')

        self.assertGreater(PrivacyPolicy.current().updated_at, old)

    def test_it_records_who_saved_it_last(self):
        self._written()
        self.assertEqual(PrivacyPolicy.current().updated_by, self.admin)

        other = User.objects.create_user('other@example.com', 'pw-4', is_staff=True)
        self.client.force_authenticate(other)
        self._written(title='Edited by someone else')

        self.assertEqual(PrivacyPolicy.current().updated_by, other)

    def test_a_client_cannot_choose_the_time_or_the_editor(self):
        someone = User.objects.create_user('someone@example.com', 'pw-5')
        response = self._put(
            updated_at='2001-01-01T00:00:00Z', updated_by=someone.pk,
        )

        self.assertEqual(response.status_code, 200)
        policy = PrivacyPolicy.current()
        self.assertGreater(policy.updated_at.year, 2001)
        self.assertEqual(policy.updated_by, self.admin)

    def test_the_html_is_kept_exactly_as_written(self):
        content = (
            '<h1>Title</h1><p style="text-align:center">Centre</p>'
            '<ul><li>One</li><li>Two</li></ul>'
            '<p><a href="https://example.com/terms?a=1&amp;b=2">Terms</a></p>'
        )

        self._written(content=content)

        self.assertEqual(self._get().data['content'], content)

    def test_other_languages_survive(self):
        title = 'গোপনীয়তা নীতি'
        content = '<p>سياسة الخصوصية - আপনার তথ্য</p>'

        self._written(title=title, content=content)

        self.assertEqual(self._get().data['title'], title)
        self.assertEqual(self._get().data['content'], content)

    def test_whitespace_around_the_text_is_trimmed(self):
        self._written(title='  Privacy Policy \n', content='\n <p>Body</p>  ')

        self.assertEqual(self._get().data['title'], 'Privacy Policy')
        self.assertEqual(self._get().data['content'], '<p>Body</p>')

    def test_the_longest_allowed_title_and_content_are_accepted(self):
        response = self._put(
            title='t' * MAX_TITLE_LENGTH,
            content='<p>' + 'c' * (MAX_CONTENT_LENGTH - len('<p>')),
        )

        self.assertEqual(response.status_code, 200, response.data)


class ValidationTests(PolicyTestCase):
    def _refused(self, response, *fields):
        self.assertEqual(response.status_code, 400, response.data)
        for field in fields:
            self.assertIn(field, response.data)

    def test_both_fields_are_required(self):
        self._refused(self._put({}), 'title', 'content')
        self._refused(self._put({'title': 'Only a title'}), 'content')
        self._refused(self._put({'content': '<p>Only a body</p>'}), 'title')

    def test_a_blank_title_is_refused(self):
        for blank in ('', '   ', '\n\t'):
            with self.subTest(title=blank):
                self._refused(self._put(title=blank), 'title')

    def test_null_is_refused(self):
        self._refused(self._put(title=None), 'title')
        self._refused(self._put(content=None), 'content')

    def test_blank_content_is_refused(self):
        for blank in ('', '   ', '\n'):
            with self.subTest(content=blank):
                self._refused(self._put(content=blank), 'content')

    def test_content_that_shows_nothing_is_refused(self):
        # What the rich-text editor writes when it is empty, and its cousins.
        for empty in (
            '<p><br></p>',
            '<p></p>',
            '<p>&nbsp;</p>',
            '<p>\xa0</p><p> </p>',
            '<h2> </h2><ul><li></li></ul>',
            '<!-- nothing -->',
        ):
            with self.subTest(content=empty):
                self._refused(self._put(content=empty), 'content')

    def test_content_that_only_looks_like_tags_but_has_text_is_accepted(self):
        self.assertEqual(self._put(content='a < b and c > d').status_code, 200)

    def test_content_with_an_image_or_break_and_text_is_accepted(self):
        self.assertEqual(self._put(content='<p>Hello<br>world</p>').status_code, 200)

    def test_a_title_that_is_too_long_is_refused(self):
        self._refused(self._put(title='t' * (MAX_TITLE_LENGTH + 1)), 'title')

    def test_content_that_is_too_long_is_refused(self):
        self._refused(self._put(content='c' * (MAX_CONTENT_LENGTH + 1)), 'content')

    def test_a_refused_write_leaves_the_policy_as_it_was(self):
        self._written(title='Good policy', content='<p>Good</p>')

        self._refused(self._put(title='Replaced', content='<p><br></p>'), 'content')

        policy = PrivacyPolicy.current()
        self.assertEqual(policy.title, 'Good policy')
        self.assertEqual(policy.content, '<p>Good</p>')

    def test_a_body_that_is_not_json_is_refused(self):
        response = self.client.put(
            reverse('admin-privacy-policy'), 'title=Nope&content=<p>x</p>',
            content_type='application/x-www-form-urlencoded',
        )

        self.assertEqual(response.status_code, 415)
        self.assertFalse(PrivacyPolicy.objects.exists())

    def test_json_that_is_not_an_object_is_a_400_not_a_500(self):
        for body in ('[]', '"text"', '5'):
            with self.subTest(body=body):
                response = self.client.put(
                    reverse('admin-privacy-policy'), body, content_type='application/json',
                )
                self.assertEqual(response.status_code, 400)


class VisibleTextTests(PolicyTestCase):
    def test_it_is_what_a_reader_would_see(self):
        self.assertEqual(visible_text('<p>Hello <b>world</b></p>'), 'Hello world')
        self.assertEqual(visible_text('<p>a &amp; b</p>'), 'a & b')

    def test_blanks_of_every_kind_are_nothing(self):
        for blank in ('', ' ', '<p></p>', '<p>&nbsp;</p>', '<br>', '<p>\xa0</p>'):
            with self.subTest(markup=blank):
                self.assertEqual(visible_text(blank), '')


class OneDocumentTests(PolicyTestCase):
    def test_the_document_always_has_the_same_id(self):
        PrivacyPolicy(title='One', content='<p>x</p>').save()

        self.assertEqual(list(PrivacyPolicy.objects.values_list('pk', flat=True)), [1])

    def test_saving_a_new_instance_edits_the_one_document(self):
        PrivacyPolicy(title='One', content='<p>x</p>').save()

        PrivacyPolicy(title='Two', content='<p>y</p>').save()

        self.assertEqual(PrivacyPolicy.objects.count(), 1)
        self.assertEqual(PrivacyPolicy.current().title, 'Two')

    def test_the_database_refuses_a_second_row(self):
        PrivacyPolicy(title='One', content='<p>x</p>').save()

        with self.assertRaises(IntegrityError), transaction.atomic():
            PrivacyPolicy.objects.bulk_create([
                PrivacyPolicy(pk=2, title='Two', content='<p>y</p>'),
            ])

        self.assertEqual(PrivacyPolicy.objects.count(), 1)

    def test_current_is_none_until_one_is_written(self):
        self.assertIsNone(PrivacyPolicy.current())

        self._written()

        self.assertEqual(PrivacyPolicy.current().title, BODY['title'])

    def test_deleting_the_account_that_saved_it_keeps_the_policy(self):
        self._written()

        self.admin.delete()

        policy = PrivacyPolicy.current()
        self.assertIsNotNone(policy)
        self.assertIsNone(policy.updated_by)
        self.client.force_authenticate(self.customer)
        self.assertEqual(self._get().data['title'], BODY['title'])


class AdminSiteTests(PolicyTestCase):
    """The Django admin screen - a second way to write the same document."""

    def setUp(self):
        super().setUp()
        self.superuser = User.objects.create_superuser('root@example.com', 'pw-9')
        self.client.force_login(self.superuser)

    def test_it_can_be_added_when_there_is_none(self):
        response = self.client.get('/admin/policies/privacypolicy/add/')

        self.assertEqual(response.status_code, 200)

    def test_it_cannot_be_added_once_there_is_one(self):
        self._written()

        response = self.client.get('/admin/policies/privacypolicy/add/')

        self.assertEqual(response.status_code, 403)

    def test_it_cannot_be_deleted(self):
        policy = self._written()

        response = self.client.post(
            f'/admin/policies/privacypolicy/{policy.pk}/delete/', {'post': 'yes'},
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(PrivacyPolicy.objects.exists())

    def test_it_lists_and_opens(self):
        policy = self._written()

        self.assertEqual(self.client.get('/admin/policies/privacypolicy/').status_code, 200)
        self.assertEqual(
            self.client.get(f'/admin/policies/privacypolicy/{policy.pk}/change/').status_code, 200,
        )

    def test_an_edit_there_records_who_made_it(self):
        policy = self._written()

        response = self.client.post(
            f'/admin/policies/privacypolicy/{policy.pk}/change/',
            {'title': 'Edited in the admin', 'content': '<p>New</p>'},
        )

        self.assertEqual(response.status_code, 302)
        policy = PrivacyPolicy.current()
        self.assertEqual(policy.title, 'Edited in the admin')
        self.assertEqual(policy.updated_by, self.superuser)
