"""
core/permissions.py

هذا الملف هو "المرجع الوحيد" لكل منطق الصلاحيات بالنظام.
كل شاشة (لوحة تحكم، بحث، قائمة وثائق، عرض تفاصيل، تحميل) يجب أن تستخدم
هذه الدوال فقط لتحديد ما يراه المستخدم - لا يُسمح بأي فلترة يدوية موازية
بأي View آخر، تجنباً لأي ثغرة أو تسريب معلومات.

القاعدة الحاكمة:
    مدير عام        → يرى كل الوثائق بكل المديريات
    مدير مديرية      → يرى وثائق مديريته فقط (بكل دوائرها)
    رئيس دائرة       → يرى وثائق دائرته فقط (لا يرى دوائر أخرى حتى بنفس مديريته)
    موظف            → يرى وثائقه هو فقط (التي رفعها بنفسه)
"""

from .models import Document, CustomUser, Folder


def get_visible_documents(user):
    """
    يُرجع QuerySet بالوثائق التي يحق للمستخدم رؤيتها، حسب دوره ونطاقه التنظيمي.
    هذا الفلتر يُطبَّق على مستوى الاستعلام (Query) نفسه، وليس مجرد إخفاء بالواجهة -
    أي أن الوثائق خارج النطاق لا تصل أصلاً لأي صفحة أو نتيجة بحث أو إحصائية.

    ملاحظة: حساب أدمن النظام (is_staff/is_superuser) ليس له role وظيفي أصلاً،
    لأنه خارج الهيكل الوظيفي بالكامل (راجع core/models.py). في حال حاول هذا
    الحساب الوصول لواجهة الأرشيف العادية (بدل لوحة إدارة Django)، لا يُعرض له
    أي محتوى إطلاقاً.
    """
    if not user.is_authenticated:
        return Document.objects.none()

    if not user.role:
        return Document.objects.none()

    if user.role == CustomUser.Role.GENERAL_MANAGER:
        return Document.objects.all()

    elif user.role == CustomUser.Role.DIRECTORATE_MANAGER:
        if not user.directorate_id:
            return Document.objects.none()
        return Document.objects.filter(directorate_id=user.directorate_id)

    elif user.role == CustomUser.Role.HEAD_OF_DEPT:
        if not user.department_id:
            return Document.objects.none()
        return Document.objects.filter(department_id=user.department_id)

    else:  # موظف عادي
        return Document.objects.filter(uploaded_by_id=user.id)


def can_view_document(user, document):
    """فحص إمكانية عرض وثيقة واحدة بعينها - يُستخدم بصفحة التفاصيل والتحميل"""
    return get_visible_documents(user).filter(pk=document.pk).exists()


def can_manage_document(user, document):
    """
    فحص إمكانية التعديل أو الحذف. صاحب الوثيقة يقدر دائماً، وأي مسؤول
    أعلى ضمن نطاقه التنظيمي المباشر يقدر كذلك (مع تسجيل الإجراء بسجل التدقيق).
    """
    if not user.is_authenticated:
        return False

    if document.uploaded_by_id == user.id:
        return True

    if user.role == CustomUser.Role.GENERAL_MANAGER:
        return True

    if user.role == CustomUser.Role.DIRECTORATE_MANAGER:
        return document.directorate_id == user.directorate_id

    if user.role == CustomUser.Role.HEAD_OF_DEPT:
        return document.department_id == user.department_id

    return False


def is_supervisory_action(user, document):
    """
    يحدد إن كان الإجراء (تعديل/حذف) صادراً عن مسؤول إشرافي على وثيقة
    ليست من رفعه هو - وهي الحالة التي تستوجب تسجيلاً مفصلاً بسجل التدقيق.
    """
    return document.uploaded_by_id != user.id


# ==========================================================
# المجلدات - نفس فلسفة الصلاحيات الحاكمة بالضبط، مطبَّقة على المجلد
# بدل الوثيقة مباشرة. مجلد الموظف = ملكه هو تنظيمياً، ورؤيته تخضع
# لنفس تسلسل النطاقات (موظف → رئيس دائرة → مدير مديرية → مدير عام).
# ==========================================================

def get_visible_folders(user):
    """يُرجع QuerySet بالمجلدات التي يحق للمستخدم رؤيتها، بنفس منطق الوثائق تماماً"""
    if not user.is_authenticated or not user.role:
        return Folder.objects.none()

    if user.role == CustomUser.Role.GENERAL_MANAGER:
        return Folder.objects.all()

    elif user.role == CustomUser.Role.DIRECTORATE_MANAGER:
        if not user.directorate_id:
            return Folder.objects.none()
        return Folder.objects.filter(directorate_id=user.directorate_id)

    elif user.role == CustomUser.Role.HEAD_OF_DEPT:
        if not user.department_id:
            return Folder.objects.none()
        return Folder.objects.filter(department_id=user.department_id)

    else:  # موظف عادي
        return Folder.objects.filter(created_by_id=user.id)


def can_view_folder(user, folder):
    return get_visible_folders(user).filter(pk=folder.pk).exists()


def can_manage_folder(user, folder):
    """نفس منطق can_manage_document تماماً، مطبَّق على المجلد"""
    if not user.is_authenticated:
        return False

    if folder.created_by_id == user.id:
        return True

    if user.role == CustomUser.Role.GENERAL_MANAGER:
        return True

    if user.role == CustomUser.Role.DIRECTORATE_MANAGER:
        return folder.directorate_id == user.directorate_id

    if user.role == CustomUser.Role.HEAD_OF_DEPT:
        return folder.department_id == user.department_id

    return False