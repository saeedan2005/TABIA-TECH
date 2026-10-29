تعبئة تك — حزمة بناء ملف EXE لنظام Windows 7 SP1 (32-bit)
==============================================================

حالة التسليم: كود جاهز للبناء وليس ملف EXE مبنياً مسبقاً.
لم يكن Windows أو Wine متاحاً في بيئة إنشاء هذه الحزمة، ولذلك لم يكن ممكناً إنتاج ملف التثبيت الفعلي أو تشغيله على Windows 7 هنا.

ما الذي ستنتجه الحزمة عند البناء على Windows:
1. dist\TABIA_TECH\TABIA_TECH.exe — برنامج Windows 32-bit يحتوي Python/Tkinter/SQLite ضمن ملفاته المرفقة، ولا يطلب تثبيت Python على جهاز العميل.
2. installer_output\TABIA_TECH_Setup_Win7_x86.exe — ملف تثبيت واحد يحتوي البرنامج بكل ملفاته وينشئ اختصاراً على سطح المكتب.

الطريقة (أ) — بناء تلقائي عبر GitHub Actions:
- أنشئ مستودع GitHub خاصاً وارفع محتويات الحزمة إلى جذر المستودع مع المجلد المخفي .github.
- افتح Actions ثم اختر Build TABIA TECH Windows 7 x86 installer ثم Run workflow.
- بعد اكتمال البناء، نزّل الأثر باسم TABIA_TECH_Setup_Win7_x86 وافتح ملف EXE بداخله.
- هذا يتطلب حساب GitHub وإنترنت وقت البناء فقط؛ البرنامج النهائي يعمل محلياً بلا إنترنت.

الطريقة (ب) — البناء على جهاز Windows 10/11 أو Windows 7 SP1:
- ثبّت Python 3.8.10 32-bit (x86) مع Tcl/Tk وpip من Python.org.
- ثبّت Inno Setup 6 (مترجم ISCC.exe).
- انقر build_win7_x86.cmd نقراً مزدوجاً أو نفّذ build_win7_x86.ps1 من PowerShell.
- بعد نجاح البناء ستجد: installer_output\TABIA_TECH_Setup_Win7_x86.exe

مواصفات التوافق:
- Windows 7 SP1، 32-bit (x86)، أو أحدث.
- Python المستخدم أثناء البناء: 3.8.10 x86؛ PyInstaller 5.13.2.
- مخطط SQLite متوافق مع الإصدارات القديمة، دون STRICT (التي تتطلب SQLite 3.37+).
- تتم المحافظة على CHECK وFOREIGN KEY وقيود سجلات التعديل والحركات.
- دالة json_valid مسجلة محلياً للتوافق مع نسخة SQLite التي قد لا تحتوي JSON1.
- كافة بيانات العمل تحفظ في %LOCALAPPDATA%\TABIA_TECH وليس داخل Program Files.
- تحديث البرنامج أو إلغاء تثبيته لا يحذف قاعدة المستخدم الموجودة في مجلد بياناته.

مهم جداً:
- الحزمة تحتوي قاعدة بيانات أولية فارغة، وليست سجلات العمل الحقيقية.
- إن كانت لديك بالفعل قاعدة بيانات مستخدمة من الإصدار السابق (STRICT) فلا تنسخها عشوائياً على Windows 7؛ احتفظ بنسخة سليمة منها واطلب تحويلها على SQLite أحدث قبل الاستخدام.
- Windows 7 انتهى دعمه الأمني. يُنصح باستخدام جهاز غير متصل بالإنترنت وحفظ نسخ احتياطية خارجية.
- قبل الاستخدام اليومي تحقق من نجاح التثبيت والتجربة على جهاز Windows 7 SP1 فعلي.
- قد يحتاج Windows 7 إلى تحديث Universal C Runtime وخدمات Visual C++ المناسبة؛ لا يمكن ضمان ذلك دون اختبار الجهاز المستهدف.

مكونات الحزمة:
- TABIA_TECH_desktop.py    الواجهات العربية
- TABIA_TECH_engine.py     محرك العمليات
- TABIA_TECH_schema.sql    مخطط قاعدة البيانات المتوافق
- TABIA_TECH.db            ملف SQLite فارغ ومحضر للعمل
- TABIA_TECH_Win7_x86.iss  تعريف المثبت
- build_win7_x86.ps1 / .cmd   بناء البرنامج والمثبت
- verify_win32_build.py   التحقق من صيغة EXE والعمارة والمكونات
- .github/workflows/..   أتمتة البناء على Windows x86
- TABIA_TECH_integration_tests.py  اختبارات العمليات
- TABIA_TECH_ui_smoke_tests.py   اختبارات الواجهات
