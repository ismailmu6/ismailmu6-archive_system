from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.utils import timezone
import os

from .utils.files import sanitize_folder_name


# ==========================================================
# دالة تسمية ملف الوثيقة (تُستخدم فقط عند رفع ملف جديد)
# ==========================================================
# ملاحظة مهمة:
# هذه الدالة تُطبَّق فقط على الملفات الجديدة. الملفات القديمة التي
# رُفعت قبل هذا التعديل تبقى في مسارها القديم ولا تتأثر إطلاقاً، لأن
# Django يحفظ مسار كل ملف نصيًّا في قاعدة البيانات.
# ==========================================================

def upload_document_path(instance, filename):
    """
    تسمية ملف الوثيقة برقم الوثيقة + تنظيم حسب المديرية/الدائرة/المجلد/السنة.
    البنية:
      - داخل مجلد:   archive/<directorate_name>/<department_name>/<folder_name>/<year>/<number>.<ext>
      - غير مصنف:    archive/<directorate_name>/<department_name>/uncategorized/<year>/<number>.<ext>

    في حال تكرار الاسم (نفس الرقم بنفس المديرية/السنة)، Django يضيف
    لاحقة عشوائية تلقائياً (مثل: 2403_AbC123.pdf) دون أي حذف أو تداخل.
    """
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'bin'
    # ✅ تنظيف رقم الوثيقة كاملاً من الرموز غير الآمنة
    doc_num = sanitize_folder_name(
        str(instance.document_number).replace('/', '-').replace('\\', '-')
    )
    new_filename = f"{doc_num}.{ext}"

    year = instance.document_date.year if instance.document_date and hasattr(instance.document_date, 'year') else 'unknown'

    # أسماء واضحة للمديرية والدائرة
    dir_name = sanitize_folder_name(instance.directorate.name) if instance.directorate else 'unknown_directorate'
    dept_name = sanitize_folder_name(instance.department.name) if instance.department else 'unknown_department'

    if instance.folder_id:
        folder_name = sanitize_folder_name(instance.folder.name) if instance.folder else f"folder_{instance.folder_id}"
        return os.path.join('archive', dir_name, dept_name, folder_name, str(year), new_filename)
    else:
        return os.path.join('archive', dir_name, dept_name, 'uncategorized', str(year), new_filename)


def upload_attachment_path(instance, filename):
    """
    تسمية الملف المرفق برقم الوثيقة + عنوانها + رقم تسلسلي، وتنظيم
    المسار حسب المديرية/الدائرة/رقم_الوثيقة_السنة.

    البنية:
      archive/attachments/<directorate>/<department>/<number>_<year>/<number>_<title>_<n>.<ext>

    المثال:
      archive/attachments/معلوماتية/الاول/741258_2026/741258_وثيقة_تجربة_1.pdf

    - رقم الوثيقة يظهر في اسم المجلد واسم الملف (يسهل البحث والفرز).
    - السنة تظهر في اسم المجلد.
    - الرقم التسلسلي يزيد تلقائياً مع كل مرفق جديد لنفس الوثيقة.
    - في حال تداخل نادر (مثلاً رفع متزامن)، Django يضيف لاحقة عشوائية
      تلقائياً دون أي حذف أو استبدال.
    """
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'bin'
    doc = instance.document

    # المديرية والدائرة
    dir_name = sanitize_folder_name(doc.directorate.name) if doc.directorate else 'unknown_directorate'
    dept_name = sanitize_folder_name(doc.department.name) if doc.department else 'unknown_department'

    # ✅ تنظيف رقم الوثيقة كاملاً من الرموز غير الآمنة
    doc_num = sanitize_folder_name(
        str(doc.document_number).replace('/', '-').replace('\\', '-')
    )

    # السنة (من document_year أو من document_date)
    year = doc.document_year or (doc.document_date.year if doc.document_date else 'unknown')

    # مجلد فرعي فريد لكل وثيقة: <رقم>_<سنة>
    doc_folder = f"{doc_num}_{year}"

    # اسم الملف = رقم الوثيقة + عنوان الوثيقة + رقم تسلسلي
    title_base = sanitize_folder_name(doc.title)[:80] or 'attachment'

    # عدّاد تسلسلي: عدد المرفقات الحالية لنفس الوثيقة + 1
    qs = DocumentAttachment.objects.filter(document=doc)
    if instance.pk:
        qs = qs.exclude(pk=instance.pk)
    counter = qs.count() + 1

    new_filename = f"{doc_num}_{title_base}_{counter}.{ext}"
    return os.path.join('archive', 'attachments', dir_name, dept_name, doc_folder, new_filename)


