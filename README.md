# تعبئة تك — TABIA TECH

برنامج مكتبي عربي يعمل محلياً لإدارة المواد الخام والمشتريات وأوامر الإنتاج وأجور العمال والتقارير باستخدام **SQLite** و **Tkinter**.

## البناء الآلي لمثبّت Windows 7 SP1 بنواة 32 بت

بعد رفع هذه الملفات إلى GitHub في فرع `main`، يبدأ سير عمل **Build TABIA TECH - Win7 x86 Installer** تلقائياً عندما يتغير كود البرنامج. يمكن تشغيله يدوياً من تبويب **Actions → Build TABIA TECH - Win7 x86 Installer → Run workflow**.

عند نجاح البناء، افتح آخر تشغيل ناجح ثم **Artifacts → TABIA_TECH_Setup_Win7_x86**، ونزّل الأرشيف الذي يحتوي على الملف:

`TABIA_TECH_Setup_Win7_x86.exe`

هذا الملف ليس مُرفقاً بالمستودع قبل نجاح GitHub Actions. يحتاج حساب GitHub إلى السماح بتشغيل Actions، وقد يحتاج إلى مراجعة صلاحيات تشغيل مهام البناء.

### محتويات المشروع

- `TABIA_TECH_desktop.py`: الواجهات العربية (Tkinter).
- `TABIA_TECH_engine.py`: محرك SQLite ومعاملات الإنتاج والمشتريات والعمال.
- `TABIA_TECH_schema.sql`: تعريف الجداول والفهارس والتقارير.
- `TABIA_TECH.db`: قاعدة **أولية تجريبية بلا سجلات عملاء أو مشتريات أو إنتاج فعلية**.
- `build_win7_x86.ps1`: بناء برنامج Windows 32-bit والمثبّت.
- `TABIA_TECH_Win7_x86.iss`: إعداد Inno Setup.
- `.github/workflows/build-win7-32bit.yml`: مهمة GitHub Actions.
- `TABIA_TECH_integration_tests.py`, `TABIA_TECH_ui_smoke_tests.py`: الاختبارات.

### التشغيل من المصدر

يحتاج Python 3.8 مع Tkinter:

```bash
python TABIA_TECH_desktop.py
```

### خصوصية البيانات

هذه النسخة لا ترسل بيانات المصنع عبر الإنترنت. تحفظ بيانات التشغيل على جهاز Windows في `%LOCALAPPDATA%\TABIA_TECH`. **لا ترفع قاعدة البيانات المستخدمة بالفعل إلى مستودع GitHub عام**، ولا تضع بيانات تجارية أو كلمات مرور أو مفاتيح API في Git.

### التوافق والتنبيه

المستهدف: **Windows 7 SP1 (32-bit x86)**. عملية البناء تتم بواسطة runner حديث Windows x64 مع Python x86. **لم يتم تأكيد تشغيل البرنامج على جهاز Windows 7 فعلي**؛ يلزم اختبار المثبّت قبل استخدامه لإدارة بيانات حقيقية. ويندوز 7 خارج الدعم الأمني.

للتفاصيل راجع `README_WIN7_32bit_AR.txt`.
