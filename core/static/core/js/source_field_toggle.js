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

document.addEventListener('DOMContentLoaded', initSourceFieldToggle);