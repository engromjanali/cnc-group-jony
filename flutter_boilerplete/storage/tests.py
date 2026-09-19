import io
import itertools
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework.test import APITestCase

from designs.models import Category, Design

from . import config
from .cleanup import run_cleanup
from .models import StoredFile
from .services import UploadedObject
from .validators import build_object_key, sanitize_file_name

User = get_user_model()

DXF_BYTES = b'0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n'


def _image_file(name='preview.png', image_format='PNG', size=(8, 8)):
    buffer = io.BytesIO()
    Image.new('RGB', size, (0, 128, 128)).save(buffer, format=image_format)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=f'image/{image_format.lower()}')


def _dxf_file(name='07 E.dxf', content=DXF_BYTES, content_type='application/dxf'):
    return SimpleUploadedFile(name, content, content_type=content_type)


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


class _FakeProviders:
    """Stands in for Cloudinary and R2, recording every call."""

    def __init__(self):
        self.stored = []
        self.deleted = []
        self.fail_on = None  # provider name whose store() should raise
        self._ids = itertools.count()

    def service(self, provider):
        service = MagicMock()

        def store(file, *, owner_id, file_name, content_type):
            if self.fail_on == provider:
                raise RuntimeError(f'{provider} is down')
            data = file.read()
            key = (
                f'users/{owner_id}/images/{next(self._ids)}' if provider == 'cloudinary'
                else build_object_key(owner_id, file_name)
            )
            self.stored.append((provider, key, len(data), content_type))
            return UploadedObject(storage_key=key, size=len(data), content_type=content_type)

        service.store.side_effect = store
        service.delete.side_effect = lambda key: self.deleted.append((provider, key))
        service.url_for.return_value = f'https://{provider}.example/signed'
        return service


class _ProvidersMixin:
    def setUp(self):
        super().setUp()
        self.providers = _FakeProviders()
        patcher = patch(
            'storage.uploads.get_storage_service', side_effect=self.providers.service,
        )
        patcher.start()
        self.addCleanup(patcher.stop)


