from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator


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
    """الدائرة - تتبع مديرية واحدة، عدد الدوائر بكل مديرية غير محدود ومتغير"""
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
        unique_together = ('directorate', 'name')  # ما يتكرر نفس اسم الدائرة بنفس المديرية
        indexes = [
            models.Index(fields=['directorate']),
        ]

    def __str__(self):
        return f"{self.name} - {self.directorate.name}"


# ==========================================================
# المستخدمون
# ==========================================================

class CustomUser(AbstractUser):
    """
    مستخدم النظام.

    نوعان من الحسابات منفصلان تماماً:

    1. أدمن النظام (is_staff=True / is_superuser=True):
       حساب إداري تقني بحت (مسؤول IT مثلاً)، مهمته الوحيدة إدارة الحسابات
       وتوزيع الأدوار من لوحة إدارة Django الجاهزة (/admin). هذا الحساب
       لا ينتمي لأي مديرية أو دائرة، ولا يملك role وظيفي، ولا يملك أي صلاحية
       لرؤية محتوى الأرشيف نفسه - دوره إداري فقط.

    2. المستخدم الوظيفي (role محدد: موظف/رئيس دائرة/مدير مديرية/مدير عام):
       حساب يستخدم واجهة النظام (لا لوحة إدارة Django)، ونطاق رؤيته للأرشيف
       يُحدَّد بالكامل حسب دوره ومكانه التنظيمي (directorate/department)،
       وفق القاعدة المتفق عليها بملف core/permissions.py.

    الربط بين الدور والمكان التنظيمي هو أساس نظام الصلاحيات بالكامل.
    """
    class Role(models.TextChoices):
        EMPLOYEE = 'EMP', 'موظف'
        HEAD_OF_DEPT = 'HD', 'رئيس دائرة'
        DIRECTORATE_MANAGER = 'DM', 'مدير مديرية'
        GENERAL_MANAGER = 'GM', 'مدير عام'

    # اختياري عمداً: حساب أدمن النظام (IT) لا يُنسب لأي من الأربعة أدوار الوظيفية
    role = models.CharField(
        max_length=3, choices=Role.choices,
        null=True, blank=True, verbose_name="الدور الوظيفي"
    )

    # مدير عام: بدون مديرية/دائرة محددة (نطاقه كل شي)
    # أدمن النظام: كذلك بدون مديرية/دائرة، لأنه أصلاً خارج الهيكل الوظيفي
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
        """حساب إداري تقني بحت (IT) - منفصل تماماً عن الأدوار الوظيفية الأربعة"""
        return self.is_staff or self.is_superuser

    def save(self, *args, **kwargs):
        # اتساق البيانات: الدائرة يجب أن تتبع نفس مديرية المستخدم
        if self.department and self.department.directorate_id != self.directorate_id:
            self.directorate = self.department.directorate
        super().save(*args, **kwargs)


# ==========================================================
# المجلدات - نظام تنظيم متداخل يقدر الموظف ينشئه لترتيب أرشيفه
# ==========================================================

class Folder(models.Model):
    """
    مجلد يقدر أي مستخدم وظيفي ينشئه لتنظيم وثائقه (مثلاً "مالية 2026"،
    وجواه "ميزانية" ← "رواتب شهر 1"). المجلد "يتبع" منشئه ومكانه
    التنظيمي تماماً كما الوثيقة، وتُطبَّق عليه نفس قواعد الصلاحيات
    الحاكمة بالكامل (راجع core/permissions.py) - أي أن رؤية المجلد
    محصورة بمنشئه ومن هو أعلى منه تنظيمياً فقط.
    """
    name = models.CharField(max_length=255, verbose_name="اسم المجلد")
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True,
        related_name='subfolders', verbose_name="المجلد الأب"
    )

    # نفس منطق الوثيقة بالضبط: تلقائي من حساب منشئ المجلد وقت الإنشاء
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
        """يُستخدم لمنع حذف مجلد يحتوي وثائق أو مجلدات فرعية غير فارغة"""
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
    file = models.FileField(upload_to='archive/%Y/%m/', verbose_name="الملف")

    document_date = models.DateField(verbose_name="تاريخ الوثيقة")
    document_year = models.PositiveIntegerField(editable=False, default=0, verbose_name="سنة الوثيقة")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الرفع")

    tags = models.ManyToManyField(Tag, blank=True, related_name='documents', verbose_name="الوسوم")
    source = models.CharField(max_length=10, choices=Source.choices, verbose_name="المصدر")

    issuing_directorate = models.ForeignKey(
        Directorate, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='issued_documents', verbose_name="المديرية الصادرة عنها (داخلي)"
    )
    external_entity_name = models.CharField(
        max_length=255, null=True, blank=True, verbose_name="اسم الجهة الخارجية"
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
            models.Index(fields=['source']),
            models.Index(fields=['directorate']),
            models.Index(fields=['department']),
            models.Index(fields=['uploaded_by']),
            models.Index(fields=['folder']),
            models.Index(fields=['document_year']),
            models.Index(fields=['created_at']),
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
# سجل التدقيق (Audit Log)
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