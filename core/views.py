from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.db.models import Q
from django.utils.dateparse import parse_date
from django.core.paginator import Paginator

from .models import Document, Comment, Tag, AuditLog, Folder, Directorate, Department, CustomUser
from .permissions import (
    get_visible_documents, can_view_document, can_edit_document, can_delete_document,
    is_supervisory_action, get_visible_folders, can_view_folder, can_manage_folder,
    can_delete_folder,
)
from .audit import log_action


# ==========================================================
# تسجيل الدخول / الخروج
# ==========================================================

def login_view(request):
    """
    شاشة تسجيل الدخول. لا وجود لأي رابط "إنشاء حساب" هنا - إنشاء الحسابات
    حصراً من لوحة إدارة Django (/admin) بمعرفة أدمن النظام.
    """
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            # حساب أدمن النظام (IT) لا ينتمي للهيكل الوظيفي - لا يدخل واجهة الأرشيف
            if user.is_system_admin and not user.role:
                messages.error(request, 'هذا الحساب مخصص لإدارة النظام، الرجاء استخدام لوحة الإدارة.')
                return render(request, 'core/login.html')

            auth_login(request, user)
            return redirect('dashboard')
        else:
            messages.error(request, 'اسم المستخدم أو كلمة المرور غير صحيحة.')

    return render(request, 'core/login.html')


@login_required
def logout_view(request):
    auth_logout(request)
    return redirect('login')


# ==========================================================
# لوحة التحكم
# ==========================================================

@login_required
def dashboard(request):
    """
    لوحة تحكم تخدم كل الأدوار الأربعة، لكنها لا تعرض أي قائمة ملفات.
    فقط إحصائيات عامة: عدد الوثائق الكلي، الداخلي والخارجي.
    """
    documents = get_visible_documents(request.user)

    context = {
        'total_documents': documents.count(),
        'internal_count': documents.filter(source=Document.Source.INTERNAL).count(),
        'external_count': documents.filter(source=Document.Source.EXTERNAL).count(),
        # ملاحظة: لا نمرر أي queryset للوثائق نفسها
    }
    return render(request, 'core/dashboard.html', context)


# ==========================================================
# المجلدات (تنظيم اختياري متداخل يديره كل مستخدم لأرشيفه)
# ==========================================================

@login_required
def folder_list(request):
    """
    يعرض المجلدات الجذرية (بلا مجلد أب) المرئية للمستخدم،
    مع الوثائق غير المصنّفة داخل أي مجلد، مقسمة على صفحات.
    """
    folders_list = get_visible_folders(request.user).filter(parent__isnull=True).select_related('created_by')
    documents_list = get_visible_documents(request.user).filter(folder__isnull=True).select_related('department', 'directorate', 'uploaded_by')

    # ترقيم المجلدات
    folders_paginator = Paginator(folders_list, 25)  # 25 مجلد في الصفحة
    folders_page_number = request.GET.get('folders_page')
    folders_page = folders_paginator.get_page(folders_page_number)

    # ترقيم الوثائق
    documents_paginator = Paginator(documents_list, 25)  # 25 وثيقة في الصفحة
    documents_page_number = request.GET.get('page')
    documents_page = documents_paginator.get_page(documents_page_number)

    context = {
        'folders': folders_page,          # نمرر page_obj للمجلدات
        'page_obj': documents_page,       # نمرر page_obj للوثائق
        'current_folder': None,
    }
    return render(request, 'core/folder_browser.html', context)


@login_required
def folder_detail(request, folder_id):
    """
    يعرض محتوى مجلد معيّن: المجلدات الفرعية + الوثائق بداخله مباشرة،
    مع تقسيم الوثائق والمجلدات الفرعية على صفحات.
    """
    folder = get_object_or_404(Folder, id=folder_id)

    if not can_view_folder(request.user, folder):
        raise PermissionDenied

    subfolders_list = get_visible_folders(request.user).filter(parent_id=folder.id).select_related('created_by')
    documents_list = get_visible_documents(request.user).filter(folder_id=folder.id).select_related('department', 'directorate', 'uploaded_by')

    # ترقيم المجلدات الفرعية
    folders_paginator = Paginator(subfolders_list, 25)
    folders_page_number = request.GET.get('folders_page')
    folders_page = folders_paginator.get_page(folders_page_number)

    # ترقيم الوثائق
    documents_paginator = Paginator(documents_list, 25)
    documents_page_number = request.GET.get('page')
    documents_page = documents_paginator.get_page(documents_page_number)

    context = {
        'folders': folders_page,
        'page_obj': documents_page,
        'current_folder': folder,
        'can_delete': can_delete_folder(request.user, folder),
    }
    return render(request, 'core/folder_browser.html', context)


