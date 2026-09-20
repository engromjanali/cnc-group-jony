"""Fills the catalogue with dummy categories and designs, for trying the app out.

    python manage.py seed_dummy_catalog                    10 categories x 30 designs
    python manage.py seed_dummy_catalog --dry-run          say what it would do, change nothing
    python manage.py seed_dummy_catalog --categories 3 --designs 5
    python manage.py seed_dummy_catalog --remove           take the dummy data out again

Nothing is uploaded: each design gets a picture URL (picsum.photos) instead of an
image in Cloudinary, and no cutting file, so there is nothing in storage to
clean up. That URL is also how the dummy designs are recognised - `--remove`
deletes exactly the designs that carry it and never touches a real one.

Safe to run again: whatever already exists is left as it is and only what is
missing is added.
"""
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Max

from designs.models import Category, Design

# Every dummy design's picture starts with this, and nothing real does.
MARKER = 'https://picsum.photos/seed/cnc-dummy-'

# A portrait picture, matching the app's 1 : 1.3 design cards.
PICTURE_SIZE = '600/780'

MAX_DESIGNS_PER_CATEGORY = 100

# One style word per design, so titles inside a category never repeat.
STYLES = [
    'Royal', 'Classic', 'Modern', 'Floral', 'Geometric', 'Arabesque', 'Mughal',
    'Minimal', 'Vintage', 'Ornate', 'Celtic', 'Lotus', 'Peacock', 'Tribal',
    'Heritage', 'Elegant', 'Grand', 'Rustic', 'Art Deco', 'Islamic', 'Paisley',
    'Vine', 'Mandala', 'Leaf', 'Lattice', 'Sunburst', 'Imperial', 'Petal',
    'Dragon', 'Crown',
]

# (category name, the kinds of design it holds), in the order they are ranked.
CATALOGUE = [
    ('3D Bed', ['Headboard', 'Bed Frame', 'Bed Back Panel', 'Bedside Carving']),
    ('2D Door', ['Door Panel', 'Door Border', 'Main Door Inlay']),
    ('3D Door', ['Carved Door', 'Door Panel', 'Double Door']),
    ('3D Panel', ['Wall Panel', 'Feature Wall', 'Relief Panel']),
    ('2D Panel', ['Wall Screen', 'Jali Panel', 'Partition Panel']),
    ('Frame', ['Photo Frame', 'Portrait Frame', 'Border Frame']),
    ('Mirror', ['Mirror Frame', 'Dressing Mirror', 'Round Mirror Border']),
    ('Temple', ['Mandir Door', 'Temple Arch', 'Puja Cabinet']),
    ('Window', ['Window Grill', 'Window Frame', 'Jali Window']),
    ('CNC Art', ['Wall Art', 'Calligraphy Panel', 'Decor Piece']),
]


def slug(label):
    return re.sub(r'[^a-z0-9]+', '-', label.lower()).strip('-')


def design_specs(label, kinds, count):
    """The `count` dummy designs of one category, always the same ones."""
    specs = []
    for index in range(count):
        style = STYLES[index % len(STYLES)]
        # Past one lap of the styles, number them so titles stay unique.
        lap = index // len(STYLES)
        title = f'{style} {kinds[index % len(kinds)]}' + (f' {lap + 1}' if lap else '')
        specs.append({
            'title': title,
            'description': (
                f'{title}: a {style.lower()} CNC design for {label.lower()} work. '
                'Sample data for trying the app out.'
            ),
            'image_url': f'{MARKER}{slug(label)}-{index + 1:02d}/{PICTURE_SIZE}',
        })
    return specs


