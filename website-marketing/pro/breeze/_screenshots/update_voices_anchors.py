"""Switch voices.para2 and para3 inline links from external URLs to in-page
anchors that point at the new sidebar reference cards. Keep the prose verbatim
otherwise. Also add the new card-related strings (aside_label + ref_*).
"""
import json

LA = 'style="color: var(--accent); text-decoration: underline; text-underline-offset: 2px;"'
LM = 'style="color: var(--accent-3); text-decoration: underline; text-underline-offset: 2px; font-family: \'JetBrains Mono\', monospace; font-size: 0.92em;"'

A_BOOK   = '#voices-ref-book'
A_CAD    = '#voices-ref-cad2data'
A_CWICR  = '#voices-ref-cwicr'

def link(href, text, mono=False):
    style = LM if mono else LA
    return f'<a href="{href}" {style}>{text}</a>'

EN = {
  'para2': (
    'Over the years, dozens of articles have come off my desk, read by millions of '
    'professionals around the world. At the same time, I\u2019ve consulted with major '
    'construction and consulting firms, developers, and software vendors themselves on data '
    'management in projects\u2014helping them navigate processes where data is not a byproduct '
    'but the foundation for decision-making. This work gave me a rare opportunity to see the '
    'industry from both sides: through the eyes of those who create the tools and through the '
    'eyes of those who use them in real projects every day. Many of these observations and '
    'reflections are collected in my book <em>Data-Driven Construction</em>, which is now '
    'available in 16 languages\u2014' + link(A_BOOK, 'datadrivenconstruction.io/books') + '.'
  ),
  'para3': (
    'My research journey has also taken me into areas that few take seriously: '
    'reverse-engineering closed formats and systematizing descriptions of construction work '
    'using a resource model. These efforts have resulted in open-source tools\u2014'
    + link(A_CAD, 'DDC CAD/BIM data converters') + ' (Revit, IFC, DWG, DGN \u2192 structured '
    'data), ' + link(A_CAD, 'available on GitHub') + ', and the multilingual '
    + link(A_CWICR, 'CWICR database') + ' of construction works and resources\u2014over 55,000 '
    'items in 11 languages, published as '
    + link(A_CWICR, 'OpenConstructionEstimate-DDC-CWICR', mono=True) + '. All of this was a '
    'necessary step toward the idea I\u2019ve been pursuing for the past decade\u2014creating '
    'an open-source ERP for the construction industry. Many who asked me what tools I was '
    'developing inevitably heard my ideas about creating an open-source modular ERP system.'
  ),
  'aside_label': 'Mentioned in this note',
  'ref_book_name':  'Data-Driven Construction',
  'ref_book_meta':  'Book \u00b7 16 languages',
  'ref_book_desc':  'A decade of observations on data, AI and cost in construction \u2014 the thinking behind every product the lab ships.',
  'ref_cad_name':   'DDC CAD/BIM converters',
  'ref_cad_meta':   'GitHub \u00b7 RVT \u00b7 IFC \u00b7 DWG \u00b7 DGN',
  'ref_cad_desc':   'Reverse-engineering closed CAD/BIM formats into clean structured data.',
  'ref_cwicr_name': 'CWICR cost database',
  'ref_cwicr_meta': 'GitHub \u00b7 55,000+ items \u00b7 11 languages',
  'ref_cwicr_desc': 'Multilingual database of construction works and resources, structured for estimation.',
}