@login_required
def create_folder(request):
    """
    إنشاء مجلد جديد. المجلد "يتبع" منشئه تماماً كالوثيقة: المديرية والدائرة
    تُؤخذان تلقائياً من حساب المستخدم، دون أي حقل اختيار يدوي،
    باستثناء مدير المديرية الذي يختار الدائرة من قائمة دوائر مديريته.
    """
    if not request.user.role:
        raise PermissionDenied

    if not request.user.directorate_id:
        messages.error(request, 'حسابك غير مرتبط بمديرية، الرجاء مراجعة الإدارة.')
        return redirect('dashboard')

    # تحديد الدائرة حسب الدور
    department = None
    if request.user.role in [CustomUser.Role.EMPLOYEE, CustomUser.Role.HEAD_OF_DEPT]:
        department = request.user.department
        if not department:
            messages.error(request, 'حسابك غير مرتبط بدائرة، الرجاء مراجعة الإدارة.')
            return redirect('dashboard')
    elif request.user.role == CustomUser.Role.DIRECTORATE_MANAGER:
        # مدير المديرية يختار الدائرة من النموذج
        department_id = request.POST.get('department_id') or request.GET.get('department_id')
        if department_id:
            try:
                department = Department.objects.get(
                    id=department_id,
                    directorate_id=request.user.directorate_id
                )
            except Department.DoesNotExist:
                raise PermissionDenied
        # في حالة GET سيعرض النموذج مع قائمة الدوائر

    parent_id = request.POST.get('parent_id') or request.GET.get('parent_id')
    parent = None
    if parent_id:
        parent = get_object_or_404(Folder, id=parent_id)
        if not can_view_folder(request.user, parent):
            raise PermissionDenied

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'الرجاء إدخال اسم المجلد.')
        else:
            # التحقق من وجود دائرة للمدير مديرية
            if request.user.role == CustomUser.Role.DIRECTORATE_MANAGER and not department:
                messages.error(request, 'الرجاء اختيار الدائرة.')
                departments = Department.objects.filter(directorate_id=request.user.directorate_id)
                return render(request, 'core/create_folder.html', {
                    'parent': parent,
                    'departments': departments,
                })

            folder = Folder.objects.create(
                name=name,
                parent=parent,
                directorate=request.user.directorate,
                department=department,   # الدائرة المحددة
                created_by=request.user,
            )
            messages.success(request, f'تم إنشاء المجلد "{folder.name}" بنجاح.')
            if parent:
                return redirect('folder_detail', folder_id=parent.id)
            return redirect('folder_list')

    # GET: تجهيز departments لمدير المديرية
    departments = None
    if request.user.role == CustomUser.Role.DIRECTORATE_MANAGER:
        departments = Department.objects.filter(directorate_id=request.user.directorate_id)

    return render(request, 'core/create_folder.html', {
        'parent': parent,
        'departments': departments,
    })


@login_required
def delete_folder(request, folder_id):
    """
    حذف مجلد. يُمنع الحذف صراحة إذا كان المجلد يحتوي وثائق أو مجلدات فرعية،
    منعاً لفقدان أرشيف بالخطأ - يجب تفريغه أولاً.
    """
    folder = get_object_or_404(Folder, id=folder_id)

    if not can_delete_folder(request.user, folder):
        raise PermissionDenied

    if folder.has_content():
        messages.error(request, 'لا يمكن حذف المجلد لأنه يحتوي على وثائق أو مجلدات فرعية. الرجاء تفريغه أولاً.')
        return redirect('folder_detail', folder_id=folder.id)

    if request.method == 'POST':
        parent_id = folder.parent_id
        folder.delete()
        messages.success(request, 'تم حذف المجلد.')
        if parent_id:
            return redirect('folder_detail', folder_id=parent_id)
        return redirect('folder_list')

    return render(request, 'core/confirm_delete_folder.html', {'folder': folder})


