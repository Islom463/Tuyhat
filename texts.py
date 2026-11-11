"""
texts.py — bot matnlari (o'zbek lotin, o'zbek kirill, rus, ingliz) va lotin→kirill o'giruvchi.
 
Kirill matnlari alohida yozilmaydi: o'zbek lotin matni avtomatik kirillga o'giriladi
(HTML teglar, {joy_belgilari}, @username va /buyruqlar o'zgarmaydi).
"""
import re
 
LANGS = ("uz", "uz_cyrl", "ru", "en")
LANG_NAMES = {"uz": "🇺🇿 O'zbekcha", "uz_cyrl": "🇺🇿 Ўзбекча", "ru": "🇷🇺 Русский", "en": "🇬🇧 English"}
 
# ----------------------------------------------------------------------------------------------
# Lotin -> Kirill (o'zbek)
# ----------------------------------------------------------------------------------------------
_PROTECT = re.compile(
    r"(<[^>]+>|\{[^}]*\}|https?://\S+|@\w+|/\w+|"
    r"\b(?:AI|PDF|IQ|SYNTX|Groq|ID|HTML|PNG|MP4|MP3|Telegram|WhatsApp|Instagram|DEMO)\b)")
_VOW = set("aeiou")
_MAP = dict(a="а", b="б", d="д", f="ф", g="г", h="ҳ", i="и", j="ж", k="к", l="л", m="м", n="н", o="о", p="п",
            q="қ", r="р", s="с", t="т", u="у", v="в", x="х", y="й", z="з", c="ц", w="в")
 
 
def _lat2cyr(s):
    s = re.sub(r"[ʻʼ‘’`´]", "'", s)
    out, i, n = [], 0, len(s)
    while i < n:
        ch = s[i]
        lo = ch.lower()
        if not (lo.isascii() and (lo.isalpha() or lo == "'")):
            out.append(ch)
            i += 1
            continue
        nx = s[i + 1].lower() if i + 1 < n else ""
        nx2 = s[i + 2] if i + 2 < n else ""
        prev = s[i - 1] if i > 0 else ""
        up = ch.isupper()
 
        def put(c):
            out.append(c.upper() if up else c)
 
        if lo == "o" and nx == "'":
            put("ў"); i += 2; continue
        if lo == "g" and nx == "'":
            put("ғ"); i += 2; continue
        if lo == "s" and nx == "h":
            put("ш"); i += 2; continue
        if lo == "c" and nx == "h":
            put("ч"); i += 2; continue
        if lo == "y" and nx == "o" and nx2 == "'":      # yo'q -> йўқ
            put("й"); i += 1; continue
        if lo == "y" and nx in ("a", "o", "u", "e"):
            put({"a": "я", "o": "ё", "u": "ю", "e": "е"}[nx]); i += 2; continue
        if lo == "e":
            put("э" if (not prev.isalpha() or prev.lower() in _VOW) else "е"); i += 1; continue
        if lo == "'":
            out.append("ъ" if (prev.isalpha() and nx.isalpha()) else "'")
            i += 1
            continue
        put(_MAP.get(lo, ch)); i += 1
    return "".join(out)
 
 
def to_cyrillic(text):
    parts = _PROTECT.split(text)
    return "".join(p if i % 2 else _lat2cyr(p) for i, p in enumerate(parts))
 
 
_CYR2LAT = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z", "и": "i",
            "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
            "у": "u", "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "'", "ы": "i", "ь": "",
            "э": "e", "ю": "yu", "я": "ya", "ў": "o'", "қ": "q", "ғ": "g'", "ҳ": "h"}
 
 
def to_latin(text):
    """Kirill -> o'zbek lotin (taxminiy; ismlar uchun yetarli)."""
    out = []
    for ch in text:
        lo = ch.lower()
        if lo in _CYR2LAT:
            r = _CYR2LAT[lo]
            if lo == "е" and (not out or not out[-1].isalpha()):
                r = "ye"
            out.append(r.capitalize() if ch.isupper() and r else r)
        else:
            out.append(ch)
    return "".join(out)
 
 