# ==========================================================
# الهيكل التنظيمي: مديرية → دائرة
# ==========================================================

class Directorate(models.Model):
    """المديرية - المستوى الأعلى بالهيكل التنظيمي"""
    name = models.CharField(max_length=150, unique=True, verbose_name="اسم المديرية")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "مديرية"
        verbose_name_plural = "المديريات"
        ordering = ['name']

    def __str__(self):
        return self.name


class Department(models.Model):
    """الدائرة - تتبع مديرية واحدة"""
    directorate = models.ForeignKey(
        Directorate, on_delete=models.CASCADE,
        related_name='departments', verbose_name="المديرية"
    )
    name = models.CharField(max_length=150, verbose_name="اسم الدائرة")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "دائرة"
        verbose_name_plural = "الدوائر"
        ordering = ['directorate', 'name']
        unique_together = ('directorate', 'name')
        indexes = [
            models.Index(fields=['directorate']),
        ]

    def __str__(self):
        return f"{self.name} - {self.directorate.name}"


# ==========================================================
# نوع الوثيقة
# ==========================================================

class DocumentType(models.Model):
    """نوع الوثيقة - قائمة ثابتة تُدار من لوحة الأدمن"""
    name = models.CharField(max_length=150, unique=True, verbose_name="نوع الوثيقة")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "نوع وثيقة"
        verbose_name_plural = "أنواع الوثائق"
        ordering = ['name']

    def __str__(self):
        return self.name


# ==========================================================
# المستخدمون
# ==========================================================

class CustomUser(AbstractUser):
    class Role(models.TextChoices):
        EMPLOYEE = 'EMP', 'موظف'
        HEAD_OF_DEPT = 'HD', 'رئيس دائرة'
        DIRECTORATE_MANAGER = 'DM', 'مدير مديرية'
        GENERAL_MANAGER = 'GM', 'مدير عام'

    role = models.CharField(
        max_length=3, choices=Role.choices,
        null=True, blank=True, verbose_name="الدور الوظيفي"
    )
    directorate = models.ForeignKey(
        Directorate, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='users', verbose_name="المديرية"
    )
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='users', verbose_name="الدائرة"
    )

    class Meta:
        verbose_name = "مستخدم"
        verbose_name_plural = "المستخدمون"
        indexes = [
            models.Index(fields=['role']),
            models.Index(fields=['directorate']),
            models.Index(fields=['department']),
        ]

    def __str__(self):
        if self.role:
            return f"{self.get_full_name() or self.username} ({self.get_role_display()})"
        return f"{self.get_full_name() or self.username} (أدمن النظام)"

    @property
    def is_system_admin(self):
        return self.is_staff or self.is_superuser

    def save(self, *args, **kwargs):
        if self.department and self.department.directorate_id != self.directorate_id:
            self.directorate = self.department.directorate
        super().save(*args, **kwargs)


# ==========================================================
# المجلدات
# ==========================================================

