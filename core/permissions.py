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

الصلاحيات الخاصة بالتعديل والحذف:
    - التعديل: متاح لصاحب الوثيقة دائماً، وللمسؤولين الأعلى ضمن نطاقهم
    - الحذف: الموظف العادي لا يستطيع الحذف إطلاقاً حتى لو كان صاحب الوثيقة،
             بينما المسؤولون (مدير عام / مدير مديرية / رئيس دائرة) يستطيعون
             ضمن نطاقهم فقط.
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


def can_edit_document(user, document):
    """
    يسمح بالتعديل على الوثيقة:
    - صاحب الوثيقة (أي مستخدم رفعها) يستطيع تعديلها دائماً.
    - المدير العام يستطيع تعديل أي وثيقة.
    - مدير المديرية يستطيع تعديل وثائق مديريته فقط.
    - رئيس الدائرة يستطيع تعديل وثائق دائرته فقط.
    """
    if not user.is_authenticated:
        return False

    # صاحب الوثيقة يستطيع التعديل (حتى لو كان موظفاً عادياً)
    if document.uploaded_by_id == user.id:
        return True

    if user.role == CustomUser.Role.GENERAL_MANAGER:
        return True

    if user.role == CustomUser.Role.DIRECTORATE_MANAGER:
        return document.directorate_id == user.directorate_id

    if user.role == CustomUser.Role.HEAD_OF_DEPT:
        return document.department_id == user.department_id

    return False


def can_delete_document(user, document):
    """
    يسمح بحذف الوثيقة:
    - الموظف العادي (EMPLOYEE) لا يستطيع الحذف نهائياً حتى لو كان صاحب الوثيقة.
    - المدير العام يستطيع حذف أي وثيقة.
    - مدير المديرية يستطيع حذف وثائق مديريته فقط.
    - رئيس الدائرة يستطيع حذف وثائق دائرته فقط.
    """
    if not user.is_authenticated:
        return False

    # منع الموظف العادي من الحذف إطلاقاً
    if user.role == CustomUser.Role.EMPLOYEE:
        return False

    if user.role == CustomUser.Role.GENERAL_MANAGER:
        return True

    if user.role == CustomUser.Role.DIRECTORATE_MANAGER:
        return document.directorate_id == user.directorate_id

    if user.role == CustomUser.Role.HEAD_OF_DEPT:
        return document.department_id == user.department_id

    return False


# للتوافق مع أي كود قديم، يمكن الإبقاء على can_manage_document لكن نوجهها إلى can_edit_document
def can_manage_document(user, document):
    """مرادف لـ can_edit_document (للتوافق مع أي استخدام سابق)"""
    return can_edit_document(user, document)


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
    """نفس منطق can_manage_document (التعديل) مطبَّق على المجلد (للتعديل مستقبلاً)"""
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


def can_delete_folder(user, folder):
    """
    يسمح بحذف المجلد فقط للمسؤولين (مدير عام / مدير مديرية / رئيس قسم) ضمن نطاقهم.
    الموظف العادي لا يستطيع حذف المجلد حتى لو كان منشئه.
    """
    if not user.is_authenticated:
        return False

    # منع الموظف العادي من حذف المجلد
    if user.role == CustomUser.Role.EMPLOYEE:
        return False

    if user.role == CustomUser.Role.GENERAL_MANAGER:
        return True

    if user.role == CustomUser.Role.DIRECTORATE_MANAGER:
        return folder.directorate_id == user.directorate_id

    if user.role == CustomUser.Role.HEAD_OF_DEPT:
        return folder.department_id == user.department_id

    return False