from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from .models import StoredFile
from .validators import MAX_FILE_BYTES, build_object_key, sanitize_file_name

User = get_user_model()


class ObjectKeyTests(APITestCase):
    def test_key_is_namespaced_per_user_and_unique(self):
        first = build_object_key(7, 'panel.dxf')
        second = build_object_key(7, 'panel.dxf')
        self.assertTrue(first.startswith('users/7/'))
        self.assertTrue(first.endswith('-panel.dxf'))
        self.assertNotEqual(first, second)

    def test_traversal_and_unsafe_characters_are_stripped(self):
        self.assertEqual(sanitize_file_name('../../etc/passwd'), 'passwd')
        self.assertEqual(sanitize_file_name('my design (1).dxf'), 'my-design-1-.dxf')


class StorageEndpointTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user('owner@example.com', 'pw-for-tests-1')
        self.other = User.objects.create_user('other@example.com', 'pw-for-tests-2')

    def test_every_endpoint_requires_authentication(self):
        self.assertEqual(self.client.post(reverse('file-upload-url')).status_code, 401)
        self.assertEqual(
            self.client.post(reverse('cloudinary-upload-signature')).status_code, 401,
        )

    @patch('storage.views.r2.presigned_put_url', return_value='https://r2.example/put')
    def test_upload_url_creates_pending_row_with_server_generated_key(self, _presign):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            reverse('file-upload-url'),
            {'fileName': 'panel.dxf', 'contentType': 'application/dxf', 'size': 2048},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        stored_file = StoredFile.objects.get(pk=response.data['fileId'])
        self.assertEqual(stored_file.status, StoredFile.Status.PENDING)
        self.assertTrue(stored_file.key.startswith(f'users/{self.owner.id}/'))

    def test_upload_url_rejects_disallowed_content_type(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            reverse('file-upload-url'),
            {'fileName': 'evil.exe', 'contentType': 'application/x-msdownload', 'size': 10},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(StoredFile.objects.exists())

    def test_upload_url_rejects_oversized_file(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            reverse('file-upload-url'),
            {
                'fileName': 'panel.dxf',
                'contentType': 'application/dxf',
                'size': MAX_FILE_BYTES + 1,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    @patch('storage.views.r2.delete_object')
    @patch('storage.views.r2.head_object', return_value={'ContentLength': 1024})
    def test_confirm_marks_ready(self, _head, _delete):
        stored_file = self._pending_file(self.owner)
        self.client.force_authenticate(self.owner)

        response = self.client.post(reverse('file-confirm', args=[stored_file.id]))

        self.assertEqual(response.status_code, 200)
        stored_file.refresh_from_db()
        self.assertEqual(stored_file.status, StoredFile.Status.READY)
        self.assertEqual(stored_file.size, 1024)

    @patch('storage.views.r2.head_object', return_value=None)
    def test_confirm_drops_record_when_object_missing(self, _head):
        stored_file = self._pending_file(self.owner)
        self.client.force_authenticate(self.owner)

        response = self.client.post(reverse('file-confirm', args=[stored_file.id]))

        self.assertEqual(response.status_code, 400)
        self.assertFalse(StoredFile.objects.filter(pk=stored_file.id).exists())

    @patch('storage.views.r2.delete_object')
    @patch(
        'storage.views.r2.head_object',
        return_value={'ContentLength': MAX_FILE_BYTES + 1},
    )
    def test_confirm_deletes_object_that_exceeds_the_limit(self, _head, delete_object):
        stored_file = self._pending_file(self.owner)
        self.client.force_authenticate(self.owner)

        response = self.client.post(reverse('file-confirm', args=[stored_file.id]))

        self.assertEqual(response.status_code, 400)
        delete_object.assert_called_once_with(stored_file.key)
        self.assertFalse(StoredFile.objects.filter(pk=stored_file.id).exists())

    @patch('storage.views.r2.presigned_get_url', return_value='https://r2.example/get')
    def test_download_url_is_denied_for_another_user(self, _presign):
        stored_file = self._pending_file(self.owner, status=StoredFile.Status.READY)
        self.client.force_authenticate(self.other)

        response = self.client.get(reverse('file-download-url', args=[stored_file.id]))

        self.assertEqual(response.status_code, 404)

    @patch('storage.views.r2.delete_object')
    def test_delete_is_denied_for_another_user(self, delete_object):
        stored_file = self._pending_file(self.owner)
        self.client.force_authenticate(self.other)

        response = self.client.delete(reverse('file-delete', args=[stored_file.id]))

        self.assertEqual(response.status_code, 404)
        delete_object.assert_not_called()
        self.assertTrue(StoredFile.objects.filter(pk=stored_file.id).exists())

    def _pending_file(self, owner, status=StoredFile.Status.PENDING):
        return StoredFile.objects.create(
            owner=owner,
            key=build_object_key(owner.id, 'panel.dxf'),
            original_name='panel.dxf',
            content_type='application/dxf',
            size=2048,
            status=status,
        )
