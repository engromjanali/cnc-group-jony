import itertools
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from designs.models import Category
from storage import config as storage_config
from storage.cleanup import run_cleanup
from storage.models import StoredFile
from storage.tests import _image_file, _ProvidersMixin

from .limits import MAX_BANNERS, BannerLimitReached
from .models import Banner

User = get_user_model()


@override_settings(CLOUDINARY_CLOUD_NAME='demo-cloud')
class BannerTestCase(_ProvidersMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user('admin@example.com', 'pw-1', is_staff=True)
        self.customer = User.objects.create_user('customer@example.com', 'pw-3')
        self.client.force_authenticate(self.admin)
        self._keys = itertools.count()

    def _add(self, title='Eid sale', **overrides):
        data = {'title': title, 'image': _image_file(), **overrides}
        data = {key: value for key, value in data.items() if value is not None}
        return self.client.post(reverse('admin-banner-add'), data, format='multipart')

    def _patch(self, banner, **data):
        return self.client.patch(
            reverse('admin-banner-update', args=[banner.id]), data, format='multipart',
        )

    def _delete(self, banner):
        return self.client.delete(reverse('admin-banner-delete', args=[banner.id]))

    def _banner_via_api(self, title='Eid sale', **overrides):
        response = self._add(title, **overrides)
        self.assertEqual(response.status_code, 201, response.data)
        return Banner.objects.get(pk=response.data['id'])

    def _make(self, title='Sale', *, with_image=True, **fields):
        """A banner straight in the database, skipping the upload."""
        image = None
        if with_image:
            image = StoredFile.objects.create(
                owner=self.admin, provider=StoredFile.Provider.CLOUDINARY,
                storage_key=f'users/{self.admin.id}/images/seed-{next(self._keys)}',
                original_name='banner.png', content_type='image/png', size=1,
                status=StoredFile.Status.READY,
            )
        return Banner.objects.create(title=title, image_file=image, **fields)

    def _fill_to_the_cap(self, **fields):
        return [self._make(f'Banner {i}', **fields) for i in range(MAX_BANNERS)]


class AddBannerTests(BannerTestCase):
    def test_an_admin_adds_a_banner_with_its_image(self):
        response = self._add(cta_label='Shop now', priority=2)

        self.assertEqual(response.status_code, 201, response.data)
        banner = Banner.objects.get(pk=response.data['id'])
        self.assertEqual(banner.title, 'Eid sale')
        self.assertEqual(banner.cta_label, 'Shop now')
        self.assertEqual(banner.priority, 2)
        self.assertEqual(banner.image_file.provider, StoredFile.Provider.CLOUDINARY)
        self.assertEqual(banner.image_file.status, StoredFile.Status.READY)
        self.assertEqual([p[0] for p in self.providers.stored], ['cloudinary'])

        self.assertIn('demo-cloud', response.data['image_url'])
        self.assertIn(banner.image_file.storage_key, response.data['image_url'])
        self.assertEqual(response.data['status'], 'live')
        self.assertNotIn('image', response.data)

    def test_a_banner_is_active_and_labelled_by_default(self):
        # Sent as a form, an absent checkbox reads as "off" unless the field
        # says otherwise - this must not create switched-off banners.
        response = self._add()

        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data['is_active'])
        self.assertEqual(response.data['cta_label'], 'Try Now')
        self.assertIsNone(response.data['category'])
        self.assertIsNone(response.data['priority'])

    def test_a_banner_can_be_added_switched_off(self):
        response = self._add(is_active='false')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(response.data['is_active'])
        self.assertEqual(response.data['status'], 'inactive')

    def test_a_blank_button_label_is_allowed(self):
        response = self._add(cta_label='')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['cta_label'], '')

    def test_a_new_banner_needs_an_image(self):
        response = self._add(image=None)

        self.assertEqual(response.status_code, 400)
        self.assertIn('image', response.data)
        self.assertEqual(Banner.objects.count(), 0)

    def test_a_new_banner_needs_a_title(self):
        response = self._add(title='')
        self.assertEqual(response.status_code, 400)
        self.assertIn('title', response.data)
        self.assertEqual(self.providers.stored, [])

    def test_a_file_that_is_not_an_image_is_rejected(self):
        fake = SimpleUploadedFile('banner.png', b'not really a picture', content_type='image/png')
        response = self._add(image=fake)

        self.assertEqual(response.status_code, 400)
        self.assertIn('image', response.data)
        self.assertEqual(self.providers.stored, [])

    def test_an_image_over_the_upload_limit_is_rejected(self):
        with patch.object(storage_config, 'MAX_DESIGN_UPLOAD_BYTES', 10):
            response = self._add()

        self.assertEqual(response.status_code, 400)
        self.assertIn('image', response.data)
        self.assertEqual(self.providers.stored, [])

    def test_the_end_must_come_after_the_start(self):
        now = timezone.now()
        response = self._add(
            start_at=(now + timedelta(days=2)).isoformat(),
            end_at=(now + timedelta(days=1)).isoformat(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('end_at', response.data)
        self.assertEqual(self.providers.stored, [])

    def test_a_banner_can_lead_to_a_category(self):
        category = Category.objects.create(label='Beds')
        response = self._add(category=category.id)

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['category'], category.id)
        self.assertEqual(response.data['category_label'], 'Beds')

    def test_an_unknown_category_is_rejected(self):
        response = self._add(category=9999)
        self.assertEqual(response.status_code, 400)
        self.assertIn('category', response.data)

    def test_a_failed_save_removes_the_uploaded_image(self):
        with patch.object(Banner.objects, 'create', side_effect=RuntimeError('db down')):
            with self.assertRaises(RuntimeError):
                self._add()

        self.assertEqual(Banner.objects.count(), 0)
        self.assertEqual(StoredFile.objects.count(), 0)
        self.assertEqual([p for p, _ in self.providers.deleted], ['cloudinary'])

    def test_only_admins_can_add(self):
        self.client.force_authenticate(self.customer)
        self.assertEqual(self._add().status_code, 403)

        self.client.force_authenticate(None)
        self.assertEqual(self._add().status_code, 401)

        self.assertEqual(Banner.objects.count(), 0)
        self.assertEqual(self.providers.stored, [])


class BannerLimitTests(BannerTestCase):
    def test_the_last_free_slot_can_be_used(self):
        for i in range(MAX_BANNERS - 1):
            self._make(f'Banner {i}')

        self.assertEqual(self._add().status_code, 201)
        self.assertEqual(Banner.objects.count(), MAX_BANNERS)

    def test_a_banner_over_the_cap_is_refused_before_anything_is_uploaded(self):
        self._fill_to_the_cap()

        response = self._add()

        self.assertEqual(response.status_code, 409)
        self.assertIn(str(MAX_BANNERS), response.data['detail'])
        self.assertEqual(Banner.objects.count(), MAX_BANNERS)
        self.assertEqual(self.providers.stored, [])

    def test_switched_off_banners_still_count_toward_the_cap(self):
        self._fill_to_the_cap(is_active=False)
        self.assertEqual(self._add().status_code, 409)

    def test_losing_a_race_for_the_last_slot_discards_the_upload(self):
        # The early check passes, then another request takes the slot before
        # the locked check inside create() runs.
        with patch('banners.serializers.ensure_room', side_effect=[None, BannerLimitReached()]):
            response = self._add()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(Banner.objects.count(), 0)
        self.assertEqual(StoredFile.objects.count(), 0)
        self.assertEqual(len(self.providers.stored), 1)
        self.assertEqual([p for p, _ in self.providers.deleted], ['cloudinary'])

    def test_deleting_a_banner_frees_its_slot(self):
        banners = self._fill_to_the_cap()
        self.assertEqual(self._add().status_code, 409)

        self.assertEqual(self._delete(banners[0]).status_code, 204)

        self.assertEqual(self._add().status_code, 201)

    def test_a_full_set_can_still_be_edited(self):
        banners = self._fill_to_the_cap()
        response = self._patch(banners[0], title='Renamed')
        self.assertEqual(response.status_code, 200, response.data)


class EditBannerTests(BannerTestCase):
    def test_editing_keeps_the_image_when_none_is_sent(self):
        banner = self._banner_via_api()
        image = banner.image_file

        response = self._patch(banner, title='Ramadan sale', cta_label='View')

        self.assertEqual(response.status_code, 200, response.data)
        banner.refresh_from_db()
        self.assertEqual(banner.title, 'Ramadan sale')
        self.assertEqual(banner.cta_label, 'View')
        self.assertEqual(banner.image_file, image)
        self.assertEqual(len(self.providers.stored), 1)
        self.assertEqual(self.providers.deleted, [])

    def test_replacing_the_image_removes_the_old_one_after_saving(self):
        banner = self._banner_via_api()
        old = banner.image_file

        response = self._patch(banner, image=_image_file('new.png'))

        self.assertEqual(response.status_code, 200, response.data)
        banner.refresh_from_db()
        self.assertNotEqual(banner.image_file, old)
        self.assertEqual(self.providers.deleted, [('cloudinary', old.storage_key)])
        self.assertFalse(StoredFile.objects.filter(pk=old.pk).exists())

    def test_a_failed_replacement_keeps_the_old_image_and_removes_the_new_one(self):
        banner = self._banner_via_api()
        old = banner.image_file

        with patch.object(Banner, 'save', side_effect=RuntimeError('db down')):
            with self.assertRaises(RuntimeError):
                self._patch(banner, image=_image_file('new.png'))

        banner.refresh_from_db()
        self.assertEqual(banner.image_file, old)
        self.assertEqual(len(self.providers.stored), 2)
        self.assertEqual([p for p, _ in self.providers.deleted], ['cloudinary'])
        self.assertTrue(StoredFile.objects.filter(pk=old.pk).exists())

    def test_an_empty_value_clears_the_optional_fields(self):
        category = Category.objects.create(label='Beds')
        now = timezone.now()
        banner = self._banner_via_api(
            priority=4, category=category.id,
            start_at=(now - timedelta(days=1)).isoformat(),
            end_at=(now + timedelta(days=1)).isoformat(),
        )

        response = self._patch(banner, priority='', category='', start_at='', end_at='')

        self.assertEqual(response.status_code, 200, response.data)
        banner.refresh_from_db()
        self.assertIsNone(banner.priority)
        self.assertIsNone(banner.category)
        self.assertIsNone(banner.start_at)
        self.assertIsNone(banner.end_at)

    def test_a_banner_can_be_switched_off_and_on(self):
        banner = self._banner_via_api()

        off = self._patch(banner, is_active='false')
        self.assertEqual(off.status_code, 200, off.data)
        self.assertEqual(off.data['status'], 'inactive')

        on = self._patch(banner, is_active='true')
        self.assertEqual(on.data['status'], 'live')

    def test_the_schedule_is_checked_against_the_dates_already_saved(self):
        now = timezone.now()
        banner = self._banner_via_api(start_at=(now + timedelta(days=5)).isoformat())

        response = self._patch(banner, end_at=(now + timedelta(days=1)).isoformat())

        self.assertEqual(response.status_code, 400)
        self.assertIn('end_at', response.data)

    def test_editing_a_missing_banner_is_a_404(self):
        response = self.client.patch(
            reverse('admin-banner-update', args=[9999]), {'title': 'x'}, format='multipart',
        )
        self.assertEqual(response.status_code, 404)

    def test_only_admins_can_edit(self):
        banner = self._banner_via_api()
        self.client.force_authenticate(self.customer)

        self.assertEqual(self._patch(banner, title='Hijacked').status_code, 403)

        banner.refresh_from_db()
        self.assertEqual(banner.title, 'Eid sale')


class DeleteBannerTests(BannerTestCase):
    def test_deleting_removes_the_banner_and_its_image(self):
        banner = self._banner_via_api()
        image = banner.image_file

        response = self._delete(banner)

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Banner.objects.filter(pk=banner.pk).exists())
        self.assertFalse(StoredFile.objects.filter(pk=image.pk).exists())
        self.assertEqual(self.providers.deleted, [('cloudinary', image.storage_key)])

    def test_deleting_a_missing_banner_is_a_404(self):
        response = self.client.delete(reverse('admin-banner-delete', args=[9999]))
        self.assertEqual(response.status_code, 404)

    def test_only_admins_can_delete(self):
        banner = self._make()
        self.client.force_authenticate(self.customer)

        self.assertEqual(self._delete(banner).status_code, 403)

        self.assertTrue(Banner.objects.filter(pk=banner.pk).exists())

    def test_deleting_a_category_keeps_its_banners(self):
        category = Category.objects.create(label='Beds')
        banner = self._make(category=category)

        response = self.client.delete(reverse('admin-category-delete', args=[category.id]))

        self.assertEqual(response.status_code, 204)
        banner.refresh_from_db()
        self.assertIsNone(banner.category)