# ==========================================================
# رفع وثيقة
# ==========================================================

@login_required
def upload_document(request):
    """
    رفع وثيقة جديدة.
    - المدير العام لا يرفع وثائق (يُمنع).
    - الموظف ورئيس القسم: تُؤخذ المديرية والدائرة تلقائياً من حسابهما.
    - مدير المديرية: تُؤخذ المديرية من حسابه، ويختار الدائرة من قائمة دوائر مديريته.
    """
    if not request.user.role:
        raise PermissionDenied

    # منع المدير العام من الرفع
    if request.user.role == CustomUser.Role.GENERAL_MANAGER:
        raise PermissionDenied

    if not request.user.directorate_id:
        messages.error(request, 'حسابك غير مرتبط بمديرية، الرجاء مراجعة الإدارة.')
        return redirect('dashboard')

    # تحديد الدائرة حسب الدور
    department = None
    if request.user.role in [CustomUser.Role.EMPLOYEE, CustomUser.Role.HEAD_OF_DEPT]:
        department = request.user.department
        if not department:
            messages.error(request, 'حسابك غير مرتبط بدائرة، الرجاء مراجعة الإدارة.')
            return redirect('dashboard')
    elif request.user.role == CustomUser.Role.DIRECTORATE_MANAGER:
        # مدير المديرية يختار الدائرة من النموذج
        department_id = request.POST.get('department_id') or request.GET.get('department_id')
        if department_id:
            try:
                department = Department.objects.get(
                    id=department_id,
                    directorate_id=request.user.directorate_id
                )
            except Department.DoesNotExist:
                raise PermissionDenied
        # في حالة GET سيعرض النموذج مع قائمة الدوائر

    folder_id = request.POST.get('folder_id') or request.GET.get('folder_id')
    folder = None
    if folder_id:
        folder = get_object_or_404(Folder, id=folder_id)
        if not can_view_folder(request.user, folder):
            raise PermissionDenied

    if request.method == 'POST':
        document_number = request.POST.get('document_number', '').strip()
        title = request.POST.get('title', '').strip()
        document_date = request.POST.get('document_date')
        source = request.POST.get('source')
        uploaded_file = request.FILES.get('file')
        tags_raw = request.POST.get('tags', '')

        issuing_directorate_id = request.POST.get('issuing_directorate')
        external_entity_name = request.POST.get('external_entity_name', '').strip()

        if not (document_number and title and document_date and source and uploaded_file):
            return _upload_error(request, folder, 'الرجاء تعبئة كل الحقول المطلوبة واختيار ملف.')

        # التحقق من أن رقم الوثيقة يبدأ برقم
        if not document_number[0].isdigit():
            return _upload_error(request, folder, 'رقم الوثيقة يجب أن يبدأ برقم.')

        if source not in Document.Source.values:
            return _upload_error(request, folder, 'قيمة المصدر غير صحيحة.')

        # للمدير المديرية: التحقق من اختيار الدائرة
        if request.user.role == CustomUser.Role.DIRECTORATE_MANAGER and not department:
            return _upload_error(request, folder, 'الرجاء اختيار الدائرة.')

        parsed_date = parse_date(document_date)
        if not parsed_date:
            return _upload_error(request, folder, 'تاريخ الوثيقة غير صالح.')
        document_year = parsed_date.year

        duplicate_exists = Document.objects.filter(
            directorate=request.user.directorate,
            document_year=document_year,
            document_number=document_number
        ).exists()
        if duplicate_exists:
            return _upload_error(
                request, folder,
                f'رقم الوثيقة "{document_number}" مستخدم مسبقاً ضمن مديرية {request.user.directorate.name} لسنة {document_year}. الرجاء اختيار رقم آخر.'
            )

        doc = Document.objects.create(
            document_number=document_number,
            title=title,
            file=uploaded_file,
            document_date=parsed_date,
            source=source,
            issuing_directorate_id=issuing_directorate_id if source == Document.Source.INTERNAL else None,
            external_entity_name=external_entity_name if source == Document.Source.EXTERNAL else '',
            folder=folder,
            directorate=request.user.directorate,
            department=department,
            uploaded_by=request.user,
        )

        for tag_name in [t.strip() for t in tags_raw.split(',') if t.strip()]:
            tag, _ = Tag.objects.get_or_create(name=tag_name)
            doc.tags.add(tag)

        log_action(request.user, doc, AuditLog.Action.CREATE)

        messages.success(request, f'تم رفع الوثيقة رقم {doc.document_number} بنجاح.')
        return redirect('document_detail', doc_id=doc.id)

    # GET: تجهيز سياق العرض مع قائمة الدوائر لمدير المديرية
    departments = None
    if request.user.role == CustomUser.Role.DIRECTORATE_MANAGER:
        departments = Department.objects.filter(directorate_id=request.user.directorate_id)
    return render(request, 'core/upload.html', _upload_context(folder, departments=departments))


