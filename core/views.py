from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.db.models import Q
from django.utils.dateparse import parse_date

from .models import Document, Comment, Tag, AuditLog, Folder, Directorate
from .permissions import (
    get_visible_documents, can_view_document, can_manage_document, is_supervisory_action,
    get_visible_folders, can_view_folder, can_manage_folder,
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
    لوحة تحكم واحدة تخدم كل الأدوار الأربعة، لأن get_visible_documents
    نفسها تحدد ما يظهر - لا حاجة لأربع شاشات منفصلة لكل دور.
    """
    documents = get_visible_documents(request.user)

    context = {
        'total_documents': documents.count(),
        'recent_documents': documents[:10],
        'internal_count': documents.filter(source=Document.Source.INTERNAL).count(),
        'external_count': documents.filter(source=Document.Source.EXTERNAL).count(),
    }
    return render(request, 'core/dashboard.html', context)


# ==========================================================
# المجلدات (تنظيم اختياري متداخل يديره كل مستخدم لأرشيفه)
# ==========================================================

@login_required
def folder_list(request):
    """يعرض المجلدات الجذرية (بلا مجلد أب) المرئية للمستخدم، مدخل تصفح الأرشيف بشكل شجري"""
    folders = get_visible_folders(request.user).filter(parent__isnull=True)
    # الوثائق غير المصنّفة داخل أي مجلد، ضمن نفس نطاق رؤية المستخدم
    documents = get_visible_documents(request.user).filter(folder__isnull=True)

    context = {'folders': folders, 'documents': documents, 'current_folder': None}
    return render(request, 'core/folder_browser.html', context)


@login_required
def folder_detail(request, folder_id):
    """يعرض محتوى مجلد معيّن: المجلدات الفرعية + الوثائق بداخله مباشرة"""
    folder = get_object_or_404(Folder, id=folder_id)

    if not can_view_folder(request.user, folder):
        raise PermissionDenied

    subfolders = get_visible_folders(request.user).filter(parent_id=folder.id)
    documents = get_visible_documents(request.user).filter(folder_id=folder.id)

    context = {'folders': subfolders, 'documents': documents, 'current_folder': folder}
    return render(request, 'core/folder_browser.html', context)


@login_required
def create_folder(request):
    """
    إنشاء مجلد جديد. المجلد "يتبع" منشئه تماماً كالوثيقة: المديرية والدائرة
    تُؤخذان تلقائياً من حساب المستخدم، دون أي حقل اختيار يدوي.
    """
    if not request.user.role:
        raise PermissionDenied

    if not request.user.department_id or not request.user.directorate_id:
        messages.error(request, 'حسابك غير مرتبط بمديرية/دائرة، الرجاء مراجعة الإدارة.')
        return redirect('dashboard')

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
            folder = Folder.objects.create(
                name=name,
                parent=parent,
                directorate=request.user.directorate,
                department=request.user.department,
                created_by=request.user,
            )
            messages.success(request, f'تم إنشاء المجلد "{folder.name}" بنجاح.')
            if parent:
                return redirect('folder_detail', folder_id=parent.id)
            return redirect('folder_list')

    return render(request, 'core/create_folder.html', {'parent': parent})


@login_required
def delete_folder(request, folder_id):
    """
    حذف مجلد. يُمنع الحذف صراحة إذا كان المجلد يحتوي وثائق أو مجلدات فرعية،
    منعاً لفقدان أرشيف بالخطأ - يجب تفريغه أولاً.
    """
    folder = get_object_or_404(Folder, id=folder_id)

    if not can_manage_folder(request.user, folder):
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
    رفع وثيقة جديدة. المديرية والدائرة (نطاق الصلاحيات) تُؤخذان مباشرة من
    حساب المستخدم - لا يوجد أي حقل بالنموذج يسمح باختيار مديرية/دائرة مختلفة
    عن مكانه التنظيمي الفعلي.

    الجهة الصادرة تختلف حسب المصدر:
      - داخلي: تُختار من قائمة المديريات الموجودة فعلياً بالنظام
      - خارجي: نص حر يكتبه الموظف (جهات خارجية كثيرة وغير محصورة)

    المجلد اختياري بالكامل - رفع مباشر بدون مجلد، أو داخل مجلد حدده الموظف.
    """
    if not request.user.role:
        raise PermissionDenied

    if not request.user.department_id or not request.user.directorate_id:
        messages.error(request, 'حسابك غير مرتبط بمديرية/دائرة، الرجاء مراجعة الإدارة.')
        return redirect('dashboard')

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

        if source not in Document.Source.values:
            return _upload_error(request, folder, 'قيمة المصدر غير صحيحة.')

        # تحويل نص التاريخ القادم من النموذج (HTML) إلى كائن date حقيقي بلغة
        # Python - ضروري لأن Document.objects.create() لا يمر بعملية validation
        # التلقائية التي تحوّل النص لكائن تاريخ (بعكس ModelForm)، وبدون هذا
        # التحويل تفشل self.document_date.year بدالة save() بالموديل
        parsed_date = parse_date(document_date)
        if not parsed_date:
            return _upload_error(request, folder, 'تاريخ الوثيقة غير صالح.')
        document_year = parsed_date.year

        # منع تكرار رقم الوثيقة ضمن نفس المديرية ونفس السنة فقط - يبدأ الترقيم
        # من جديد تلقائياً كل سنة (نفس الرقم مسموح يتكرر بمديرية أخرى أو بسنة مختلفة)
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
            document_date=parsed_date,  # كائن date حقيقي، وليس نصاً
            source=source,
            issuing_directorate_id=issuing_directorate_id if source == Document.Source.INTERNAL else None,
            external_entity_name=external_entity_name if source == Document.Source.EXTERNAL else '',
            folder=folder,
            directorate=request.user.directorate,   # تلقائي، غير قابل للتعديل من المستخدم
            department=request.user.department,      # تلقائي، غير قابل للتعديل من المستخدم
            uploaded_by=request.user,
        )

        for tag_name in [t.strip() for t in tags_raw.split(',') if t.strip()]:
            tag, _ = Tag.objects.get_or_create(name=tag_name)
            doc.tags.add(tag)

        log_action(request.user, doc, AuditLog.Action.CREATE)

        messages.success(request, f'تم رفع الوثيقة رقم {doc.document_number} بنجاح.')
        return redirect('document_detail', doc_id=doc.id)

    return render(request, 'core/upload.html', _upload_context(folder))