DE = {
  'para2': (
    '\u00dcber die Jahre sind Dutzende Artikel aus meiner Feder erschienen, die von Millionen '
    'Fachleuten weltweit gelesen wurden. Parallel dazu habe ich gro\u00dfe Bauunternehmen und '
    'Beratungsfirmen, Entwickler und Softwareanbieter selbst zum Thema Datenmanagement in '
    'Projekten beraten\u2014und ihnen geholfen, Prozesse zu gestalten, in denen Daten kein '
    'Nebenprodukt sind, sondern die Grundlage f\u00fcr Entscheidungen. Diese Arbeit hat mir '
    'die seltene M\u00f6glichkeit gegeben, die Branche von beiden Seiten zu sehen: durch die '
    'Augen derjenigen, die die Werkzeuge entwickeln, und durch die Augen derjenigen, die sie '
    't\u00e4glich in realen Projekten einsetzen. Viele dieser Beobachtungen und '
    '\u00dcberlegungen sind in meinem Buch <em>Data-Driven Construction</em> '
    'zusammengefasst, das inzwischen in 16 Sprachen verf\u00fcgbar ist\u2014'
    + link(A_BOOK, 'datadrivenconstruction.io/books') + '.'
  ),
  'para3': (
    'Meine Forschung hat mich auch in Bereiche gef\u00fchrt, die nur wenige ernsthaft angehen: '
    'das Reverse Engineering geschlossener Formate und die Systematisierung der Beschreibung '
    'von Bauleistungen \u00fcber ein Ressourcenmodell. Diese Arbeit hat Open-Source-Werkzeuge '
    'hervorgebracht\u2014' + link(A_CAD, 'DDC CAD/BIM-Datenkonverter') + ' (Revit, IFC, DWG, '
    'DGN \u2192 strukturierte Daten), ' + link(A_CAD, 'verf\u00fcgbar auf GitHub') + ', und die '
    'mehrsprachige ' + link(A_CWICR, 'CWICR-Datenbank') + ' f\u00fcr Bauleistungen und '
    'Ressourcen\u2014mehr als 55.000 Positionen in 11 Sprachen, ver\u00f6ffentlicht als '
    + link(A_CWICR, 'OpenConstructionEstimate-DDC-CWICR', mono=True) + '. All dies war ein '
    'notwendiger Schritt hin zu der Idee, die ich seit einem Jahrzehnt verfolge\u2014ein '
    'Open-Source-ERP f\u00fcr das Bauwesen. Viele, die mich fragten, woran ich arbeite, '
    'h\u00f6rten unweigerlich meine Gedanken zu einem modularen Open-Source-ERP-System.'
  ),
  'aside_label': 'In diesem Beitrag erw\u00e4hnt',
  'ref_book_name':  'Data-Driven Construction',
  'ref_book_meta':  'Buch \u00b7 16 Sprachen',
  'ref_book_desc':  'Ein Jahrzehnt Beobachtungen zu Daten, KI und Kosten im Bauwesen \u2014 das Denken hinter jedem Produkt des Labors.',
  'ref_cad_name':   'DDC CAD/BIM-Konverter',
  'ref_cad_meta':   'GitHub \u00b7 RVT \u00b7 IFC \u00b7 DWG \u00b7 DGN',
  'ref_cad_desc':   'Reverse Engineering geschlossener CAD/BIM-Formate in saubere strukturierte Daten.',
  'ref_cwicr_name': 'CWICR-Kostendatenbank',
  'ref_cwicr_meta': 'GitHub \u00b7 55.000+ Positionen \u00b7 11 Sprachen',
  'ref_cwicr_desc': 'Mehrsprachige Datenbank f\u00fcr Bauleistungen und Ressourcen, strukturiert f\u00fcr die Kalkulation.',
}

