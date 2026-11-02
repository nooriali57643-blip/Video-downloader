# دانلودر ویدیو — Ali Noori x Claude

دو بخش دارد:
- پوشه `web/` ← ظاهر سایت (فقط فایل `index.html`) → روی GitHub Pages
- پوشه `server/` ← سرور (`app.py`, `requirements.txt`, `Dockerfile`) → روی Render / Railway / VPS

## ۱) سرور (Render، با موبایل)
1. یک ریپوی GitHub بسازید (مثلاً `video-server`) و سه فایل پوشه `server/` را در آن آپلود کنید.
2. در render.com ثبت‌نام کنید → New → Web Service → ریپو را انتخاب کنید → Runtime: **Docker**.
3. بعد از Deploy یک آدرس مثل `https://xxx.onrender.com` می‌گیرید.
4. (اختیاری) در Environment متغیر `ALLOWED_ORIGIN` را برابر `https://USERNAME.github.io` بگذارید تا فقط سایت شما اجازه‌ی استفاده داشته باشد.
5. اینستاگرام اغلب به کوکی نیاز دارد: فایل cookies.txt بسازید و مسیرش را در `COOKIES_FILE` بگذارید.
6. yt-dlp را هر چند هفته آپدیت کنید (Redeploy)، چون پلتفرم‌ها مدام تغییر می‌کنند.

## ۲) سایت (GitHub Pages)
1. ریپوی دیگری بسازید (مثلاً `video-site`) و فایل `index.html` را آپلود کنید.
2. Settings → Pages → Branch: main → Save.
3. سایت را باز کنید، روی ⚙ بزنید و آدرس سرور مرحله‌ی ۱ را وارد کنید.
   (یا در فایل `index.html` مقدار `DEFAULT_API` را عوض کنید.)

## نکته
فقط برای ویدیوهای خودتان یا ویدیوهایی که اجازه‌ی دانلودشان را دارید استفاده کنید.
