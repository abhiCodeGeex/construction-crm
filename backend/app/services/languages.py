"""Phase L block 7 — the languages the app and the site workers' WhatsApp messages come in (v4 §15).

The web app translates its menus, the portal and the site screens (frontend i18n); here are the languages a user can
choose and the phrases the server itself sends to site workers (the morning message and its buttons). A phrase with no
translation falls back to English.
"""
LANGUAGES = {"en": "English", "hi": "हिन्दी", "mr": "मराठी", "gu": "ગુજરાતી", "ta": "தமிழ்", "te": "తెలుగు", "kn": "ಕನ್ನಡ", "bn": "বাংলা"}

WORKER = {
    "hi": {"morning": "सुप्रभात {name}। आज का काम:", "card": "जॉब कार्ड / ड्रॉइंग", "sup": "सुपरवाइज़र",
           "tap": "सामग्री चाहिए, काम पूरा या मदद — नीचे बटन दबाएँ या आवाज़ संदेश भेजें।",
           "material": "सामग्री चाहिए", "done": "काम पूरा", "help": "मदद चाहिए"},
    "mr": {"morning": "सुप्रभात {name}. आजचे काम:", "card": "जॉब कार्ड / ड्रॉइंग", "sup": "सुपरवायझर",
           "tap": "साहित्य हवे, काम पूर्ण किंवा मदत — खालील बटण दाबा किंवा आवाज संदेश पाठवा.",
           "material": "साहित्य हवे", "done": "काम पूर्ण", "help": "मदत हवी"},
    "gu": {"morning": "સુપ્રભાત {name}. આજનું કામ:", "card": "જોબ કાર્ડ / ડ્રોઇંગ", "sup": "સુપરવાઇઝર",
           "tap": "સામગ્રી જોઈએ, કામ પૂરું કે મદદ — નીચેનું બટન દબાવો અથવા વૉઇસ સંદેશ મોકલો.",
           "material": "સામગ્રી જોઈએ", "done": "કામ પૂરું", "help": "મદદ જોઈએ"},
    "ta": {"morning": "காலை வணக்கம் {name}. இன்றைய வேலை:", "card": "வேலை அட்டை / வரைபடம்", "sup": "மேற்பார்வையாளர்",
           "tap": "பொருள் தேவை, வேலை முடிந்தது அல்லது உதவி — கீழே உள்ள பொத்தானை அழுத்தவும் அல்லது குரல் செய்தி அனுப்பவும்.",
           "material": "பொருள் தேவை", "done": "வேலை முடிந்தது", "help": "உதவி தேவை"},
    "te": {"morning": "శుభోదయం {name}. ఈరోజు పని:", "card": "జాబ్ కార్డ్ / డ్రాయింగ్", "sup": "సూపర్‌వైజర్",
           "tap": "సామగ్రి కావాలి, పని పూర్తయింది లేదా సహాయం — క్రింది బటన్ నొక్కండి లేదా వాయిస్ సందేశం పంపండి.",
           "material": "సామగ్రి కావాలి", "done": "పని పూర్తయింది", "help": "సహాయం కావాలి"},
    "kn": {"morning": "ಶುಭೋದಯ {name}. ಇಂದಿನ ಕೆಲಸ:", "card": "ಜಾಬ್ ಕಾರ್ಡ್ / ಡ್ರಾಯಿಂಗ್", "sup": "ಮೇಲ್ವಿಚಾರಕ",
           "tap": "ಸಾಮಗ್ರಿ ಬೇಕು, ಕೆಲಸ ಮುಗಿದಿದೆ ಅಥವಾ ಸಹಾಯ — ಕೆಳಗಿನ ಬಟನ್ ಒತ್ತಿ ಅಥವಾ ಧ್ವನಿ ಸಂದೇಶ ಕಳುಹಿಸಿ.",
           "material": "ಸಾಮಗ್ರಿ ಬೇಕು", "done": "ಕೆಲಸ ಮುಗಿದಿದೆ", "help": "ಸಹಾಯ ಬೇಕು"},
    "bn": {"morning": "সুপ্রভাত {name}। আজকের কাজ:", "card": "জব কার্ড / ড্রয়িং", "sup": "সুপারভাইজার",
           "tap": "মাল লাগবে, কাজ শেষ বা সাহায্য — নিচের বোতাম টিপুন বা ভয়েস বার্তা পাঠান।",
           "material": "মাল লাগবে", "done": "কাজ শেষ", "help": "সাহায্য দরকার"},
}
EN = {"morning": "Good morning {name}. Today's work:", "card": "Job card / drawing", "sup": "Supervisor",
      "tap": "Tap a button below (or send a voice note) when you need material, finish, or need help.",
      "material": "Material needed", "done": "Work done", "help": "Need help"}


def worker_text(lang, key, **kw):
    return (WORKER.get(lang) or {}).get(key, EN[key]).format(**kw)
