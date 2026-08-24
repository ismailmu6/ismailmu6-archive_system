/*
 * core/static/core/js/department_filter.js
 *
 * يحتوي وظيفتين مترابطتين لشاشة إنشاء/تعديل مستخدم (CustomUser) بلوحة /admin:
 *
 * 1. فلترة "الدائرة" حسب "المديرية" المختارة - تعرض فقط الدوائر التابعة لها.
 * 2. قفل/تعطيل الحقلين حسب "الدور الوظيفي" المختار، لمنع إدخال بيانات
 *    غير منطقية (مثلاً مدير عام مربوط بمديرية معينة بالغلط):
 *      - مدير عام:      حقلا المديرية والدائرة يُعطَّلان تماماً (نطاقه كل شي)
 *      - مدير مديرية:   حقل المديرية يبقى فعالاً، حقل الدائرة يُعطَّل
 *      - رئيس دائرة/موظف: الحقلان يبقيان فعالين كالمعتاد
 *
 * ملاحظة أمنية: هذا تحسين واجهة فقط لمساعدة الأدمن على إدخال صحيح -
 * منطق الصلاحيات الفعلي (من يرى ماذا) مبني بالكامل بملف core/permissions.py
 * ولا يعتمد على حالة هذا الحقل بالواجهة إطلاقاً.
 */

document.addEventListener('DOMContentLoaded', function () {
    var directorateSelect = document.getElementById('id_directorate');
    var departmentSelect = document.getElementById('id_department');
    var roleSelect = document.getElementById('id_role');

    if (!directorateSelect || !departmentSelect) {
        return;
    }

    // ==========================================================
    // 1. فلترة الدائرة حسب المديرية المختارة
    // ==========================================================
    var allDepartmentOptions = Array.prototype.slice.call(departmentSelect.options);

    function filterDepartments() {
        var selectedDirectorateId = directorateSelect.value;
        var currentDepartmentValue = departmentSelect.value;

        departmentSelect.innerHTML = '';

        allDepartmentOptions.forEach(function (option) {
            if (option.value === '') {
                departmentSelect.appendChild(option.cloneNode(true));
                return;
            }

            var optionDirectorateId = option.getAttribute('data-directorate-id');

            if (!selectedDirectorateId || optionDirectorateId === selectedDirectorateId) {
                departmentSelect.appendChild(option.cloneNode(true));
            }
        });

        var stillValid = Array.prototype.some.call(departmentSelect.options, function (o) {
            return o.value === currentDepartmentValue;
        });
        if (stillValid) {
            departmentSelect.value = currentDepartmentValue;
        }
    }

    directorateSelect.addEventListener('change', filterDepartments);
    filterDepartments();

    // ==========================================================
    // 2. قفل الحقول حسب الدور الوظيفي
    // ==========================================================
    if (!roleSelect) {
        return; // شاشة الوثيقة مثلاً ما فيها حقل دور - نكتفي بالفلترة فقط
    }

    var GENERAL_MANAGER = 'GM';
    var DIRECTORATE_MANAGER = 'DM';

    function setFieldState(select, shouldDisable) {
        select.disabled = shouldDisable;
        if (shouldDisable) {
            select.value = '';
            // نطبّق الفلترة مجدداً بعد تفريغ القيمة حتى تنعكس بصرياً فوراً
            if (select === departmentSelect) {
                filterDepartments();
            }
        }
        var wrapper = select.closest('.form-row') || select.parentElement;
        if (wrapper) {
            wrapper.style.opacity = shouldDisable ? '0.5' : '1';
        }
    }

    function applyRoleLock() {
        var role = roleSelect.value;

        if (role === GENERAL_MANAGER) {
            setFieldState(directorateSelect, true);
            setFieldState(departmentSelect, true);
        } else if (role === DIRECTORATE_MANAGER) {
            setFieldState(directorateSelect, false);
            setFieldState(departmentSelect, true);
        } else {
            setFieldState(directorateSelect, false);
            setFieldState(departmentSelect, false);
        }
    }

    roleSelect.addEventListener('change', applyRoleLock);
    directorateSelect.addEventListener('change', applyRoleLock);

    // تطبيق فوري عند فتح صفحة تعديل مستخدم موجود مسبقاً
    applyRoleLock();
});