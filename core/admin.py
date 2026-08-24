from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django import forms
from .models import CustomUser, Directorate, Department, Tag, Document, Comment, AuditLog, Folder


class DirectorateAwareDepartmentSelect(forms.Select):
    """
    قائمة منسدلة مخصصة لحقل "الدائرة": تضيف لكل <option> سمة
    data-directorate-id تحمل رقم المديرية التابعة لها تلك الدائرة.
    يقرأ ملف core/static/core/js/department_filter.js هذه السمة
    ليُخفي الدوائر غير التابعة للمديرية المختارة بحقل "المديرية".
    """
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value:
            try:
                dept_id = value.value if hasattr(value, 'value') else value
                dept = Department.objects.select_related('directorate').get(pk=dept_id)
                option['attrs']['data-directorate-id'] = str(dept.directorate_id)
            except Department.DoesNotExist:
                pass
        return option


# ==========================================================
# المديريات والدوائر والوسوم
# ==========================================================

@admin.register(Directorate)
class DirectorateAdmin(admin.ModelAdmin):
    list_display = ['name', 'department_count', 'created_at']
    search_fields = ['name']

    @admin.display(description='عدد الدوائر')
    def department_count(self, obj):
        return obj.departments.count()


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ['name', 'directorate']
    list_filter = ['directorate']
    search_fields = ['name']


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ['name']
    search_fields = ['name']


# ==========================================================
# المجلدات
#
# مثل الوثيقة تماماً: بيانات إدارية بس (الاسم، من أنشأه، مديريته) تظهر
# لأغراض الصيانة والدعم الفني، والإنشاء يبقى حصراً من واجهة النظام
# العادية بمعرفة صاحب المجلد ونطاقه.
# ==========================================================

@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    list_display = ['name', 'parent', 'directorate', 'department', 'created_by', 'created_at']
    list_filter = ['directorate', 'department']
    search_fields = ['name']

    def has_add_permission(self, request):
        # المجلدات تُنشأ فقط من واجهة النظام العادية بمعرفة صاحبها
        return False


# ==========================================================
# المستخدمون
# ==========================================================

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    """
    لوحة إدارة المستخدمين: عند إنشاء أو تعديل مستخدم، يحدد المسؤول
    دوره ومديريته ودائرته مباشرة من هذه الشاشة - بدون أي تعديل كود.
    قائمة "الدائرة" تُفلتَر تلقائياً (بـ JavaScript) لتعرض فقط دوائر
    المديرية المختارة، منعاً لأي ربط خاطئ بين مديرية ودائرة لا تتبعها.
    """
    model = CustomUser
    list_display = ['username', 'email', 'role', 'directorate', 'department', 'is_staff']
    list_filter = ['role', 'directorate', 'department', 'is_staff', 'is_active']

    fieldsets = UserAdmin.fieldsets + (
        ('الصلاحيات الإدارية للأرشيف', {'fields': ('role', 'directorate', 'department')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('الصلاحيات الإدارية للأرشيف', {'fields': ('role', 'directorate', 'department')}),
    )

    class Media:
        js = ('core/js/department_filter.js',)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'department':
            kwargs['widget'] = DirectorateAwareDepartmentSelect()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


# ==========================================================
# الوثائق
#
# ملاحظة أمنية مهمة: تسجيل الوثيقة هنا لا يعني كشف محتواها لأي شخص.
# لوحة /admin أصلاً محصورة بحسابات is_staff فقط (موظف IT المخوَّل).
# لكننا نمنع صراحة عرض حقل "الملف" نفسه من هذه الشاشة، بحيث يقدر IT
# يشوف البيانات الإدارية (الرقم، الاسم، التاريخ، من رفعها) لأغراض
# الصيانة والدعم الفني، دون أن يقدر يفتح أو يقرأ محتوى الملف الفعلي.
# ==========================================================

class CommentInline(admin.TabularInline):
    model = Comment
    extra = 0
    readonly_fields = ['created_by', 'created_at']
    can_delete = False


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ['document_number', 'title', 'directorate', 'department',
                     'source', 'document_date', 'uploaded_by']
    list_filter = ['directorate', 'department', 'source', 'document_date']
    search_fields = ['document_number', 'title']
    filter_horizontal = ['tags']
    inlines = [CommentInline]

    # الحقول المعروضة عند فتح وثيقة بعينها - "file" غير موجود هنا عمداً
    # حتى لا يقدر IT يفتح/يحمّل محتوى الملف نفسه من لوحة الإدارة
    fields = ['document_number', 'title', 'document_date', 'source',
              'issuing_directorate', 'external_entity_name', 'folder',
              'directorate', 'department', 'tags', 'uploaded_by', 'created_at']
    readonly_fields = ['created_at']

    class Media:
        js = ('core/js/department_filter.js',)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'department':
            kwargs['widget'] = DirectorateAwareDepartmentSelect()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def has_add_permission(self, request):
        # الوثائق تُرفع فقط من واجهة النظام العادية (بمعرفة صاحبها ونطاقه)
        # وليس من لوحة إدارة Django
        return False


# ==========================================================
# سجل التدقيق (Audit Log)
# سجل للقراءة فقط - يُنشأ تلقائياً من الكود عند كل إجراء إشرافي،
# ولا يجوز التعديل عليه يدوياً بأي حال لضمان مصداقيته كسجل موثوق
# ==========================================================

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['document_number', 'document_title', 'action',
                     'performed_by', 'performed_by_role', 'timestamp']
    list_filter = ['action', 'performed_by_role', 'timestamp']
    search_fields = ['document_number', 'document_title']
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False