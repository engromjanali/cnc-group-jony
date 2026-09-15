from django.urls import path

from .views import (
    AdminCategoryCreateView,
    AdminDesignAddView,
    AdminDesignDeleteView,
    AdminDesignUpdateView,
    AdminSubCategoryCreateView,
    CategoryListView,
    DesignDetailView,
    SubCategoryListView,
)

urlpatterns = [
    path('category/list', CategoryListView.as_view(), name='category-list'),
    path('subcategory/list', SubCategoryListView.as_view(), name='subcategory-list'),
    path('admin/category/add', AdminCategoryCreateView.as_view(), name='admin-category-add'),
    path('admin/subcategory/add', AdminSubCategoryCreateView.as_view(), name='admin-subcategory-add'),
    path('admin/design/add', AdminDesignAddView.as_view(), name='admin-design-add'),
    path('admin/design/update/<int:pk>', AdminDesignUpdateView.as_view(), name='admin-design-update'),
    path('admin/design/delete/<int:pk>', AdminDesignDeleteView.as_view(), name='admin-design-delete'),
    path('design/details/<int:pk>', DesignDetailView.as_view(), name='design-details'),
]
