# النسخ الاحتياطي والاسترجاع

## الطبقات
| الطبقة | أين | متى | الاحتفاظ |
|---|---|---|---|
| خدمة `backup` | داخل السيرفر (وحدة `backups`) | يومياً 02:00 الرياض | 7 أيام، 4 أسابيع، 6 أشهر |
| خدمة `offsite` | تخزين خارجي S3 (Backblaze B2 مثلاً) **مشفّر** | يومياً 03:30 الرياض | 200 يوم (`OFFSITE_KEEP_DAYS`) |
| نسخ Hostinger | لقطة كاملة للسيرفر | أسبوعياً (من لوحة Hostinger) | حسب الخطة |

خدمة `offsite` تنسخ نسخ القاعدة وملفات المنصة (`evidence`) بـ `rclone copy` (ما يُحذف من السيرفر لا يُحذف من الخارج)،
وتشفّر المحتوى وأسماء الملفات بعبارة المرور، فلا يقرأها مزوّد التخزين. بعد كل نجاح تكتب `_last_success.txt`.

## التفعيل (مرة واحدة)
في Coolify ← التطبيق ← Environment Variables (قيم سرية، لا تُلصق في المحادثات):

| المتغير | المثال |
|---|---|
| `OFFSITE_ENDPOINT` | `https://s3.eu-central-003.backblazeb2.com` (من صفحة الحاوية في B2) |
| `OFFSITE_REGION` | `eu-central-003` |
| `OFFSITE_BUCKET` | اسم الحاوية |
| `OFFSITE_KEY_ID` | keyID |
| `OFFSITE_SECRET` | applicationKey (Lock) |
| `OFFSITE_ENC_PASSWORD` | عبارة مرور طويلة (Lock) — **احفظها خارج السيرفر؛ بدونها لا يمكن فك النسخ** |

ثم Redeploy. سجل خدمة `offsite` يجب أن يُظهر «✓ اكتمل» بعد دقيقتين تقريباً.

## تجربة الاسترجاع (دون المساس بالبيانات الحقيقية)
Coolify ← Terminal ← حاوية **backup** ← الصق:
```
export PGPASSWORD="$POSTGRES_PASSWORD"; F=$(ls -1t /backups/last/*.sql.gz | head -1); echo "النسخة: $F"; psql -h db -U "$POSTGRES_USER" -d postgres -qc "DROP DATABASE IF EXISTS restore_test" -c "CREATE DATABASE restore_test" && gunzip -c "$F" | psql -q -h db -U "$POSTGRES_USER" -d restore_test >/dev/null && psql -h db -U "$POSTGRES_USER" -d restore_test -c "SELECT (SELECT count(*) FROM aqap.app_user) AS users, (SELECT count(*) FROM aqap.assessment) AS assessments, (SELECT count(*) FROM aqap.evidence) AS evidence"; psql -h db -U "$POSTGRES_USER" -d postgres -qc "DROP DATABASE restore_test"; echo "انتهت التجربة"
```
تنشئ قاعدة مؤقتة من آخر نسخة، تعرض أعداد السجلات لتقارنها بالمنصة، ثم تحذفها. القاعدة الحقيقية لا تُمس.
لأخذ نسخة فورية قبل التجربة: `/backup.sh` في الحاوية نفسها.

## الاسترجاع الفعلي (عند الكارثة)
1. أوقف خدمة `api` (Coolify ← Stop).
2. من حاوية `backup`: احذف القاعدة وأعد إنشاءها ثم استرجع:
   `psql -h db -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE aqap" -c "CREATE DATABASE aqap"` ثم
   `gunzip -c /backups/daily/aqap-latest.sql.gz | psql -h db -U "$POSTGRES_USER" -d aqap`
3. شغّل `api`.

### من النسخة الخارجية (إن ضاع السيرفر)
على أي جهاز فيه rclone، بنفس متغيرات OFFSITE_*:
```
export RCLONE_CONFIG_STORE_TYPE=s3 RCLONE_CONFIG_STORE_PROVIDER=Other RCLONE_CONFIG_STORE_ENDPOINT=... RCLONE_CONFIG_STORE_ACCESS_KEY_ID=... RCLONE_CONFIG_STORE_SECRET_ACCESS_KEY=...
export RCLONE_CONFIG_SAFE_TYPE=crypt RCLONE_CONFIG_SAFE_REMOTE="store:BUCKET/aqap"
export RCLONE_CONFIG_SAFE_PASSWORD=$(rclone obscure "PASSPHRASE") RCLONE_CONFIG_SAFE_PASSWORD2=$(rclone obscure "PASSPHRASE-salt")
rclone copy safe:db ./restore/db && rclone copy safe:files ./restore/files
```
