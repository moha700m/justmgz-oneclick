# justmgz — حزمة المصدر (تسليم)

المستودع: https://github.com/moha700m/justmgz-oneclick

## البنية
```
justmgz.py                      التطبيق: UAC، WSL، بناء المحرك، usbipd، نافذة WebView2
app/justmgz-engine.py           الجسر v3: EventBus + SSE + محاكي + 5 باكندات كشف
app/ui.html                     الواجهة العربية (RTL) — مدمجة أيضاً داخل الجسر
app/names.json                  82 موديل: ProductType → الاسم التجاري
app/fix-build.patch             ترقيع إلزامي لبناء المحرك
.github/workflows/build-exe.yml بناء exe + Release
.github/workflows/ci.yml        اختبارات windows/ubuntu
build-local.ps1                 بناء محلي
```

## بناء
```powershell
python -m pip install pyinstaller pywebview pythonnet
pyinstaller --onefile --noconfirm --clean --name justmgz `
  --add-data "app;app" --hidden-import=webview --collect-all webview justmgz.py
.\dist\justmgz.exe --selftest
```

## المسارات (15)
GET: `/` `/health` `/api/state` `/api/device` `/api/diag` `/api/events` `/api/log-stream`
     `/api/usbipd` `/api/sim` `/api/routes`
POST: `/api/run?mode=` `/api/attach` `/api/detach` `/api/sim` `/api/build`

## المعمارية v3
- **EventBus**: pub/sub، backlog 400، قائمة كل مشترك 800.
- **SSE**: `/api/events` — الواجهة تحدّث الجهاز والفحص من الأحداث، والـpolling احتياط.
- **5 باكندات**: pyusb → PowerShell PnP → usbipd → pymobiledevice3 → libimobiledevice.
- **parse_serial + CPID_CHIP + A_CHIPS** في بايثون، تُعرض في `/api/device`.
- **محاكي**: `TR4MPASS_SIM=dfu_a12` أو `POST /api/sim?state=` — كل شيء موسوم `simulated:true` و`verdict:"sim"`.

## المشكلة المفتوحة
الجهاز لا يُقرأ على جهاز المستخدم. الفحص يبدأ من:
1. `do_attach()` — usbipd bind/attach + توزيعة صريحة
2. `detect_backends()` — أي باكند يشوف الجهاز
3. `probe_device()` — مخرجات `tr4mpass -d`
ملف المستخدم: `%USERPROFILE%\justmgz-diag.txt`

## تحذير
المحرك خارجي (github.com/tr4m0ryp/tr4mpass). A12+ تحتاج إنترنت وقت التنشيط.
