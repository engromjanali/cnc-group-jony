from django.urls import path

from .views import (
    AdminCategoryCreateView,
    AdminCategoryDeleteView,
    AdminCategoryUpdateView,
    AdminDesignAddView,
    AdminDesignDeleteView,
    AdminDesignListView,
    AdminDesignUpdateView,
    AdminSubCategoryCreateView,
    CategoryListView,
    DesignDetailView,
    DesignDownloadUrlView,
    DesignListView,
    HomeCategoriesView,
    SubCategoryListView,
)

urlpatterns = [
    path('category/list', CategoryListView.as_view(), name='category-list'),
    path('home/categories-designs', HomeCategoriesView.as_view(), name='home-categories'),
    path('subcategory/list', SubCategoryListView.as_view(), name='subcategory-list'),
    path('admin/category/add', AdminCategoryCreateView.as_view(), name='admin-category-add'),
    path(
        'admin/category/update/<int:pk>',
        AdminCategoryUpdateView.as_view(),
        name='admin-category-update',
    ),
    path(
        'admin/category/delete/<int:pk>',
        AdminCategoryDeleteView.as_view(),
        name='admin-category-delete',
    ),
    path('admin/subcategory/add', AdminSubCategoryCreateView.as_view(), name='admin-subcategory-add'),
    path('admin/design/list', AdminDesignListView.as_view(), name='admin-design-list'),
    path('admin/design/add', AdminDesignAddView.as_view(), name='admin-design-add'),
    path('admin/design/update/<int:pk>', AdminDesignUpdateView.as_view(), name='admin-design-update'),
    path('admin/design/delete/<int:pk>', AdminDesignDeleteView.as_view(), name='admin-design-delete'),
    path('promotional-banner/list', DesignListView.as_view(), name='design-list'),
    path('design/details/<int:pk>', DesignDetailView.as_view(), name='design-details'),
    path(
        'design/<int:pk>/download-url',
        DesignDownloadUrlView.as_view(),
        name='design-download-url',
    ),
]
