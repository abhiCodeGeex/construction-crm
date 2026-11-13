import { Injectable, Pipe, PipeTransform, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

/** Phase I block 7 — Hindi for the menus, the client portal and the site screens (§15 "multi-language").
 *  The English text is the key; a phrase without a Hindi entry stays in English. The choice is kept on the user
 *  (PUT /api/me/language) and in this browser. */
const HI: Record<string, string> = {
  // menu sections and items
  'Sales': 'बिक्री', 'Delivery': 'डिलीवरी', 'Money': 'पैसा', 'Team': 'टीम', 'Admin': 'प्रशासन',
  'Home': 'होम', 'My access': 'मेरी पहुँच', 'Leads & pipeline': 'लीड और पाइपलाइन', 'Contacts': 'संपर्क', 'Proposals & contracts': 'प्रस्ताव और अनुबंध',
  'Projects': 'प्रोजेक्ट', 'Documents & drawings': 'दस्तावेज़ और ड्रॉइंग', 'Selections': 'चयन', 'Site reports': 'साइट रिपोर्ट',
  'Change orders': 'बदलाव आदेश', 'Procurement': 'खरीद', 'Finance': 'वित्त', 'Reports': 'रिपोर्ट', 'Follow-ups': 'फ़ॉलो-अप', 'Inbox': 'इनबॉक्स',
  'Users & roles': 'उपयोगकर्ता और भूमिकाएँ', 'Company settings': 'कंपनी सेटिंग्स',
  'Change password': 'पासवर्ड बदलें', 'Sign out': 'साइन आउट', 'Calendar feed': 'कैलेंडर लिंक', 'Language': 'भाषा', 'view': 'देखें', 'soon': 'जल्द',
  // site
  'Daily reports': 'दैनिक रिपोर्ट', 'Attendance': 'हाज़िरी', 'Snags': 'कमियाँ', 'Stock': 'स्टॉक', 'Ask for a change': 'बदलाव माँगें',
  "Write today's report": 'आज की रिपोर्ट लिखें', 'One report a day. It can be changed until the end of the next day.': 'दिन में एक रिपोर्ट। अगले दिन के अंत तक बदली जा सकती है।',
  'Weather': 'मौसम', 'Manpower': 'मज़दूर', 'Work done': 'किया गया काम', 'Photos': 'फ़ोटो', 'Save report': 'रिपोर्ट सहेजें', 'Issue': 'समस्या', 'Delay': 'देरी',
  'No reports yet.': 'अभी कोई रिपोर्ट नहीं।', 'Day': 'दिन', 'Month summary': 'महीने का सारांश', 'Save attendance': 'हाज़िरी सहेजें', 'Add a site worker': 'साइट मज़दूर जोड़ें',
  'present': 'उपस्थित', 'half_day': 'आधा दिन', 'absent': 'अनुपस्थित', 'leave': 'छुट्टी',
  'New snag': 'नई कमी', 'Mark fixed': 'ठीक हुआ', 'Close': 'बंद करें', 'Reopen': 'फिर खोलें', 'Not closed': 'खुली', 'All': 'सभी', 'No snags here.': 'कोई कमी नहीं।',
  'Record use': 'उपयोग दर्ज करें', 'Move stock': 'स्टॉक भेजें', 'Material': 'सामग्री', 'Received': 'मिला', 'Used': 'उपयोग', 'On site': 'साइट पर',
  'Send to the PM': 'पीएम को भेजें', 'What needs to change': 'क्या बदलना है',
  // Phase J
  'Workers on WhatsApp': 'व्हाट्सऐप पर मज़दूर', 'Morning digest': 'सुबह का सारांश', 'Design options': 'डिज़ाइन विकल्प',
  '360° views and renders': '360° व्यू और रेंडर', 'You approved': 'आपने चुना', 'You asked for changes': 'आपने बदलाव माँगे',
  'Please decide by': 'कृपया तय करें', 'No extra cost': 'कोई अतिरिक्त लागत नहीं', 'Choose': 'चुनें', 'Ask for changes': 'बदलाव माँगें',
  'Approve option': 'विकल्प स्वीकार करें', 'This adds': 'इससे जुड़ता है', '— the team will send a change order.': '— टीम बदलाव आदेश भेजेगी।',
  'Comment (optional)': 'टिप्पणी (वैकल्पिक)', 'Your comment': 'आपकी टिप्पणी',
  // portal
  'None of these': 'इनमें से कोई नहीं',
  'Your projects': 'आपके प्रोजेक्ट', 'For you to act on': 'आपके लिए काम', 'Documents': 'दस्तावेज़', 'Site photos': 'साइट की फ़ोटो', 'Mood boards': 'मूड बोर्ड',
  'Your change requests': 'आपके बदलाव अनुरोध', 'Send to the team': 'टीम को भेजें', 'Messages': 'संदेश', 'Project team': 'प्रोजेक्ट टीम', 'Invoices': 'बिल',
  'Proposals for you': 'आपके लिए प्रस्ताव', 'Open and answer': 'खोलें और जवाब दें', 'View': 'देखें', 'Pay now': 'अभी भुगतान करें', 'Back': 'वापस',
  'You never see the firm\'s internal costs.': 'आप फर्म की आंतरिक लागत कभी नहीं देखते।', 'Progress': 'प्रगति', 'Approve': 'स्वीकार करें', 'Reject': 'अस्वीकार करें',
};

/** Phase L block 7 — six more Indian languages for the menus, the portal and the site screens. A phrase without an
 *  entry stays in English; the most-used ones are translated. */
const MR: Record<string, string> = {
  'Sales': 'विक्री', 'Delivery': 'डिलिव्हरी', 'Money': 'पैसे', 'Team': 'टीम', 'Admin': 'प्रशासन', 'Home': 'होम', 'Contacts': 'संपर्क',
  'Projects': 'प्रकल्प', 'Site reports': 'साइट अहवाल', 'Reports': 'अहवाल', 'Follow-ups': 'पाठपुरावा', 'Inbox': 'इनबॉक्स', 'Finance': 'वित्त',
  'Change password': 'पासवर्ड बदला', 'Sign out': 'बाहेर पडा', 'Language': 'भाषा', 'Daily reports': 'दैनिक अहवाल', 'Attendance': 'हजेरी',
  'Snags': 'त्रुटी', 'Stock': 'साठा', 'Weather': 'हवामान', 'Manpower': 'कामगार', 'Work done': 'झालेले काम', 'Photos': 'फोटो',
  'Save report': 'अहवाल जतन करा', 'Issue': 'समस्या', 'Delay': 'विलंब', 'present': 'हजर', 'half_day': 'अर्धा दिवस', 'absent': 'गैरहजर', 'leave': 'रजा',
  'New snag': 'नवीन त्रुटी', 'Mark fixed': 'दुरुस्त झाले', 'Close': 'बंद करा', 'Reopen': 'पुन्हा उघडा', 'All': 'सर्व', 'Material': 'साहित्य',
  'Your projects': 'तुमचे प्रकल्प', 'Documents': 'कागदपत्रे', 'Site photos': 'साइटचे फोटो', 'Messages': 'संदेश', 'Project team': 'प्रकल्प टीम',
  'Invoices': 'बिले', 'View': 'पहा', 'Pay now': 'आता भरा', 'Back': 'मागे', 'Progress': 'प्रगती', 'Approve': 'मंजूर करा', 'Reject': 'नाकारा',
  'Safety': 'सुरक्षा', 'Field app': 'फील्ड ॲप', 'Sync now': 'आता पाठवा', 'Offline': 'ऑफलाइन', 'Online': 'ऑनलाइन', 'Waiting to send': 'पाठवायचे बाकी',
};
const GU: Record<string, string> = {
  'Sales': 'વેચાણ', 'Delivery': 'ડિલિવરી', 'Money': 'પૈસા', 'Team': 'ટીમ', 'Admin': 'વહીવટ', 'Home': 'હોમ', 'Contacts': 'સંપર્કો',
  'Projects': 'પ્રોજેક્ટ', 'Site reports': 'સાઇટ રિપોર્ટ', 'Reports': 'રિપોર્ટ', 'Follow-ups': 'ફોલો-અપ', 'Inbox': 'ઇનબોક્સ', 'Finance': 'નાણાં',
  'Change password': 'પાસવર્ડ બદલો', 'Sign out': 'સાઇન આઉટ', 'Language': 'ભાષા', 'Daily reports': 'દૈનિક રિપોર્ટ', 'Attendance': 'હાજરી',
  'Snags': 'ખામીઓ', 'Stock': 'સ્ટોક', 'Weather': 'હવામાન', 'Manpower': 'કારીગરો', 'Work done': 'થયેલું કામ', 'Photos': 'ફોટા',
  'Save report': 'રિપોર્ટ સાચવો', 'Issue': 'સમસ્યા', 'Delay': 'વિલંબ', 'present': 'હાજર', 'half_day': 'અડધો દિવસ', 'absent': 'ગેરહાજર', 'leave': 'રજા',
  'New snag': 'નવી ખામી', 'Mark fixed': 'સુધારાયું', 'Close': 'બંધ કરો', 'Reopen': 'ફરી ખોલો', 'All': 'બધા', 'Material': 'સામગ્રી',
  'Your projects': 'તમારા પ્રોજેક્ટ', 'Documents': 'દસ્તાવેજો', 'Site photos': 'સાઇટના ફોટા', 'Messages': 'સંદેશા', 'Project team': 'પ્રોજેક્ટ ટીમ',
  'Invoices': 'બિલ', 'View': 'જુઓ', 'Pay now': 'હમણાં ચૂકવો', 'Back': 'પાછા', 'Progress': 'પ્રગતિ', 'Approve': 'મંજૂર કરો', 'Reject': 'નામંજૂર કરો',
  'Safety': 'સલામતી', 'Field app': 'ફીલ્ડ એપ', 'Sync now': 'હમણાં મોકલો', 'Offline': 'ઑફલાઇન', 'Online': 'ઑનલાઇન', 'Waiting to send': 'મોકલવાનું બાકી',
};
const TA: Record<string, string> = {
  'Sales': 'விற்பனை', 'Delivery': 'செயல்படுத்தல்', 'Money': 'பணம்', 'Team': 'குழு', 'Admin': 'நிர்வாகம்', 'Home': 'முகப்பு', 'Contacts': 'தொடர்புகள்',
  'Projects': 'திட்டங்கள்', 'Site reports': 'தள அறிக்கைகள்', 'Reports': 'அறிக்கைகள்', 'Follow-ups': 'பின்தொடர்தல்', 'Inbox': 'உள்பெட்டி', 'Finance': 'நிதி',
  'Change password': 'கடவுச்சொல்லை மாற்று', 'Sign out': 'வெளியேறு', 'Language': 'மொழி', 'Daily reports': 'தினசரி அறிக்கை', 'Attendance': 'வருகை',
  'Snags': 'குறைகள்', 'Stock': 'இருப்பு', 'Weather': 'வானிலை', 'Manpower': 'தொழிலாளர்கள்', 'Work done': 'முடிந்த வேலை', 'Photos': 'புகைப்படங்கள்',
  'Save report': 'அறிக்கையைச் சேமி', 'Issue': 'பிரச்சனை', 'Delay': 'தாமதம்', 'present': 'வந்தார்', 'half_day': 'அரை நாள்', 'absent': 'வரவில்லை', 'leave': 'விடுப்பு',
  'New snag': 'புதிய குறை', 'Mark fixed': 'சரி செய்யப்பட்டது', 'Close': 'மூடு', 'Reopen': 'மீண்டும் திற', 'All': 'அனைத்தும்', 'Material': 'பொருள்',
  'Your projects': 'உங்கள் திட்டங்கள்', 'Documents': 'ஆவணங்கள்', 'Site photos': 'தள புகைப்படங்கள்', 'Messages': 'செய்திகள்', 'Project team': 'திட்டக் குழு',
  'Invoices': 'பில்கள்', 'View': 'பார்', 'Pay now': 'இப்போது செலுத்து', 'Back': 'பின்', 'Progress': 'முன்னேற்றம்', 'Approve': 'ஒப்புதல்', 'Reject': 'நிராகரி',
  'Safety': 'பாதுகாப்பு', 'Field app': 'தள செயலி', 'Sync now': 'இப்போது அனுப்பு', 'Offline': 'இணைப்பு இல்லை', 'Online': 'இணைப்பில்', 'Waiting to send': 'அனுப்ப காத்திருக்கிறது',
};
const TE: Record<string, string> = {
  'Sales': 'అమ్మకాలు', 'Delivery': 'అమలు', 'Money': 'డబ్బు', 'Team': 'బృందం', 'Admin': 'నిర్వహణ', 'Home': 'హోమ్', 'Contacts': 'పరిచయాలు',
  'Projects': 'ప్రాజెక్టులు', 'Site reports': 'సైట్ నివేదికలు', 'Reports': 'నివేదికలు', 'Follow-ups': 'ఫాలో-అప్‌లు', 'Inbox': 'ఇన్‌బాక్స్', 'Finance': 'ఆర్థికం',
  'Change password': 'పాస్‌వర్డ్ మార్చండి', 'Sign out': 'సైన్ అవుట్', 'Language': 'భాష', 'Daily reports': 'రోజువారీ నివేదిక', 'Attendance': 'హాజరు',
  'Snags': 'లోపాలు', 'Stock': 'స్టాక్', 'Weather': 'వాతావరణం', 'Manpower': 'కార్మికులు', 'Work done': 'చేసిన పని', 'Photos': 'ఫోటోలు',
  'Save report': 'నివేదిక సేవ్ చేయండి', 'Issue': 'సమస్య', 'Delay': 'ఆలస్యం', 'present': 'హాజరు', 'half_day': 'సగం రోజు', 'absent': 'గైర్హాజరు', 'leave': 'సెలవు',
  'New snag': 'కొత్త లోపం', 'Mark fixed': 'సరిచేయబడింది', 'Close': 'మూసివేయండి', 'Reopen': 'మళ్ళీ తెరవండి', 'All': 'అన్నీ', 'Material': 'సామగ్రి',
  'Your projects': 'మీ ప్రాజెక్టులు', 'Documents': 'పత్రాలు', 'Site photos': 'సైట్ ఫోటోలు', 'Messages': 'సందేశాలు', 'Project team': 'ప్రాజెక్ట్ బృందం',
  'Invoices': 'బిల్లులు', 'View': 'చూడండి', 'Pay now': 'ఇప్పుడు చెల్లించండి', 'Back': 'వెనుకకు', 'Progress': 'పురోగతి', 'Approve': 'ఆమోదించండి', 'Reject': 'తిరస్కరించండి',
  'Safety': 'భద్రత', 'Field app': 'ఫీల్డ్ యాప్', 'Sync now': 'ఇప్పుడు పంపండి', 'Offline': 'ఆఫ్‌లైన్', 'Online': 'ఆన్‌లైన్', 'Waiting to send': 'పంపడానికి వేచి ఉంది',
};
const KN: Record<string, string> = {
  'Sales': 'ಮಾರಾಟ', 'Delivery': 'ಅನುಷ್ಠಾನ', 'Money': 'ಹಣ', 'Team': 'ತಂಡ', 'Admin': 'ಆಡಳಿತ', 'Home': 'ಮುಖಪುಟ', 'Contacts': 'ಸಂಪರ್ಕಗಳು',
  'Projects': 'ಯೋಜನೆಗಳು', 'Site reports': 'ಸೈಟ್ ವರದಿಗಳು', 'Reports': 'ವರದಿಗಳು', 'Follow-ups': 'ಫಾಲೋ-ಅಪ್', 'Inbox': 'ಇನ್‌ಬಾಕ್ಸ್', 'Finance': 'ಹಣಕಾಸು',
  'Change password': 'ಪಾಸ್‌ವರ್ಡ್ ಬದಲಿಸಿ', 'Sign out': 'ಸೈನ್ ಔಟ್', 'Language': 'ಭಾಷೆ', 'Daily reports': 'ದೈನಂದಿನ ವರದಿ', 'Attendance': 'ಹಾಜರಾತಿ',
  'Snags': 'ದೋಷಗಳು', 'Stock': 'ದಾಸ್ತಾನು', 'Weather': 'ಹವಾಮಾನ', 'Manpower': 'ಕಾರ್ಮಿಕರು', 'Work done': 'ಮಾಡಿದ ಕೆಲಸ', 'Photos': 'ಫೋಟೋಗಳು',
  'Save report': 'ವರದಿ ಉಳಿಸಿ', 'Issue': 'ಸಮಸ್ಯೆ', 'Delay': 'ವಿಳಂಬ', 'present': 'ಹಾಜರು', 'half_day': 'ಅರ್ಧ ದಿನ', 'absent': 'ಗೈರು', 'leave': 'ರಜೆ',
  'New snag': 'ಹೊಸ ದೋಷ', 'Mark fixed': 'ಸರಿಪಡಿಸಲಾಗಿದೆ', 'Close': 'ಮುಚ್ಚಿ', 'Reopen': 'ಮತ್ತೆ ತೆರೆಯಿರಿ', 'All': 'ಎಲ್ಲಾ', 'Material': 'ಸಾಮಗ್ರಿ',
  'Your projects': 'ನಿಮ್ಮ ಯೋಜನೆಗಳು', 'Documents': 'ದಾಖಲೆಗಳು', 'Site photos': 'ಸೈಟ್ ಫೋಟೋಗಳು', 'Messages': 'ಸಂದೇಶಗಳು', 'Project team': 'ಯೋಜನಾ ತಂಡ',
  'Invoices': 'ಬಿಲ್‌ಗಳು', 'View': 'ನೋಡಿ', 'Pay now': 'ಈಗ ಪಾವತಿಸಿ', 'Back': 'ಹಿಂದೆ', 'Progress': 'ಪ್ರಗತಿ', 'Approve': 'ಅನುಮೋದಿಸಿ', 'Reject': 'ತಿರಸ್ಕರಿಸಿ',
  'Safety': 'ಸುರಕ್ಷತೆ', 'Field app': 'ಫೀಲ್ಡ್ ಆ್ಯಪ್', 'Sync now': 'ಈಗ ಕಳುಹಿಸಿ', 'Offline': 'ಆಫ್‌ಲೈನ್', 'Online': 'ಆನ್‌ಲೈನ್', 'Waiting to send': 'ಕಳುಹಿಸಲು ಬಾಕಿ',
};
const BN: Record<string, string> = {
  'Sales': 'বিক্রি', 'Delivery': 'বাস্তবায়ন', 'Money': 'টাকা', 'Team': 'দল', 'Admin': 'প্রশাসন', 'Home': 'হোম', 'Contacts': 'যোগাযোগ',
  'Projects': 'প্রকল্প', 'Site reports': 'সাইট রিপোর্ট', 'Reports': 'রিপোর্ট', 'Follow-ups': 'ফলো-আপ', 'Inbox': 'ইনবক্স', 'Finance': 'অর্থ',
  'Change password': 'পাসওয়ার্ড বদলান', 'Sign out': 'সাইন আউট', 'Language': 'ভাষা', 'Daily reports': 'দৈনিক রিপোর্ট', 'Attendance': 'হাজিরা',
  'Snags': 'ত্রুটি', 'Stock': 'মজুত', 'Weather': 'আবহাওয়া', 'Manpower': 'শ্রমিক', 'Work done': 'হওয়া কাজ', 'Photos': 'ছবি',
  'Save report': 'রিপোর্ট সংরক্ষণ', 'Issue': 'সমস্যা', 'Delay': 'দেরি', 'present': 'উপস্থিত', 'half_day': 'অর্ধ দিন', 'absent': 'অনুপস্থিত', 'leave': 'ছুটি',
  'New snag': 'নতুন ত্রুটি', 'Mark fixed': 'ঠিক হয়েছে', 'Close': 'বন্ধ করুন', 'Reopen': 'আবার খুলুন', 'All': 'সব', 'Material': 'মাল',
  'Your projects': 'আপনার প্রকল্প', 'Documents': 'নথি', 'Site photos': 'সাইটের ছবি', 'Messages': 'বার্তা', 'Project team': 'প্রকল্প দল',
  'Invoices': 'বিল', 'View': 'দেখুন', 'Pay now': 'এখন পেমেন্ট', 'Back': 'ফিরে', 'Progress': 'অগ্রগতি', 'Approve': 'অনুমোদন', 'Reject': 'বাতিল',
  'Safety': 'নিরাপত্তা', 'Field app': 'ফিল্ড অ্যাপ', 'Sync now': 'এখন পাঠান', 'Offline': 'অফলাইন', 'Online': 'অনলাইন', 'Waiting to send': 'পাঠানোর অপেক্ষায়',
};
Object.assign(HI, { 'Safety': 'सुरक्षा', 'Field app': 'फ़ील्ड ऐप', 'Sync now': 'अभी भेजें', 'Offline': 'ऑफ़लाइन', 'Online': 'ऑनलाइन', 'Waiting to send': 'भेजना बाकी' });

export type Lang = 'en' | 'hi' | 'mr' | 'gu' | 'ta' | 'te' | 'kn' | 'bn';
const DICTS: Partial<Record<Lang, Record<string, string>>> = { hi: HI, mr: MR, gu: GU, ta: TA, te: TE, kn: KN, bn: BN };
export const LANGUAGES: { code: Lang; name: string }[] = [
  { code: 'en', name: 'English' }, { code: 'hi', name: 'हिन्दी' }, { code: 'mr', name: 'मराठी' }, { code: 'gu', name: 'ગુજરાતી' },
  { code: 'ta', name: 'தமிழ்' }, { code: 'te', name: 'తెలుగు' }, { code: 'kn', name: 'ಕನ್ನಡ' }, { code: 'bn', name: 'বাংলা' }];

@Injectable({ providedIn: 'root' })
export class I18n {
  private http = inject(HttpClient);
  readonly languages = LANGUAGES;
  lang = signal<Lang>(I18n.saved());

  private static saved(): Lang {
    try {
      const v = localStorage.getItem('bs.lang') as Lang;
      return v && v in DICTS ? v : 'en';
    } catch {
      return 'en';
    }
  }

  t(text: string): string {
    const d = DICTS[this.lang()];
    return d ? d[text] ?? text : text;
  }

  name(code = this.lang()) {
    return LANGUAGES.find((l) => l.code === code)?.name ?? code;
  }

  /** Called with the signed-in user: their saved choice wins over this browser's. */
  adopt(language?: string | null) {
    if (language && (language === 'en' || language in DICTS)) this.apply(language as Lang);
  }

  async set(language: Lang) {
    this.apply(language);
    try {
      await firstValueFrom(this.http.put('/api/me/language', { language }));
    } catch { /* kept in this browser at least */ }
  }

  private apply(language: Lang) {
    this.lang.set(language);
    try {
      localStorage.setItem('bs.lang', language);
    } catch { /* private window */ }
    document.documentElement.lang = language;
  }
}

/** `{{ 'Site photos' | t }}` — impure so it follows a language switch at once. */
@Pipe({ name: 't', pure: false })
export class TPipe implements PipeTransform {
  private i18n = inject(I18n);
  transform(text: string | null | undefined): string {
    return text ? this.i18n.t(text) : '';
  }
}
