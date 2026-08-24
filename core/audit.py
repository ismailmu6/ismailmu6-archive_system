"""
core/audit.py

دالة موحدة لتسجيل أي إجراء (إنشاء/عرض/تعديل/حذف/تحميل) على وثيقة.
تُستدعى من الـ Views مباشرة بعد كل عملية، لضمان أن كل نشاط موثّق
باسم المنفذ ودوره ووقته دون استثناء.
"""

from .models import AuditLog
from .permissions import is_supervisory_action


def log_action(user, document, action, notes=''):
    """
    يسجل إجراءً بسجل التدقيق.
    إذا كان الإجراء صادراً عن مسؤول إشرافي (مو صاحب الوثيقة نفسه)،
    تُضاف ملاحظة توضيحية تلقائياً لتوثيق الصفة التي تم بها الإجراء.
    """
    auto_note = notes
    if action in (AuditLog.Action.EDIT, AuditLog.Action.DELETE) and is_supervisory_action(user, document):
        role_label = user.get_role_display()
        auto_note = (notes + ' | ' if notes else '') + f'تم تنفيذ الإجراء بصفته {role_label} على وثيقة ليست من رفعه'

    AuditLog.objects.create(
        document=document,
        document_number=document.document_number,
        document_title=document.title,
        action=action,
        performed_by=user,
        performed_by_role=user.role,
        notes=auto_note,
    )