RU = {
  'para2': (
    '\u0417\u0430 \u044d\u0442\u0438 \u0433\u043e\u0434\u044b \u0438\u0437-\u043f\u043e\u0434 \u043c\u043e\u0435\u0433\u043e \u043f\u0435\u0440\u0430 \u0432\u044b\u0448\u043b\u0438 \u0434\u0435\u0441\u044f\u0442\u043a\u0438 \u0441\u0442\u0430\u0442\u0435\u0439, \u043f\u0440\u043e\u0447\u0438\u0442\u0430\u043d\u043d\u044b\u0445 '
    '\u043c\u0438\u043b\u043b\u0438\u043e\u043d\u0430\u043c\u0438 \u043f\u0440\u043e\u0444\u0435\u0441\u0441\u0438\u043e\u043d\u0430\u043b\u043e\u0432 \u043f\u043e \u0432\u0441\u0435\u043c\u0443 \u043c\u0438\u0440\u0443. \u041f\u0430\u0440\u0430\u043b\u043b\u0435\u043b\u044c\u043d\u043e \u044f \u043a\u043e\u043d\u0441\u0443\u043b\u044c\u0442\u0438\u0440\u043e\u0432\u0430\u043b '
    '\u043a\u0440\u0443\u043f\u043d\u044b\u0435 \u0441\u0442\u0440\u043e\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0435 \u0438 \u043a\u043e\u043d\u0441\u0430\u043b\u0442\u0438\u043d\u0433\u043e\u0432\u044b\u0435 \u043a\u043e\u043c\u043f\u0430\u043d\u0438\u0438, \u0434\u0435\u0432\u0435\u043b\u043e\u043f\u0435\u0440\u043e\u0432, \u0430 \u0442\u0430\u043a\u0436\u0435 \u0441\u0430\u043c\u0438\u0445 '
    '\u0432\u0435\u043d\u0434\u043e\u0440\u043e\u0432 \u043f\u0440\u043e\u0433\u0440\u0430\u043c\u043c\u043d\u043e\u0433\u043e \u043e\u0431\u0435\u0441\u043f\u0435\u0447\u0435\u043d\u0438\u044f \u043f\u043e \u0432\u043e\u043f\u0440\u043e\u0441\u0430\u043c \u0443\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u044f \u0434\u0430\u043d\u043d\u044b\u043c\u0438 \u0432 \u043f\u0440\u043e\u0435\u043a\u0442\u0430\u0445\u2014\u043f\u043e\u043c\u043e\u0433\u0430\u044f '
    '\u0438\u043c \u0432\u044b\u0441\u0442\u0440\u0430\u0438\u0432\u0430\u0442\u044c \u043f\u0440\u043e\u0446\u0435\u0441\u0441\u044b, \u0432 \u043a\u043e\u0442\u043e\u0440\u044b\u0445 \u0434\u0430\u043d\u043d\u044b\u0435 \u044f\u0432\u043b\u044f\u044e\u0442\u0441\u044f \u043d\u0435 \u043f\u043e\u0431\u043e\u0447\u043d\u044b\u043c \u043f\u0440\u043e\u0434\u0443\u043a\u0442\u043e\u043c, \u0430 \u043e\u0441\u043d\u043e\u0432\u043e\u0439 '
    '\u0434\u043b\u044f \u043f\u0440\u0438\u043d\u044f\u0442\u0438\u044f \u0440\u0435\u0448\u0435\u043d\u0438\u0439. \u042d\u0442\u0430 \u0440\u0430\u0431\u043e\u0442\u0430 \u0434\u0430\u043b\u0430 \u043c\u043d\u0435 \u0440\u0435\u0434\u043a\u0443\u044e \u0432\u043e\u0437\u043c\u043e\u0436\u043d\u043e\u0441\u0442\u044c \u0443\u0432\u0438\u0434\u0435\u0442\u044c \u043e\u0442\u0440\u0430\u0441\u043b\u044c \u0441 \u0434\u0432\u0443\u0445 '
    '\u0441\u0442\u043e\u0440\u043e\u043d: \u0433\u043b\u0430\u0437\u0430\u043c\u0438 \u0442\u0435\u0445, \u043a\u0442\u043e \u0441\u043e\u0437\u0434\u0430\u0451\u0442 \u0438\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442\u044b, \u0438 \u0433\u043b\u0430\u0437\u0430\u043c\u0438 \u0442\u0435\u0445, \u043a\u0442\u043e \u043a\u0430\u0436\u0434\u044b\u0439 \u0434\u0435\u043d\u044c \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0435\u0442 \u0438\u0445 '
    '\u0432 \u0440\u0435\u0430\u043b\u044c\u043d\u044b\u0445 \u043f\u0440\u043e\u0435\u043a\u0442\u0430\u0445. \u041c\u043d\u043e\u0433\u0438\u0435 \u0438\u0437 \u044d\u0442\u0438\u0445 \u043d\u0430\u0431\u043b\u044e\u0434\u0435\u043d\u0438\u0439 \u0438 \u0440\u0430\u0437\u043c\u044b\u0448\u043b\u0435\u043d\u0438\u0439 \u0441\u043e\u0431\u0440\u0430\u043d\u044b \u0432 \u043c\u043e\u0435\u0439 \u043a\u043d\u0438\u0433\u0435 '
    '<em>Data-Driven Construction</em>, \u0438\u0437\u0434\u0430\u043d\u043d\u043e\u0439 \u043d\u0430 16 \u044f\u0437\u044b\u043a\u0430\u0445\u2014'
    + link(A_BOOK, 'datadrivenconstruction.io/books') + '.'
  ),
  'para3': (
    '\u0418\u0441\u0441\u043b\u0435\u0434\u043e\u0432\u0430\u0442\u0435\u043b\u044c\u0441\u043a\u0438\u0439 \u043f\u0443\u0442\u044c \u043f\u0440\u0438\u0432\u0451\u043b \u043c\u0435\u043d\u044f \u0438 \u0432 \u043e\u0431\u043b\u0430\u0441\u0442\u0438, \u043a\u043e\u0442\u043e\u0440\u044b\u043c\u0438 '
    '\u043c\u0430\u043b\u043e \u043a\u0442\u043e \u0437\u0430\u043d\u0438\u043c\u0430\u0435\u0442\u0441\u044f \u0432\u0441\u0435\u0440\u044c\u0451\u0437: \u043e\u0431\u0440\u0430\u0442\u043d\u0430\u044f \u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u043a\u0430 \u0437\u0430\u043a\u0440\u044b\u0442\u044b\u0445 \u0444\u043e\u0440\u043c\u0430\u0442\u043e\u0432 \u0438 '
    '\u0441\u0438\u0441\u0442\u0435\u043c\u0430\u0442\u0438\u0437\u0430\u0446\u0438\u044f \u043e\u043f\u0438\u0441\u0430\u043d\u0438\u044f \u0441\u0442\u0440\u043e\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0445 \u0440\u0430\u0431\u043e\u0442 \u043d\u0430 \u043e\u0441\u043d\u043e\u0432\u0435 \u0440\u0435\u0441\u0443\u0440\u0441\u043d\u043e\u0439 \u043c\u043e\u0434\u0435\u043b\u0438. '
    '\u0420\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442\u043e\u043c \u044d\u0442\u0438\u0445 \u0443\u0441\u0438\u043b\u0438\u0439 \u0441\u0442\u0430\u043b\u0438 open-source \u0438\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442\u044b\u2014'
    + link(A_CAD, '\u043a\u043e\u043d\u0432\u0435\u0440\u0442\u0435\u0440\u044b \u0434\u0430\u043d\u043d\u044b\u0445 DDC CAD/BIM') + ' (Revit, IFC, DWG, DGN \u2192 \u0441\u0442\u0440\u0443\u043a\u0442\u0443\u0440\u0438\u0440\u043e\u0432\u0430\u043d\u043d\u044b\u0435 \u0434\u0430\u043d\u043d\u044b\u0435), '
    + link(A_CAD, '\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u044b\u0435 \u043d\u0430 GitHub') + ', \u0438 \u043c\u043d\u043e\u0433\u043e\u044f\u0437\u044b\u0447\u043d\u0430\u044f '
    + link(A_CWICR, '\u0431\u0430\u0437\u0430 CWICR') + ' \u0441\u0442\u0440\u043e\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0445 \u0440\u0430\u0431\u043e\u0442 \u0438 \u0440\u0435\u0441\u0443\u0440\u0441\u043e\u0432\u2014\u0431\u043e\u043b\u0435\u0435 55 000 \u043f\u043e\u0437\u0438\u0446\u0438\u0439 '
    '\u043d\u0430 11 \u044f\u0437\u044b\u043a\u0430\u0445, \u043e\u043f\u0443\u0431\u043b\u0438\u043a\u043e\u0432\u0430\u043d\u043d\u0430\u044f \u043a\u0430\u043a '
    + link(A_CWICR, 'OpenConstructionEstimate-DDC-CWICR', mono=True) + '. \u0412\u0441\u0451 \u044d\u0442\u043e \u0431\u044b\u043b\u043e \u043d\u0435\u043e\u0431\u0445\u043e\u0434\u0438\u043c\u044b\u043c '
    '\u0448\u0430\u0433\u043e\u043c \u043a \u0438\u0434\u0435\u0435, \u043a\u043e\u0442\u043e\u0440\u0443\u044e \u044f \u043d\u0435\u0441\u0443 \u0443\u0436\u0435 \u0434\u0435\u0441\u044f\u0442\u044c \u043b\u0435\u0442\u2014\u0441\u043e\u0437\u0434\u0430\u0442\u044c open-source ERP \u0434\u043b\u044f '
    '\u0441\u0442\u0440\u043e\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u0439 \u043e\u0442\u0440\u0430\u0441\u043b\u0438. \u041c\u043d\u043e\u0433\u0438\u0435, \u043a\u0442\u043e \u0441\u043f\u0440\u0430\u0448\u0438\u0432\u0430\u043b \u043c\u0435\u043d\u044f, \u043a\u0430\u043a\u0438\u0435 \u0438\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442\u044b \u044f '
    '\u0440\u0430\u0437\u0440\u0430\u0431\u0430\u0442\u044b\u0432\u0430\u044e, \u043d\u0435\u0438\u0437\u0431\u0435\u0436\u043d\u043e \u0441\u043b\u044b\u0448\u0430\u043b\u0438 \u043c\u043e\u0438 \u0438\u0434\u0435\u0438 \u043e \u0441\u043e\u0437\u0434\u0430\u043d\u0438\u0438 \u043e\u0442\u043a\u0440\u044b\u0442\u043e\u0439 \u043c\u043e\u0434\u0443\u043b\u044c\u043d\u043e\u0439 ERP-\u0441\u0438\u0441\u0442\u0435\u043c\u044b.'
  ),
  'aside_label': '\u0423\u043f\u043e\u043c\u0438\u043d\u0430\u0435\u0442\u0441\u044f \u0432 \u0442\u0435\u043a\u0441\u0442\u0435',
  'ref_book_name':  'Data-Driven Construction',
  'ref_book_meta':  '\u041a\u043d\u0438\u0433\u0430 \u00b7 16 \u044f\u0437\u044b\u043a\u043e\u0432',
  'ref_book_desc':  '\u0414\u0435\u0441\u044f\u0442\u044c \u043b\u0435\u0442 \u043d\u0430\u0431\u043b\u044e\u0434\u0435\u043d\u0438\u0439 \u043e \u0434\u0430\u043d\u043d\u044b\u0445, AI \u0438 \u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u0438 \u0432 \u0441\u0442\u0440\u043e\u0438\u0442\u0435\u043b\u044c\u0441\u0442\u0432\u0435 \u2014 \u043e\u0441\u043d\u043e\u0432\u0430 \u0432\u0441\u0435\u0445 \u043f\u0440\u043e\u0434\u0443\u043a\u0442\u043e\u0432 \u043b\u0430\u0431\u043e\u0440\u0430\u0442\u043e\u0440\u0438\u0438.',
  'ref_cad_name':   '\u041a\u043e\u043d\u0432\u0435\u0440\u0442\u0435\u0440\u044b DDC CAD/BIM',
  'ref_cad_meta':   'GitHub \u00b7 RVT \u00b7 IFC \u00b7 DWG \u00b7 DGN',
  'ref_cad_desc':   '\u041e\u0431\u0440\u0430\u0442\u043d\u0430\u044f \u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u043a\u0430 \u0437\u0430\u043a\u0440\u044b\u0442\u044b\u0445 CAD/BIM-\u0444\u043e\u0440\u043c\u0430\u0442\u043e\u0432 \u0432 \u0447\u0438\u0441\u0442\u044b\u0435 \u0441\u0442\u0440\u0443\u043a\u0442\u0443\u0440\u0438\u0440\u043e\u0432\u0430\u043d\u043d\u044b\u0435 \u0434\u0430\u043d\u043d\u044b\u0435.',
  'ref_cwicr_name': '\u0411\u0430\u0437\u0430 \u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u0435\u0439 CWICR',
  'ref_cwicr_meta': 'GitHub \u00b7 55 000+ \u043f\u043e\u0437\u0438\u0446\u0438\u0439 \u00b7 11 \u044f\u0437\u044b\u043a\u043e\u0432',
  'ref_cwicr_desc': '\u041c\u043d\u043e\u0433\u043e\u044f\u0437\u044b\u0447\u043d\u0430\u044f \u0431\u0430\u0437\u0430 \u0441\u0442\u0440\u043e\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0445 \u0440\u0430\u0431\u043e\u0442 \u0438 \u0440\u0435\u0441\u0443\u0440\u0441\u043e\u0432, \u0441\u0442\u0440\u0443\u043a\u0442\u0443\u0440\u0438\u0440\u043e\u0432\u0430\u043d\u043d\u0430\u044f \u0434\u043b\u044f \u043a\u0430\u043b\u044c\u043a\u0443\u043b\u044f\u0446\u0438\u0438.',
}

content = {'en': EN, 'de': DE, 'ru': RU}
for loc, blk in content.items():
    p = f"C:/Users/Artem Boiko/Desktop/CodeProjects/ERP_26030500/website-marketing/pro/breeze/locales/{loc}.json"
    d = json.load(open(p, encoding='utf-8'))
    v = d.setdefault('voices', {})
    for k, val in blk.items():
        v[k] = val
    json.dump(d, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print('updated', loc)