# ----------------------------------------------------------------------------------------------
# Bot matnlari
# ----------------------------------------------------------------------------------------------
PALETTE_LABELS = {
    "uz": {"bordo": "🍷 Bordo", "zumrad": "🌿 Zumrad", "qora": "🖤 Qora-oltin", "binafsha": "💜 Binafsha",
           "kobalt": "💙 Kobalt", "firuza": "🌊 Firuza", "krem": "🤍 Krem", "pushti": "🌸 Pushti",
           "osmon": "☁️ Osmon", "shalfey": "🍃 Shalfey"},
    "ru": {"bordo": "🍷 Бордо", "zumrad": "🌿 Изумруд", "qora": "🖤 Чёрно-золотой", "binafsha": "💜 Фиолетовый",
           "kobalt": "💙 Кобальт", "firuza": "🌊 Бирюза", "krem": "🤍 Кремовый", "pushti": "🌸 Розовый",
           "osmon": "☁️ Небесный", "shalfey": "🍃 Шалфей"},
    "en": {"bordo": "🍷 Burgundy", "zumrad": "🌿 Emerald", "qora": "🖤 Black & gold", "binafsha": "💜 Purple",
           "kobalt": "💙 Cobalt", "firuza": "🌊 Teal", "krem": "🤍 Cream", "pushti": "🌸 Blush",
           "osmon": "☁️ Sky", "shalfey": "🍃 Sage"},
}
 
TR_LANGS = {  # tarjima tillari: kod -> (nomi, Groq uchun tavsif)
    "uz": ("🇺🇿 O'zbekcha (lotin)", "Uzbek (Latin script, standard o' and g' letters)"),
    "uz_cyrl": ("🇺🇿 Ўзбекча (кирилл)", "Uzbek (Cyrillic script)"),
    "ru": ("🇷🇺 Русский", "Russian"),
    "en": ("🇬🇧 English", "English"),
    "tr": ("🇹🇷 Türkçe", "Turkish"),
    "ar": ("🇸🇦 العربية", "Arabic"),
    "de": ("🇩🇪 Deutsch", "German"),
    "fr": ("🇫🇷 Français", "French"),
    "ko": ("🇰🇷 한국어", "Korean"),
    "zh": ("🇨🇳 中文", "Chinese (Simplified)"),
}
 