@override_settings(CLOUDINARY_CLOUD_NAME='demo-cloud')
class AddDesignTests(_ProvidersMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user('admin@example.com', 'pw-1', is_staff=True)
        self.customer = User.objects.create_user('customer@example.com', 'pw-3')
        self.category = Category.objects.create(label='Panels')
        self.client.force_authenticate(self.admin)

    def _add(self, **overrides):
        data = {
            'category': self.category.id,
            'title': 'Panel',
            'image': _image_file(),
            'design_file': _dxf_file(),
            **overrides,
        }
        data = {key: value for key, value in data.items() if value is not None}
        return self.client.post(reverse('admin-design-add'), data, format='multipart')

    def test_one_request_stores_both_files_and_creates_the_design(self):
        response = self._add(description='Cut list')

        self.assertEqual(response.status_code, 201, response.data)
        design = Design.objects.get(pk=response.data['id'])
        self.assertEqual(design.image_file.provider, StoredFile.Provider.CLOUDINARY)
        self.assertEqual(design.design_stored_file.provider, StoredFile.Provider.R2)
        self.assertEqual(design.design_stored_file.status, StoredFile.Status.READY)
        self.assertEqual(design.design_file_name, '07 E.dxf')
        self.assertTrue(design.design_stored_file.storage_key.startswith(f'users/{self.admin.id}/'))

        providers = [entry[0] for entry in self.providers.stored]
        self.assertEqual(sorted(providers), ['cloudinary', 'r2'])
        r2_entry = next(e for e in self.providers.stored if e[0] == 'r2')
        self.assertEqual(r2_entry[2], len(DXF_BYTES))

    def test_response_has_a_display_url_but_no_permanent_file_url(self):
        response = self._add()

        self.assertIn('res.cloudinary.com/demo-cloud', response.data['image_url'])
        self.assertIsNone(response.data['design_file_url'])
        self.assertTrue(response.data['has_design_file'])
        # Nothing was written to the server's own disk.
        design = Design.objects.get(pk=response.data['id'])
        self.assertFalse(design.image)
        self.assertFalse(design.design_file)

    def test_a_design_without_a_cutting_file_is_allowed(self):
        response = self._add(design_file=None)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(response.data['has_design_file'])

    def test_requires_an_image(self):
        response = self._add(image=None)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.providers.stored, [])

    def test_non_staff_users_cannot_add(self):
        self.client.force_authenticate(self.customer)
        self.assertEqual(self._add().status_code, 403)
        self.assertEqual(self.providers.stored, [])

    def test_rejects_something_that_is_not_an_image(self):
        fake = SimpleUploadedFile('preview.png', b'not really a png', content_type='image/png')
        response = self._add(image=fake)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.providers.stored, [])

    def test_rejects_an_image_format_outside_the_allowlist(self):
        response = self._add(image=_image_file('preview.bmp', image_format='BMP'))
        self.assertEqual(response.status_code, 400)
        self.assertIn('image', response.data)
        self.assertEqual(self.providers.stored, [])

    def test_rejects_a_design_file_with_a_disallowed_extension(self):
        response = self._add(design_file=_dxf_file('evil.exe', content_type='application/x-msdownload'))
        self.assertEqual(response.status_code, 400)
        self.assertIn('design_file', response.data)
        self.assertEqual(self.providers.stored, [])

    def test_unknown_content_type_is_stored_as_octet_stream_when_the_extension_is_fine(self):
        response = self._add(design_file=_dxf_file(content_type='text/plain'))
        self.assertEqual(response.status_code, 201, response.data)
        r2_entry = next(e for e in self.providers.stored if e[0] == 'r2')
        self.assertEqual(r2_entry[3], 'application/octet-stream')

    def test_rejects_files_over_the_combined_size_limit(self):
        big = _dxf_file(content=b'x' * (config.MAX_DESIGN_UPLOAD_BYTES + 1))
        response = self._add(design_file=big)

        self.assertEqual(response.status_code, 400)
        self.assertIn('limit', str(response.data))
        self.assertEqual(self.providers.stored, [])

    def test_a_failure_after_the_image_uploaded_removes_the_image(self):
        self.providers.fail_on = 'r2'

        with self.assertRaises(RuntimeError):
            self._add()

        self.assertEqual([provider for provider, *_ in self.providers.stored], ['cloudinary'])
        self.assertEqual(len(self.providers.deleted), 1)
        self.assertEqual(self.providers.deleted[0][0], 'cloudinary')
        self.assertFalse(StoredFile.objects.exists())
        self.assertFalse(Design.objects.exists())

    def test_a_failed_design_save_removes_both_uploads(self):
        with patch('designs.serializers.Design.objects.create', side_effect=RuntimeError('db down')):
            with self.assertRaises(RuntimeError):
                self._add()

        self.assertEqual(len(self.providers.stored), 2)
        self.assertEqual(sorted(p for p, _ in self.providers.deleted), ['cloudinary', 'r2'])
        self.assertFalse(StoredFile.objects.exists())

    def test_missing_provider_credentials_are_a_503_not_a_500(self):
        with patch(
            'storage.uploads.get_storage_service',
            side_effect=ImproperlyConfigured('not configured'),
        ):
            response = self._add()
        self.assertEqual(response.status_code, 503)


