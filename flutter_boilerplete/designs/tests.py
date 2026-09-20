import itertools

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APITestCase

from storage.models import StoredFile

from .models import Category, Design, SubCategory

User = get_user_model()


@override_settings(CLOUDINARY_CLOUD_NAME='demo-cloud')
class DesignListTests(APITestCase):
    """GET /api/v1/design/list - the designs any signed-in user can browse."""

    def setUp(self):
        self.admin = User.objects.create_user('admin@example.com', 'pw-1', is_staff=True)
        self.customer = User.objects.create_user('customer@example.com', 'pw-2')
        self.beds = Category.objects.create(label='Beds')
        self.doors = Category.objects.create(label='Doors')
        self._keys = itertools.count()
        self.client.force_authenticate(self.customer)

    def _stored(self, provider, name):
        return StoredFile.objects.create(
            owner=self.admin, provider=provider,
            storage_key=f'users/{self.admin.id}/{next(self._keys)}-{name}',
            original_name=name, content_type='image/png', size=1,
            status=StoredFile.Status.READY,
        )

    def _design(self, title, category=None, *, image=True, design_file=False, sub_category=None):
        return Design.objects.create(
            category=category or self.beds,
            sub_category=sub_category,
            title=title,
            image_file=self._stored(StoredFile.Provider.CLOUDINARY, f'{title}.png') if image else None,
            design_stored_file=(
                self._stored(StoredFile.Provider.R2, f'{title}.dxf') if design_file else None
            ),
            design_file_name=f'{title}.dxf' if design_file else '',
        )

    def _list(self, **params):
        return self.client.get(reverse('design-list'), params)

    def _titles(self, response):
        self.assertEqual(response.status_code, 200, response.data)
        return [item['title'] for item in response.data['results']]

    # --- access ---------------------------------------------------------------

    def test_it_needs_a_login(self):
        self.client.force_authenticate(None)
        self.assertEqual(self._list().status_code, 401)

    def test_any_signed_in_user_can_browse_not_only_admins(self):
        self._design('Panel')

        self.assertEqual(self._list().status_code, 200)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self._list().status_code, 200)

    def test_the_admin_list_stays_admin_only(self):
        # The public list is a separate endpoint; it must not have loosened
        # the admin one.
        response = self.client.get(reverse('admin-design-list'))
        self.assertEqual(response.status_code, 403)

    # --- filtering and order ---------------------------------------------------

    def test_it_lists_only_the_requested_category(self):
        self._design('Headboard', self.beds)
        self._design('Bed frame', self.beds)
        self._design('Front door', self.doors)

        self.assertEqual(
            sorted(self._titles(self._list(category=self.beds.id))),
            ['Bed frame', 'Headboard'],
        )
        self.assertEqual(self._titles(self._list(category=self.doors.id)), ['Front door'])

    def test_without_a_category_it_lists_everything(self):
        self._design('Headboard', self.beds)
        self._design('Front door', self.doors)

        response = self._list()

        self.assertEqual(response.data['count'], 2)

    def test_an_empty_category_parameter_means_no_filter(self):
        self._design('Headboard', self.beds)
        self._design('Front door', self.doors)

        self.assertEqual(self._list(category='').data['count'], 2)

    def test_newest_first(self):
        for title in ('First', 'Second', 'Third'):
            self._design(title)

        self.assertEqual(self._titles(self._list()), ['Third', 'Second', 'First'])

    def test_designs_created_in_the_same_instant_keep_a_stable_order(self):
        # A bulk import can give several designs one timestamp; without a
        # tie-break the database may order them differently on each page.
        from django.utils import timezone

        made = [self._design(title) for title in ('First', 'Second', 'Third')]
        Design.objects.filter(pk__in=[d.pk for d in made]).update(created_at=timezone.now())

        self.assertEqual(self._titles(self._list()), ['Third', 'Second', 'First'])
        paged = [self._titles(self._list(page_size=1, page=n))[0] for n in (1, 2, 3)]
        self.assertEqual(paged, ['Third', 'Second', 'First'])

    def test_a_category_with_no_designs_is_an_empty_page(self):
        self._design('Headboard', self.beds)

        response = self._list(category=self.doors.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(response.data['results'], [])
        self.assertIsNone(response.data['next'])

    def test_an_unknown_category_is_an_empty_page_not_an_error(self):
        self._design('Headboard')

        response = self._list(category=9999)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 0)

    def test_a_category_that_is_not_a_number_is_a_400(self):
        # Anything else would reach the database as a bad integer and 500.
        for bad in ('abc', '1.5', '-1', '1;drop', '²'):
            with self.subTest(category=bad):
                response = self._list(category=bad)
                self.assertEqual(response.status_code, 400)
                self.assertIn('category', response.data)

    # --- what each item carries ------------------------------------------------

    def test_an_item_has_what_a_card_and_the_details_screen_need(self):
        sub = SubCategory.objects.create(category=self.beds, label='King')
        design = self._design('Headboard', sub_category=sub, design_file=True)

        item = self._list().data['results'][0]

        self.assertEqual(item['id'], design.id)
        self.assertEqual(item['title'], 'Headboard')
        self.assertEqual(item['category_id'], self.beds.id)
        self.assertEqual(item['category_label'], 'Beds')
        self.assertEqual(item['sub_category_label'], 'King')
        self.assertTrue(item['has_design_file'])
        self.assertIn('demo-cloud', item['image_url'])
        self.assertIn(design.image_file.storage_key, item['image_url'])

    def test_it_never_exposes_the_private_cutting_file(self):
        design = self._design('Headboard', design_file=True)

        response = self._list()

        item = response.data['results'][0]
        self.assertIsNone(item['design_file_url'])
        self.assertTrue(item['has_design_file'])
        # Not in the payload in any form: downloads are signed per design.
        self.assertNotIn(design.design_stored_file.storage_key, response.content.decode())

    def test_a_design_with_no_picture_still_lists(self):
        self._design('No picture', image=False)

        item = self._list().data['results'][0]

        self.assertEqual(item['title'], 'No picture')
        self.assertIsNone(item['image_url'])

    def test_a_design_with_no_file_says_so(self):
        self._design('Preview only')

        self.assertFalse(self._list().data['results'][0]['has_design_file'])

    # --- paging -----------------------------------------------------------------

    def test_pages_do_not_overlap_or_skip_designs(self):
        for i in range(5):
            self._design(f'Design {i}')

        first = self._list(page_size=2)
        second = self._list(page_size=2, page=2)
        third = self._list(page_size=2, page=3)

        self.assertEqual(first.data['count'], 5)
        self.assertIsNotNone(first.data['next'])
        self.assertIsNotNone(second.data['next'])
        self.assertIsNone(third.data['next'], 'the last page has no next')
        seen = self._titles(first) + self._titles(second) + self._titles(third)
        self.assertEqual(seen, [f'Design {i}' for i in (4, 3, 2, 1, 0)])

    def test_paging_keeps_the_category_filter(self):
        for i in range(3):
            self._design(f'Bed {i}', self.beds)
            self._design(f'Door {i}', self.doors)

        first = self._list(category=self.beds.id, page_size=2)
        second = self._list(category=self.beds.id, page_size=2, page=2)

        self.assertEqual(first.data['count'], 3)
        self.assertEqual(self._titles(first) + self._titles(second), ['Bed 2', 'Bed 1', 'Bed 0'])

    def test_a_page_holds_twenty_designs_by_default(self):
        for i in range(21):
            self._design(f'Design {i}')

        response = self._list()

        self.assertEqual(len(response.data['results']), 20)
        self.assertIsNotNone(response.data['next'])

    def test_a_page_past_the_end_is_a_404(self):
        # Clients page by `next`, so they never ask for one.
        self._design('Only')
        self.assertEqual(self._list(page=2).status_code, 404)

    # --- cost ---------------------------------------------------------------------

    def test_the_number_of_queries_does_not_grow_with_the_designs(self):
        sub = SubCategory.objects.create(category=self.beds, label='King')

        def queries():
            with CaptureQueriesContext(connection) as captured:
                self.assertEqual(self._list().status_code, 200)
            return len(captured)

        for i in range(2):
            self._design(f'Early {i}', sub_category=sub, design_file=True)
        few = queries()

        for i in range(8):
            self._design(f'Later {i}', sub_category=sub, design_file=True)
        many = queries()

        self.assertEqual(few, many)