S = {
    # ------------------------------------------------------------------------------ O'ZBEKCHA (lotin)
    "uz": {
        "welcome": ("👋 Salom, <b>{name}</b>!\n\n"
                    "Bu bot:\n"
                    "🎬 AI yordamida <b>video taklifnoma</b> yasaydi — ism, sana, manzil yozasiz, dizayn va musiqani o'zi tanlaydi\n"
                    "🌐 matn va rasmni <b>tarjima</b> qiladi\n"
                    "✅ <b>grammatik xatolarni</b> topib tuzatadi\n\n"
                    "Pastdagi tugmalardan birini tanlang 👇"),
        "m_invite": "🎬 Taklifnoma yasash", "m_tr": "🌐 Tarjima", "m_gr": "✅ Xatolarni topish",
        "m_pay": "💳 Obuna", "m_lang": "🌍 Til", "m_help": "☎️ Aloqa",
        "lang_changed": "✅ Til o'zgartirildi.",
        "cancelled": "✅ Bekor qilindi.",
        "help": ("☎️ <b>Aloqa</b>\n\nSavollar, to'lov va hamkorlik uchun admin: {admin}\n\n"
                 "Bekor qilish uchun istalgan paytda /cancel yozing."),
        # ---- to'lov
        "pay_info": ("💳 <b>Obuna narxi: {price} so'm</b> ({period})\n\n"
                     "To'lov kartasi:\n<code>{card}</code>\n{owner}\n\n"
                     "1️⃣ Kartaga <b>{price} so'm</b> o'tkazing\n"
                     "2️⃣ «📤 Chek yuborish» ni bosing va to'lov chekini (skrinshot) yuboring\n"
                     "3️⃣ Admin tasdiqlagach, taklifnoma yasash ochiladi (odatda bir necha daqiqada)\n\n"
                     "Savollar uchun admin: {admin}"),
        "period_life": "bir marta to'lanadi, muddatsiz", "period_days": "{d} kunga",
        "pay_need": "🔒 Taklifnoma yasash pullik xizmat.\n\n",
        "pay_send": "📤 Chek yuborish", "pay_admin": "💬 Adminga yozish", "pay_demo": "👀 Namunani ko'rish",
        "pay_receipt_prompt": "📤 To'lov chekini (rasm yoki skrinshot) yuboring.\nBekor qilish: /cancel",
        "pay_need_photo": "Iltimos, chekni rasm yoki fayl ko'rinishida yuboring.",
        "pay_sent": "✅ Chek adminga yuborildi. Tasdiqlangach sizga xabar beramiz.",
        "pay_pending": "⏳ To'lovingiz tekshirilmoqda. Savol bo'lsa: {admin}",
        "pay_ok": "🎉 <b>To'lovingiz tasdiqlandi!</b>\nEndi «🎬 Taklifnoma yasash» ni bosib, taklifnoma yasashingiz mumkin.",
        "pay_no": "❌ To'lovingiz tasdiqlanmadi. Chek aniq ko'rinishi kerak. Savol bo'lsa: {admin}",
        "sub_active": "✅ Obunangiz faol: <b>{until}</b>", "sub_life": "muddatsiz", "sub_none": "🔓 Obuna yo'q.",
        "demo_caption": "👀 Namuna. Har safar dizayn va musiqa boshqacha chiqadi, o'zingiz tanlashingiz ham mumkin.",
        # ---- taklifnoma
        "inv_names": "👰🤵 <b>Kelin va kuyov ismlari?</b>\nMasalan: <i>Aziz va Madina</i>",
        "inv_date": "📅 <b>To'y sanasi?</b>\nMasalan: <i>15 dekabr 2026</i>",
        "inv_time": "⏰ <b>Vaqti?</b>\nMasalan: <i>18:00</i>  (kerak bo'lmasa «-» yuboring)",
        "inv_venue": "📍 <b>To'yxona nomi va manzili?</b>\nMasalan: <i>«Registon» to'yxonasi, Toshkent sh.</i>",
        "inv_lang": "🌐 Taklifnoma qaysi tilda bo'lsin?",
        "inv_text": "✍️ <b>Taklif matni</b> qanday bo'lsin?",
        "inv_text_ai": "🤖 AI yozsin", "inv_text_own": "✍️ O'zim yozaman",
        "inv_text_prompt": "✍️ Taklif matnini yuboring.\nMasalan: <i>Sizni farzandlarimizning nikoh to'yiga taklif etamiz</i>",
        "inv_style": "🎨 <b>Dizayn</b> qanday bo'lsin?",
        "inv_style_rand": "🎲 AI o'zi tanlasin", "inv_style_pal": "🖌 Rangni tanlayman", "inv_style_desc": "💬 O'zim ta'riflayman",
        "inv_style_text": ("💬 Qanday dizayn xohlaysiz? Erkin yozing.\n"
                           "Masalan: <i>bordo va oltin rang, suzani naqshli</i> yoki <i>yumshoq pushti, gullar</i>"),
        "inv_pal": "🖌 Rangni tanlang:",
        "inv_music": "🎵 <b>Musiqa</b> qanday bo'lsin?",
        "inv_music_auto": "🎲 Avtomatik", "inv_music_own": "🎧 O'zim yuboraman",
        "inv_music_prompt": "🎧 Musiqani (audio yoki mp3 fayl) yuboring.",
        "inv_music_bad": "Audio fayl yuboring (mp3 yoki ovozli xabar).",
        "inv_working": "⏳ Taklifnoma tayyorlanmoqda... Odatda 1-2 daqiqa.",
        "inv_queue": "⏳ Navbatda {n} ta ish bor. Biroz kuting...",
        "inv_done": "✅ <b>Tayyor!</b> {names}",
        "inv_novideo": "⚠️ Video yasab bo'lmadi, shuning uchun tayyor rasm yuborildi.",
        "inv_again_design": "🔄 Boshqa dizayn", "inv_again_music": "🎵 Boshqa musiqa", "inv_new": "🆕 Yangi taklifnoma",
        "inv_expired": "⚠️ Buyurtma ma'lumoti topilmadi. «🎬 Taklifnoma yasash» orqali qaytadan boshlang.",
        "inv_busy": "⏳ Oldingi taklifnomangiz hali tayyorlanyapti. Kuting.",
        "inv_too_long": "Juda uzun. Iltimos, qisqaroq yozing.",
        "inv_ai_text_used": "🤖 AI yozgan matn:\n<i>{text}</i>",
        # ---- tarjima va xato tuzatish
        "tr_pick": "🌐 <b>Tarjima</b>\nQaysi tilga tarjima qilamiz?",
        "tr_ready": ("🌐 Tarjima tili: <b>{lang}</b>\n\nMatn yoki rasm yuboring — tarjima qilaman "
                     "(grammatik xatolar avtomatik tuzatiladi). Tilni almashtirish: «🔁 Tilni o'zgartirish»."),
        "tr_change": "🔁 Tilni o'zgartirish",
        "tr_result": "🌐 <b>Tarjima ({lang}):</b>\n\n{text}",
        "tr_original": "📝 <b>Rasmdagi matn:</b>\n{text}",
        "gr_ready": ("✅ <b>Xatolarni topish</b>\n\nTekshiriladigan matn yoki rasm yuboring. "
                     "Men xatolarni topib, tuzatilgan matnni beraman."),
        "gr_fixed": "✅ <b>Tuzatilgan matn:</b>\n\n{text}",
        "gr_errors": "🔎 <b>Topilgan xatolar:</b>\n{items}",
        "gr_none": "🎉 Xato topilmadi — matn to'g'ri yozilgan!",
        "ai_working": "⏳ Ishlayapman...",
        "ai_fail": "⚠️ AI hozir band yoki ishlamayapti. Birozdan keyin qayta urinib ko'ring.",
        "ai_no_text": "Matn yoki rasm yuboring.",
        "ai_no_text_found": "😕 Rasmda matn topilmadi.",
        "ai_too_long": "Matn juda uzun (3500 belgigacha).",
        "free_over": ("⚠️ Bugungi bepul limit ({n} ta) tugadi.\nCheksiz foydalanish uchun obuna bo'ling: «💳 Obuna». "
                      "Limit ertaga yangilanadi."),
        "err": "⚠️ Xatolik yuz berdi. Qayta urinib ko'ring yoki /start bosing.",
    },
    # ------------------------------------------------------------------------------ RUSCHA
    "ru": {
        "welcome": ("👋 Привет, <b>{name}</b>!\n\n"
                    "Этот бот:\n"
                    "🎬 создаёт <b>видеоприглашение</b> на свадьбу с помощью AI — вы пишете имена, дату и адрес, дизайн и музыку он подберёт сам\n"
                    "🌐 <b>переводит</b> текст и фото\n"
                    "✅ находит и исправляет <b>грамматические ошибки</b>\n\n"
                    "Выберите кнопку внизу 👇"),
        "m_invite": "🎬 Создать приглашение", "m_tr": "🌐 Перевод", "m_gr": "✅ Поиск ошибок",
        "m_pay": "💳 Подписка", "m_lang": "🌍 Язык", "m_help": "☎️ Контакты",
        "lang_changed": "✅ Язык изменён.",
        "cancelled": "✅ Отменено.",
        "help": ("☎️ <b>Контакты</b>\n\nПо вопросам, оплате и сотрудничеству пишите админу: {admin}\n\n"
                 "Чтобы отменить действие, отправьте /cancel."),
        "pay_info": ("💳 <b>Стоимость: {price} сум</b> ({period})\n\n"
                     "Карта для оплаты:\n<code>{card}</code>\n{owner}\n\n"
                     "1️⃣ Переведите <b>{price} сум</b> на карту\n"
                     "2️⃣ Нажмите «📤 Отправить чек» и пришлите чек (скриншот)\n"
                     "3️⃣ После подтверждения админом откроется создание приглашений (обычно за несколько минут)\n\n"
                     "По вопросам пишите админу: {admin}"),
        "period_life": "разовая оплата, бессрочно", "period_days": "на {d} дн.",
        "pay_need": "🔒 Создание приглашений — платная услуга.\n\n",
        "pay_send": "📤 Отправить чек", "pay_admin": "💬 Написать админу", "pay_demo": "👀 Посмотреть пример",
        "pay_receipt_prompt": "📤 Пришлите чек об оплате (фото или скриншот).\nОтмена: /cancel",
        "pay_need_photo": "Пожалуйста, отправьте чек в виде фото или файла.",
        "pay_sent": "✅ Чек отправлен админу. Сообщим, когда он подтвердит.",
        "pay_pending": "⏳ Ваш платёж проверяется. Вопросы: {admin}",
        "pay_ok": "🎉 <b>Платёж подтверждён!</b>\nТеперь нажмите «🎬 Создать приглашение».",
        "pay_no": "❌ Платёж не подтверждён. Чек должен быть чётким. Вопросы: {admin}",
        "sub_active": "✅ Подписка активна: <b>{until}</b>", "sub_life": "бессрочно", "sub_none": "🔓 Подписки нет.",
        "demo_caption": "👀 Пример. Каждый раз дизайн и музыка получаются разными, можно выбрать и самому.",
        "inv_names": "👰🤵 <b>Имена жениха и невесты?</b>\nНапример: <i>Азиз и Мадина</i>",
        "inv_date": "📅 <b>Дата свадьбы?</b>\nНапример: <i>15 декабря 2026</i>",
        "inv_time": "⏰ <b>Время?</b>\nНапример: <i>18:00</i>  (если не нужно, отправьте «-»)",
        "inv_venue": "📍 <b>Название и адрес зала?</b>\nНапример: <i>Банкетный зал «Регистан», Ташкент</i>",
        "inv_lang": "🌐 На каком языке сделать приглашение?",
        "inv_text": "✍️ Какой будет <b>текст приглашения</b>?",
        "inv_text_ai": "🤖 Пусть напишет AI", "inv_text_own": "✍️ Напишу сам",
        "inv_text_prompt": "✍️ Отправьте текст приглашения.\nНапример: <i>Приглашаем вас на свадьбу наших детей</i>",
        "inv_style": "🎨 Какой будет <b>дизайн</b>?",
        "inv_style_rand": "🎲 AI выберет сам", "inv_style_pal": "🖌 Выберу цвет", "inv_style_desc": "💬 Опишу сам",
        "inv_style_text": ("💬 Какой дизайн вы хотите? Опишите свободно.\n"
                           "Например: <i>бордовый с золотом, узоры сюзане</i> или <i>нежно-розовый, цветы</i>"),
        "inv_pal": "🖌 Выберите цвет:",
        "inv_music": "🎵 Какая будет <b>музыка</b>?",
        "inv_music_auto": "🎲 Автоматически", "inv_music_own": "🎧 Пришлю свою",
        "inv_music_prompt": "🎧 Отправьте музыку (аудио или mp3-файл).",
        "inv_music_bad": "Отправьте аудиофайл (mp3 или голосовое сообщение).",
        "inv_working": "⏳ Готовлю приглашение... Обычно 1-2 минуты.",
        "inv_queue": "⏳ Впереди в очереди: {n}. Немного подождите...",
        "inv_done": "✅ <b>Готово!</b> {names}",
        "inv_novideo": "⚠️ Видео создать не удалось, поэтому отправляю готовую картинку.",
        "inv_again_design": "🔄 Другой дизайн", "inv_again_music": "🎵 Другая музыка", "inv_new": "🆕 Новое приглашение",
        "inv_expired": "⚠️ Данные заказа не найдены. Начните заново через «🎬 Создать приглашение».",
        "inv_busy": "⏳ Предыдущее приглашение ещё готовится. Подождите.",
        "inv_too_long": "Слишком длинно. Напишите короче.",
        "inv_ai_text_used": "🤖 Текст от AI:\n<i>{text}</i>",
        "tr_pick": "🌐 <b>Перевод</b>\nНа какой язык переводим?",
        "tr_ready": ("🌐 Язык перевода: <b>{lang}</b>\n\nОтправьте текст или фото — переведу "
                     "(грамматические ошибки исправляются автоматически). Сменить язык: «🔁 Сменить язык»."),
        "tr_change": "🔁 Сменить язык",
        "tr_result": "🌐 <b>Перевод ({lang}):</b>\n\n{text}",
        "tr_original": "📝 <b>Текст с фото:</b>\n{text}",
        "gr_ready": ("✅ <b>Поиск ошибок</b>\n\nОтправьте текст или фото для проверки. "
                     "Я найду ошибки и пришлю исправленный текст."),
        "gr_fixed": "✅ <b>Исправленный текст:</b>\n\n{text}",
        "gr_errors": "🔎 <b>Найденные ошибки:</b>\n{items}",
        "gr_none": "🎉 Ошибок не найдено — текст написан правильно!",
        "ai_working": "⏳ Работаю...",
        "ai_fail": "⚠️ AI сейчас занят или не работает. Попробуйте чуть позже.",
        "ai_no_text": "Отправьте текст или фото.",
        "ai_no_text_found": "😕 На фото не найден текст.",
        "ai_too_long": "Текст слишком длинный (до 3500 символов).",
        "free_over": ("⚠️ Бесплатный лимит на сегодня ({n}) исчерпан.\nДля безлимита оформите подписку: «💳 Подписка». "
                      "Лимит обновится завтра."),
        "err": "⚠️ Произошла ошибка. Попробуйте ещё раз или нажмите /start.",
    },
    # ------------------------------------------------------------------------------ INGLIZCHA
    "en": {
        "welcome": ("👋 Hi, <b>{name}</b>!\n\n"
                    "This bot:\n"
                    "🎬 creates a <b>video wedding invitation</b> with AI — you enter names, date and venue, it picks the design and music\n"
                    "🌐 <b>translates</b> text and photos\n"
                    "✅ finds and fixes <b>grammar mistakes</b>\n\n"
                    "Choose a button below 👇"),
        "m_invite": "🎬 Create invitation", "m_tr": "🌐 Translate", "m_gr": "✅ Find mistakes",
        "m_pay": "💳 Subscription", "m_lang": "🌍 Language", "m_help": "☎️ Contact",
        "lang_changed": "✅ Language changed.",
        "cancelled": "✅ Cancelled.",
        "help": ("☎️ <b>Contact</b>\n\nFor questions, payments and partnership write to the admin: {admin}\n\n"
                 "Send /cancel at any time to cancel."),
        "pay_info": ("💳 <b>Price: {price} UZS</b> ({period})\n\n"
                     "Payment card:\n<code>{card}</code>\n{owner}\n\n"
                     "1️⃣ Transfer <b>{price} UZS</b> to the card\n"
                     "2️⃣ Tap «📤 Send receipt» and send the payment receipt (screenshot)\n"
                     "3️⃣ After the admin confirms, invitation creation unlocks (usually within minutes)\n\n"
                     "Questions: {admin}"),
        "period_life": "one-time payment, lifetime", "period_days": "for {d} days",
        "pay_need": "🔒 Creating invitations is a paid service.\n\n",
        "pay_send": "📤 Send receipt", "pay_admin": "💬 Message admin", "pay_demo": "👀 See a sample",
        "pay_receipt_prompt": "📤 Send the payment receipt (photo or screenshot).\nCancel: /cancel",
        "pay_need_photo": "Please send the receipt as a photo or a file.",
        "pay_sent": "✅ Receipt sent to the admin. We'll notify you once it's confirmed.",
        "pay_pending": "⏳ Your payment is being checked. Questions: {admin}",
        "pay_ok": "🎉 <b>Payment confirmed!</b>\nNow tap «🎬 Create invitation».",
        "pay_no": "❌ Payment was not confirmed. The receipt must be clear. Questions: {admin}",
        "sub_active": "✅ Subscription active: <b>{until}</b>", "sub_life": "lifetime", "sub_none": "🔓 No subscription.",
        "demo_caption": "👀 Sample. Design and music differ every time, or you can choose them yourself.",
        "inv_names": "👰🤵 <b>Names of the bride and groom?</b>\nFor example: <i>Aziz and Madina</i>",
        "inv_date": "📅 <b>Wedding date?</b>\nFor example: <i>15 December 2026</i>",
        "inv_time": "⏰ <b>Time?</b>\nFor example: <i>18:00</i>  (send «-» to skip)",
        "inv_venue": "📍 <b>Venue name and address?</b>\nFor example: <i>Registan Hall, Tashkent</i>",
        "inv_lang": "🌐 In which language should the invitation be?",
        "inv_text": "✍️ What should the <b>invitation text</b> be?",
        "inv_text_ai": "🤖 Let AI write it", "inv_text_own": "✍️ I'll write it",
        "inv_text_prompt": "✍️ Send the invitation text.\nFor example: <i>We joyfully invite you to our wedding</i>",
        "inv_style": "🎨 What should the <b>design</b> be?",
        "inv_style_rand": "🎲 AI picks for me", "inv_style_pal": "🖌 I'll pick a color", "inv_style_desc": "💬 I'll describe it",
        "inv_style_text": ("💬 What design do you want? Describe it freely.\n"
                           "For example: <i>burgundy and gold, suzani patterns</i> or <i>soft pink, flowers</i>"),
        "inv_pal": "🖌 Choose a color:",
        "inv_music": "🎵 What about the <b>music</b>?",
        "inv_music_auto": "🎲 Automatic", "inv_music_own": "🎧 I'll send my own",
        "inv_music_prompt": "🎧 Send the music (audio or mp3 file).",
        "inv_music_bad": "Please send an audio file (mp3 or a voice message).",
        "inv_working": "⏳ Preparing your invitation... Usually 1-2 minutes.",
        "inv_queue": "⏳ {n} job(s) ahead of you. Please wait...",
        "inv_done": "✅ <b>Done!</b> {names}",
        "inv_novideo": "⚠️ Could not make the video, so here is the finished image.",
        "inv_again_design": "🔄 Another design", "inv_again_music": "🎵 Another music", "inv_new": "🆕 New invitation",
        "inv_expired": "⚠️ Order data not found. Start again with «🎬 Create invitation».",
        "inv_busy": "⏳ Your previous invitation is still being prepared. Please wait.",
        "inv_too_long": "Too long. Please write something shorter.",
        "inv_ai_text_used": "🤖 Text written by AI:\n<i>{text}</i>",
        "tr_pick": "🌐 <b>Translate</b>\nWhich language should I translate into?",
        "tr_ready": ("🌐 Target language: <b>{lang}</b>\n\nSend text or a photo — I'll translate it "
                     "(grammar mistakes are fixed automatically). Change language: «🔁 Change language»."),
        "tr_change": "🔁 Change language",
        "tr_result": "🌐 <b>Translation ({lang}):</b>\n\n{text}",
        "tr_original": "📝 <b>Text from the photo:</b>\n{text}",
        "gr_ready": ("✅ <b>Find mistakes</b>\n\nSend a text or photo to check. "
                     "I'll find the mistakes and send back the corrected text."),
        "gr_fixed": "✅ <b>Corrected text:</b>\n\n{text}",
        "gr_errors": "🔎 <b>Mistakes found:</b>\n{items}",
        "gr_none": "🎉 No mistakes found — the text is correct!",
        "ai_working": "⏳ Working...",
        "ai_fail": "⚠️ AI is busy or unavailable right now. Please try again a bit later.",
        "ai_no_text": "Send text or a photo.",
        "ai_no_text_found": "😕 No text found in the photo.",
        "ai_too_long": "The text is too long (up to 3500 characters).",
        "free_over": ("⚠️ Today's free limit ({n}) is used up.\nSubscribe for unlimited use: «💳 Subscription». "
                      "The limit resets tomorrow."),
        "err": "⚠️ Something went wrong. Try again or press /start.",
    },
}
 