class Folder(models.Model):
    name = models.CharField(max_length=255, verbose_name="اسم المجلد")
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True,
        related_name='subfolders', verbose_name="المجلد الأب"
    )
    directorate = models.ForeignKey(Directorate, on_delete=models.PROTECT, related_name='folders')
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name='folders')
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='folders')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "مجلد"
        verbose_name_plural = "المجلدات"
        ordering = ['name']
        indexes = [
            models.Index(fields=['parent']),
            models.Index(fields=['directorate']),
            models.Index(fields=['department']),
            models.Index(fields=['created_by']),
        ]

    def __str__(self):
        return self.name

    def has_content(self):
        return self.documents.exists() or self.subfolders.exists()


# ==========================================================
# الوسوم
# ==========================================================

class Tag(models.Model):
    name = models.CharField(max_length=80, unique=True, verbose_name="الوسم")

    class Meta:
        verbose_name = "وسم"
        verbose_name_plural = "الوسوم"
        ordering = ['name']

    def __str__(self):
        return self.name


# ==========================================================
# الوثيقة
# ==========================================================

class Document(models.Model):
    class Source(models.TextChoices):
        INTERNAL = 'internal', 'داخلي'
        EXTERNAL = 'external', 'خارجي'

    document_number = models.CharField(
        max_length=50,
        validators=[RegexValidator(r'^\d.*$', 'يجب أن يبدأ رقم الوثيقة برقم.')],
        verbose_name="رقم الوثيقة"
    )
    title = models.CharField(max_length=255, verbose_name="اسم الوثيقة")

    # ✅ تم تغيير upload_to من 'archive/%Y/%m/' إلى الدالة الجديدة
    # ملاحظة: الملفات القديمة لا تتأثر — Django يحتفظ بمسار كل ملف
    # نصيًّا في قاعدة البيانات، والتغيير يطبَّق على الرفع الجديد فقط.
    file = models.FileField(upload_to=upload_document_path, verbose_name="الملف")

    document_date = models.DateField(verbose_name="تاريخ الوثيقة")
    export_date = models.DateField(null=True, blank=True, verbose_name="تاريخ التصدير/الختم")
    document_year = models.PositiveIntegerField(editable=False, default=0, verbose_name="سنة الوثيقة")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الرفع")

    document_type = models.ForeignKey(
        DocumentType, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='documents', verbose_name="نوع الوثيقة"
    )

    tags = models.ManyToManyField(Tag, blank=True, related_name='documents', verbose_name="الوسوم")
    source = models.CharField(max_length=10, choices=Source.choices, verbose_name="المصدر")

    issuing_directorate = models.ForeignKey(
        Directorate, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='issued_documents', verbose_name="المديرية الصادرة عنها (داخلي)"
    )
    external_entity_name = models.CharField(
        max_length=255, null=True, blank=True, verbose_name="اسم الجهة الخارجية"
    )

    destination_entity_name = models.CharField(
        max_length=255, null=True, blank=True, verbose_name="الجهة المحولة إليها"
    )

    diwan_number = models.CharField(
        max_length=50, null=True, blank=True, verbose_name="رقم الديوان"
    )

    # ✅✅✅ جديد: حالة الوثيقة (نص حر) ✅✅✅
    status = models.CharField(
        max_length=100, null=True, blank=True, verbose_name="حالة الوثيقة"
    )

    folder = models.ForeignKey(
        Folder, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='documents', verbose_name="المجلد"
    )

    directorate = models.ForeignKey(
        Directorate, on_delete=models.PROTECT, related_name='documents', verbose_name="المديرية"
    )
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name='documents', verbose_name="الدائرة"
    )

    uploaded_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True,
        related_name='documents', verbose_name="رفعها"
    )

    class Meta:
        verbose_name = "وثيقة"
        verbose_name_plural = "الوثائق"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['document_number']),
            models.Index(fields=['title']),
            models.Index(fields=['document_date']),
            models.Index(fields=['export_date']),
            models.Index(fields=['source']),
            models.Index(fields=['directorate']),
            models.Index(fields=['department']),
            models.Index(fields=['uploaded_by']),
            models.Index(fields=['folder']),
            models.Index(fields=['document_year']),
            models.Index(fields=['created_at']),
            models.Index(fields=['document_type']),
            models.Index(fields=['destination_entity_name']),
            models.Index(fields=['diwan_number']),
            # ✅✅✅ جديد: فهرس لحالة الوثيقة ✅✅✅
            models.Index(fields=['status']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['directorate', 'document_year', 'document_number'],
                name='unique_document_number_per_directorate_per_year',
                violation_error_message='رقم الوثيقة هذا مستخدم مسبقاً ضمن هذه المديرية لنفس السنة.'
            )
        ]

    def __str__(self):
        return f"{self.document_number} - {self.title}"

    @property
    def full_number(self):
        return f"{self.document_number}/{self.document_year}"

    def save(self, *args, **kwargs):
        if self.department_id and self.department.directorate_id != self.directorate_id:
            self.directorate_id = self.department.directorate_id
        if self.document_date:
            if isinstance(self.document_date, str):
                from django.utils.dateparse import parse_date
                parsed = parse_date(self.document_date)
                if parsed:
                    self.document_date = parsed
            if hasattr(self.document_date, 'year'):
                self.document_year = self.document_date.year
        super().save(*args, **kwargs)


