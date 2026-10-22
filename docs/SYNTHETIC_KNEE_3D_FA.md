# نمونهٔ بازسازی سه‌بعدی زانوی ساختگی

این مرحله روی `feature/synthetic-knee-3d` با مبنای PR۴۶ در commit `bb185ce4c6cdff3b50f9de00514d308af2ee9702` ساخته شده است. فایل‌های مسیرهای دانش و یکپارچه‌سازی، API، مدل‌های SQLAlchemy، Safety و شاخه main تغییر نمی‌کنند. این یک نمونهٔ مستقل قابل اتصال است؛ در مسیر پرونده واقعی یا Physician Copilot ثبت نمی‌شود.

## نتیجه و محدوده

نمونه به‌طور پیش‌فرض از ۹۶ فایل MR یا CT کاملاً تولیدشده، حجم voxel واقعی می‌سازد و برچسب‌های معلوم همان phantom را به ۱۳ سطح تبدیل می‌کند. ران و درشت‌نی از الگوی عمومی OpenSim می‌آیند؛ کشکک، نازک‌نی، غضروف، دو منیسک، دو رباط صلیبی، دو رباط جانبی و تاندون‌های کشکک و چهارسر به‌صورت هندسی ساخته می‌شوند. این یک تصویرسازی عمومی از زانوی چپ با وضعیت قرارگیری تقریبی است و آناتومی بیمار یا شبیه‌سازی حرکتی OpenSim نیست. وضوح ۶۴ نیز برای آزمون سریع قابل انتخاب است. MR و CT از همان مدل ساختگی ساخته می‌شوند؛ الگوریتم registration بین دو اسکن واقعی در این مرحله وجود ندارد.

**این مرحله segmentation خودکار MRI/CT واقعی، تشخیص آسیب یا جایگزین آرتروسکوپی نیست.** رنگ پیش‌فرض به رنگ تقریبی بافت‌ها نزدیک شده و حالت رنگ تفکیکی نیز قابل انتخاب است. هیچ رنگی از اسکن اندازه‌گیری نشده است. «دید داخلی» یک دوربین آزاد در هندسهٔ تولیدشده است؛ حرکت فیزیولوژیک، تماس ابزار، collision، بافت نوری واقعی و جزئیات نادیدهٔ اسکن بازسازی نمی‌شوند. هیچ مدل آموزش‌دیده یا confidence بالینی ساخته نشده است. هش‌ها ردیابی محتوا را ممکن می‌کنند و تضمین صحت بالینی نیستند.

```mermaid
flowchart LR
  P[الگوی عمومی استخوان + بافت هندسی با برچسب معلوم] --> D[فایل‌های DICOM ساختگی]
  D --> G[کنترل موجود Study/Series]
  G --> V[حجم voxel و affine در LPS]
  P --> L[برچسب مرجع همان شبکه]
  V --> S[سطح VTK بدون smoothing]
  L --> S
  V --> B[نمایشگر محلی و مقاطع متصل]
  S --> M[سطح نرم‌شده مستقل فقط برای نمایش]
  M --> B
```

## کد و کنترل هندسه

