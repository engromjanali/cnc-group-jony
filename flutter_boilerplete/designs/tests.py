import itertools
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APITestCase

from storage.models import StoredFile

from .management.commands.seed_dummy_catalog import CATALOGUE, MARKER
from .models import Category, Design, SubCategory

User = get_user_model()


@override_settings(CLOUDINARY_CLOUD_NAME='demo-cloud')
class DesignFixtures(APITestCase):
    """Two users (one admin), two categories and a way to make designs with
    their files - what every test here starts from. Has no tests itself."""

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

    def _design(
        self, title, category=None, *, image=True, design_file=False, sub_category=None,
        is_paid=None, amount=None,
    ):
        return Design.objects.create(
            category=category or self.beds,
            sub_category=sub_category,
            title=title,
            image_file=self._stored(StoredFile.Provider.CLOUDINARY, f'{title}.png') if image else None,
            design_stored_file=(
                self._stored(StoredFile.Provider.R2, f'{title}.dxf') if design_file else None
            ),
            design_file_name=f'{title}.dxf' if design_file else '',
            **({} if is_paid is None else {'is_paid': is_paid}),
            **({} if amount is None else {'amount': amount}),
        )


class DesignListTests(DesignFixtures):
    """The browsable design list - the designs any signed-in user can page
    through, optionally for one category."""

    def _list(self, **params):
        return self.client.get(reverse('design-list'), params)

    def _titles(self, response):
        self.assertEqual(response.status_code, 200, response.data)
        return [item['title'] for item in response.data['results']]

    # --- access ---------------------------------------------------------------

    def test_it_is_served_at_category_design_list(self):
        self.assertEqual(reverse('design-list'), '/api/v1/designs/list')
        self.assertEqual(self.client.get('/api/v1/designs/list').status_code, 200)

    def test_the_old_path_is_gone(self):
        self.assertEqual(self.client.get('/api/v1/promotional-banner/list').status_code, 404)

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
        design = self._design(
            'Headboard', sub_category=sub, design_file=True,
            is_paid=True, amount='9.99',
        )

        item = self._list().data['results'][0]

        self.assertEqual(item['id'], design.id)
        self.assertEqual(item['title'], 'Headboard')
        self.assertEqual(item['category_id'], self.beds.id)
        self.assertEqual(item['category_label'], 'Beds')
        self.assertEqual(item['sub_category_label'], 'King')
        self.assertEqual(item['design_type'], '2d')
        self.assertIs(item['is_paid'], True)
        self.assertEqual(item['amount'], '9.99')
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


