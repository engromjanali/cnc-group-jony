import itertools
from decimal import Decimal
from unittest.mock import patch
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
from .models import Category, Design, DesignPurchase, SubCategory

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

    # --- search and filters -----------------------------------------------------

    def _filter_fixtures(self):
        panel = SubCategory.objects.create(category=self.beds, label='Panel')
        self._design('Royal Bed', self.beds, sub_category=panel, is_paid=True, amount='9.00')
        third = self._design('Modern Door', self.doors)
        Design.objects.filter(pk=third.pk).update(design_type='3d', description='Carved royal look')
        self._design('Plain Door', self.doors)
        return panel

    def test_search_matches_title_description_category_and_sub_category(self):
        self._filter_fixtures()

        self.assertEqual(self._titles(self._list(search='ROYAL')), ['Modern Door', 'Royal Bed'])
        self.assertEqual(self._titles(self._list(search='plain')), ['Plain Door'])
        self.assertEqual(self._titles(self._list(search='doors')), ['Plain Door', 'Modern Door'])
        self.assertEqual(self._titles(self._list(search='panel')), ['Royal Bed'])
        self.assertEqual(self._titles(self._list(search='nothing like it')), [])

    def test_a_blank_search_is_ignored(self):
        self._filter_fixtures()

        self.assertEqual(len(self._titles(self._list(search='   '))), 3)
        self.assertEqual(len(self._titles(self._list(search=''))), 3)

    def test_design_type_filter(self):
        self._filter_fixtures()

        self.assertEqual(self._titles(self._list(design_type='3d')), ['Modern Door'])
        self.assertEqual(len(self._titles(self._list(design_type='2d'))), 2)

    def test_is_paid_filter(self):
        self._filter_fixtures()

        self.assertEqual(self._titles(self._list(is_paid='true')), ['Royal Bed'])
        self.assertEqual(self._titles(self._list(is_paid='false')), ['Plain Door', 'Modern Door'])
        self.assertEqual(len(self._titles(self._list(is_paid='TRUE'))), 1)

    def test_sub_category_filter_takes_the_id(self):
        panel = self._filter_fixtures()

        self.assertEqual(self._titles(self._list(sub_category=panel.pk)), ['Royal Bed'])
        self.assertEqual(self._titles(self._list(sub_category=99999)), [])

    def test_filters_combine(self):
        self._filter_fixtures()

        self.assertEqual(self._titles(self._list(search='royal', design_type='3d')), ['Modern Door'])
        self.assertEqual(self._titles(self._list(search='royal', category=self.beds.pk)), ['Royal Bed'])
        self.assertEqual(self._titles(self._list(search='royal', is_paid='true', design_type='3d')), [])

    def test_filtered_results_still_paginate(self):
        for n in range(5):
            self._design(f'Frame {n}', self.doors)
        response = self._list(search='frame', page_size=2)

        self.assertEqual(response.data['count'], 5)
        self.assertEqual(len(response.data['results']), 2)
        self.assertIsNotNone(response.data['next'])

    def test_malformed_filters_are_a_400_naming_the_parameter(self):
        for params, name in (
            ({'design_type': 'flat'}, 'design_type'),
            ({'is_paid': 'maybe'}, 'is_paid'),
            ({'sub_category': 'abc'}, 'sub_category'),
        ):
            response = self._list(**params)
            self.assertEqual(response.status_code, 400, params)
            self.assertIn(name, response.data)

    # --- the category picture shown beside the category name --------------------

    def test_each_design_carries_its_categorys_picture(self):
        self.beds.image_file = self._stored(StoredFile.Provider.CLOUDINARY, 'beds.png')
        self.beds.save()
        self._design('Royal Bed', self.beds)
        self._design('Plain Door', self.doors)  # a category with no picture

        by_title = {item['title']: item for item in self._list().data['results']}

        self.assertTrue(by_title['Royal Bed']['category_image_url'])
        self.assertIn('beds', by_title['Royal Bed']['category_image_url'])
        self.assertIsNone(by_title['Plain Door']['category_image_url'])

    def test_the_details_and_the_admin_list_carry_it_too(self):
        self.beds.image_file = self._stored(StoredFile.Provider.CLOUDINARY, 'beds.png')
        self.beds.save()
        design = self._design('Royal Bed', self.beds)

        details = self.client.get(reverse('design-details', args=[design.pk]))
        self.assertTrue(details.data['category_image_url'])

        self.client.force_authenticate(self.admin)
        admin_list = self.client.get(reverse('admin-design-list'))
        self.assertTrue(admin_list.data['results'][0]['category_image_url'])

    def test_the_category_picture_costs_no_query_per_design(self):
        self.beds.image_file = self._stored(StoredFile.Provider.CLOUDINARY, 'beds.png')
        self.beds.save()
        self._design('One', self.beds)

        with CaptureQueriesContext(connection) as few:
            self._list()
        for n in range(6):
            self._design(f'More {n}', self.beds)
        with CaptureQueriesContext(connection) as many:
            self._list()

        self.assertEqual(len(many), len(few))

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


