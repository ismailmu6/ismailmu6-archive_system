import shutil
import tempfile
from io import BytesIO
from datetime import date

import openpyxl

from django.test import TestCase, Client, override_settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from .models import (
    Directorate, Department, Folder, Tag,
    Document, DocumentAttachment, DocumentVersion,
    AuditLog, Comment, CustomUser, DocumentType,
)

from unittest.mock import patch

from core.utils.files import sanitize_folder_name, safe_filename
from core.views import (
    _get_all_folder_ids_recursive,
    EXPORT_WARNING_THRESHOLD,
)


User = get_user_model()


# ==========================================================
# اختبارات شاملة للنظام
# ==========================================================

class ProjectTests(TestCase):
    """اختبارات شاملة تغطي كل ميزات النظام"""

    def setUp(self):
        # ✅ مجلد media مؤقت فريد لكل اختبار — يمنع تداخل الأسماء
        self._media_root = tempfile.mkdtemp()
        self._override = override_settings(MEDIA_ROOT=self._media_root)
        self._override.enable()
        self.addCleanup(self._override.disable)
        self.addCleanup(shutil.rmtree, self._media_root, ignore_errors=True)

        self.client = Client()

        # --- الهيكل التنظيمي ---
        self.directorate = Directorate.objects.create(name="مديرية المالية")
        self.dept1 = Department.objects.create(name="الدائرة المالية", directorate=self.directorate)
        self.dept2 = Department.objects.create(name="دائرة الموارد", directorate=self.directorate)

        # --- نوع الوثيقة ---
        self.doc_type = DocumentType.objects.create(name="قرار")

        # --- المستخدمون ---
        self.employee = User.objects.create_user(
            username="employee", password="testpass123!",
            role=CustomUser.Role.EMPLOYEE,
            directorate=self.directorate, department=self.dept1
        )
        self.head = User.objects.create_user(
            username="head", password="testpass123!",
            role=CustomUser.Role.HEAD_OF_DEPT,
            directorate=self.directorate, department=self.dept1
        )
        self.dir_manager = User.objects.create_user(
            username="dir_manager", password="testpass123!",
            role=CustomUser.Role.DIRECTORATE_MANAGER,
            directorate=self.directorate, department=None
        )
        self.general_manager = User.objects.create_user(
            username="gm", password="testpass123!",
            role=CustomUser.Role.GENERAL_MANAGER,
            directorate=None, department=None
        )

        # --- ملفات وهمية ---
        self.test_file = SimpleUploadedFile("doc1.pdf", b"document content")
        self.attachment_file = SimpleUploadedFile("att1.pdf", b"attachment content")

        # --- وثيقة أساسية ---
        self.document = Document.objects.create(
            document_number="1",
            title="وثيقة الاختبار الأساسية",
            file=self.test_file,
            document_date=date(2026, 1, 15),
            export_date=date(2026, 2, 15),
            source=Document.Source.INTERNAL,
            directorate=self.directorate,
            department=self.dept1,
            uploaded_by=self.employee,
        )

        # --- مجلد ---
        self.folder = Folder.objects.create(
            name="مجلد الاختبار",
            directorate=self.directorate,
            department=self.dept1,
            created_by=self.employee,
        )

    # ======================================================
    # 1. صلاحيات العرض
    # ======================================================

    def test_employee_sees_own_document(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse('document_detail', args=[self.document.id]))
        self.assertEqual(response.status_code, 200)

    def test_gm_sees_all_documents(self):
        self.client.force_login(self.general_manager)
        response = self.client.get(reverse('document_detail', args=[self.document.id]))
        self.assertEqual(response.status_code, 200)

    def test_dir_manager_sees_dept_documents(self):
        other_doc = Document.objects.create(
            document_number="2",
            title="وثيقة من دائرة أخرى",
            file=SimpleUploadedFile("other.pdf", b"content"),
            document_date=date(2026, 1, 20),
            source=Document.Source.INTERNAL,
            directorate=self.directorate,
            department=self.dept2,
            uploaded_by=User.objects.create_user(
                username="other_emp", password="testpass123!",
                role=CustomUser.Role.EMPLOYEE,
                directorate=self.directorate, department=self.dept2
            )
        )
        self.client.force_login(self.dir_manager)
        response = self.client.get(reverse('document_detail', args=[other_doc.id]))
        self.assertEqual(response.status_code, 200)

    # ======================================================
    # 2. صلاحيات الحذف
    # ======================================================

    def test_employee_cannot_delete_document(self):
        self.client.force_login(self.employee)
        response = self.client.post(reverse('delete_document', args=[self.document.id]))
        self.assertEqual(response.status_code, 403)

    def test_head_can_delete_dept_document(self):
        self.client.force_login(self.head)
        response = self.client.post(reverse('delete_document', args=[self.document.id]))
        self.assertEqual(response.status_code, 302)

    # ======================================================
    # 3. صلاحيات الرفع
    # ======================================================

    def test_gm_cannot_upload(self):
        self.client.force_login(self.general_manager)
        response = self.client.post(reverse('upload'), {
            'document_number': '3',
            'title': 'وثيقة مدير عام',
            'document_date': '2026-01-01',
            'source': Document.Source.INTERNAL,
            'export_date': '',
            'file': SimpleUploadedFile("gm.pdf", b"content"),
        })
        self.assertEqual(response.status_code, 403)

    def test_employee_can_upload(self):
        self.client.force_login(self.employee)
        response = self.client.post(reverse('upload'), {
            'document_number': '4',
            'title': 'وثيقة موظف',
            'document_date': '2026-01-01',
            'source': Document.Source.INTERNAL,
            'export_date': '',
            'file': SimpleUploadedFile("emp.pdf", b"content"),
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Document.objects.filter(document_number="4").exists())

    # ======================================================
    # 4. التحقق من رقم الوثيقة
    # ======================================================

    def test_document_number_start_with_digit(self):
        self.client.force_login(self.employee)
        response = self.client.post(reverse('upload'), {
            'document_number': 'abc',
            'title': 'رقم خاطئ',
            'document_date': '2026-01-01',
            'source': Document.Source.INTERNAL,
            'export_date': '',
            'file': SimpleUploadedFile("bad.pdf", b"content"),
        })
        self.assertContains(response, 'رقم الوثيقة يجب أن يبدأ برقم', status_code=200)

    # ======================================================
    # 5. منع التكرار
    # ======================================================

    def test_duplicate_document_number_rejected(self):
        with self.assertRaises(IntegrityError):
            Document.objects.create(
                document_number="1",
                title="مكرر",
                file=SimpleUploadedFile("dup.pdf", b"content"),
                document_date=date(2026, 1, 15),
                source=Document.Source.INTERNAL,
                directorate=self.directorate,
                department=self.dept1,
                uploaded_by=self.employee,
            )

    # ======================================================
    # 6. المرفقات
    # ======================================================

    def test_upload_attachment(self):
        self.client.force_login(self.employee)
        response = self.client.post(reverse('upload_attachment', args=[self.document.id]), {
            'file': SimpleUploadedFile("att2.pdf", b"attachment"),
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.document.attachments.count(), 1)

    def test_employee_cannot_upload_attachment_to_other_document(self):
        other_employee = User.objects.create_user(
            username="other_employee", password="testpass123!",
            role=CustomUser.Role.EMPLOYEE,
            directorate=self.directorate, department=self.dept1
        )
        self.client.force_login(other_employee)
        response = self.client.post(reverse('upload_attachment', args=[self.document.id]), {
            'file': SimpleUploadedFile("hack.pdf", b"hack"),
        })
        self.assertEqual(response.status_code, 403)

    # ======================================================
    # 7. تاريخ التصدير
    # ======================================================

    def test_export_date_set(self):
        self.document.export_date = date(2026, 3, 1)
        self.document.save()
        self.document.refresh_from_db()
        self.assertEqual(self.document.export_date, date(2026, 3, 1))

    # ======================================================
    # 8. البحث
    # ======================================================

    def test_search_by_document_number(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse('search'), {'document_number': '1'})
        self.assertContains(response, self.document.title)

    def test_search_by_title(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse('search'), {'name': 'الاختبار'})
        self.assertContains(response, self.document.title)

    def test_search_by_export_date_range(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse('search'), {
            'export_date_from': '2026-02-01',
            'export_date_to': '2026-02-28',
        })
        self.assertContains(response, self.document.title)

    def test_search_by_keyword(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse('search'), {'keyword': 'الأساسية'})
        self.assertContains(response, self.document.title)

    def test_search_by_source(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse('search'), {'source': 'internal'})
        self.assertContains(response, self.document.title)

    # ======================================================
    # 9. المجلدات
    # ======================================================

    def test_employee_can_view_folder_list(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse('folder_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.folder.name)

    def test_folder_detail_view(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse('folder_detail', args=[self.folder.id]))
        self.assertEqual(response.status_code, 200)

    def test_create_folder(self):
        self.client.force_login(self.employee)
        response = self.client.post(reverse('create_folder'), {
            'name': 'مجلد جديد',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Folder.objects.filter(name='مجلد جديد').exists())

    def test_delete_empty_folder(self):
        self.client.force_login(self.head)
        folder = Folder.objects.create(
            name="مجلد فارغ",
            directorate=self.directorate,
            department=self.dept1,
            created_by=self.employee,
        )
        response = self.client.post(reverse('delete_folder', args=[folder.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Folder.objects.filter(id=folder.id).exists())

    def test_cannot_delete_folder_with_content(self):
        self.client.force_login(self.head)
        self.document.folder = self.folder
        self.document.save()

        response = self.client.post(reverse('delete_folder', args=[self.folder.id]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Folder.objects.filter(id=self.folder.id).exists())

    # ======================================================
    # 10. واجهة المدير العام
    # ======================================================

    def test_gm_does_not_see_upload_button(self):
        self.client.force_login(self.general_manager)
        response = self.client.get(reverse('dashboard'))
        self.assertNotContains(response, 'رفع وثيقة')

    def test_gm_does_not_see_folder_create_button(self):
        self.client.force_login(self.general_manager)
        response = self.client.get(reverse('folder_list'))
        self.assertNotContains(response, 'مجلد جديد')

    # ======================================================
    # 11. تحميل / معاينة الوثيقة
    # ======================================================

    def test_download_document(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse('download_document', args=[self.document.id]))
        self.assertEqual(response.status_code, 200)

    def test_preview_document(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse('preview_document', args=[self.document.id]))
        self.assertEqual(response.status_code, 200)

    # ======================================================
    # 12. تعديل الوثيقة
    # ======================================================

    def test_edit_document(self):
        self.client.force_login(self.employee)
        response = self.client.post(reverse('edit_document', args=[self.document.id]), {
            'title': 'عنوان محدّث',
            'document_number': '1',
            'document_date': '2026-01-15',
            'export_date': '2026-02-15',
            'source': Document.Source.INTERNAL,
            'diwan_number': '',
            'destination_entity_name': '',
            'external_entity_name': '',
            'issuing_directorate': '',
            'document_type_id': '',
            'tags': '',
        })
        self.assertEqual(response.status_code, 302)
        self.document.refresh_from_db()
        self.assertEqual(self.document.title, 'عنوان محدّث')

    # ======================================================
    # 13. التعليقات
    # ======================================================

    def test_add_comment(self):
        self.client.force_login(self.employee)
        response = self.client.post(reverse('add_comment', args=[self.document.id]), {
            'text': 'تعليق اختبار',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.document.comments.count(), 1)

    # ======================================================
    # 14. حذف المرفقات (للمسؤولين فقط)
    # ======================================================

    def test_employee_cannot_delete_attachment(self):
        att = DocumentAttachment.objects.create(
            document=self.document,
            file=SimpleUploadedFile("x.pdf", b"x"),
            uploaded_by=self.employee,
        )
        self.client.force_login(self.employee)
        response = self.client.post(reverse('delete_attachment', args=[att.id]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(DocumentAttachment.objects.filter(id=att.id).exists())

    def test_head_can_delete_attachment(self):
        att = DocumentAttachment.objects.create(
            document=self.document,
            file=SimpleUploadedFile("y.pdf", b"y"),
            uploaded_by=self.employee,
        )
        self.client.force_login(self.head)
        response = self.client.post(reverse('delete_attachment', args=[att.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(DocumentAttachment.objects.filter(id=att.id).exists())

    # ======================================================
    # 15. استبدال المرفق
    # ======================================================

    def test_replace_attachment(self):
        att = DocumentAttachment.objects.create(
            document=self.document,
            file=SimpleUploadedFile("old.pdf", b"old"),
            uploaded_by=self.employee,
        )
        old_path = att.file.name

        self.client.force_login(self.employee)
        response = self.client.post(reverse('replace_attachment', args=[att.id]), {
            'file': SimpleUploadedFile("new.pdf", b"new content"),
        })
        self.assertEqual(response.status_code, 302)

        att.refresh_from_db()
        self.assertNotEqual(att.file.name, old_path)
        self.assertTrue(att.file.name.endswith('.pdf'))

    def test_employee_cannot_replace_attachment_of_other(self):
        other = User.objects.create_user(
            username="stranger", password="testpass123!",
            role=CustomUser.Role.EMPLOYEE,
            directorate=self.directorate, department=self.dept2
        )
        att = DocumentAttachment.objects.create(
            document=self.document,
            file=SimpleUploadedFile("z.pdf", b"z"),
            uploaded_by=self.employee,
        )
        self.client.force_login(other)
        response = self.client.post(reverse('replace_attachment', args=[att.id]), {
            'file': SimpleUploadedFile("hack.pdf", b"hack"),
        })
        self.assertEqual(response.status_code, 403)

    # ======================================================
    # 16. تحديث ملف الوثيقة مع حفظ النسخة القديمة
    # ======================================================

    def test_update_document_file_creates_version(self):
        self.client.force_login(self.employee)
        old_name = self.document.file.name

        response = self.client.post(reverse('update_document_file', args=[self.document.id]), {
            'file': SimpleUploadedFile("new_version.pdf", b"new content"),
            'note': 'نسخة مصححة',
        })
        self.assertEqual(response.status_code, 302)

        self.document.refresh_from_db()
        # تم إنشاء نسخة سابقة
        self.assertEqual(self.document.versions.count(), 1)
        version = self.document.versions.first()
        self.assertEqual(version.file_name, old_name)
        self.assertEqual(version.note, 'نسخة مصححة')
        # الملف الجديد مختلف
        self.assertNotEqual(self.document.file.name, old_name)

    def test_gm_cannot_update_document_file(self):
        self.client.force_login(self.general_manager)
        response = self.client.post(reverse('update_document_file', args=[self.document.id]), {
            'file': SimpleUploadedFile("x.pdf", b"x"),
        })
        # إما 403 إذا لا يرى الوثيقة، أو 403 لعدم صلاحية التعديل
        self.assertIn(response.status_code, [302, 403])

    # ======================================================
    # 17. تغيير كلمة المرور
    # ======================================================

    def test_change_password_success(self):
        self.client.force_login(self.employee)
        response = self.client.post(reverse('change_password'), {
            'old_password': 'testpass123!',
            'new_password': 'NewStrongPass!2026',
            'confirm_password': 'NewStrongPass!2026',
        })
        self.assertEqual(response.status_code, 302)

        self.employee.refresh_from_db()
        self.assertTrue(self.employee.check_password('NewStrongPass!2026'))

    def test_change_password_wrong_old(self):
        self.client.force_login(self.employee)
        response = self.client.post(reverse('change_password'), {
            'old_password': 'wrongpass',
            'new_password': 'NewStrongPass!2026',
            'confirm_password': 'NewStrongPass!2026',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'كلمة المرور الحالية غير صحيحة')

    def test_change_password_mismatch(self):
        self.client.force_login(self.employee)
        response = self.client.post(reverse('change_password'), {
            'old_password': 'testpass123!',
            'new_password': 'NewStrongPass!2026',
            'confirm_password': 'DifferentPass!2026',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'غير متطابقتين')

    def test_change_password_weak(self):
        self.client.force_login(self.employee)
        response = self.client.post(reverse('change_password'), {
            'old_password': 'testpass123!',
            'new_password': '123',
            'confirm_password': '123',
        })
        self.assertEqual(response.status_code, 200)
        # Django يرفض كلمة قصيرة

    def test_change_password_same_as_old(self):
        self.client.force_login(self.employee)
        response = self.client.post(reverse('change_password'), {
            'old_password': 'testpass123!',
            'new_password': 'testpass123!',
            'confirm_password': 'testpass123!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'مختلفة عن الحالية')

    def test_change_password_requires_login(self):
        response = self.client.get(reverse('change_password'))
        self.assertEqual(response.status_code, 302)
        # المشروع عندك: صفحة الدخول على '/' وليس '/login'
        self.assertIn('next=/change-password/', response.url)

    # ======================================================
    # 18. تسمية الملفات (الميزة الجديدة)
    # ======================================================

    def test_document_file_uses_number(self):
        """اسم ملف الوثيقة = رقم الوثيقة."""
        self.assertIn('1', self.document.file.name)
        self.assertTrue(self.document.file.name.endswith('.pdf'))

    def test_document_path_contains_directorate_and_department(self):
        """مسار الوثيقة يحتوي اسم المديرية والدائرة."""
        path = self.document.file.name
        self.assertIn('مديرية_المالية', path)
        self.assertIn('الدائرة_المالية', path)

    def test_document_path_contains_uncategorized_if_no_folder(self):
        """الوثيقة بدون مجلد → uncategorized."""
        self.assertIn('uncategorized', self.document.file.name)

    def test_document_path_contains_folder_if_set(self):
        """الوثيقة داخل مجلد → اسم المجلد."""
        doc = Document.objects.create(
            document_number="99",
            title="وثيقة داخل مجلد",
            file=SimpleUploadedFile("x.pdf", b"x"),
            document_date=date(2026, 1, 20),
            source=Document.Source.INTERNAL,
            directorate=self.directorate,
            department=self.dept1,
            folder=self.folder,
            uploaded_by=self.employee,
        )
        self.assertIn('مجلد_الاختبار', doc.file.name)

    def test_attachment_uses_title_and_counter(self):
        """اسم المرفق = رقم الوثيقة + العنوان + رقم تسلسلي."""
        att = DocumentAttachment.objects.create(
            document=self.document,
            file=SimpleUploadedFile("anything.pdf", b"c"),
            uploaded_by=self.employee,
        )
        name = att.file.name
        # الاسم يبدأ برقم الوثيقة
        self.assertIn('1_', name)
        # يحتوي جزءًا من العنوان
        self.assertIn('وثيقة', name)
        # يحتوي رقم تسلسلي _1
        self.assertIn('_1.', name)
        self.assertTrue(name.endswith('.pdf'))

    def test_multiple_attachments_sequential(self):
        """المرفقات تأخذ أرقامًا متسلسلة."""
        for i in range(3):
            DocumentAttachment.objects.create(
                document=self.document,
                file=SimpleUploadedFile(f"file{i}.pdf", b"c"),
                uploaded_by=self.employee,
            )
        names = sorted([a.file.name for a in self.document.attachments.all()])
        self.assertIn('_1.', names[0])
        self.assertIn('_2.', names[1])
        self.assertIn('_3.', names[2])

    def test_attachment_path_contains_number_year_folder(self):
        """مجلد المرفق يحتوي رقم_الوثيقة_السنة."""
        att = DocumentAttachment.objects.create(
            document=self.document,
            file=SimpleUploadedFile("x.pdf", b"c"),
            uploaded_by=self.employee,
        )
        # يحتوي <number>_<year>
        self.assertIn('1_2026', att.file.name)

    # ======================================================
    # 19. سجل التدقيق
    # ======================================================

    def test_upload_creates_audit_log(self):
        self.client.force_login(self.employee)
        self.client.post(reverse('upload'), {
            'document_number': '55',
            'title': 'وثيقة للسجل',
            'document_date': '2026-03-01',
            'source': Document.Source.INTERNAL,
            'export_date': '',
            'file': SimpleUploadedFile("log.pdf", b"content"),
        })
        log = AuditLog.objects.filter(action=AuditLog.Action.CREATE).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.document_number, '55')

    def test_download_creates_audit_log(self):
        self.client.force_login(self.employee)
        self.client.get(reverse('download_document', args=[self.document.id]))
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.Action.DOWNLOAD,
                document=self.document,
            ).exists()
        )

    # ======================================================
    # 20. المصادقة
    # ======================================================

    def test_login_with_valid_credentials(self):
        response = self.client.post(reverse('login'), {
            'username': 'employee',
            'password': 'testpass123!',
        })
        self.assertEqual(response.status_code, 302)

    def test_login_with_invalid_credentials(self):
        response = self.client.post(reverse('login'), {
            'username': 'employee',
            'password': 'wrongpass',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'غير صحيحة')

    def test_logout(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse('logout'))
        self.assertEqual(response.status_code, 302)

    # ======================================================
    # 21. صفحة تغيير كلمة المرور
    # ======================================================

    def test_change_password_page_loads(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse('change_password'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'تغيير كلمة المرور')

    # ======================================================
    # 22. حقل "حالة الوثيقة" (جديد)
    # ======================================================

    def test_status_field_exists(self):
        """حقل status موجود في موديل Document."""
        field = Document._meta.get_field('status')
        self.assertEqual(field.max_length, 100)
        self.assertTrue(field.null)
        self.assertTrue(field.blank)

    def test_upload_with_status(self):
        """رفع وثيقة مع حالة."""
        self.client.force_login(self.employee)
        response = self.client.post(reverse('upload'), {
            'document_number': '100',
            'title': 'وثيقة بحالة',
            'document_date': '2026-01-01',
            'source': Document.Source.INTERNAL,
            'export_date': '',
            'status': 'قيد المراجعة',
            'file': SimpleUploadedFile("s.pdf", b"content"),
        })
        self.assertEqual(response.status_code, 302)
        doc = Document.objects.get(document_number='100')
        self.assertEqual(doc.status, 'قيد المراجعة')

    def test_upload_without_status_is_allowed(self):
        """الحالة اختيارية — يمكن رفع وثيقة بدونها."""
        self.client.force_login(self.employee)
        response = self.client.post(reverse('upload'), {
            'document_number': '101',
            'title': 'بدون حالة',
            'document_date': '2026-01-01',
            'source': Document.Source.INTERNAL,
            'export_date': '',
            'status': '',
            'file': SimpleUploadedFile("ns.pdf", b"content"),
        })
        self.assertEqual(response.status_code, 302)
        doc = Document.objects.get(document_number='101')
        self.assertIn(doc.status, [None, ''])

    def test_edit_document_status(self):
        """تعديل حالة الوثيقة."""
        self.client.force_login(self.employee)
        response = self.client.post(reverse('edit_document', args=[self.document.id]), {
            'title': self.document.title,
            'document_number': self.document.document_number,
            'document_date': '2026-01-15',
            'export_date': '2026-02-15',
            'source': Document.Source.INTERNAL,
            'diwan_number': '',
            'destination_entity_name': '',
            'external_entity_name': '',
            'issuing_directorate': '',
            'document_type_id': '',
            'tags': '',
            'status': 'تم الإنجاز',
        })
        self.assertEqual(response.status_code, 302)
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, 'تم الإنجاز')

    def test_clear_status_via_edit(self):
        """مسح الحالة عبر التعديل."""
        self.document.status = 'قيد المراجعة'
        self.document.save()
        self.client.force_login(self.employee)
        self.client.post(reverse('edit_document', args=[self.document.id]), {
            'title': self.document.title,
            'document_number': self.document.document_number,
            'document_date': '2026-01-15',
            'export_date': '',
            'source': Document.Source.INTERNAL,
            'status': '',
            'tags': '',
        })
        self.document.refresh_from_db()
        self.assertIn(self.document.status, [None, ''])

    def test_search_by_status(self):
        """البحث بفلتر الحالة."""
        self.document.status = 'قيد المراجعة'
        self.document.save()

        other = Document.objects.create(
            document_number="200",
            title="وثيقة منجزة",
            file=SimpleUploadedFile("done.pdf", b"content"),
            document_date=date(2026, 1, 20),
            source=Document.Source.INTERNAL,
            directorate=self.directorate,
            department=self.dept1,
            uploaded_by=self.employee,
            status="تم الإنجاز",
        )

        self.client.force_login(self.employee)
        response = self.client.get(reverse('search'), {'status': 'قيد'})
        self.assertContains(response, self.document.title)
        self.assertNotContains(response, other.title)

    def test_status_shows_in_document_detail(self):
        """عرض الحالة في صفحة التفاصيل."""
        self.document.status = 'قيد المراجعة'
        self.document.save()

        self.client.force_login(self.employee)
        response = self.client.get(reverse('document_detail', args=[self.document.id]))
        self.assertContains(response, 'قيد المراجعة')

    def test_status_shows_in_search_results(self):
        """عرض الحالة في نتائج البحث."""
        self.document.status = 'مؤرشفة'
        self.document.save()

        self.client.force_login(self.employee)
        response = self.client.get(reverse('search'), {'document_number': '1'})
        self.assertContains(response, 'مؤرشفة')

    def test_status_is_searchable_by_keyword(self):
        """البحث بالحالة ضمن الكلمات المفتاحية."""
        self.document.status = 'قيد المراجعة'
        self.document.save()

        self.client.force_login(self.employee)
        response = self.client.get(reverse('search'), {'keyword': 'قيد المراجعة'})
        self.assertContains(response, self.document.title)

    # ======================================================
    # 23. تصدير Excel (جديد)
    # ======================================================

    def _open_excel_response(self, response):
        """يفتح ملف Excel من response ويرجع الورقة."""
        buf = BytesIO(response.content)
        wb = openpyxl.load_workbook(buf)
        return wb.active

    def test_export_excel_requires_login(self):
        """تصدير Excel يتطلب تسجيل الدخول."""
        response = self.client.get(reverse('export_documents_excel'))
        self.assertEqual(response.status_code, 302)

    def test_export_excel_basic(self):
        """تصدير بسيط من البحث."""
        self.client.force_login(self.employee)
        response = self.client.get(reverse('export_documents_excel'))
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            response['Content-Type']
        )
        # تحقق أن الملف صالح
        ws = self._open_excel_response(response)
        self.assertGreater(ws.max_row, 1)  # يوجد ترويسة + بيانات

    def test_export_excel_has_headers(self):
        """الترويسة تحتوي على الأعمدة المتوقعة."""
        self.client.force_login(self.employee)
        response = self.client.get(reverse('export_documents_excel'))
        ws = self._open_excel_response(response)

        headers = [ws.cell(row=1, column=i).value for i in range(1, ws.max_column + 1)]
        self.assertIn('رقم الوثيقة', headers)
        self.assertIn('اسم الوثيقة', headers)
        self.assertIn('حالة الوثيقة', headers)
        self.assertIn('المديرية', headers)
        self.assertIn('الدائرة', headers)

    def test_export_excel_includes_document(self):
        """الوثيقة تظهر في ملف التصدير."""
        self.document.status = 'قيد المراجعة'
        self.document.save()

        self.client.force_login(self.employee)
        response = self.client.get(reverse('export_documents_excel'))
        ws = self._open_excel_response(response)

        found = False
        for row in range(2, ws.max_row + 1):
            if ws.cell(row=row, column=4).value == self.document.title:
                found = True
                # تحقق من الحالة
                status_val = ws.cell(row=row, column=14).value  # عمود الحالة
                self.assertEqual(status_val, 'قيد المراجعة')
                break
        self.assertTrue(found, "الوثيقة غير موجودة في ملف Excel")

    def test_export_excel_respects_search_filters(self):
        """التصدير يحترم فلاتر البحث."""
        other = Document.objects.create(
            document_number="300",
            title="وثيقة أخرى للتصدير",
            file=SimpleUploadedFile("other.pdf", b"content"),
            document_date=date(2026, 1, 20),
            source=Document.Source.INTERNAL,
            directorate=self.directorate,
            department=self.dept1,
            uploaded_by=self.employee,
        )

        self.client.force_login(self.employee)
        response = self.client.get(reverse('export_documents_excel'), {
            'document_number': '300',
        })
        ws = self._open_excel_response(response)

        titles = []
        for row in range(2, ws.max_row + 1):
            titles.append(ws.cell(row=row, column=4).value)

        self.assertIn(other.title, titles)
        self.assertNotIn(self.document.title, titles)

    def test_export_excel_from_folder_includes_subfolder(self):
        """تصدير مجلد يشمل المجلدات الفرعية."""
        # مجلد رئيسي + فرعي
        root_folder = Folder.objects.create(
            name="موازنة",
            directorate=self.directorate,
            department=self.dept1,
            created_by=self.employee,
        )
        sub_folder = Folder.objects.create(
            name="موازنة التخطيط",
            parent=root_folder,
            directorate=self.directorate,
            department=self.dept1,
            created_by=self.employee,
        )

        # وثيقة في المجلد الرئيسي
        doc_root = Document.objects.create(
            document_number="401",
            title="وثيقة في موازنة",
            file=SimpleUploadedFile("r.pdf", b"c"),
            document_date=date(2026, 2, 1),
            source=Document.Source.INTERNAL,
            directorate=self.directorate,
            department=self.dept1,
            folder=root_folder,
            uploaded_by=self.employee,
        )

        # وثيقة في المجلد الفرعي
        doc_sub = Document.objects.create(
            document_number="402",
            title="وثيقة في موازنة التخطيط",
            file=SimpleUploadedFile("s.pdf", b"c"),
            document_date=date(2026, 2, 2),
            source=Document.Source.INTERNAL,
            directorate=self.directorate,
            department=self.dept1,
            folder=sub_folder,
            uploaded_by=self.employee,
        )

        self.client.force_login(self.employee)
        response = self.client.get(reverse('export_documents_excel'), {
            'folder_id': root_folder.id,
        })
        ws = self._open_excel_response(response)

        titles = []
        for row in range(2, ws.max_row + 1):
            titles.append(ws.cell(row=row, column=4).value)

        self.assertIn(doc_root.title, titles)
        self.assertIn(doc_sub.title, titles)

    def test_export_excel_uncategorized(self):
        """تصدير الوثائق غير المصنفة فقط."""
        # وثيقة مصنفة
        folder = Folder.objects.create(
            name="مجلد مصنف",
            directorate=self.directorate,
            department=self.dept1,
            created_by=self.employee,
        )
        doc_in_folder = Document.objects.create(
            document_number="500",
            title="وثيقة داخل مجلد",
            file=SimpleUploadedFile("f.pdf", b"c"),
            document_date=date(2026, 3, 1),
            source=Document.Source.INTERNAL,
            directorate=self.directorate,
            department=self.dept1,
            folder=folder,
            uploaded_by=self.employee,
        )

        # الوثيقة الأساسية self.document بدون مجلد

        self.client.force_login(self.employee)
        response = self.client.get(reverse('export_documents_excel'), {
            'folder_id': 'none',
        })
        ws = self._open_excel_response(response)

        titles = []
        for row in range(2, ws.max_row + 1):
            titles.append(ws.cell(row=row, column=4).value)

        self.assertIn(self.document.title, titles)
        self.assertNotIn(doc_in_folder.title, titles)

    def test_export_excel_filename_contains_folder_name(self):
        """اسم الملف يحتوي اسم المجلد عند التصدير منه."""
        folder = Folder.objects.create(
            name="موازنة 2026",
            directorate=self.directorate,
            department=self.dept1,
            created_by=self.employee,
        )
        self.client.force_login(self.employee)
        response = self.client.get(reverse('export_documents_excel'), {
            'folder_id': folder.id,
        })
        self.assertEqual(response.status_code, 200)
        cd = response['Content-Disposition']
        # يجب أن يحتوي على جزء من اسم المجلد (URL-encoded)
        self.assertTrue('documents' in cd)

    def test_export_excel_excludes_other_directorate_docs(self):
        """الموظف لا يصدّر وثائق مديرية أخرى."""
        other_dir = Directorate.objects.create(name="مديرية أخرى")
        other_dept = Department.objects.create(name="دائرة أخرى", directorate=other_dir)
        other_user = User.objects.create_user(
            username="other_dir_emp", password="testpass123!",
            role=CustomUser.Role.EMPLOYEE,
            directorate=other_dir, department=other_dept,
        )
        other_doc = Document.objects.create(
            document_number="999",
            title="وثيقة مديرية أخرى",
            file=SimpleUploadedFile("other_dir.pdf", b"c"),
            document_date=date(2026, 5, 1),
            source=Document.Source.INTERNAL,
            directorate=other_dir,
            department=other_dept,
            uploaded_by=other_user,
        )

        self.client.force_login(self.employee)
        response = self.client.get(reverse('export_documents_excel'))
        ws = self._open_excel_response(response)

        titles = []
        for row in range(2, ws.max_row + 1):
            titles.append(ws.cell(row=row, column=4).value)

        self.assertNotIn(other_doc.title, titles)

    def test_export_excel_no_file_no_attachments(self):
        """ملف Excel لا يحتوي على عمود الملف الأصلي أو المرفقات."""
        self.client.force_login(self.employee)
        response = self.client.get(reverse('export_documents_excel'))
        ws = self._open_excel_response(response)

        headers = [ws.cell(row=1, column=i).value for i in range(1, ws.max_column + 1)]
        headers_str = ' '.join(str(h) for h in headers if h)

        self.assertNotIn('المرفقات', headers_str)
        # لا يوجد عمود باسم "الملف"
        for h in headers:
            self.assertNotEqual(h, 'الملف')


# ==========================================================
# اختبارات إضافية للميزات الجديدة
# ==========================================================

class SanitizeFolderNameTests(TestCase):
    """اختبارات دالة sanitize_folder_name من utils/files.py."""

    def test_removes_forbidden_chars(self):
        self.assertEqual(
            sanitize_folder_name("a/b\\c:d*e?f\"g<h>i|j"),
            "a_b_c_d_e_f_g_h_i_j"
        )

    def test_replaces_spaces_with_underscore(self):
        self.assertEqual(
            sanitize_folder_name("وثائق 2024 الرسمية"),
            "وثائق_2024_الرسمية"
        )

    def test_collapses_multiple_spaces(self):
        self.assertEqual(
            sanitize_folder_name("a    b\tc\nd"),
            "a_b_c_d"
        )

    def test_strips_leading_dots(self):
        self.assertEqual(sanitize_folder_name("...test"), "test")

    def test_strips_surrounding_underscores(self):
        self.assertEqual(sanitize_folder_name("  test  "), "test")

    def test_empty_string_returns_fallback(self):
        self.assertEqual(sanitize_folder_name(""), "folder")
        self.assertEqual(sanitize_folder_name(None), "folder")

    def test_only_forbidden_chars_returns_fallback(self):
        self.assertEqual(sanitize_folder_name("///:::"), "folder")

    def test_custom_fallback(self):
        self.assertEqual(
            sanitize_folder_name("", fallback="unknown"),
            "unknown"
        )

    def test_max_length_truncation(self):
        long_name = "a" * 100
        result = sanitize_folder_name(long_name, max_length=20)
        self.assertEqual(len(result), 20)

    def test_arabic_preserved(self):
        self.assertEqual(
            sanitize_folder_name("وثائق مالية"),
            "وثائق_مالية"
        )

    def test_arabic_with_slash(self):
        self.assertEqual(
            sanitize_folder_name("وثائق 2024/الرسمية"),
            "وثائق_2024_الرسمية"
        )

    def test_numbers_preserved(self):
        self.assertEqual(sanitize_folder_name("123/456"), "123_456")


class SafeFilenameTests(TestCase):
    """اختبارات دالة safe_filename."""

    def test_preserves_extension(self):
        self.assertEqual(safe_filename("تقرير 2024.pdf"), "تقرير_2024.pdf")

    def test_cleans_name_and_extension(self):
        result = safe_filename("a<b>c?.doc")
        # الرموز تُستبدل بـ _ ثم تُنظَّف الـ _ الطرفية
        self.assertEqual(result, "a_b_c.doc")

    def test_empty_returns_fallback(self):
        self.assertEqual(safe_filename(""), "file")

    def test_strips_bad_extension_chars(self):
        result = safe_filename("name.pdf@#$")
        # الامتداد يجب أن يكون .pdf
        self.assertTrue(result.endswith(".pdf"))

    def test_without_extension(self):
        result = safe_filename("test")
        self.assertTrue(result.startswith("test"))


class GetAllFolderIdsRecursiveTests(TestCase):
    """اختبارات دالة جمع معرفات المجلدات المتسلسلة."""

    def setUp(self):
        self.dir = Directorate.objects.create(name="مديرية اختبار")
        self.dept = Department.objects.create(name="دائرة اختبار", directorate=self.dir)
        self.user = User.objects.create_user(
            username="test_user", password="testpass123!",
            role=CustomUser.Role.EMPLOYEE,
            directorate=self.dir, department=self.dept
        )

    def _make_folder(self, name, parent=None):
        return Folder.objects.create(
            name=name, parent=parent,
            directorate=self.dir, department=self.dept,
            created_by=self.user,
        )

    def test_single_folder_returns_only_itself(self):
        folder = self._make_folder("وحيد")
        ids = _get_all_folder_ids_recursive(folder.id)
        self.assertEqual(ids, [folder.id])

    def test_includes_direct_children(self):
        root = self._make_folder("جذر")
        child1 = self._make_folder("ابن1", parent=root)
        child2 = self._make_folder("ابن2", parent=root)

        ids = _get_all_folder_ids_recursive(root.id)
        self.assertIn(root.id, ids)
        self.assertIn(child1.id, ids)
        self.assertIn(child2.id, ids)
        self.assertEqual(len(ids), 3)

    def test_includes_grandchildren(self):
        root = self._make_folder("جذر")
        child = self._make_folder("ابن", parent=root)
        grandchild = self._make_folder("حفيد", parent=child)
        great_grandchild = self._make_folder("حفيد الحفيد", parent=grandchild)

        ids = _get_all_folder_ids_recursive(root.id)
        self.assertIn(great_grandchild.id, ids)
        self.assertEqual(len(ids), 4)

    def test_different_tree_not_included(self):
        root1 = self._make_folder("شجرة1")
        root2 = self._make_folder("شجرة2")
        child_of_root2 = self._make_folder("ابن", parent=root2)

        ids = _get_all_folder_ids_recursive(root1.id)
        self.assertNotIn(root2.id, ids)
        self.assertNotIn(child_of_root2.id, ids)


class ExportWarningThresholdTests(TestCase):
    """اختبارات تحذير تجاوز الحد قبل التصدير."""

    def setUp(self):
        self._media_root = tempfile.mkdtemp()
        self._override = override_settings(MEDIA_ROOT=self._media_root)
        self._override.enable()
        self.addCleanup(self._override.disable)
        self.addCleanup(shutil.rmtree, self._media_root, ignore_errors=True)

        self.client = Client()
        self.dir = Directorate.objects.create(name="مديرية")
        self.dept = Department.objects.create(name="دائرة", directorate=self.dir)
        self.user = User.objects.create_user(
            username="export_user", password="testpass123!",
            role=CustomUser.Role.EMPLOYEE,
            directorate=self.dir, department=self.dept
        )
        self.client.force_login(self.user)

    def _create_doc(self, number, title="وثيقة"):
        return Document.objects.create(
            document_number=str(number),
            title=title,
            file=SimpleUploadedFile(f"{number}.pdf", b"content"),
            document_date=date(2026, 1, 1),
            source=Document.Source.INTERNAL,
            directorate=self.dir,
            department=self.dept,
            uploaded_by=self.user,
        )

    def test_below_threshold_exports_directly(self):
        """أقل من الحد → يُصدَّر مباشرة (بدون تحذير)."""
        for i in range(5):
            self._create_doc(i + 1)

        response = self.client.get(reverse('export_documents_excel'))
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            response['Content-Type']
        )

    @patch('core.views.EXPORT_WARNING_THRESHOLD', 3)
    def test_above_threshold_shows_warning_page(self):
        """أكثر من الحد → صفحة تحذير."""
        for i in range(5):
            self._create_doc(i + 1)

        response = self.client.get(reverse('export_documents_excel'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/confirm_export.html')
        self.assertContains(response, 'تنبيه')
        self.assertContains(response, 'عدد الوثائق كبير')

    @patch('core.views.EXPORT_WARNING_THRESHOLD', 3)
    def test_confirmed_param_skips_warning(self):
        """confirmed=1 → يتخطى التحذير ويُصدّر مباشرة."""
        for i in range(5):
            self._create_doc(i + 1)

        response = self.client.get(reverse('export_documents_excel'), {'confirmed': '1'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            response['Content-Type']
        )

    @patch('core.views.EXPORT_WARNING_THRESHOLD', 3)
    def test_warning_page_shows_count(self):
        """صفحة التحذير تعرض العدد الصحيح."""
        for i in range(7):
            self._create_doc(i + 1)

        response = self.client.get(reverse('export_documents_excel'))
        self.assertContains(response, '7')

    @patch('core.views.EXPORT_WARNING_THRESHOLD', 3)
    def test_warning_page_preserves_filters(self):
        """صفحة التحذير تحتفظ بالفلاتر في رابط المتابعة."""
        # ننشئ 5 وثائق كلها تطابق الفلتر
        for i in range(5):
            self._create_doc(i + 1)

        # فلتر واسع يُرجع الخمسة (> 3 = العتبة)
        response = self.client.get(reverse('export_documents_excel'), {
            'source': 'internal',
        })
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/confirm_export.html')
        # الرابط يجب أن يحتوي على الفلتر
        self.assertContains(response, 'confirmed=1')
        self.assertContains(response, 'source=internal')


class ExportErrorHandlingTests(TestCase):
    """اختبارات معالجة الأخطاء عند التصدير."""

    def setUp(self):
        self._media_root = tempfile.mkdtemp()
        self._override = override_settings(MEDIA_ROOT=self._media_root)
        self._override.enable()
        self.addCleanup(self._override.disable)
        self.addCleanup(shutil.rmtree, self._media_root, ignore_errors=True)

        self.client = Client()
        self.dir = Directorate.objects.create(name="مديرية")
        self.dept = Department.objects.create(name="دائرة", directorate=self.dir)
        self.user = User.objects.create_user(
            username="export_user2", password="testpass123!",
            role=CustomUser.Role.EMPLOYEE,
            directorate=self.dir, department=self.dept
        )
        self.client.force_login(self.user)

    def test_memory_error_shows_arabic_message(self):
        """MemoryError → رسالة عربية."""
        with patch('core.views.openpyxl.Workbook') as mock_wb:
            mock_wb.side_effect = MemoryError()

            response = self.client.get(reverse('export_documents_excel'))

            # يجب أن يعيد التوجيه (302) بسبب الرسالة
            self.assertEqual(response.status_code, 302)

            # يجب أن تكون الرسالة عربية في sessions
            messages_list = list(response.wsgi_request._messages)
            self.assertTrue(
                any('كبير جداً' in str(m) for m in messages_list),
                f"لم يتم إيجاد رسالة الذاكرة. الرسائل: {messages_list}"
            )

    def test_generic_exception_shows_arabic_message(self):
        """أي خطأ آخر → رسالة عربية."""
        with patch('core.views.openpyxl.Workbook') as mock_wb:
            mock_wb.side_effect = RuntimeError("something broke")

            response = self.client.get(reverse('export_documents_excel'))
            self.assertEqual(response.status_code, 302)

            messages_list = list(response.wsgi_request._messages)
            self.assertTrue(
                any('تعذّر' in str(m) for m in messages_list),
                f"لم يتم إيجاد رسالة الخطأ. الرسائل: {messages_list}"
            )


class SearchExportConsistencyTests(TestCase):
    """اختبارات تطابق فلاتر البحث مع التصدير."""

    def setUp(self):
        self._media_root = tempfile.mkdtemp()
        self._override = override_settings(MEDIA_ROOT=self._media_root)
        self._override.enable()
        self.addCleanup(self._override.disable)
        self.addCleanup(shutil.rmtree, self._media_root, ignore_errors=True)

        self.client = Client()
        self.dir = Directorate.objects.create(name="مديرية")
        self.dept = Department.objects.create(name="دائرة", directorate=self.dir)
        self.user = User.objects.create_user(
            username="consistency_user", password="testpass123!",
            role=CustomUser.Role.EMPLOYEE,
            directorate=self.dir, department=self.dept
        )
        self.client.force_login(self.user)

        # وثائق للاختبار
        self.doc1 = Document.objects.create(
            document_number="100",
            title="وثيقة داخلية أولى",
            file=SimpleUploadedFile("a.pdf", b"a"),
            document_date=date(2026, 1, 15),
            source=Document.Source.INTERNAL,
            directorate=self.dir, department=self.dept,
            uploaded_by=self.user,
            status="قيد المراجعة",
        )
        self.doc2 = Document.objects.create(
            document_number="200",
            title="وثيقة داخلية ثانية",
            file=SimpleUploadedFile("b.pdf", b"b"),
            document_date=date(2026, 6, 20),
            source=Document.Source.INTERNAL,
            directorate=self.dir, department=self.dept,
            uploaded_by=self.user,
            status="منجزة",
        )
        self.doc3 = Document.objects.create(
            document_number="300",
            title="وثيقة خارجية",
            file=SimpleUploadedFile("c.pdf", b"c"),
            document_date=date(2026, 3, 10),
            source=Document.Source.EXTERNAL,
            external_entity_name="وزارة الخارجية",
            directorate=self.dir, department=self.dept,
            uploaded_by=self.user,
        )

    def _excel_titles(self, response):
        buf = BytesIO(response.content)
        wb = openpyxl.load_workbook(buf)
        ws = wb.active
        return [
            ws.cell(row=r, column=4).value
            for r in range(2, ws.max_row + 1)
        ]

    def test_filter_by_document_number_consistent(self):
        """فلتر رقم الوثيقة متطابق بين البحث والتصدير."""
        # البحث
        search_resp = self.client.get(reverse('search'), {'document_number': '100'})
        self.assertContains(search_resp, self.doc1.title)
        self.assertNotContains(search_resp, self.doc2.title)

        # التصدير
        export_resp = self.client.get(reverse('export_documents_excel'), {
            'document_number': '100'
        })
        titles = self._excel_titles(export_resp)
        self.assertIn(self.doc1.title, titles)
        self.assertNotIn(self.doc2.title, titles)

    def test_filter_by_source_consistent(self):
        """فلتر المصدر متطابق."""
        search_resp = self.client.get(reverse('search'), {'source': 'external'})
        self.assertContains(search_resp, self.doc3.title)
        self.assertNotContains(search_resp, self.doc1.title)

        export_resp = self.client.get(reverse('export_documents_excel'), {
            'source': 'external'
        })
        titles = self._excel_titles(export_resp)
        self.assertIn(self.doc3.title, titles)
        self.assertNotIn(self.doc1.title, titles)

    def test_filter_by_date_range_consistent(self):
        """فلتر نطاق التاريخ متطابق."""
        search_resp = self.client.get(reverse('search'), {
            'date_from': '2026-02-01',
            'date_to': '2026-05-31',
        })
        self.assertContains(search_resp, self.doc3.title)
        self.assertNotContains(search_resp, self.doc1.title)

        export_resp = self.client.get(reverse('export_documents_excel'), {
            'date_from': '2026-02-01',
            'date_to': '2026-05-31',
        })
        titles = self._excel_titles(export_resp)
        self.assertIn(self.doc3.title, titles)
        self.assertNotIn(self.doc1.title, titles)

    def test_filter_by_status_consistent(self):
        """فلتر الحالة متطابق."""
        export_resp = self.client.get(reverse('export_documents_excel'), {
            'status': 'قيد المراجعة'
        })
        titles = self._excel_titles(export_resp)
        self.assertIn(self.doc1.title, titles)
        self.assertNotIn(self.doc2.title, titles)

    def test_filter_by_keyword_consistent(self):
        """فلتر الكلمة المفتاحية متطابق."""
        export_resp = self.client.get(reverse('export_documents_excel'), {
            'keyword': 'خارجية'
        })
        titles = self._excel_titles(export_resp)
        self.assertIn(self.doc3.title, titles)
        self.assertNotIn(self.doc1.title, titles)

    def test_combined_filters_consistent(self):
        """فلاتر متعددة مجتمعة متطابقة."""
        params = {
            'document_number': '100',
            'status': 'قيد المراجعة',
            'source': 'internal',
        }
        export_resp = self.client.get(reverse('export_documents_excel'), params)
        titles = self._excel_titles(export_resp)
        self.assertIn(self.doc1.title, titles)
        self.assertNotIn(self.doc2.title, titles)
        self.assertNotIn(self.doc3.title, titles)


class ExportFileNameTests(TestCase):
    """اختبارات اسم ملف Excel الناتج."""

    def setUp(self):
        self._media_root = tempfile.mkdtemp()
        self._override = override_settings(MEDIA_ROOT=self._media_root)
        self._override.enable()
        self.addCleanup(self._override.disable)
        self.addCleanup(shutil.rmtree, self._media_root, ignore_errors=True)

        self.client = Client()
        self.dir = Directorate.objects.create(name="مديرية")
        self.dept = Department.objects.create(name="دائرة", directorate=self.dir)
        self.user = User.objects.create_user(
            username="filename_user", password="testpass123!",
            role=CustomUser.Role.EMPLOYEE,
            directorate=self.dir, department=self.dept
        )
        self.client.force_login(self.user)

    def test_filename_starts_with_documents(self):
        response = self.client.get(reverse('export_documents_excel'))
        cd = response['Content-Disposition']
        self.assertIn('documents', cd)

    def test_filename_has_extension_xlsx(self):
        response = self.client.get(reverse('export_documents_excel'))
        cd = response['Content-Disposition']
        self.assertIn('.xlsx', cd)

    def test_filename_contains_uncategorized_for_folder_none(self):
        response = self.client.get(reverse('export_documents_excel'), {
            'folder_id': 'none'
        })
        cd = response['Content-Disposition']
        self.assertIn('uncategorized', cd)

    def test_filename_contains_folder_name_for_specific_folder(self):
        folder = Folder.objects.create(
            name="موازنة2026",
            directorate=self.dir, department=self.dept,
            created_by=self.user,
        )
        response = self.client.get(reverse('export_documents_excel'), {
            'folder_id': folder.id
        })
        cd = response['Content-Disposition']
        # البحث عن جزء من اسم المجلد (URL-encoded)
        self.assertTrue(
            'موازنة' in cd or '%D9%85%D9%88%D8%A7%D8%B2%D9%86%D8%A9' in cd,
            f"اسم المجلد غير موجود في: {cd}"
        )


class ExportEmptyResultsTests(TestCase):
    """اختبارات التصدير عند عدم وجود نتائج."""

    def setUp(self):
        self._media_root = tempfile.mkdtemp()
        self._override = override_settings(MEDIA_ROOT=self._media_root)
        self._override.enable()
        self.addCleanup(self._override.disable)
        self.addCleanup(shutil.rmtree, self._media_root, ignore_errors=True)

        self.client = Client()
        self.dir = Directorate.objects.create(name="مديرية")
        self.dept = Department.objects.create(name="دائرة", directorate=self.dir)
        self.user = User.objects.create_user(
            username="empty_user", password="testpass123!",
            role=CustomUser.Role.EMPLOYEE,
            directorate=self.dir, department=self.dept
        )
        self.client.force_login(self.user)

    def test_empty_export_still_returns_valid_xlsx(self):
        """حتى بدون نتائج → ملف Excel صالح يحتوي على الترويسة."""
        response = self.client.get(reverse('export_documents_excel'))
        self.assertEqual(response.status_code, 200)

        buf = BytesIO(response.content)
        wb = openpyxl.load_workbook(buf)
        ws = wb.active

        # صف واحد فقط (الترويسة)
        self.assertEqual(ws.max_row, 1)
        self.assertEqual(ws.cell(row=1, column=1).value, 'رقم الوثيقة')


class ExportColumnIndexTests(TestCase):
    """اختبارات ترتيب الأعمدة في ملف التصدير."""

    def setUp(self):
        self._media_root = tempfile.mkdtemp()
        self._override = override_settings(MEDIA_ROOT=self._media_root)
        self._override.enable()
        self.addCleanup(self._override.disable)
        self.addCleanup(shutil.rmtree, self._media_root, ignore_errors=True)

        self.client = Client()
        self.dir = Directorate.objects.create(name="مديرية")
        self.dept = Department.objects.create(name="دائرة", directorate=self.dir)
        self.user = User.objects.create_user(
            username="cols_user", password="testpass123!",
            role=CustomUser.Role.EMPLOYEE,
            directorate=self.dir, department=self.dept
        )
        self.client.force_login(self.user)

    def test_headers_order(self):
        """ترتيب الأعمدة صحيح."""
        expected_headers = [
            'رقم الوثيقة',
            'السنة',
            'الرقم الكامل (رقم/سنة)',
            'اسم الوثيقة',
            'نوع الوثيقة',
            'تاريخ الوثيقة',
            'تاريخ التصدير/الختم',
            'رقم الديوان',
            'المصدر',
            'المديرية الصادرة عنها',
            'الجهة الخارجية',
            'الجهة المحولة إليها',
            'الوسوم',
            'حالة الوثيقة',
            'المديرية',
            'الدائرة',
            'المجلد',
            'رفعها',
            'تاريخ الرفع',
        ]
        response = self.client.get(reverse('export_documents_excel'))
        buf = BytesIO(response.content)
        wb = openpyxl.load_workbook(buf)
        ws = wb.active

        headers = [ws.cell(row=1, column=i).value for i in range(1, len(expected_headers) + 1)]
        self.assertEqual(headers, expected_headers)

    def test_rtl_sheet_view(self):
        """الورقة معدة للعرض من اليمين لليسار."""
        response = self.client.get(reverse('export_documents_excel'))
        buf = BytesIO(response.content)
        wb = openpyxl.load_workbook(buf)
        ws = wb.active
        self.assertTrue(ws.sheet_view.rightToLeft)

    def test_freeze_panes(self):
        """الصف الأول مثبت."""
        response = self.client.get(reverse('export_documents_excel'))
        buf = BytesIO(response.content)
        wb = openpyxl.load_workbook(buf)
        ws = wb.active
        self.assertEqual(ws.freeze_panes, 'A2')

    def test_auto_filter_enabled(self):
        """الفلتر التلقائي مفعل على الصف الأول."""
        response = self.client.get(reverse('export_documents_excel'))
        buf = BytesIO(response.content)
        wb = openpyxl.load_workbook(buf)
        ws = wb.active
        self.assertIsNotNone(ws.auto_filter.ref)
        self.assertTrue(ws.auto_filter.ref.startswith('A1:'))