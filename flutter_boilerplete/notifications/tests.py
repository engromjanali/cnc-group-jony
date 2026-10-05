from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from firebase_admin import exceptions as firebase_exceptions
from rest_framework.test import APITestCase

from accounts import firebase

from .limits import MAX_BODY_LENGTH, MAX_TITLE_LENGTH
from .models import Notification
from .push import ADMIN_NOTIFICATION, ALL_USERS_TOPIC, PushUnavailable, send_to_all_users

User = get_user_model()

BODY = {'title': 'New designs', 'body': 'Fresh door panels were just published.'}

SEND = 'notifications.views.send_to_all_users'


class NotificationTestCase(APITestCase):
    """An admin, a customer, and a helper to send - what every test here
    starts from. Has no tests itself."""

    def setUp(self):
        self.admin = User.objects.create_user('admin@example.com', 'pw-1', is_staff=True)
        self.customer = User.objects.create_user('customer@example.com', 'pw-2')
        self.client.force_authenticate(self.admin)

    def _send(self, **fields):
        return self.client.post(
            reverse('admin-notification-send'), {**BODY, **fields}, format='json',
        )


class AccessTests(NotificationTestCase):
    def test_list_needs_a_login(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(reverse('notification-list')).status_code, 401)

    def test_list_is_paginated_and_does_not_expose_the_sender(self):
        Notification.objects.bulk_create([
            Notification(title=str(index), body='News', sent_by=self.admin)
            for index in range(21)
        ])
        self.client.force_authenticate(self.customer)
        response = self.client.get(reverse('notification-list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 21)
        self.assertEqual(len(response.data['results']), 20)
        self.assertIsNotNone(response.data['next'])
        self.assertEqual(response.data['results'][0]['title'], '20')
        self.assertEqual(set(response.data['results'][0]), {'id', 'title', 'body', 'created_at'})
        second = self.client.get(reverse('notification-list'), {'page': 2})
        self.assertEqual(len(second.data['results']), 1)

    def test_a_customer_cannot_send(self):
        self.client.force_authenticate(self.customer)

        with patch(SEND) as send:
            self.assertEqual(self._send().status_code, 403)
        send.assert_not_called()
        self.assertFalse(Notification.objects.exists())

    def test_reading_needs_a_login(self):
        notification = Notification.objects.create(**BODY)
        self.client.force_authenticate(None)

        response = self.client.get(reverse('notification-detail', args=[notification.pk]))

        self.assertEqual(response.status_code, 401)

    def test_any_signed_in_user_can_read_one(self):
        notification = Notification.objects.create(**BODY)
        self.client.force_authenticate(self.customer)

        response = self.client.get(reverse('notification-detail', args=[notification.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['title'], BODY['title'])
        self.assertEqual(response.data['body'], BODY['body'])

    def test_an_unknown_id_is_a_404(self):
        self.assertEqual(
            self.client.get(reverse('notification-detail', args=[999])).status_code, 404,
        )


class SendTests(NotificationTestCase):
    def test_saves_and_pushes_it(self):
        with patch(SEND, return_value='projects/p/messages/1') as send:
            response = self._send()

        self.assertEqual(response.status_code, 201, response.data)
        notification = Notification.objects.get(pk=response.data['id'])
        self.assertEqual(notification.title, BODY['title'])
        self.assertEqual(notification.sent_by, self.admin)
        send.assert_called_once_with(notification)

    def test_trims_and_refuses_blanks(self):
        with patch(SEND):
            response = self._send(title='  Hello  ')
            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual(response.data['title'], 'Hello')

            self.assertEqual(self._send(title='   ').status_code, 400)
            self.assertEqual(self._send(body='').status_code, 400)

    def test_refuses_too_long(self):
        with patch(SEND) as send:
            self.assertEqual(self._send(title='x' * (MAX_TITLE_LENGTH + 1)).status_code, 400)
            self.assertEqual(self._send(body='x' * (MAX_BODY_LENGTH + 1)).status_code, 400)
        send.assert_not_called()

    def test_nothing_is_saved_when_the_push_fails(self):
        with patch(SEND, side_effect=PushUnavailable('down')):
            response = self._send()

        self.assertEqual(response.status_code, 503)
        self.assertFalse(Notification.objects.exists())


class PushTests(NotificationTestCase):
    def setUp(self):
        super().setUp()
        self.notification = Notification.objects.create(**BODY)

    def test_sends_to_the_all_users_topic_with_the_id(self):
        with patch.object(firebase, 'firebase_app', return_value=object()), \
                patch('notifications.push.messaging.send', return_value='id-1') as send:
            self.assertEqual(send_to_all_users(self.notification), 'id-1')

        message = send.call_args.args[0]
        self.assertEqual(ALL_USERS_TOPIC, 'all-user')
        self.assertEqual(message.topic, ALL_USERS_TOPIC)
        self.assertEqual(message.notification.title, BODY['title'])
        self.assertEqual(message.notification.body, BODY['body'])
        self.assertEqual(
            message.data,
            {'type': ADMIN_NOTIFICATION, 'notification_id': str(self.notification.pk)},
        )

    def test_not_configured_is_push_unavailable(self):
        with patch.object(
            firebase, 'firebase_app', side_effect=firebase.FirebaseNotConfigured('no key'),
        ), self.assertLogs('notifications.push', 'ERROR'):
            with self.assertRaises(PushUnavailable):
                send_to_all_users(self.notification)

    def test_multibyte_push_is_bounded_but_saved_body_stays_complete(self):
        self.notification.body = '\U0001f680' * 1000
        self.notification.save()
        with patch.object(firebase, 'firebase_app', return_value=object()), \
                patch('notifications.push.messaging.send', return_value='id-1') as send:
            send_to_all_users(self.notification)
        body = send.call_args.args[0].notification.body
        self.assertLessEqual(len(body.encode('utf-8')), 2500)
        self.assertEqual(Notification.objects.get(pk=self.notification.pk).body, self.notification.body)

    def test_a_firebase_error_is_push_unavailable(self):
        error = firebase_exceptions.UnavailableError('down')
        with patch.object(firebase, 'firebase_app', return_value=object()), \
                patch('notifications.push.messaging.send', side_effect=error), \
                self.assertLogs('notifications.push', 'ERROR'):
            with self.assertRaises(PushUnavailable):
                send_to_all_users(self.notification)