class UpdateAndDeleteDesignTests(_ProvidersMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user('admin@example.com', 'pw-1', is_staff=True)
        self.category = Category.objects.create(label='Panels')
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            reverse('admin-design-add'),
            {
                'category': self.category.id,
                'title': 'Panel',
                'image': _image_file(),
                'design_file': _dxf_file(),
            },
            format='multipart',
        )
        self.design = Design.objects.get(pk=response.data['id'])
        self.old_image = self.design.image_file
        self.old_file = self.design.design_stored_file
        self.providers.stored.clear()

    def _patch(self, **data):
        return self.client.patch(
            reverse('admin-design-update', args=[self.design.id]), data, format='multipart',
        )

    def test_editing_text_leaves_the_files_untouched(self):
        response = self._patch(title='Renamed')

        self.assertEqual(response.status_code, 200, response.data)
        self.design.refresh_from_db()
        self.assertEqual(self.design.title, 'Renamed')
        self.assertEqual(self.design.image_file, self.old_image)
        self.assertEqual(self.providers.stored, [])
        self.assertEqual(self.providers.deleted, [])

    def test_replacing_a_file_removes_the_old_one_after_saving(self):
        response = self._patch(design_file=_dxf_file('new.dxf', content=b'0\nEOF\n'))

        self.assertEqual(response.status_code, 200, response.data)
        self.design.refresh_from_db()
        self.assertNotEqual(self.design.design_stored_file, self.old_file)
        self.assertEqual(self.design.design_file_name, 'new.dxf')
        self.assertEqual(self.providers.deleted, [('r2', self.old_file.storage_key)])
        self.assertFalse(StoredFile.objects.filter(pk=self.old_file.pk).exists())
        self.assertTrue(StoredFile.objects.filter(pk=self.old_image.pk).exists())

    def test_a_failed_replacement_keeps_the_old_file_and_removes_the_new_one(self):
        with patch.object(
            type(self.design), 'save', side_effect=RuntimeError('db down'),
        ):
            with self.assertRaises(RuntimeError):
                self._patch(image=_image_file('other.png'))

        self.design.refresh_from_db()
        self.assertEqual(self.design.image_file, self.old_image)
        self.assertEqual([p for p, *_ in self.providers.stored], ['cloudinary'])
        self.assertEqual([p for p, _ in self.providers.deleted], ['cloudinary'])
        self.assertTrue(StoredFile.objects.filter(pk=self.old_image.pk).exists())

    def test_deleting_a_design_removes_its_files_from_storage(self):
        response = self.client.delete(reverse('admin-design-delete', args=[self.design.id]))

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Design.objects.exists())
        self.assertFalse(StoredFile.objects.exists())
        self.assertEqual(
            sorted(self.providers.deleted),
            sorted([
                ('cloudinary', self.old_image.storage_key),
                ('r2', self.old_file.storage_key),
            ]),
        )


