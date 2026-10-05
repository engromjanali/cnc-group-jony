"""Sending a notification to every user's phone through Firebase Cloud
Messaging.

The app subscribes to `ALL_USERS_TOPIC` when a user signs in, so one message
to the topic reaches every signed-in phone - no device tokens are stored here.
"""
import logging

from firebase_admin import exceptions as firebase_exceptions
from firebase_admin import messaging

from accounts import firebase

logger = logging.getLogger(__name__)

# Must match the topic the app subscribes to.
ALL_USERS_TOPIC = 'all-user'

# Tells the app what a tapped push is about, so it opens the right screen.
ADMIN_NOTIFICATION = 'admin_notification'


class PushUnavailable(Exception):
    """The push could not be sent: no service account, or Firebase refused or
    could not be reached. A server problem, not the admin's."""


def send_to_all_users(notification):
    """Pushes `notification` to the all-users topic. Returns FCM's message id,
    or raises `PushUnavailable`."""
    try:
        app = firebase.firebase_app()
    except firebase.FirebaseNotConfigured as error:
        logger.error('Push notifications are not configured', exc_info=True)
        raise PushUnavailable(str(error)) from error

    message = messaging.Message(
        topic=ALL_USERS_TOPIC,
        notification=messaging.Notification(
            title=notification.title,
            body=notification.body.encode('utf-8')[:2500].decode('utf-8', errors='ignore'),
        ),
        # Data values must be strings.
        data={'type': ADMIN_NOTIFICATION, 'notification_id': str(notification.pk)},
        android=messaging.AndroidConfig(priority='high'),
        apns=messaging.APNSConfig(payload=messaging.APNSPayload(aps=messaging.Aps(sound='default'))),
    )
    try:
        return messaging.send(message, app=app)
    except (firebase_exceptions.FirebaseError, ValueError, OSError) as error:
        logger.exception('Firebase could not send a notification')
        raise PushUnavailable('Could not reach Firebase to send the notification.') from error