class SeedDummyCatalogTests(DesignFixtures):
    """manage.py seed_dummy_catalog - dummy categories and designs for trying the
    app out, added and removed without touching anything real."""

    def _run(self, *args):
        out = StringIO()
        call_command('seed_dummy_catalog', *args, stdout=out)
        return out.getvalue()

    def _seeded(self):
        return Design.objects.filter(image_url__startswith=MARKER)

    def _dummy_categories(self):
        return Category.objects.exclude(pk__in=[self.beds.pk, self.doors.pk])

    # --- adding ------------------------------------------------------------------

    def test_it_adds_ten_categories_with_thirty_designs_each(self):
        self._run()

        self.assertEqual(self._dummy_categories().count(), 10)
        for category in self._dummy_categories():
            self.assertEqual(category.designs.count(), 30, category.label)
        self.assertEqual(
            set(self._dummy_categories().values_list('label', flat=True)),
            {label for label, _ in CATALOGUE},
        )

    def test_the_new_categories_rank_after_the_existing_ones_in_order(self):
        Category.objects.filter(pk=self.beds.pk).update(priority=5)

        self._run()

        ranked = list(self._dummy_categories().order_by('priority').values_list('label', 'priority'))
        self.assertEqual(ranked, [(label, 6 + i) for i, (label, _) in enumerate(CATALOGUE)])

    def test_titles_are_unique_within_a_category(self):
        self._run()

        for category in self._dummy_categories():
            titles = list(category.designs.values_list('title', flat=True))
            self.assertEqual(len(titles), len(set(titles)), category.label)

    def test_more_designs_than_styles_are_numbered_so_titles_stay_unique(self):
        self._run('--categories', '1', '--designs', '75')

        titles = list(Design.objects.filter(image_url__startswith=MARKER).values_list('title', flat=True))
        self.assertEqual(len(titles), 75)
        self.assertEqual(len(set(titles)), 75)

    def test_nothing_is_uploaded_only_a_picture_url_is_set(self):
        stored_before = StoredFile.objects.count()

        self._run()

        self.assertEqual(StoredFile.objects.count(), stored_before)
        for design in self._seeded():
            self.assertIsNone(design.image_file_id)
            self.assertIsNone(design.design_stored_file_id)
            self.assertFalse(design.design_file)
            self.assertEqual(design.design_file_url, '')

    def test_every_picture_url_is_unique_and_fits_its_field(self):
        self._run()

        urls = list(self._seeded().values_list('image_url', flat=True))
        self.assertEqual(len(urls), 300)
        self.assertEqual(len(set(urls)), 300)
        self.assertLessEqual(max(len(url) for url in urls), Design._meta.get_field('image_url').max_length)

    def test_it_reports_what_it_did(self):
        out = self._run()

        self.assertIn('Added 10 categories and 300 designs', out)

    def test_it_says_which_database_it_is_writing_to(self):
        self.assertIn('Database:', self._run('--categories', '1', '--designs', '1'))

    # --- safe to repeat ------------------------------------------------------------------

    def test_running_it_again_adds_nothing(self):
        self._run()
        categories, designs = Category.objects.count(), Design.objects.count()

        out = self._run()

        self.assertEqual((Category.objects.count(), Design.objects.count()), (categories, designs))
        self.assertIn('Added 0 categories and 0 designs', out)

    def test_running_it_again_restores_only_what_was_deleted(self):
        self._run()
        category = Category.objects.get(label='Frame')
        doomed = list(category.designs.order_by('id').values_list('pk', flat=True)[:5])
        Design.objects.filter(pk__in=doomed).delete()
        self.assertEqual(category.designs.count(), 25)

        out = self._run()

        self.assertEqual(category.designs.count(), 30)
        self.assertIn('Added 0 categories and 5 designs', out)

    def test_a_category_that_already_exists_is_reused_whatever_its_case(self):
        existing = Category.objects.create(label='3d bed', priority=99)

        self._run()

        self.assertEqual(Category.objects.filter(label__iexact='3D Bed').count(), 1)
        existing.refresh_from_db()
        self.assertEqual(existing.priority, 99, 'its rank is not changed')
        self.assertEqual(existing.designs.count(), 30)

    # --- what it leaves alone ---------------------------------------------------------------

    def test_existing_categories_and_designs_are_left_exactly_as_they_were(self):
        real = self._design('Real headboard', self.beds)
        Category.objects.filter(pk=self.doors.pk).update(priority=1)

        self._run()

        real.refresh_from_db()
        self.assertEqual((real.title, real.category_id), ('Real headboard', self.beds.id))
        self.assertEqual(self.beds.designs.count(), 1)
        self.assertEqual(self.doors.designs.count(), 0)
        self.doors.refresh_from_db()
        self.assertEqual(self.doors.priority, 1)

    # --- options -------------------------------------------------------------------------------

    def test_the_amounts_can_be_chosen(self):
        self._run('--categories', '2', '--designs', '4')

        self.assertEqual(self._dummy_categories().count(), 2)
        self.assertEqual(self._seeded().count(), 8)
        self.assertEqual(
            list(self._dummy_categories().order_by('priority').values_list('label', flat=True)),
            [label for label, _ in CATALOGUE[:2]],
        )

    def test_amounts_out_of_range_are_refused_and_nothing_is_written(self):
        for args in (
            ('--categories', '0'), ('--categories', '11'),
            ('--designs', '0'), ('--designs', '101'),
        ):
            with self.subTest(args=args):
                with self.assertRaises(CommandError):
                    self._run(*args)

        self.assertEqual(Design.objects.count(), 0)
        self.assertEqual(Category.objects.count(), 2)

    def test_a_dry_run_reports_the_plan_and_changes_nothing(self):
        out = self._run('--dry-run')

        self.assertIn('Would add 10 categories and 300 designs', out)
        self.assertEqual(Category.objects.count(), 2)
        self.assertEqual(Design.objects.count(), 0)

    def test_a_dry_run_after_a_partial_run_reports_only_what_is_missing(self):
        self._run('--categories', '3', '--designs', '30')

        out = self._run('--dry-run')

        self.assertIn('Would add 7 categories and 210 designs', out)

    def test_the_insert_is_a_handful_of_queries_not_one_per_design(self):
        with CaptureQueriesContext(connection) as captured:
            self._run()

        self.assertEqual(self._seeded().count(), 300)
        self.assertLess(len(captured), 80)

    # --- removing --------------------------------------------------------------------------------

    def test_remove_takes_out_the_dummy_data_and_nothing_else(self):
        real = self._design('Real headboard', self.beds)
        self._run()
        self.assertEqual(Design.objects.count(), 301)

        out = self._run('--remove')

        self.assertEqual(self._seeded().count(), 0)
        self.assertEqual(self._dummy_categories().count(), 0)
        self.assertEqual(
            set(Category.objects.values_list('pk', flat=True)), {self.beds.pk, self.doors.pk},
        )
        self.assertEqual(list(Design.objects.values_list('pk', flat=True)), [real.pk])
        self.assertIn('Removed 300 designs and 10 categories', out)

    def test_remove_keeps_a_category_that_holds_a_real_design(self):
        self._run()
        category = Category.objects.get(label='Mirror')
        real = self._design('My own mirror', category)

        self._run('--remove')

        self.assertTrue(Category.objects.filter(pk=category.pk).exists())
        self.assertEqual(list(category.designs.all()), [real])
        self.assertEqual(self._dummy_categories().count(), 1)

    def test_remove_keeps_a_category_that_has_a_picture_of_its_own(self):
        self._run()
        category = Category.objects.get(label='Temple')
        category.image_file = self._stored(StoredFile.Provider.CLOUDINARY, 'temple.png')
        category.save()

        self._run('--remove')

        self.assertTrue(Category.objects.filter(pk=category.pk).exists())
        self.assertEqual(category.designs.count(), 0, 'its dummy designs still went')

    def test_remove_never_touches_a_real_design_with_a_similar_picture(self):
        self._run()
        lookalike = self._design('Lookalike', self.beds)
        Design.objects.filter(pk=lookalike.pk).update(image_url='https://picsum.photos/seed/mine/600/780')

        self._run('--remove')

        self.assertTrue(Design.objects.filter(pk=lookalike.pk).exists())

    def test_remove_leaves_a_real_empty_category_with_a_dummy_name_alone(self):
        # Nothing dummy was ever put in it, so it is not the command's to delete.
        mine = Category.objects.create(label='Window')

        self._run('--remove')

        self.assertTrue(Category.objects.filter(pk=mine.pk).exists())

    def test_remove_dry_run_changes_nothing(self):
        self._run()

        out = self._run('--remove', '--dry-run')

        self.assertIn('Would remove 300 designs and 10 categories', out)
        self.assertEqual(self._seeded().count(), 300)
        self.assertEqual(self._dummy_categories().count(), 10)

    def test_remove_with_nothing_seeded_is_a_no_op(self):
        out = self._run('--remove')

        self.assertIn('Removed 0 designs and 0 categories', out)
        self.assertEqual(Category.objects.count(), 2)

    def test_adding_after_removing_gives_the_same_result(self):
        self._run()
        self._run('--remove')

        self._run()

        self.assertEqual(self._seeded().count(), 300)
        self.assertEqual(self._dummy_categories().count(), 10)

    # --- what the app sees --------------------------------------------------------------------------------

    def test_the_dummy_data_shows_up_in_the_home_and_list_endpoints(self):
        self._run('--categories', '2', '--designs', '25')
        first = Category.objects.get(label=CATALOGUE[0][0])

        categories = {
            c['label']: c for c in self.client.get(reverse('category-list')).data
        }
        self.assertEqual(categories[CATALOGUE[0][0]]['design_count'], 25)

        listed = self.client.get(reverse('design-list'), {'category': first.pk})
        self.assertEqual(listed.data['count'], 25)
        designs = listed.data['results']
        self.assertTrue(designs[0]['image_url'].startswith(MARKER))
        self.assertFalse(designs[0]['has_design_file'])
        self.assertEqual(len(listed.data['results']), 20)