# ---- Tariflar: 1 ta taklifnoma / cheksiz (yuqoridagi eski matnlarni yangilaydi)
S["uz"].update({
    "m_pay": "💳 To'lov",
    "pay_info": ("💳 <b>Narxlar</b>\n\n"
                 "🎬 1 ta taklifnoma — <b>{price1} so'm</b>\n   (ichida {regen} marta «boshqa dizayn / musiqa»)\n"
                 "♾ Cheksiz ({period}) — <b>{price2} so'm</b>\n\n"
                 "To'lov kartasi:\n<code>{card}</code>\n{owner}\n\n"
                 "1️⃣ Kartaga tarif narxini o'tkazing\n"
                 "2️⃣ Pastdagi tarif tugmasini bosib, to'lov chekini (skrinshot) yuboring\n"
                 "3️⃣ Admin tasdiqlagach, taklifnoma yasash ochiladi (odatda bir necha daqiqada)\n\n"
                 "Savollar uchun admin: {admin}"),
    "pay_btn_single": "📤 1 ta taklifnoma · {price} so'm",
    "pay_btn_unlimited": "📤 Cheksiz · {price} so'm",
    "plan_single": "1 ta taklifnoma", "plan_unlimited": "Cheksiz",
    "pay_receipt_prompt": "📤 Tarif: <b>{plan}</b> — {price} so'm.\nTo'lov chekini (rasm yoki skrinshot) yuboring.\nBekor qilish: /cancel",
    "pay_ok": "🎉 <b>To'lovingiz tasdiqlandi!</b>\n♾ Endi cheksiz taklifnoma yasashingiz mumkin. «🎬 Taklifnoma yasash» ni bosing.",
    "pay_ok_single": "🎉 <b>To'lovingiz tasdiqlandi!</b>\n🎟 Hisobingizda <b>{n}</b> ta taklifnoma bor. «🎬 Taklifnoma yasash» ni bosing.",
    "sub_credits": "🎟 Qolgan taklifnomalar: <b>{n}</b>",
    "inv_regen_limit": "⚠️ Bu taklifnoma uchun «boshqa dizayn / musiqa» limiti ({n} marta) tugadi. Yangi taklifnoma uchun «💳 To'lov» bo'limiga o'ting.",
    "free_over": ("⚠️ Bugungi bepul limit ({n} ta) tugadi.\nCheksiz foydalanish uchun «💳 To'lov» bo'limidan cheksiz tarifni oling. "
                  "Limit ertaga yangilanadi."),
})
S["ru"].update({
    "m_pay": "💳 Оплата",
    "pay_info": ("💳 <b>Цены</b>\n\n"
                 "🎬 1 приглашение — <b>{price1} сум</b>\n   (в цену входит {regen} раз «другой дизайн / музыка»)\n"
                 "♾ Безлимит ({period}) — <b>{price2} сум</b>\n\n"
                 "Карта для оплаты:\n<code>{card}</code>\n{owner}\n\n"
                 "1️⃣ Переведите стоимость тарифа на карту\n"
                 "2️⃣ Нажмите кнопку тарифа ниже и пришлите чек (скриншот)\n"
                 "3️⃣ После подтверждения админом откроется создание приглашений (обычно за несколько минут)\n\n"
                 "По вопросам пишите админу: {admin}"),
    "pay_btn_single": "📤 1 приглашение · {price} сум",
    "pay_btn_unlimited": "📤 Безлимит · {price} сум",
    "plan_single": "1 приглашение", "plan_unlimited": "Безлимит",
    "pay_receipt_prompt": "📤 Тариф: <b>{plan}</b> — {price} сум.\nПришлите чек об оплате (фото или скриншот).\nОтмена: /cancel",
    "pay_ok": "🎉 <b>Платёж подтверждён!</b>\n♾ Теперь можно создавать приглашения без ограничений. Нажмите «🎬 Создать приглашение».",
    "pay_ok_single": "🎉 <b>Платёж подтверждён!</b>\n🎟 На вашем счету приглашений: <b>{n}</b>. Нажмите «🎬 Создать приглашение».",
    "sub_credits": "🎟 Осталось приглашений: <b>{n}</b>",
    "inv_regen_limit": "⚠️ Лимит «другой дизайн / музыка» для этого приглашения ({n}) исчерпан. Для нового приглашения перейдите в «💳 Оплата».",
    "free_over": ("⚠️ Бесплатный лимит на сегодня ({n}) исчерпан.\nДля безлимита возьмите безлимитный тариф в «💳 Оплата». "
                  "Лимит обновится завтра."),
})
S["en"].update({
    "m_pay": "💳 Payment",
    "pay_info": ("💳 <b>Prices</b>\n\n"
                 "🎬 1 invitation — <b>{price1} UZS</b>\n   (includes {regen} × «another design / music»)\n"
                 "♾ Unlimited ({period}) — <b>{price2} UZS</b>\n\n"
                 "Payment card:\n<code>{card}</code>\n{owner}\n\n"
                 "1️⃣ Transfer the plan price to the card\n"
                 "2️⃣ Tap the plan button below and send the receipt (screenshot)\n"
                 "3️⃣ After the admin confirms, invitation creation unlocks (usually within minutes)\n\n"
                 "Questions: {admin}"),
    "pay_btn_single": "📤 1 invitation · {price} UZS",
    "pay_btn_unlimited": "📤 Unlimited · {price} UZS",
    "plan_single": "1 invitation", "plan_unlimited": "Unlimited",
    "pay_receipt_prompt": "📤 Plan: <b>{plan}</b> — {price} UZS.\nSend the payment receipt (photo or screenshot).\nCancel: /cancel",
    "pay_ok": "🎉 <b>Payment confirmed!</b>\n♾ You can now create unlimited invitations. Tap «🎬 Create invitation».",
    "pay_ok_single": "🎉 <b>Payment confirmed!</b>\n🎟 Invitations on your account: <b>{n}</b>. Tap «🎬 Create invitation».",
    "sub_credits": "🎟 Invitations left: <b>{n}</b>",
    "inv_regen_limit": "⚠️ The «another design / music» limit for this invitation ({n}) is used up. For a new invitation go to «💳 Payment».",
    "free_over": ("⚠️ Today's free limit ({n}) is used up.\nGet the unlimited plan in «💳 Payment» for unlimited use. "
                  "The limit resets tomorrow."),
})
 
# o'zbek kirill: lotin matnidan avtomatik hosil qilinadi
S["uz_cyrl"] = {k: to_cyrillic(v) for k, v in S["uz"].items()}
PALETTE_LABELS["uz_cyrl"] = {k: to_cyrillic(v) for k, v in PALETTE_LABELS["uz"].items()}
 
 
def tr(_lang, _key, /, **kw):
    """_lang/_key faqat pozitsion: matn ichidagi {lang} joy belgisi bilan to'qnashmaydi."""
    base = S.get(_lang) or S["uz"]
    text = base.get(_key) or S["uz"].get(_key, _key)
    return text.format(**kw) if kw else text
 