def _upload_context(folder):
    return {
        'folder': folder,
        'directorates': Directorate.objects.all(),
    }


def _upload_error(request, folder, message):
    """يوحّد رسالة الخطأ وإعادة عرض نموذج الرفع بنفس السياق، بدل تكرار السطرين بكل حالة فشل"""
    messages.error(request, message)
    return render(request, 'core/upload.html', _upload_context(folder))


# ==========================================================
# البحث
# ==========================================================

@login_required
def search_documents(request):
    """
    البحث بالخيارات الأربعة: الاسم، نطاق التاريخ، الوسم/الكلمة المفتاحية، المصدر.
    عند اختيار المصدر (داخلي/خارجي)، يظهر حقل بحث مخصص للجهة الصادرة، بنفس
    منطق شاشة الرفع تماماً:
      - داخلي: قائمة منسدلة لاختيار المديرية الصادرة عنها
      - خارجي: حقل نصي حر للبحث باسم الجهة الخارجية
    مبني فوق get_visible_documents مباشرة - لا يمكن لأي فلتر بحث أن يظهر
    نتيجة خارج نطاق صلاحيات المستخدم.
    """
    documents = get_visible_documents(request.user)

    document_number = request.GET.get('document_number', '').strip()
    name = request.GET.get('name', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    keyword = request.GET.get('keyword', '').strip()
    source = request.GET.get('source', '').strip()
    issuing_directorate_id = request.GET.get('issuing_directorate', '').strip()
    external_entity_name = request.GET.get('external_entity_name', '').strip()

    if document_number:
        documents = documents.filter(document_number__icontains=document_number)

    if name:
        documents = documents.filter(title__icontains=name)

    if date_from:
        documents = documents.filter(document_date__gte=date_from)
    if date_to:
        documents = documents.filter(document_date__lte=date_to)

    if keyword:
        # الكلمة المفتاحية تبقى تبحث بالوسوم ورقم الوثيقة أيضاً (بحث عام شامل)،
        # بينما حقل "رقم الوثيقة" أعلاه بحث دقيق مخصص لهذا الحقل تحديداً
        documents = documents.filter(
            Q(tags__name__icontains=keyword) | Q(document_number__icontains=keyword)
        ).distinct()

    if source in Document.Source.values:
        documents = documents.filter(source=source)

    # حقل الجهة الصادرة يُطبَّق فقط مع مصدر محدد، ونوعه يتبدّل حسب المصدر
    if source == Document.Source.INTERNAL and issuing_directorate_id:
        documents = documents.filter(issuing_directorate_id=issuing_directorate_id)
    elif source == Document.Source.EXTERNAL and external_entity_name:
        documents = documents.filter(external_entity_name__icontains=external_entity_name)

    context = {
        'documents': documents,
        'search_params': request.GET,
        'directorates': Directorate.objects.all(),
    }
    return render(request, 'core/search.html', context)


# ==========================================================
# عرض تفاصيل وثيقة / تحميل / تعديل / حذف
# ==========================================================

@login_required
def document_detail(request, doc_id):
    document = get_object_or_404(Document, id=doc_id)

    # فحص إلزامي حتى لو خُمِّن الرابط مباشرة - لا اعتماد على إخفاء الرابط بالواجهة فقط
    if not can_view_document(request.user, document):
        raise PermissionDenied

    log_action(request.user, document, AuditLog.Action.VIEW)

    context = {
        'document': document,
        'can_manage': can_manage_document(request.user, document),
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
def delete_document(request, doc_id):
    document = get_object_or_404(Document, id=doc_id)

    if not can_manage_document(request.user, document):
        raise PermissionDenied

    if request.method == 'POST':
        # تسجيل الإجراء قبل الحذف الفعلي حتى يبقى رقم/اسم الوثيقة موثقاً بالسجل
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