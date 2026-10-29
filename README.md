تصحيح فشل بناء TABIA TECH على GitHub Actions (Windows 7 x86)

السبب المؤكد من سجل التشغيل 40948379963:
  sqlite3.OperationalError: unknown function: json_valid()

SQLite 3.35.5 في Python 3.8.10 x86 لا يتيح json_valid() تلقائياً،
بينما تحتوي قاعدة المشروع على CHECK(json_valid(...)).
كان محرك البرنامج يسجل الدالة على اتصاله الرئيسي فقط، وليس على اتصالات
النسخ الاحتياطي والاستعادة. واستخدم الاختبار اتصالاً خاماً إضافياً.

التغييرات في الملفات الثلاثة المرفقة:
- TABIA_TECH_engine.py: إضافة connect_sqlite() التي تسجل json_valid()
  لكل اتصال، واستعمالها لعمليات النسخ الاحتياطي والتحقق والاستعادة.
- إغلاق اتصالات النسخ بدقة مع contextlib.closing، لحل قفل الملفات WinError 32.
- TABIA_TECH_integration_tests.py: فحص النسخة باتصال متوافق ومغلق.
- TABIA_TECH_desktop.py: إصلاح استعادة قاعدة البيانات من واجهة البرنامج،
  باستعمال الاتصال المتوافق وإغلاق جميع الملفات.

تعليمات الرفع:
1. افتح المستودع https://github.com/saeedan2005/TABIA-TECH
2. استبدل الملفات الثلاثة الموجودة في جذر المستودع بالملفات المناظرة في الأرشيف.
   لا تغيّر TABIA_TECH_schema.sql أو ملف قاعدة البيانات ولا ملف Workflow.
3. افتح Actions وتحقق من المهمة الجديدة بعد Commit إلى main.
4. إذا نجحت المهمة، حمل TABIA_TECH_Setup_Win7_x86 من Artifacts.

ملاحظة: اختبارات Linux المحلية لا تعادل اختبار GitHub Windows x86؛
ولم يثبت بعد التشغيل على Windows 7 فعلي.