class DesignDownloadChargeTests(DesignFixtures):
    """Downloading a design: free ones cost nothing, paid ones take their price
    from the wallet once, and the file is never handed over unpaid."""

    FILE = 'https://files.example/panel.dxf'

    def _paid(self, title='Royal Bed', amount='50.00', with_file=True):
        return Design.objects.create(
            category=self.beds, title=title, is_paid=True, amount=Decimal(amount),
            design_file_url=self.FILE if with_file else '',
            design_file_name='panel.dxf' if with_file else '',
        )

    def _free(self, title='Free Panel'):
        return Design.objects.create(
            category=self.beds, title=title, design_file_url=self.FILE, design_file_name='panel.dxf',
        )

    def _fund(self, amount, user=None):
        user = user or self.customer
        user.wallet_balance = Decimal(amount)
        user.save(update_fields=['wallet_balance'])

    def _balance(self, user=None):
        return (user or self.customer).__class__.objects.get(pk=(user or self.customer).pk).wallet_balance

    def _download(self, design):
        return self.client.post(reverse('design-download', args=[design.pk]))

    # --- paying -------------------------------------------------------------------

    def test_a_paid_design_takes_its_price_from_the_wallet_and_hands_over_the_file(self):
        self._fund('120.00')
        design = self._paid(amount='50.00')

        response = self._download(design)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['charged'], '50.00')
        self.assertEqual(response.data['walletBalance'], '70.00')
        self.assertFalse(response.data['alreadyPurchased'])
        self.assertEqual(response.data['designId'], design.pk)
        self.assertEqual(response.data['downloadUrl'], self.FILE)
        self.assertEqual(response.data['fileName'], 'panel.dxf')
        self.assertEqual(self._balance(), Decimal('70.00'))

    def test_the_purchase_is_recorded_with_the_price_and_title_at_the_time(self):
        self._fund('100.00')
        design = self._paid(title='Royal Bed', amount='19.99')

        self._download(design)

        purchase = DesignPurchase.objects.get()
        self.assertEqual((purchase.user, purchase.design), (self.customer, design))
        self.assertEqual((purchase.design_title, purchase.amount), ('Royal Bed', Decimal('19.99')))

    def test_cents_are_exact(self):
        self._fund('20.00')

        response = self._download(self._paid(amount='19.99'))

        self.assertEqual(response.data['walletBalance'], '0.01')
        self.assertEqual(self._balance(), Decimal('0.01'))

    def test_a_balance_exactly_equal_to_the_price_is_enough(self):
        self._fund('50.00')

        response = self._download(self._paid(amount='50.00'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._balance(), Decimal('0.00'))

    # --- once only ----------------------------------------------------------------

    def test_downloading_again_is_free(self):
        self._fund('120.00')
        design = self._paid(amount='50.00')

        self._download(design)
        again = self._download(design)

        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.data['charged'], '0.00')
        self.assertTrue(again.data['alreadyPurchased'])
        self.assertEqual(again.data['walletBalance'], '70.00')
        self.assertEqual(DesignPurchase.objects.count(), 1)
        self.assertEqual(self._balance(), Decimal('70.00'))

    def test_a_price_change_neither_recharges_nor_locks_out_the_owner(self):
        self._fund('100.00')
        design = self._paid(amount='50.00')
        self._download(design)

        Design.objects.filter(pk=design.pk).update(amount=Decimal('80.00'))
        again = self._download(design)

        self.assertEqual(again.data['charged'], '0.00')
        self.assertEqual(self._balance(), Decimal('50.00'))

    def test_each_user_pays_for_themselves(self):
        self._fund('100.00')
        self._fund('100.00', self.admin)
        design = self._paid(amount='30.00')

        self._download(design)
        self.client.force_authenticate(self.admin)
        second = self._download(design)

        self.assertEqual(second.data['charged'], '30.00')
        self.assertEqual(DesignPurchase.objects.count(), 2)
        self.assertEqual(self._balance(), Decimal('70.00'))
        self.assertEqual(self._balance(self.admin), Decimal('70.00'))

    def test_a_purchase_survives_the_design_being_deleted(self):
        self._fund('100.00')
        design = self._paid(title='Royal Bed', amount='50.00')
        self._download(design)

        design.delete()

        purchase = DesignPurchase.objects.get()
        self.assertIsNone(purchase.design)
        self.assertEqual((purchase.design_title, purchase.amount), ('Royal Bed', Decimal('50.00')))

    # --- not enough money ---------------------------------------------------------

    def test_too_little_in_the_wallet_is_a_402_and_takes_nothing(self):
        self._fund('20.00')
        design = self._paid(amount='50.00')

        response = self._download(design)

        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.data['required'], '50.00')
        self.assertEqual(response.data['walletBalance'], '20.00')
        self.assertIn('balance', response.data['detail'])
        self.assertNotIn('downloadUrl', response.data)
        self.assertEqual(self._balance(), Decimal('20.00'))
        self.assertEqual(DesignPurchase.objects.count(), 0)

    def test_two_designs_that_together_cost_more_than_the_wallet_cannot_both_be_bought(self):
        self._fund('60.00')
        first = self._paid('First', '50.00')
        second = self._paid('Second', '50.00')

        self.assertEqual(self._download(first).status_code, 200)
        refused = self._download(second)

        self.assertEqual(refused.status_code, 402)
        self.assertEqual(refused.data['walletBalance'], '10.00')
        self.assertEqual(self._balance(), Decimal('10.00'))  # never negative
        self.assertEqual(DesignPurchase.objects.count(), 1)
        self.assertFalse(DesignPurchase.objects.filter(design=second).exists())

    def test_after_adding_money_the_same_call_then_works(self):
        design = self._paid(amount='50.00')
        self.assertEqual(self._download(design).status_code, 402)

        self._fund('60.00')
        response = self._download(design)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._balance(), Decimal('10.00'))

    # --- free designs and missing files -------------------------------------------

    def test_a_free_design_costs_nothing_and_leaves_no_purchase(self):
        self._fund('5.00')

        response = self._download(self._free())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['charged'], '0.00')
        self.assertEqual(response.data['walletBalance'], '5.00')
        self.assertEqual(response.data['downloadUrl'], self.FILE)
        self.assertEqual(DesignPurchase.objects.count(), 0)

    def test_a_free_design_works_with_an_empty_wallet(self):
        self.assertEqual(self._download(self._free()).status_code, 200)

    def test_nothing_is_charged_for_a_design_with_no_file(self):
        self._fund('100.00')
        design = self._paid(with_file=False)

        response = self._download(design)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self._balance(), Decimal('100.00'))
        self.assertEqual(DesignPurchase.objects.count(), 0)

    def test_a_paid_design_stored_privately_is_charged_and_signed(self):
        self._fund('100.00')
        design = self._paid(with_file=False)
        design.design_stored_file = self._stored(StoredFile.Provider.R2, 'panel.dxf')
        design.save()

        class _Signer:
            def url_for(self, key, download_name=None):
                return f'https://r2.example/{key}?sig=1&name={download_name}'

        with patch('designs.views.get_storage_service', return_value=_Signer()):
            response = self._download(design)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['downloadUrl'].startswith('https://r2.example/'))
        self.assertEqual(response.data['charged'], '50.00')

    # --- access -------------------------------------------------------------------

    def test_it_needs_a_login(self):
        self.client.force_authenticate(None)

        self.assertEqual(self._download(self._free()).status_code, 401)

    def test_an_unknown_design_is_a_404(self):
        self.assertEqual(self.client.post(reverse('design-download', args=[9999])).status_code, 404)

    def test_only_post_charges(self):
        self._fund('100.00')
        design = self._paid()

        self.assertEqual(self.client.get(reverse('design-download', args=[design.pk])).status_code, 405)
        self.assertEqual(self._balance(), Decimal('100.00'))

    # --- the old link cannot be used to skip paying --------------------------------

    def test_the_download_url_refuses_an_unpaid_paid_design(self):
        self._fund('100.00')
        design = self._paid()

        response = self.client.get(reverse('design-download-url', args=[design.pk]))

        self.assertEqual(response.status_code, 402)
        self.assertNotIn('downloadUrl', response.data)
        self.assertEqual(self._balance(), Decimal('100.00'))  # asking never charges

    def test_the_download_url_works_once_the_design_is_bought(self):
        self._fund('100.00')
        design = self._paid()
        self._download(design)

        response = self.client.get(reverse('design-download-url', args=[design.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['downloadUrl'], self.FILE)

    def test_the_download_url_for_a_free_design_is_unchanged(self):
        response = self.client.get(reverse('design-download-url', args=[self._free().pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['downloadUrl'], self.FILE)

    def test_a_paid_designs_permanent_file_link_is_never_in_a_payload(self):
        """Otherwise the link could be fetched directly, skipping the charge."""
        paid = self._paid()
        free = self._free()

        details = self.client.get(reverse('design-details', args=[paid.pk])).data
        listing = {d['title']: d for d in self.client.get(reverse('design-list')).data['results']}

        self.assertIsNone(details['design_file_url'])
        self.assertIsNone(listing[paid.title]['design_file_url'])
        self.assertTrue(listing[paid.title]['has_design_file'])  # it can be bought
        self.assertEqual(listing[free.title]['design_file_url'], self.FILE)  # free: as before

    def test_the_link_is_still_delivered_by_the_charged_call(self):
        self._fund('100.00')
        paid = self._paid()

        self.assertEqual(self._download(paid).data['downloadUrl'], self.FILE)

    def test_someone_elses_purchase_does_not_unlock_it_for_you(self):
        self._fund('100.00', self.admin)
        design = self._paid()
        self.client.force_authenticate(self.admin)
        self._download(design)

        self.client.force_authenticate(self.customer)
        response = self.client.get(reverse('design-download-url', args=[design.pk]))

        self.assertEqual(response.status_code, 402)
