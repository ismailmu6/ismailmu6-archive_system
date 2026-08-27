from django.urls import path
from . import views

urlpatterns = [
    path('', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),

    path('upload/', views.upload_document, name='upload'),
    path('search/', views.search_documents, name='search'),

    path('document/<int:doc_id>/', views.document_detail, name='document_detail'),
    path('document/<int:doc_id>/download/', views.download_document, name='download_document'),
    path('document/<int:doc_id>/edit/', views.edit_document, name='edit_document'),
    path('document/<int:doc_id>/delete/', views.delete_document, name='delete_document'),
    path('document/<int:doc_id>/comment/', views.add_comment, name='add_comment'),

    path('folders/', views.folder_list, name='folder_list'),
    path('folders/<int:folder_id>/', views.folder_detail, name='folder_detail'),
    path('folders/create/', views.create_folder, name='create_folder'),
    path('folders/<int:folder_id>/delete/', views.delete_folder, name='delete_folder'),
]