class ListBannerTests(BannerTestCase):
    def _titles(self, response):
        self.assertEqual(response.status_code, 200, response.data)
        return [item['title'] for item in response.data]

    def test_the_public_list_shows_only_banners_that_are_live_now(self):
        now = timezone.now()
        day = timedelta(days=1)
        self._make('Always on')
        self._make('In window', start_at=now - day, end_at=now + day)
        self._make('Switched off', is_active=False)
        self._make('Not yet', start_at=now + day)
        self._make('Over', end_at=now - day)
        self._make('No picture', with_image=False)
        self.client.force_authenticate(self.customer)

        response = self.client.get(reverse('banner-list'))

        self.assertEqual(sorted(self._titles(response)), ['Always on', 'In window'])

    def test_banners_are_ordered_by_priority_then_newest(self):
        self._make('Unranked, older')
        self._make('Second', priority=5)
        self._make('Unranked, newer')
        self._make('First', priority=1)
        self.client.force_authenticate(self.customer)

        response = self.client.get(reverse('banner-list'))

        self.assertEqual(
            self._titles(response),
            ['First', 'Second', 'Unranked, newer', 'Unranked, older'],
        )

    def test_the_public_list_carries_what_the_home_screen_needs(self):
        category = Category.objects.create(label='Beds')
        self._make('Sale', cta_label='Shop', category=category)
        self.client.force_authenticate(self.customer)

        item = self.client.get(reverse('banner-list')).data[0]

        self.assertEqual(item['title'], 'Sale')
        self.assertEqual(item['cta_label'], 'Shop')
        self.assertEqual(item['category'], category.id)
        self.assertIn('demo-cloud', item['image_url'])

    def test_the_public_list_needs_a_login(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(reverse('banner-list')).status_code, 401)

    def test_the_admin_list_has_every_banner_with_its_status(self):
        now = timezone.now()
        day = timedelta(days=1)
        self._make('Live')
        self._make('Off', is_active=False)
        self._make('Soon', start_at=now + day)
        self._make('Done', end_at=now - day)

        response = self.client.get(reverse('admin-banner-list'))

        self.assertEqual(response.status_code, 200, response.data)
        statuses = {item['title']: item['status'] for item in response.data}
        self.assertEqual(
            statuses,
            {'Live': 'live', 'Off': 'inactive', 'Soon': 'scheduled', 'Done': 'expired'},
        )

    def test_a_switched_off_banner_stays_inactive_whatever_its_schedule(self):
        now = timezone.now()
        self._make('Off and expired', is_active=False, end_at=now - timedelta(days=1))

        item = self.client.get(reverse('admin-banner-list')).data[0]

        self.assertEqual(item['status'], 'inactive')

    def test_the_admin_list_is_admin_only(self):
        self.client.force_authenticate(self.customer)
        self.assertEqual(self.client.get(reverse('admin-banner-list')).status_code, 403)


class BannerCleanupTests(BannerTestCase):
    def test_the_cleanup_job_never_treats_a_banner_image_as_an_orphan(self):
        banner = self._banner_via_api()
        unused = StoredFile.objects.create(
            owner=self.admin, provider=StoredFile.Provider.CLOUDINARY,
            storage_key='users/1/images/unused', original_name='u.png',
            content_type='image/png', size=1, status=StoredFile.Status.READY,
        )
        long_ago = timezone.now() - timedelta(minutes=storage_config.CLEANUP_MAX_AGE_MINUTES + 5)
        StoredFile.objects.filter(pk__in=[banner.image_file_id, unused.pk]).update(created_at=long_ago)

        self.assertEqual(run_cleanup(), {'orphanedDeleted': 1})

        self.assertTrue(StoredFile.objects.filter(pk=banner.image_file_id).exists())
        self.assertFalse(StoredFile.objects.filter(pk=unused.pk).exists())
