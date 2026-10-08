# 🎬 Islomov Kino Telegram Boti (@Islomovkinobot)

Ushbu loyiha Telegram uchun to'liq funksional, zamonaviy va tezkor kino botidir. Bot **aiogram 3** va **aiosqlite** asosida yaratilgan.

---

## 🌟 Asosiy Imkoniyatlar

### 👤 Foydalanuvchilar uchun:
1. **Kino kodi orqali yuklash**: Foydalanuvchi ijtimoiy tarmoqlardan (TikTok, Instagram, Telegram) ko'rgan kino kodini yuborishi bilan bot kinoni darhol yuboradi.
2. **Kino qidirish**: Kino nomini yozib qidirish imkoniyati.
3. **Majburiy obuna (Sponsor kanallar)**: Foydalanuvchi belgilangan kanallarga a'zo bo'lmaguncha kinolarni ko'ra olmaydi.
4. **Tasodifiy kino**: Zerikkanda tavsiya qilinadigan tasodifiy film.
5. **Top kinolar**: Eng ko'p ko'rilgan filmlar reytingi.
6. **Ulashish tugmasi**: Kinoni do'stlarga bir bosishda ulashish.

### ⚡️ Administrator uchun (`/admin`):
1. **➕ Kino qo'shish**:
   - Telegramga video/fayl yuboriladi (Telegram serverlarida saqlanadi, server xotirasini band qilmaydi).
   - Bot avtomatik navbatdagi kodni tavsiya qiladi yoki ixtiyoriy kod berish mumkin.
   - Nomi va tavsifi kiritiladi.
2. **🗑 Kino o'chirish**: Kod orqali bazadan o'chirish.
3. **📊 Statistika**: Foydalanuvchilar, kinolar va umumiy ko'rishlar soni.
4. **📢 Xabar tarqatish (Rassilka)**: Barcha bot foydalanuvchilariga rasm, video yoki matnli e'lon yuborish (bloklaganlarni hisobga oladi).
5. **🔗 Homiy kanallarni boshqarish**: Majburiy obuna kanallarini dinamik qo'shish va o'chirish.

---

## 🚀 O'rnatish va Ishga Tushirish

### 1. Talablar:
- Python 3.10 yoki undan yuqori
- Internet aloqasi

### 2. Kutubxonalarni o'rnatish:
```bash
pip install -r requirements.txt
```

### 3. Sozlamalar (`.env` fayli):
`.env` faylini ochib, o'z Telegram ID raqamingizni `ADMINS` qatoriga yozing:
```env
BOT_TOKEN=8871611449:AAEqnJxlmrBEWYKACn7L4j-FaociSm4TyNE
ADMINS=123456789
DB_PATH=data/kino_bot.db
```

> 💡 **O'z ID raqamingizni bilish uchun**: Telegramda [@userinfobot](https://t.me/userinfobot) yoki [@myidbot](https://t.me/myidbot) ga `/start` yuboring. Bir nechta admin bo'lsa vergul bilan ajrating: `ADMINS=111111,222222`.

### 4. Botni ishga tushirish:
- **Windows uchun**: `run_bot.bat` faylini ikki marta bosing.
- **Terminal orqali**:
  ```bash
  python main.py
  ```

---

## 🔒 Xavfsizlik bo'yicha Muhim Eslatma:
> Bot tokeni maxfiy ma'lumot hisoblanadi. Agar uni ochiq joylarda (masalan ommaviy GitHub repozitoriy) qoldirgan bo'lsangiz, Telegramdagi [@BotFather](https://t.me/BotFather) orqali `/revoke` buyrug'i yordamida tokenni yangilashingiz va yangi tokenni `.env` fayliga kiritishingiz tavsiya etiladi.