def _upload_context(folder, departments=None):
    return {
        'folder': folder,
        'directorates': Directorate.objects.all(),
        'departments': departments,
    }


def _upload_error(request, folder, message, departments=None):
    """
    يوحد رسالة الخطأ وإعادة عرض نموذج الرفع مع الحفاظ على قائمة الدوائر
    إذا كان المستخدم مدير مديرية.
    """
    if departments is None and request.user.role == CustomUser.Role.DIRECTORATE_MANAGER:
        departments = Department.objects.filter(directorate_id=request.user.directorate_id)
    messages.error(request, message)
    return render(request, 'core/upload.html', _upload_context(folder, departments=departments))


# ==========================================================
# البحث
# ==========================================================

@login_required
def search_documents(request):
    """
    البحث بالخيارات: رقم الوثيقة، الاسم، نطاق التاريخ، الكلمة المفتاحية، المصدر،
    والجهة الصادرة (حسب المصدر). لا تظهر أي نتائج قبل إدخال معيار بحث واحد على الأقل.
    النتائج مقسمة على صفحات (25 لكل صفحة) عند وجودها.
    """
    # استخراج معايير البحث
    document_number = request.GET.get('document_number', '').strip()
    name = request.GET.get('name', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    keyword = request.GET.get('keyword', '').strip()
    source = request.GET.get('source', '').strip()
    issuing_directorate_id = request.GET.get('issuing_directorate', '').strip()
    external_entity_name = request.GET.get('external_entity_name', '').strip()

    # التحقق من وجود أي معيار بحث غير فارغ
    has_search_params = any([
        document_number,
        name,
        date_from,
        date_to,
        keyword,
        source,
        issuing_directorate_id,
        external_entity_name,
    ])

    # إذا لم يُدخل المستخدم أي معيار بحث، لا نعرض أي نتائج
    if not has_search_params:
        context = {
            'documents': None,
            'page_obj': None,
            'has_searched': False,
            'directorates': Directorate.objects.all(),
            'query_string': '',
        }
        return render(request, 'core/search.html', context)

    # يوجد معايير بحث -> نبدأ الفلترة
    documents = get_visible_documents(request.user).select_related('department', 'directorate', 'uploaded_by')

    if document_number:
        documents = documents.filter(document_number__icontains=document_number)

    if name:
        documents = documents.filter(title__icontains=name)

    if date_from:
        documents = documents.filter(document_date__gte=date_from)
    if date_to:
        documents = documents.filter(document_date__lte=date_to)

    if keyword:
        documents = documents.filter(
            Q(tags__name__icontains=keyword) | Q(document_number__icontains=keyword)
        ).distinct()

    if source in Document.Source.values:
        documents = documents.filter(source=source)

    if source == Document.Source.INTERNAL and issuing_directorate_id:
        documents = documents.filter(issuing_directorate_id=issuing_directorate_id)
    elif source == Document.Source.EXTERNAL and external_entity_name:
        documents = documents.filter(external_entity_name__icontains=external_entity_name)

    # ترتيب النتائج (الأحدث أولاً)
    documents = documents.order_by('-document_date', '-id')

    # تقسيم النتائج على صفحات
    paginator = Paginator(documents, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # بناء query string للحفاظ على معايير البحث في روابط التنقل
    query_params = request.GET.copy()
    query_params.pop('page', None)
    query_string = query_params.urlencode()

    context = {
        'documents': page_obj,
        'page_obj': page_obj,
        'has_searched': True,
        'directorates': Directorate.objects.all(),
        'query_string': query_string,
    }
    return render(request, 'core/search.html', context)


# ==========================================================
# عرض تفاصيل وثيقة / تحميل / تعديل / حذف
# ==========================================================

@login_required
def document_detail(request, doc_id):
    document = get_object_or_404(Document, id=doc_id)

    if not can_view_document(request.user, document):
        raise PermissionDenied

    # تم إلغاء تسجيل حدث VIEW لتقليل حجم سجل التدقيق

    context = {
        'document': document,
        'can_edit': can_edit_document(request.user, document),
        'can_delete': can_delete_document(request.user, document),
        'comments': document.comments.select_related('created_by'),
    }
    return render(request, 'core/document_detail.html', context)


@login_required
def download_document(request, doc_id):
    document = get_object_or_404(Document, id=doc_id)

    if not can_view_document(request.user, document):
        raise PermissionDenied

    log_action(request.user, document, AuditLog.Action.DOWNLOAD)

    try:
        return FileResponse(document.file.open('rb'), as_attachment=True,
                             filename=document.file.name.split('/')[-1])
    except FileNotFoundError:
        raise Http404('الملف غير موجود على الخادم.')


@login_required
def edit_document(request, doc_id):
    document = get_object_or_404(Document, id=doc_id)

    if not can_edit_document(request.user, document):
        raise PermissionDenied

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        document_number = request.POST.get('document_number', '').strip()
        document_date = request.POST.get('document_date')

        if not (title and document_number and document_date):
            messages.error(request, 'الرجاء تعبئة جميع الحقول.')
        else:
            # التحقق من أن رقم الوثيقة يبدأ برقم
            if not document_number[0].isdigit():
                messages.error(request, 'رقم الوثيقة يجب أن يبدأ برقم.')
                return render(request, 'core/edit_document.html', {'document': document})
            
            parsed_date = parse_date(document_date)
            if not parsed_date:
                messages.error(request, 'تاريخ غير صالح.')
            else:
                # فحص التكرار: نفس المديرية ونفس السنة ونفس الرقم مع استبعاد الوثيقة الحالية
                duplicate_exists = Document.objects.filter(
                    directorate=document.directorate,
                    document_year=parsed_date.year,
                    document_number=document_number
                ).exclude(pk=document.pk).exists()

                if duplicate_exists:
                    messages.error(
                        request,
                        f'رقم الوثيقة "{document_number}" مستخدم مسبقاً ضمن مديرية {document.directorate.name} لسنة {parsed_date.year}. الرجاء اختيار رقم آخر.'
                    )
                else:
                    document.title = title
                    document.document_number = document_number
                    document.document_date = parsed_date
                    document.save()
                    log_action(request.user, document, AuditLog.Action.EDIT)
                    messages.success(request, 'تم تعديل الوثيقة بنجاح.')
                    return redirect('document_detail', doc_id=document.id)

    return render(request, 'core/edit_document.html', {'document': document})


@login_required
def delete_document(request, doc_id):
    document = get_object_or_404(Document, id=doc_id)

    if not can_delete_document(request.user, document):
        raise PermissionDenied

    if request.method == 'POST':
        log_action(request.user, document, AuditLog.Action.DELETE)
        document.delete()
        messages.success(request, 'تم حذف الوثيقة، وتم تسجيل الإجراء بسجل التدقيق.')
        return redirect('dashboard')

    return render(request, 'core/confirm_delete.html', {'document': document})


@login_required
def add_comment(request, doc_id):
    document = get_object_or_404(Document, id=doc_id)

    if not can_view_document(request.user, document):
        raise PermissionDenied

    if request.method == 'POST':
        text = request.POST.get('text', '').strip()
        if text:
            Comment.objects.create(document=document, text=text, created_by=request.user)

    return redirect('document_detail', doc_id=document.id)