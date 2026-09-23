from django.urls import path

from .views import FavoriteAddView, FavoriteListView, FavoriteRemoveView

urlpatterns = [
    path('favorites/list', FavoriteListView.as_view(), name='favorite-list'),
    path('favorites/add/<int:design_id>', FavoriteAddView.as_view(), name='favorite-add'),
    path('favorites/remove/<int:design_id>', FavoriteRemoveView.as_view(), name='favorite-remove'),
]