- `backend/tools/knee_anatomy.py`: دریافت فقط دو mesh همراه مخزن با SHA ثابت، تبدیل محور، آینه‌کردن الگوی راست برای زانوی چپ، تبدیل متر به میلی‌متر، جابه‌جایی نمایشی، کوتاه‌کردن ساقه و voxelization در دامنه ثابت ۱۲۰×۱۱۰×۲۲۰ میلی‌متر. با تغییر وضوح، اندازه فیزیکی ثابت می‌ماند. منیسک‌ها روی ستون‌های سطح درشت‌نی قرار می‌گیرند؛ شکل C و ضخامت بیشتر لبه بیرونی دارند. شکل و اتصال بافت‌ها تقریبی و فاقد تأیید متخصص است.
- `backend/tools/knee_templates/ATTRIBUTION.md`: منبع immutable، نام سازندگان، مجوز CC BY 3.0، SHA و تغییرات الگوهای OpenSim؛ نسخه آن در artifact با نام `ANATOMY_ATTRIBUTION.md` کپی می‌شود. فایل اسکن بیمار دریافت نشده است.
- `backend/tools/synthetic_knee_fixture.py`: تولید Part 10 ساختگی؛ phantom تحلیلی قدیمی برای regression حفظ شده است؛ شدت‌ها فقط برای آزمودن مسیر pixel هستند و شبیه‌ساز فیزیک MRI/CT محسوب نمی‌شوند.
- `backend/app/imaging_intelligence/reconstruction.py`: پروفایل بستهٔ ساختگی با inventory صریح و SHA فایل‌ها. هر فایل از یک descriptor معمولی، بدون دنبال‌کردن symlink و با سقف ۱۲۸ KiB به snapshot بایتی خوانده می‌شود. metadata و pixel از همان snapshot مصرف می‌شوند. کنترل موجود Study/Series دوباره استفاده می‌شود. marker مصنوعی جلوی اشتباه ساده را می‌گیرد؛ اثبات ناشناس‌سازی یا هویت نیست.
- پروفایل فعلی فقط single-frame، Explicit VR Little Endian، MONOCHROME2 شانزده‌بیتی و اندازه حداکثر ۹۶ در هر محور را می‌پذیرد. CT signed و MR unsigned هستند. PixelData باید طول دقیق داشته باشد؛ slope/intercept معتبر روی مقدار واقعی decodeشده اعمال می‌شود. ورودی فشرده یا خارج از پروفایل متوقف می‌شود.
- آرایه `zyx` است. affine چهاردرچهار، مرکز voxel با indexهای `[i,j,k,1]` را به LPS میلی‌متر می‌برد. ضریب i برابر نخستین بردار IOP ضربدر **PixelSpacing[1]** و ضریب j برابر دومین بردار ضربدر **PixelSpacing[0]** است. فاصلهٔ k از position برش‌ها به دست می‌آید؛ SliceThickness جای آن را نمی‌گیرد. نام فایل و ترتیب ورودی دخالتی ندارند.
- `surface_reconstruction.py`: سطح‌های `vtkDiscreteFlyingEdges3D` از برچسب معلوم و با مرز نیم‌voxel ساخته و با همان affine به LPS منتقل می‌شوند. سطح مرجع، بدون smoothing یا resampling حفظ می‌شود. نسخهٔ جداگانهٔ نمایشی با `vtkWindowedSincPolyDataFilter`، ۱۵ iteration و pass band برابر ۰٫۱ ساخته می‌شود. index مثلث‌ها ثابت است؛ مختصات، hash و حداکثر جابه‌جایی سطح نمایشی جدا گزارش می‌شوند و جابه‌جایی بیش از دو برابر بزرگ‌ترین spacing مجاز نیست. مساحت، bounds و حجم گزارش‌شده همواره به هندسه مرجع مربوط‌اند. نرم‌شدن، افزایش جزئیات واقعی یا اعتبار آناتومیک ایجاد نمی‌کند. مثلث‌های مساحت صفر حذف می‌شوند. حجم گزارش‌شده از شمارش voxel و determinant affine است؛ برآورد بالینی یا حجم محصور mesh نیست.

نام، PatientID، raw UID و مسیر فایل به artifact صادر نمی‌شوند. referenceهای مصدر HMACشده‌اند؛ کلید نمونه ثابت و مخصوص دادهٔ ساختگی است و برای بیمار مناسب نیست. فایل‌های DICOM موقت پس از export حذف می‌شوند؛ artifact فقط شامل داده مشتق‌شده ساختگی است. ورودی arbitrary فایل یا URL، endpoint شبکه و اتصال DB در CLI وجود ندارد. ورود تصویر واقعی به پروفایل بعدی به طراحی دسترسی، حریم خصوصی، پروفایل pixel، segmentation و اعتبارسنجی مستقل نیاز دارد.

