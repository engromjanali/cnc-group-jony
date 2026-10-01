from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from .limits import MAX_ANSWER_LENGTH, MAX_QUESTION_LENGTH
from .models import Faq


User = get_user_model()

BODY = {
    'question': 'How do I download a design?',
    'answer': 'Open the design and tap Download.',
}


class FaqTestCase(APITestCase):
    """An admin, a customer, and helpers for the endpoints - what every test
    here starts from. Has no tests itself."""

    def setUp(self):
        self.admin = User.objects.create_user('admin@example.com', 'pw-1', is_staff=True)
        self.customer = User.objects.create_user('customer@example.com', 'pw-2')
        self.client.force_authenticate(self.admin)

    def _add(self, **fields):
        return self.client.post(reverse('admin-faq-add'), {**BODY, **fields}, format='json')

    def _added(self, **fields):
        response = self._add(**fields)
        self.assertEqual(response.status_code, 201, response.data)
        return Faq.objects.get(pk=response.data['id'])

    def _questions(self, url_name):
        return [faq['question'] for faq in self.client.get(reverse(url_name)).data]


class AccessTests(FaqTestCase):
    def test_reading_needs_a_login(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(reverse('faq-list')).status_code, 401)

    def test_any_signed_in_user_can_read_the_list(self):
        self._added()
        self.client.force_authenticate(self.customer)

        response = self.client.get(reverse('faq-list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_a_customer_cannot_use_the_admin_endpoints(self):
        faq = self._added()
        self.client.force_authenticate(self.customer)

        self.assertEqual(self.client.get(reverse('admin-faq-list')).status_code, 403)
        self.assertEqual(self._add().status_code, 403)
        self.assertEqual(
            self.client.patch(
                reverse('admin-faq-update', args=[faq.pk]), {'question': 'Defaced'}, format='json',
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.delete(reverse('admin-faq-delete', args=[faq.pk])).status_code, 403,
        )
        faq.refresh_from_db()
        self.assertEqual(faq.question, BODY['question'])
        self.assertEqual(Faq.objects.count(), 1)


class ListTests(FaqTestCase):
    def test_ordered_by_order_then_oldest_first(self):
        self._added(question='Second', order=1)
        self._added(question='Third', order=1)
        self._added(question='First', order=0)

        self.assertEqual(self._questions('faq-list'), ['First', 'Second', 'Third'])

    def test_switched_off_faqs_are_hidden_from_the_app_but_not_the_admin(self):
        self._added(question='Shown')
        self._added(question='Hidden', is_active=False)

        self.assertEqual(self._questions('faq-list'), ['Shown'])
        self.assertEqual(self._questions('admin-faq-list'), ['Shown', 'Hidden'])

    def test_shape(self):
        self._added()

        faq = self.client.get(reverse('faq-list')).data[0]

        self.assertEqual(
            set(faq), {'id', 'question', 'answer', 'order', 'is_active', 'updated_at'},
        )


class AddTests(FaqTestCase):
    def test_defaults(self):
        faq = self._added()

        self.assertEqual(faq.order, 0)
        self.assertTrue(faq.is_active)

    def test_question_and_answer_are_required_and_not_blank(self):
        for field in ('question', 'answer'):
            for value in (None, '', '   '):
                with self.subTest(field=field, value=value):
                    body = {**BODY, field: value}
                    if value is None:
                        del body[field]
                    response = self.client.post(reverse('admin-faq-add'), body, format='json')
                    self.assertEqual(response.status_code, 400)
                    self.assertIn(field, response.data)
        self.assertFalse(Faq.objects.exists())

    def test_whitespace_is_trimmed(self):
        faq = self._added(question='  Why?  ', answer='\nBecause.\n')

        self.assertEqual(faq.question, 'Why?')
        self.assertEqual(faq.answer, 'Because.')

    def test_length_limits(self):
        self.assertEqual(self._add(question='q' * (MAX_QUESTION_LENGTH + 1)).status_code, 400)
        self.assertEqual(self._add(answer='a' * (MAX_ANSWER_LENGTH + 1)).status_code, 400)
        self._added(question='q' * MAX_QUESTION_LENGTH, answer='a' * MAX_ANSWER_LENGTH)

    def test_order_cannot_be_negative(self):
        self.assertEqual(self._add(order=-1).status_code, 400)


class UpdateAndDeleteTests(FaqTestCase):
    def test_patch_changes_only_what_is_sent(self):
        faq = self._added(order=3)

        response = self.client.patch(
            reverse('admin-faq-update', args=[faq.pk]), {'is_active': False}, format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        faq.refresh_from_db()
        self.assertFalse(faq.is_active)
        self.assertEqual(faq.order, 3)
        self.assertEqual(faq.question, BODY['question'])

    def test_put_replaces_the_faq(self):
        faq = self._added()

        response = self.client.put(
            reverse('admin-faq-update', args=[faq.pk]),
            {'question': 'New?', 'answer': 'New.', 'order': 2},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        faq.refresh_from_db()
        self.assertEqual((faq.question, faq.answer, faq.order), ('New?', 'New.', 2))

    def test_delete(self):
        faq = self._added()

        response = self.client.delete(reverse('admin-faq-delete', args=[faq.pk]))

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Faq.objects.exists())

    def test_unknown_id_is_404(self):
        self.assertEqual(
            self.client.patch(reverse('admin-faq-update', args=[999]), BODY, format='json').status_code,
            404,
        )
        self.assertEqual(self.client.delete(reverse('admin-faq-delete', args=[999])).status_code, 404)