class DesignDownloadTests(APITestCase):
    """Any logged-in user gets a fresh signed link to a published design."""

    def setUp(self):
        self.admin = User.objects.create_user('admin@example.com', 'pw-1', is_staff=True)
        self.customer = User.objects.create_user('customer@example.com', 'pw-3')
        self.category = Category.objects.create(label='Panels')
        self.service = MagicMock()
        patcher = patch('designs.views.get_storage_service', return_value=self.service)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _design_with_r2_file(self):
        stored = StoredFile.objects.create(
            owner=self.admin,
            provider=StoredFile.Provider.R2,
            storage_key=build_object_key(self.admin.id, '07 E.dxf'),
            original_name='07 E.dxf',
            content_type='application/dxf',
            size=4096,
            status=StoredFile.Status.READY,
        )
        design = Design.objects.create(
            category=self.category,
            title='Panel',
            image_url='https://example.com/preview.png',
            design_stored_file=stored,
            design_file_name='07 E.dxf',
        )
        return design, stored

    def test_any_logged_in_user_gets_a_fresh_download_url(self):
        design, stored = self._design_with_r2_file()
        self.service.url_for.return_value = 'https://r2.example/signed-get'

        self.client.force_authenticate(self.customer)
        response = self.client.get(reverse('design-download-url', args=[design.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['downloadUrl'], 'https://r2.example/signed-get')
        self.assertEqual(response.data['fileName'], '07 E.dxf')
        self.assertEqual(response.data['expiresIn'], config.DOWNLOAD_URL_TTL_SECONDS)
        self.service.url_for.assert_called_once_with(stored.storage_key, download_name='07 E.dxf')

    def test_details_never_carry_a_presigned_url(self):
        design, _ = self._design_with_r2_file()
        self.client.force_authenticate(self.customer)

        detail = self.client.get(reverse('design-details', args=[design.id]))

        self.assertIsNone(detail.data['design_file_url'])
        self.assertTrue(detail.data['has_design_file'])

    def test_download_url_requires_login(self):
        design, _ = self._design_with_r2_file()
        response = self.client.get(reverse('design-download-url', args=[design.id]))
        self.assertEqual(response.status_code, 401)

    def test_design_without_a_file_has_no_download_url(self):
        design = Design.objects.create(
            category=self.category, title='Preview only', image_url='https://example.com/p.png',
        )
        self.client.force_authenticate(self.customer)
        response = self.client.get(reverse('design-download-url', args=[design.id]))
        self.assertEqual(response.status_code, 404)

    def test_legacy_design_file_url_is_returned_as_is(self):
        design = Design.objects.create(
            category=self.category,
            title='Legacy',
            image_url='https://example.com/p.png',
            design_file_url='https://legacy.example/old.dxf',
            design_file_name='old.dxf',
        )
        self.client.force_authenticate(self.customer)

        response = self.client.get(reverse('design-download-url', args=[design.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['downloadUrl'], 'https://legacy.example/old.dxf')
        self.assertIsNone(response.data['expiresIn'])
        self.service.url_for.assert_not_called()


class CleanupViewTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user('owner@example.com', 'pw-for-tests-1')

    def _file(self, minutes_old, provider=StoredFile.Provider.R2):
        stored_file = StoredFile.objects.create(
            owner=self.owner,
            provider=provider,
            storage_key=build_object_key(self.owner.id, 'x.dxf'),
            original_name='x.dxf',
            content_type='application/dxf',
            size=10,
            status=StoredFile.Status.READY,
        )
        StoredFile.objects.filter(pk=stored_file.pk).update(
            created_at=timezone.now() - timedelta(minutes=minutes_old),
        )
        return stored_file

    @override_settings(CRON_SECRET='')
    def test_disabled_without_a_configured_secret(self):
        response = self.client.get(reverse('storage-cleanup'), HTTP_AUTHORIZATION='Bearer anything')
        self.assertEqual(response.status_code, 401)

    @override_settings(CRON_SECRET='the-real-secret')
    def test_rejects_a_missing_or_wrong_secret(self):
        self.assertEqual(self.client.get(reverse('storage-cleanup')).status_code, 401)
        wrong = self.client.get(reverse('storage-cleanup'), HTTP_AUTHORIZATION='Bearer wrong')
        self.assertEqual(wrong.status_code, 401)

    @override_settings(CRON_SECRET='the-real-secret')
    @patch('storage.uploads.get_storage_service')
    def test_reclaims_only_old_files_that_no_design_uses(self, get_storage_service):
        service = MagicMock()
        get_storage_service.return_value = service
        stale = config.CLEANUP_MAX_AGE_MINUTES + 1

        old_orphan = self._file(stale)
        fresh_orphan = self._file(1)
        old_referenced = self._file(stale, provider=StoredFile.Provider.CLOUDINARY)
        category = Category.objects.create(label='Panels')
        Design.objects.create(category=category, title='Kept', image_file=old_referenced)

        response = self.client.get(
            reverse('storage-cleanup'), HTTP_AUTHORIZATION='Bearer the-real-secret',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'orphanedDeleted': 1})
        self.assertEqual(
            set(StoredFile.objects.values_list('id', flat=True)),
            {fresh_orphan.id, old_referenced.id},
        )
        service.delete.assert_called_once_with(old_orphan.storage_key)

    @override_settings(CRON_SECRET='the-real-secret')
    @patch('storage.uploads.get_storage_service')
    def test_a_provider_failure_does_not_stop_the_row_from_being_removed(self, get_storage_service):
        get_storage_service.return_value.delete.side_effect = Exception('boom')
        stale = self._file(config.CLEANUP_MAX_AGE_MINUTES + 1)

        response = self.client.get(
            reverse('storage-cleanup'), HTTP_AUTHORIZATION='Bearer the-real-secret',
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(StoredFile.objects.filter(pk=stale.pk).exists())

    def test_run_cleanup_is_directly_callable(self):
        self.assertEqual(run_cleanup(), {'orphanedDeleted': 0})