## نمایشگر و خروجی قابل دریافت

`backend/imaging_3d_viewer` نمایش پیش‌فرض با استخوان‌های مات، رنگ تقریبی بافت و ماده/نور متفاوت برای غضروف دارد. حالت رنگ تفکیکی قابل انتخاب است. دکمه «نمای مفصل» کشکک و دو تاندون جلویی را پنهان می‌کند و با بازگشت به نمای کامل آن‌ها را نمایش می‌دهد. این دکمه جابه‌جایی فیزیکی کشکک یا شبیه‌سازی جراحی انجام نمی‌دهد. نمایشگر همچنین روشن/خاموش‌کردن هر ساختار، شفافیت استخوان، clipping plane، سه مقطع شبکهٔ حجم، window/level و cursor مشترک دارد. نسبت فیزیکی pixel در مقاطع حفظ می‌شود. کلیک در مقطع، نقطه را با affine در فضای سه‌بعدی مشخص می‌کند. این صفحات، محورهای شبکهٔ حجم‌اند؛ برای ورودی oblique ادعای reslice مستقیم محوری/کرونال بیمار ندارند.

دید داخلی با کشیدن ماوس می‌چرخد؛ `W/A/S/D` حرکت و `R/F` بالا/پایین می‌روند. فقط با focus روی canvas این کلیدها فعال‌اند. این پیمایش، شبیه‌سازی آرتروسکوپی بالینی یا ناوبری ایمن داخل بافت نیست. بازگشت «نمای کامل» دوربین را reset می‌کند.

Three.js نسخه `0.180.0` است. فایل‌های runtime و LICENSE پس از کنترل SHA-256 در برابر commit ثابت `0af9729d0c143a86a1d725d6e2c3ad83301f3f34` داخل artifact کپی می‌شوند؛ CDN، فونت بیرونی و درخواست مرکز تصویربرداری وجود ندارد. voxel و label باینری هنگام بارگذاری در مرورگر با hash و اندازه کنترل می‌شوند. برنامه از WebGL2 استفاده می‌کند و خطای بارگذاری را به‌صورت آشکار نشان می‌دهد.

workflow `Synthetic Knee 3D` برای MR و CT، ZIP جدا شامل `viewer/`، `preview.png`، `front-preview.png`، `joint-preview.png` و گزارش آزمون مرورگر در بخش Artifacts همان run نگه می‌دارد (۱۴ روز). پس از دریافت و استخراج، وارد پوشه `viewer` شوید و سرور محلی را اجرا کنید؛ بازکردن مستقیم `file://` به‌دلیل محدودیت module/fetch مرورگر پشتیبانی نمی‌شود.

```bash
# فعلاً محیط اختیاری CPython 3.12؛ dependencyهای عملیاتی تغییر نمی‌کنند.
python -m pip install -r backend/requirements-imaging-3d.txt
npm install --prefix /tmp/4b-knee-node three@0.180.0 --ignore-scripts --no-audit --no-fund
python -m backend.tools.imaging_knee_3d_demo \
  --output /tmp/4b-knee-mr --three-root /tmp/4b-knee-node/node_modules/three --modality MR
python -m http.server 18765 --bind 127.0.0.1 --directory /tmp/4b-knee-mr
# مرورگر: http://127.0.0.1:18765
```

output باید پوشه‌ای جدید باشد. برای CT، output جدید و `--modality CT` انتخاب شود. CLI مسیر DICOM بیمار نمی‌گیرد. برای اجرای artifact دریافت‌شده از CI، نصب Python dependency یا npm لازم نیست؛ فقط سرویس فایل محلی و مرورگر WebGL2 نیاز است.

## آزمون و محدودیت اجرا