class Command(BaseCommand):
    help = 'Adds (or with --remove, takes out) dummy categories and designs.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--categories', type=int, default=len(CATALOGUE),
            help=f'How many categories, 1 to {len(CATALOGUE)} (default: all {len(CATALOGUE)}).',
        )
        parser.add_argument(
            '--designs', type=int, default=30,
            help=f'Designs per category, 1 to {MAX_DESIGNS_PER_CATEGORY} (default: 30).',
        )
        parser.add_argument('--dry-run', action='store_true', help='Show what would change; change nothing.')
        parser.add_argument('--remove', action='store_true', help='Remove the dummy data instead of adding it.')

    def handle(self, *args, **options):
        categories, designs = options['categories'], options['designs']
        if not 1 <= categories <= len(CATALOGUE):
            raise CommandError(f'--categories must be from 1 to {len(CATALOGUE)}.')
        if not 1 <= designs <= MAX_DESIGNS_PER_CATEGORY:
            raise CommandError(f'--designs must be from 1 to {MAX_DESIGNS_PER_CATEGORY}.')

        # Worth seeing before anything is written: local and deployed builds can
        # share one database.
        self.stdout.write(f'Database: {connection.vendor} ({connection.settings_dict.get("NAME")})')
        if options['dry_run']:
            self.stdout.write(self.style.WARNING('Dry run - nothing will be changed.'))

        if options['remove']:
            self._remove(dry_run=options['dry_run'])
        else:
            self._add(categories, designs, dry_run=options['dry_run'])

    # --- adding --------------------------------------------------------------------

    def _plan(self, categories, designs):
        """For each category: the row it already has (or None) and which of its
        dummy designs are still missing."""
        plan = []
        for label, kinds in CATALOGUE[:categories]:
            category = Category.objects.filter(label__iexact=label).first()
            existing = set()
            if category is not None:
                existing = set(
                    category.designs.filter(image_url__startswith=MARKER)
                    .values_list('image_url', flat=True)
                )
            missing = [s for s in design_specs(label, kinds, designs) if s['image_url'] not in existing]
            plan.append((label, category, missing))
        return plan

    def _add(self, categories, designs, *, dry_run):
        plan = self._plan(categories, designs)
        new_categories = sum(1 for _, category, _ in plan if category is None)
        new_designs = sum(len(missing) for _, _, missing in plan)

        for label, category, missing in plan:
            state = 'new' if category is None else 'exists'
            self.stdout.write(f'  {label}: {state}, {len(missing)} designs to add')

        if dry_run:
            self.stdout.write(f'Would add {new_categories} categories and {new_designs} designs.')
            return

        with transaction.atomic():
            # Ranked after the categories that already have a priority.
            next_priority = (Category.objects.aggregate(top=Max('priority'))['top'] or 0) + 1
            for label, category, missing in plan:
                if category is None:
                    category = Category.objects.create(label=label, priority=next_priority)
                    next_priority += 1
                Design.objects.bulk_create([
                    Design(category=category, title=s['title'], description=s['description'], image_url=s['image_url'])
                    for s in missing
                ])

        self.stdout.write(self.style.SUCCESS(f'Added {new_categories} categories and {new_designs} designs.'))

    # --- removing ------------------------------------------------------------------------

    def _remove(self, *, dry_run):
        dummy = Design.objects.filter(image_url__startswith=MARKER)
        touched = set(dummy.values_list('category_id', flat=True))
        design_count = dummy.count()

        # A category goes only if it is one of the dummy ones, held nothing but
        # dummy designs and has no picture of its own - never a real one.
        emptied = [
            category for category in Category.objects.filter(pk__in=touched)
            if category.label.lower() in {label.lower() for label, _ in CATALOGUE}
            and category.image_file_id is None
            and not category.designs.exclude(image_url__startswith=MARKER).exists()
        ]

        self.stdout.write(f'  {design_count} dummy designs, {len(emptied)} dummy categories left empty by that')
        if dry_run:
            self.stdout.write(f'Would remove {design_count} designs and {len(emptied)} categories.')
            return

        with transaction.atomic():
            dummy.delete()
            for category in emptied:
                category.delete()

        self.stdout.write(self.style.SUCCESS(f'Removed {design_count} designs and {len(emptied)} categories.'))
