"""
utils/files.py
==============
دوال مساعدة للتعامل مع أسماء الملفات والمجلدات.
"""

import os
import re


def sanitize_folder_name(name, max_length=100, fallback='folder'):
    """
    تنظيف اسم المجلد/الملف ليكون صالحاً للاستخدام في أسماء الملفات.

    - يزيل الرموز غير المسموحة: / \\ : * ? " < > | \n \t \r
    - يستبدل المسافات بـ _
    - يقصّر الاسم عند max_length
    - إذا فرغ الاسم تماماً، يستخدم fallback

    مثال:
        sanitize_folder_name("وثائق 2024/الرسمية")  → "وثائق_2024_الرسمية"
        sanitize_folder_name("")                    → "folder"
        sanitize_folder_name("a/b\\c:d")            → "a_b_c_d"
    """
    if not name:
        return fallback

    # إزالة الرموز غير المسموحة في أسماء الملفات
    cleaned = re.sub(r'[/\\:*?"<>|\n\r\t]', '_', str(name))

    # استبدال المسافات المتعددة بـ _ واحدة
    cleaned = re.sub(r'\s+', '_', cleaned).strip('_')

    # إزالة النقاط من البداية (تسبب مشاكل في بعض الأنظمة)
    cleaned = cleaned.lstrip('.')

    # تقصير الطول
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]

    # إذا فرغ تماماً بعد التنظيف
    return cleaned or fallback


def safe_filename(filename, max_length=100, fallback='file'):
    """
    تنظيف اسم ملف مع الحفاظ على امتداده.

    مثال:
        safe_filename("تقرير 2024.pdf")  → "تقرير_2024.pdf"
    """
    if not filename:
        return fallback

    name, ext = os.path.splitext(filename)
    name = sanitize_folder_name(name, max_length=max_length, fallback=fallback)

    # تنظيف الامتداد
    ext = re.sub(r'[^a-zA-Z0-9.]', '', ext)
    if ext and not ext.startswith('.'):
        ext = '.' + ext

    return f"{name}{ext}"