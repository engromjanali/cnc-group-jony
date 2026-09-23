from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from designs.models import Category, Design

User = get_user_model()


class FavoriteTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user('user@example.com', 'pw-1')
        self.other = User.objects.create_user('other@example.com', 'pw-2')
        category = Category.objects.create(label='Beds')
        self.one = Design.objects.create(category=category, title='One')
        self.two = Design.objects.create(category=category, title='Two')
        self.client.force_authenticate(self.user)

    def _add(self, design):
        return self.client.post(f'/api/v1/favorites/add/{design.pk}')

    def test_requires_sign_in(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get('/api/v1/favorites/list').status_code, 401)
        self.assertEqual(self._add(self.one).status_code, 401)

    def test_add_is_idempotent_and_list_is_newest_first(self):
        self.assertEqual(self._add(self.one).status_code, 201)
        self.assertEqual(self._add(self.one).status_code, 200)
        self._add(self.two)
        titles = [d['title'] for d in self.client.get('/api/v1/favorites/list').data]
        self.assertEqual(titles, ['Two', 'One'])

    def test_unknown_design_is_404(self):
        self.assertEqual(self.client.post('/api/v1/favorites/add/9999').status_code, 404)

    def test_remove_is_idempotent(self):
        self._add(self.one)
        url = f'/api/v1/favorites/remove/{self.one.pk}'
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertEqual(self.client.get('/api/v1/favorites/list').data, [])

    def test_favorites_are_per_user(self):
        self._add(self.one)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/v1/favorites/list').data, [])
