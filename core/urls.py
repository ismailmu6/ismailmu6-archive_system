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
    path('document/<int:doc_id>/preview/', views.preview_document, name='preview_document'),
    path('document/<int:doc_id>/upload_attachment/', views.upload_attachment, name='upload_attachment'),

    # ✅ حذف مرفق (للمسؤولين فقط)
    path('attachment/<int:attachment_id>/delete/', views.delete_attachment, name='delete_attachment'),

    # ✅ استبدال مرفق
    path('attachment/<int:attachment_id>/replace/', views.replace_attachment, name='replace_attachment'),

    path('document/<int:doc_id>/update-file/', views.update_document_file, name='update_document_file'),
    path('change-password/', views.change_password, name='change_password'),

    # ✅✅✅ جديد: تصدير Excel ✅✅✅
    path('search/export-excel/', views.export_documents_excel, name='export_documents_excel'),
]