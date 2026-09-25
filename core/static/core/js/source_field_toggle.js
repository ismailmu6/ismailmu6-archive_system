/*
 * core/static/core/js/source_field_toggle.js
 *
 * منطق مشترك واحد يُستخدم بشاشتي "رفع وثيقة" و"البحث": يُظهر حقل
 * "المديرية الصادرة عنها" فقط عند اختيار المصدر "داخلي"، ويُظهر حقل
 * "اسم الجهة الخارجية" فقط عند اختيار المصدر "خارجي". في حالة "الكل"
 * أو عدم الاختيار، يُخفي الحقلين معاً.
 *
 * يعمل هذا الملف بشكل عام عبر البحث عن أي عنصر <select> يحمل السمة
 * data-source-toggle، ويربطه تلقائياً بعنصرين يحملان data-source-panel
 * بقيمة "internal" و"external" على التوالي - بذلك لا حاجة لتكرار هذا
 * المنطق بكود منفصل بكل شاشة.
 */

function initSourceFieldToggle() {
    document.querySelectorAll('[data-source-toggle]').forEach(function (select) {
        var container = select.closest('form') || document;
        var internalPanel = container.querySelector('[data-source-panel="internal"]');
        var externalPanel = container.querySelector('[data-source-panel="external"]');

        function apply() {
            var value = select.value;
            if (internalPanel) {
                internalPanel.style.display = (value === 'internal') ? '' : 'none';
            }
            if (externalPanel) {
                externalPanel.style.display = (value === 'external') ? '' : 'none';
            }
        }

        select.addEventListener('change', apply);
        apply(); // تطبيق فوري عند تحميل الصفحة (يغطي حالة "الكل" الافتراضية بشاشة البحث)
    });
}

/*
 * ==========================================================
 * منطق "الجهة المحولة إليها"
 * ==========================================================
 * مشابه لمنطق المصدر أعلاه، لكنه أكثر عمومية: يعمل عبر أي عنصر
 * <select> يحمل السمة data-toggle-group="اسم المجموعة"، ويرتبط
 * تلقائياً بأي عنصر يحمل:
 *   - data-panel-group="نفس اسم المجموعة"
 *   - data-panel-value="القيمة التي يُظهر عندها"
 *
 * مثال: عند اختيار "داخلي" بالحقل data-toggle-group="destination"،
 * يُظهر العنصر الذي يحمل data-panel-group="destination" و
 * data-panel-value="internal"، ويُخفي الآخر.
 */
function initToggleGroups() {
    document.querySelectorAll('[data-toggle-group]').forEach(function (select) {
        var group = select.dataset.toggleGroup;
        var container = select.closest('form') || document;
        var panels = container.querySelectorAll('[data-panel-group="' + group + '"]');

        function apply() {
            var value = select.value;
            panels.forEach(function (panel) {
                panel.style.display = (panel.dataset.panelValue === value) ? '' : 'none';
            });
        }

        select.addEventListener('change', apply);
        apply(); // تطبيق فوري عند تحميل الصفحة
    });
}

document.addEventListener('DOMContentLoaded', function () {
    initSourceFieldToggle();
    initToggleGroups();
});