# ==========================================================
# الملفات المرفقة
# ==========================================================

class DocumentAttachment(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='attachments')

    # ✅ تغيير upload_to للمرفقات (يُطبَّق على الرفع الجديد فقط)
    file = models.FileField(upload_to=upload_attachment_path, verbose_name="ملف إضافي")

    uploaded_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "ملف مرفق"
        verbose_name_plural = "الملفات المرفقة"
        ordering = ['uploaded_at']


# ==========================================================
# نسخ الوثيقة السابقة
# ==========================================================

class DocumentVersion(models.Model):
    document = models.ForeignKey(
        Document, on_delete=models.CASCADE,
        related_name='versions', verbose_name="الوثيقة"
    )
    file_name = models.CharField(max_length=500, verbose_name="مسار الملف")
    original_filename = models.CharField(max_length=255, blank=True, verbose_name="اسم الملف الأصلي")
    note = models.CharField(max_length=255, blank=True, verbose_name="ملاحظة")
    uploaded_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True,
        related_name='document_versions', verbose_name="رفعها"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الرفع")

    class Meta:
        verbose_name = "نسخة سابقة"
        verbose_name_plural = "النسخ السابقة"
        ordering = ['-uploaded_at']
        indexes = [
            models.Index(fields=['document']),
            models.Index(fields=['uploaded_at']),
        ]

    def __str__(self):
        return f"نسخة {self.document.document_number} - {self.uploaded_at:%Y-%m-%d %H:%M}"


# ==========================================================
# التعليقات
# ==========================================================

class Comment(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='comments')
    text = models.TextField(verbose_name="التعليق")
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "تعليق"
        verbose_name_plural = "التعليقات"
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['document']),
            models.Index(fields=['created_by']),
        ]

    def __str__(self):
        return f"تعليق على {self.document.document_number}"


# ==========================================================
# سجل التدقيق
# ==========================================================

class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = 'CREATE', 'إنشاء'
        VIEW = 'VIEW', 'عرض'
        EDIT = 'EDIT', 'تعديل'
        DELETE = 'DELETE', 'حذف'
        DOWNLOAD = 'DOWNLOAD', 'تحميل'

    document = models.ForeignKey(Document, on_delete=models.SET_NULL, null=True, related_name='audit_logs')
    document_number = models.CharField(max_length=50)
    document_title = models.CharField(max_length=255)

    action = models.CharField(max_length=10, choices=Action.choices)
    performed_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    performed_by_role = models.CharField(max_length=3)

    timestamp = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "سجل تدقيق"
        verbose_name_plural = "سجلات التدقيق"
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['timestamp']),
            models.Index(fields=['performed_by']),
            models.Index(fields=['document']),
            models.Index(fields=['action']),
        ]

    def __str__(self):
        return f"{self.get_action_display()} - {self.document_number} - {self.timestamp:%Y-%m-%d %H:%M}"