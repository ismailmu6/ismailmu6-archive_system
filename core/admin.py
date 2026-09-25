from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django import forms
from .models import CustomUser, Directorate, Department, Tag, Document, Comment, AuditLog, Folder, DocumentAttachment, DocumentType


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
# أنواع الوثائق - قائمة ثابتة تُدار من الأدمن مثل المديريات والدوائر
# ==========================================================

@admin.register(DocumentType)
class DocumentTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'document_count', 'created_at']
    search_fields = ['name']

    @admin.display(description='عدد الوثائق')
    def document_count(self, obj):
        return obj.documents.count()


# ==========================================================
# المجلدات
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
# ==========================================================

class CommentInline(admin.TabularInline):
    model = Comment
    extra = 0
    readonly_fields = ['created_by', 'created_at']
    can_delete = False


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ['document_number', 'title', 'document_type', 'diwan_number',
                     'directorate', 'department',
                     'destination_entity_name',
                     'source', 'document_date', 'export_date', 'uploaded_by']
    list_filter = ['document_type', 'directorate', 'department',
                    'source', 'document_date']
    search_fields = ['document_number', 'title', 'diwan_number', 'destination_entity_name']
    filter_horizontal = ['tags']
    inlines = [CommentInline]

    fields = ['document_number', 'title', 'document_type', 'diwan_number',
              'document_date', 'export_date', 'source',
              'issuing_directorate', 'external_entity_name',
              'destination_entity_name',
              'folder',
              'directorate', 'department', 'tags', 'uploaded_by', 'created_at']
    readonly_fields = ['created_at']

    class Media:
        js = ('core/js/department_filter.js',)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'department':
            kwargs['widget'] = DirectorateAwareDepartmentSelect()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def has_add_permission(self, request):
        # الوثائق تُرفع فقط من واجهة النظام العادية
        return False


# ==========================================================
# الملفات المرفقة
# ==========================================================

@admin.register(DocumentAttachment)
class DocumentAttachmentAdmin(admin.ModelAdmin):
    list_display = ['document', 'file', 'uploaded_by', 'uploaded_at']
    search_fields = ['document__document_number', 'document__title']
    readonly_fields = ['uploaded_at']

    def has_add_permission(self, request):
        # الإضافة تتم من واجهة النظام فقط
        return False


# ==========================================================
# سجل التدقيق (Audit Log)
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