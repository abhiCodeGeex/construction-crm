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

@Injectable({ providedIn: 'root' })
export class I18n {
  private http = inject(HttpClient);
  lang = signal<'en' | 'hi'>(I18n.saved());

  private static saved(): 'en' | 'hi' {
    try {
      return localStorage.getItem('bs.lang') === 'hi' ? 'hi' : 'en';
    } catch {
      return 'en';
    }
  }

  t(text: string): string {
    return this.lang() === 'hi' ? HI[text] ?? text : text;
  }

  /** Called with the signed-in user: their saved choice wins over this browser's. */
  adopt(language?: string | null) {
    if (language === 'hi' || language === 'en') this.apply(language);
  }

  async set(language: 'en' | 'hi') {
    this.apply(language);
    try {
      await firstValueFrom(this.http.put('/api/me/language', { language }));
    } catch { /* kept in this browser at least */ }
  }

  private apply(language: 'en' | 'hi') {
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