```bash
python -m unittest discover -s backend/tests/imaging_3d -v
python -m pip install playwright==1.56.0
python -m playwright install --with-deps chromium
python backend/tests/imaging_3d_browser.py \
  --artifact /tmp/4b-knee-mr --screenshot /tmp/knee-preview.png
```

۲۱ آزمون، MR/CT signed، round-trip همه voxelها، ترتیب فایل، affine oblique و anisotropic، rescale، تفاوت thickness و فاصله برش، فایل خراب، hash تغییرکرده، pixel ناقص، marker نادرست، محدوده فایل، symlink/FIFO، هندسه سطح، topology بسته و عدم خروج اطلاعات هویتی را بررسی می‌کنند. کنترل یکسان‌ماندن هندسه و معیارهای مرجع هنگام نرم‌کردن سطح نمایش، integrity الگو، حضور ۱۳ بافت در هر دو وضوح، ترتیب مکانی ساختارها، تکیه‌گاه استخوانی منیسک‌ها و round-trip پروفایل آناتومیک نیز آزموده می‌شوند. نبود runtime اختیاری در CI عمومی backend باعث skip این ماژول تست می‌شود؛ job اختصاصی 3D پیش از تست import اجباری دارد تا نبود وابستگی را موفقیت محسوب نکند. آزمون MPR در مرورگر یک pixel را با باینری حجم واقعی مقایسه می‌کند؛ صرف نمایش canvas موفقیت محسوب نمی‌شود.

آزمون مرورگر از Chromium و WebGL2 واقعی استفاده می‌کند. Playwright همان فایل‌های artifact را با route محلی ارائه و هر درخواست بیرونی را رد می‌کند؛ سرور DB یا socket شنونده لازم نیست. pixel رنگی واقعی، ظاهر مات اولیه، تعویض palette، نمای باز مفصل، visibility، opacity، clipping، انتخاب مقطع و نقطه متصل، دوربین داخلی و چیدمان موبایل آزموده می‌شوند. دادهٔ هندسی، decoder و renderer mock نمی‌شوند.

در محیط مدیریت‌شده، نصب شبکه‌ای و راه‌اندازی Chromium با محدودیت sandbox مواجه شد (`setsockopt: Operation not permitted`). اجرای محلی VTK و ۲۱ آزمون هندسه موفق بود؛ ادعای موفقیت مرورگر محلی مطرح نمی‌شود. source رسمی pydicom 3.0.1 و فایل‌های رسمی Three.js خارج از مخزن از طریق دسترسی GitHub دریافت و blob hashهایشان کنترل شدند. اجرای مرورگر و بسته‌بندی artifact در CI انجام می‌شود؛ نتیجه هر run باید با SHA همان PR سنجیده شود.

گام بعد از پذیرش این نمونه، adapter برچسب‌های تصویربرداری با منشأ و شبکهٔ فضایی صریح، اصلاح متخصص و ارزیابی segmentation است؛ مسیرِ ورود دادهٔ بیمار یا مدل تشخیصی در این PR باز نمی‌شود.

## منابع پیاده‌سازی

- [DICOM Image Plane Module](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.7.6.2.html): قرارداد position/orientation/spacing.
- [VTK Discrete Flying Edges](https://vtk.org/doc/nightly/html/classvtkDiscreteFlyingEdges3D.html): استخراج سطح از label volume و مرز نیم‌voxel؛ runtime این نمونه به 9.3.1 pin شده است.
- [Three.js r180](https://github.com/mrdoob/three.js/tree/0af9729d0c143a86a1d725d6e2c3ad83301f3f34): renderer و OrbitControls با مجوز MIT.

- [OpenSim Gait2392 و مجوز الگو](../backend/tools/knee_templates/ATTRIBUTION.md): منبع و حدود استفاده از femur/tibia.
- [OpenStax 9.6](https://openstax.org/books/anatomy-and-physiology-2e/pages/9-6-anatomy-of-selected-synovial-joints): مرجع توصیفی ساختار و اتصال بافت‌ها؛ هیچ تصویر آن کپی نشده است.
