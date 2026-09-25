from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from datetime import date, timedelta

from .models import (
    Directorate, Department, Folder, Tag,
    Document, DocumentAttachment, AuditLog, Comment, CustomUser
)


User = get_user_model()


class ProjectTests(TestCase):
    """اختبارات شاملة للنظام"""

    def setUp(self):
        self.client = Client()

        # --- الهيكل التنظيمي ---
        self.directorate = Directorate.objects.create(name="مديرية المالية")
        self.dept1 = Department.objects.create(name="الدائرة المالية", directorate=self.directorate)
        self.dept2 = Department.objects.create(name="دائرة الموارد", directorate=self.directorate)

        # --- المستخدمون ---
        self.employee = User.objects.create_user(
            username="employee", password="testpass",
            role=CustomUser.Role.EMPLOYEE,
            directorate=self.directorate, department=self.dept1
        )
        self.head = User.objects.create_user(
            username="head", password="testpass",
            role=CustomUser.Role.HEAD_OF_DEPT,
            directorate=self.directorate, department=self.dept1
        )
        self.dir_manager = User.objects.create_user(
            username="dir_manager", password="testpass",
            role=CustomUser.Role.DIRECTORATE_MANAGER,
            directorate=self.directorate, department=None
        )
        self.general_manager = User.objects.create_user(
            username="gm", password="testpass",
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

    # ============ 1. صلاحيات العرض ============
    def test_employee_sees_own_document(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse('document_detail', args=[self.document.id]))
        self.assertEqual(response.status_code, 200)

    def test_gm_sees_all_documents(self):
        self.client.force_login(self.general_manager)
        response = self.client.get(reverse('document_detail', args=[self.document.id]))
        self.assertEqual(response.status_code, 200)

    def test_dir_manager_sees_dept_documents(self):
        # وثيقة من دائرة الموارد
        other_doc = Document.objects.create(
            document_number="2",
            title="وثيقة من دائرة أخرى",
            file=SimpleUploadedFile("other.pdf", b"content"),
            document_date=date(2026, 1, 20),
            source=Document.Source.INTERNAL,
            directorate=self.directorate,
            department=self.dept2,
            uploaded_by=User.objects.create_user(
                username="other_emp", password="testpass",
                role=CustomUser.Role.EMPLOYEE,
                directorate=self.directorate, department=self.dept2
            )
        )
        self.client.force_login(self.dir_manager)
        response = self.client.get(reverse('document_detail', args=[other_doc.id]))
        self.assertEqual(response.status_code, 200)

    # ============ 2. صلاحيات الحذف ============
    def test_employee_cannot_delete_document(self):
        self.client.force_login(self.employee)
        response = self.client.post(reverse('delete_document', args=[self.document.id]))
        self.assertEqual(response.status_code, 403)

    def test_head_can_delete_dept_document(self):
        self.client.force_login(self.head)
        response = self.client.post(reverse('delete_document', args=[self.document.id]))
        self.assertEqual(response.status_code, 302)

    # ============ 3. صلاحيات الرفع ============
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

    # ============ 4. التحقق من رقم الوثيقة ============
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

    # ============ 5. منع التكرار ============
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

    # ============ 6. المرفقات ============
    def test_upload_attachment(self):
        self.client.force_login(self.employee)
        response = self.client.post(reverse('upload_attachment', args=[self.document.id]), {
            'file': SimpleUploadedFile("att2.pdf", b"attachment"),
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.document.attachments.count(), 1)

    def test_employee_cannot_upload_attachment_to_other_document(self):
        other_employee = User.objects.create_user(
            username="other_employee", password="testpass",
            role=CustomUser.Role.EMPLOYEE,
            directorate=self.directorate, department=self.dept1
        )
        self.client.force_login(other_employee)
        response = self.client.post(reverse('upload_attachment', args=[self.document.id]), {
            'file': SimpleUploadedFile("hack.pdf", b"hack"),
        })
        self.assertEqual(response.status_code, 403)

    # ============ 7. تاريخ التصدير ============
    def test_export_date_blank(self):
        self.assertIsNotNone(self.document.export_date)

    def test_export_date_set(self):
        self.document.export_date = date(2026, 3, 1)
        self.document.save()
        self.document.refresh_from_db()
        self.assertEqual(self.document.export_date, date(2026, 3, 1))

    # ============ 8. البحث ============
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

    # ============ 9. المجلدات ============
    def test_employee_can_view_folder_list(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse('folder_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.folder.name)

    def test_folder_detail_view(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse('folder_detail', args=[self.folder.id]))
        self.assertEqual(response.status_code, 200)

    # ============ 10. واجهة المدير العام ============
    def test_gm_does_not_see_upload_button(self):
        self.client.force_login(self.general_manager)
        response = self.client.get(reverse('dashboard'))
        self.assertNotContains(response, 'رفع وثيقة')

    def test_gm_does_not_see_folder_create_button(self):
        self.client.force_login(self.general_manager)
        response = self.client.get(reverse('folder_list'))
        self.assertNotContains(response, 'مجلد جديد')