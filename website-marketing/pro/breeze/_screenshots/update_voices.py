import json

LA = 'style="color: var(--accent); text-decoration: underline; text-underline-offset: 2px;"'
LM = 'style="color: var(--accent-3); text-decoration: underline; text-underline-offset: 2px; font-family: \'JetBrains Mono\', monospace; font-size: 0.92em;"'

CAD_URL = 'https://github.com/datadrivenconstruction/cad2data-Revit-IFC-DWG-DGN'
CWICR_URL = 'https://github.com/datadrivenconstruction/OpenConstructionEstimate-DDC-CWICR'
BOOK_URL = 'https://datadrivenconstruction.io/books/'

def a(href, text, mono=False):
    style = LM if mono else LA
    return f'<a href="{href}" target="_blank" rel="noopener" {style}>{text}</a>'

content = {
    'en': {
        'para1': (
            'Over the past ten years, I have been deeply involved in resource management '
            'for construction projects. This journey inevitably led me to study the history '
            'of the technologies that have shaped the industry \u2014 from the earliest attempts '
            'at design automation to modern ERP platforms '
            '<span style="color: var(--ink-3);">(for those interested in this context, '
            'simply search for <em>\u201cHistory of BIM\u201d</em>)</span>. Without understanding where we came '
            'from, it is impossible to see where we are going.'
        ),
        'para2': (
            'Over the years, dozens of articles have come off my desk, read by millions of '
            'professionals around the world. At the same time, I\u2019ve consulted with major '
            'construction and consulting firms, developers, and software vendors themselves on '
            'data management in projects \u2014 helping them navigate processes where data is not '
            'a byproduct but the foundation for decision-making. This work gave me a rare '
            'opportunity to see the industry from both sides: through the eyes of those who '
            'create the tools and through the eyes of those who use them in real projects every '
            'day. Many of these observations and reflections are collected in my book '
            '<em>Data-Driven Construction</em>, which is now available in 16 languages \u2014 '
            + a(BOOK_URL, 'datadrivenconstruction.io/books') + '.'
        ),
        'para3': (
            'My research journey has also taken me into areas that few take seriously: '
            'reverse-engineering closed formats and systematizing descriptions of construction '
            'work using a resource model. These efforts have resulted in open-source tools \u2014 '
            'the ' + a(CAD_URL, 'DDC CAD/BIM data converters') + ' (Revit, IFC, DWG, DGN \u2192 '
            'structured data), available on GitHub, and the multilingual '
            + a(CWICR_URL, 'CWICR database') + ' of construction works and resources \u2014 over '
            '55,000 items in 11 languages, published as '
            + a(CWICR_URL, 'OpenConstructionEstimate-DDC-CWICR', mono=True) + '. All of this was '
            'a necessary step toward the idea I\u2019ve been pursuing for the past decade \u2014 '
            'creating an open-source ERP for the construction industry. Many who asked me what '
            'tools I was developing inevitably heard my ideas about creating an open-source '
            'modular ERP system.'
        ),
        'para4': (
            'And only this year did the emergence of artificial intelligence tools make it '
            'possible to consolidate the vast body of knowledge, developments, and solutions '
            'accumulated over a decade into a single platform. Today, I am presenting it to the '
            'community \u2014 in the hope that it will help companies and their clients in the '
            'construction industry transition to managing construction projects at the process '
            'level. This shift, I believe, is precisely what can finally unlock the potential '
            'for productivity and data quality in an industry that has been held back for too '
            'long by fragmented solutions and disparate approaches.'
        ),
        'pull': (
            'Progress is born from dialogue \u2014 from the clash of perspectives and openness to '
            'new approaches. I would be grateful if you would be willing to participate in this '
            'conversation on the inevitable Uberization of the construction industry and the '
            'transparency of cost and time estimation processes for construction projects.'
        ),
    },
    'de': {
        'para1': (
            'In den vergangenen zehn Jahren war ich tief in das Ressourcenmanagement von '
            'Bauprojekten eingebunden. Dieser Weg hat mich unweigerlich dazu gef\u00fchrt, die '
            'Geschichte der Technologien zu studieren, die diese Branche gepr\u00e4gt haben \u2014 von '
            'den ersten Versuchen der Konstruktionsautomatisierung bis hin zu den heutigen '
            'ERP-Plattformen <span style="color: var(--ink-3);">(wer sich f\u00fcr diesen Kontext '
            'interessiert, sucht einfach nach <em>\u201eHistory of BIM\u201c</em>)</span>. Ohne zu '
            'verstehen, woher wir kommen, ist es unm\u00f6glich zu erkennen, wohin wir gehen.'
        ),
        'para2': (
            '\u00dcber die Jahre sind Dutzende Artikel aus meiner Feder erschienen, die von Millionen '
            'Fachleuten weltweit gelesen wurden. Parallel dazu habe ich gro\u00dfe Bauunternehmen und '
            'Beratungsfirmen, Entwickler und Softwareanbieter selbst zum Thema Datenmanagement in '
            'Projekten beraten \u2014 und ihnen geholfen, Prozesse zu gestalten, in denen Daten kein '
            'Nebenprodukt sind, sondern die Grundlage f\u00fcr Entscheidungen. Diese Arbeit hat mir '
            'die seltene M\u00f6glichkeit gegeben, die Branche von beiden Seiten zu sehen: durch die '
            'Augen derjenigen, die die Werkzeuge entwickeln, und durch die Augen derjenigen, die '
            'sie t\u00e4glich in realen Projekten einsetzen. Viele dieser Beobachtungen und '
            '\u00dcberlegungen sind in meinem Buch <em>Data-Driven Construction</em> '
            'zusammengefasst, das inzwischen in 16 Sprachen verf\u00fcgbar ist \u2014 '
            + a(BOOK_URL, 'datadrivenconstruction.io/books') + '.'
        ),
        'para3': (
            'Meine Forschung hat mich auch in Bereiche gef\u00fchrt, die nur wenige ernsthaft '
            'angehen: das Reverse Engineering geschlossener Formate und die Systematisierung der '
            'Beschreibung von Bauleistungen \u00fcber ein Ressourcenmodell. Diese Arbeit hat '
            'Open-Source-Werkzeuge hervorgebracht \u2014 die '
            + a(CAD_URL, 'DDC CAD/BIM-Datenkonverter') + ' (Revit, IFC, DWG, DGN \u2192 '
            'strukturierte Daten), verf\u00fcgbar auf GitHub, und die mehrsprachige '
            + a(CWICR_URL, 'CWICR-Datenbank') + ' f\u00fcr Bauleistungen und Ressourcen \u2014 mehr als '
            '55.000 Positionen in 11 Sprachen, ver\u00f6ffentlicht als '
            + a(CWICR_URL, 'OpenConstructionEstimate-DDC-CWICR', mono=True) + '. All dies war ein '
            'notwendiger Schritt hin zu der Idee, die ich seit einem Jahrzehnt verfolge \u2014 ein '
            'Open-Source-ERP f\u00fcr das Bauwesen. Viele, die mich fragten, woran ich arbeite, '
            'h\u00f6rten unweigerlich meine Gedanken zu einem modularen Open-Source-ERP-System.'
        ),
        'para4': (
            'Und erst in diesem Jahr machte das Aufkommen von KI-Werkzeugen es m\u00f6glich, die '
            '\u00fcber ein Jahrzehnt angesammelten Erkenntnisse, Entwicklungen und L\u00f6sungen in einer '
            'einzigen Plattform zu b\u00fcndeln. Heute pr\u00e4sentiere ich sie der Community \u2014 in der '
            'Hoffnung, dass sie Unternehmen und ihren Kunden im Bauwesen hilft, Bauprojekte auf '
            'der Prozessebene zu f\u00fchren. Dieser Wandel ist meiner Ansicht nach genau das, was '
            'endlich das Potenzial f\u00fcr Produktivit\u00e4t und Datenqualit\u00e4t freisetzen kann \u2014 in '
            'einer Branche, die zu lange von fragmentierten L\u00f6sungen und uneinheitlichen '
            'Ans\u00e4tzen gebremst wurde.'
        ),
        'pull': (
            'Fortschritt entsteht im Dialog \u2014 aus dem Aufeinandertreffen von Perspektiven und '
            'der Offenheit f\u00fcr neue Ans\u00e4tze. Ich w\u00fcrde mich freuen, wenn Sie an diesem Gespr\u00e4ch '
            'teilnehmen w\u00fcrden \u2014 \u00fcber die unausweichliche Uberisierung der Bauwirtschaft und '
            '\u00fcber Transparenz in der Kosten- und Terminsch\u00e4tzung von Bauprojekten.'
        ),
    },
    'ru': {
        'para1': (
            '\u041f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 \u0434\u0435\u0441\u044f\u0442\u044c \u043b\u0435\u0442 \u044f \u0431\u044b\u043b \u0433\u043b\u0443\u0431\u043e\u043a\u043e \u0432\u043e\u0432\u043b\u0435\u0447\u0451\u043d \u0432 \u0432\u043e\u043f\u0440\u043e\u0441\u044b \u0443\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u044f '
            '\u0440\u0435\u0441\u0443\u0440\u0441\u0430\u043c\u0438 \u0432 \u0441\u0442\u0440\u043e\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0445 \u043f\u0440\u043e\u0435\u043a\u0442\u0430\u0445. \u042d\u0442\u043e\u0442 \u043f\u0443\u0442\u044c \u043d\u0435\u0438\u0437\u0431\u0435\u0436\u043d\u043e \u043f\u0440\u0438\u0432\u0451\u043b \u043c\u0435\u043d\u044f \u043a '
            '\u0438\u0437\u0443\u0447\u0435\u043d\u0438\u044e \u0438\u0441\u0442\u043e\u0440\u0438\u0438 \u0442\u0435\u0445\u043d\u043e\u043b\u043e\u0433\u0438\u0439, \u0441\u0444\u043e\u0440\u043c\u0438\u0440\u043e\u0432\u0430\u0432\u0448\u0438\u0445 \u043e\u0442\u0440\u0430\u0441\u043b\u044c \u2014 \u043e\u0442 \u043f\u0435\u0440\u0432\u044b\u0445 \u043f\u043e\u043f\u044b\u0442\u043e\u043a '
            '\u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0437\u0430\u0446\u0438\u0438 \u043f\u0440\u043e\u0435\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u044f \u0434\u043e \u0441\u043e\u0432\u0440\u0435\u043c\u0435\u043d\u043d\u044b\u0445 ERP-\u043f\u043b\u0430\u0442\u0444\u043e\u0440\u043c '
            '<span style="color: var(--ink-3);">(\u043a\u043e\u043c\u0443 \u0438\u043d\u0442\u0435\u0440\u0435\u0441\u0435\u043d \u044d\u0442\u043e\u0442 \u043a\u043e\u043d\u0442\u0435\u043a\u0441\u0442 \u2014 \u0434\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e \u043d\u0430\u0431\u0440\u0430\u0442\u044c '
            '<em>\u00abHistory of BIM\u00bb</em> \u0432 \u043f\u043e\u0438\u0441\u043a\u0435)</span>. \u041d\u0435 \u043f\u043e\u043d\u0438\u043c\u0430\u044f, \u043e\u0442\u043a\u0443\u0434\u0430 \u043c\u044b \u043f\u0440\u0438\u0448\u043b\u0438, '
            '\u043d\u0435\u0432\u043e\u0437\u043c\u043e\u0436\u043d\u043e \u0443\u0432\u0438\u0434\u0435\u0442\u044c, \u043a\u0443\u0434\u0430 \u043c\u044b \u0434\u0432\u0438\u0436\u0435\u043c\u0441\u044f.'
        ),
        'para2': (
            '\u0417\u0430 \u044d\u0442\u0438 \u0433\u043e\u0434\u044b \u0438\u0437-\u043f\u043e\u0434 \u043c\u043e\u0435\u0433\u043e \u043f\u0435\u0440\u0430 \u0432\u044b\u0448\u043b\u0438 \u0434\u0435\u0441\u044f\u0442\u043a\u0438 \u0441\u0442\u0430\u0442\u0435\u0439, \u043f\u0440\u043e\u0447\u0438\u0442\u0430\u043d\u043d\u044b\u0445 '
            '\u043c\u0438\u043b\u043b\u0438\u043e\u043d\u0430\u043c\u0438 \u043f\u0440\u043e\u0444\u0435\u0441\u0441\u0438\u043e\u043d\u0430\u043b\u043e\u0432 \u043f\u043e \u0432\u0441\u0435\u043c\u0443 \u043c\u0438\u0440\u0443. \u041f\u0430\u0440\u0430\u043b\u043b\u0435\u043b\u044c\u043d\u043e \u044f \u043a\u043e\u043d\u0441\u0443\u043b\u044c\u0442\u0438\u0440\u043e\u0432\u0430\u043b '
            '\u043a\u0440\u0443\u043f\u043d\u044b\u0435 \u0441\u0442\u0440\u043e\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0435 \u0438 \u043a\u043e\u043d\u0441\u0430\u043b\u0442\u0438\u043d\u0433\u043e\u0432\u044b\u0435 \u043a\u043e\u043c\u043f\u0430\u043d\u0438\u0438, \u0434\u0435\u0432\u0435\u043b\u043e\u043f\u0435\u0440\u043e\u0432, \u0430 \u0442\u0430\u043a\u0436\u0435 \u0441\u0430\u043c\u0438\u0445 '
            '\u0432\u0435\u043d\u0434\u043e\u0440\u043e\u0432 \u043f\u0440\u043e\u0433\u0440\u0430\u043c\u043c\u043d\u043e\u0433\u043e \u043e\u0431\u0435\u0441\u043f\u0435\u0447\u0435\u043d\u0438\u044f \u043f\u043e \u0432\u043e\u043f\u0440\u043e\u0441\u0430\u043c \u0443\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u044f \u0434\u0430\u043d\u043d\u044b\u043c\u0438 \u0432 \u043f\u0440\u043e\u0435\u043a\u0442\u0430\u0445 \u2014 '
            '\u043f\u043e\u043c\u043e\u0433\u0430\u044f \u0438\u043c \u0432\u044b\u0441\u0442\u0440\u0430\u0438\u0432\u0430\u0442\u044c \u043f\u0440\u043e\u0446\u0435\u0441\u0441\u044b, \u0432 \u043a\u043e\u0442\u043e\u0440\u044b\u0445 \u0434\u0430\u043d\u043d\u044b\u0435 \u044f\u0432\u043b\u044f\u044e\u0442\u0441\u044f \u043d\u0435 \u043f\u043e\u0431\u043e\u0447\u043d\u044b\u043c '
            '\u043f\u0440\u043e\u0434\u0443\u043a\u0442\u043e\u043c, \u0430 \u043e\u0441\u043d\u043e\u0432\u043e\u0439 \u0434\u043b\u044f \u043f\u0440\u0438\u043d\u044f\u0442\u0438\u044f \u0440\u0435\u0448\u0435\u043d\u0438\u0439. \u042d\u0442\u0430 \u0440\u0430\u0431\u043e\u0442\u0430 \u0434\u0430\u043b\u0430 \u043c\u043d\u0435 \u0440\u0435\u0434\u043a\u0443\u044e '
            '\u0432\u043e\u0437\u043c\u043e\u0436\u043d\u043e\u0441\u0442\u044c \u0443\u0432\u0438\u0434\u0435\u0442\u044c \u043e\u0442\u0440\u0430\u0441\u043b\u044c \u0441 \u0434\u0432\u0443\u0445 \u0441\u0442\u043e\u0440\u043e\u043d: \u0433\u043b\u0430\u0437\u0430\u043c\u0438 \u0442\u0435\u0445, \u043a\u0442\u043e \u0441\u043e\u0437\u0434\u0430\u0451\u0442 '
            '\u0438\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442\u044b, \u0438 \u0433\u043b\u0430\u0437\u0430\u043c\u0438 \u0442\u0435\u0445, \u043a\u0442\u043e \u043a\u0430\u0436\u0434\u044b\u0439 \u0434\u0435\u043d\u044c \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0435\u0442 \u0438\u0445 \u0432 \u0440\u0435\u0430\u043b\u044c\u043d\u044b\u0445 \u043f\u0440\u043e\u0435\u043a\u0442\u0430\u0445. '
            '\u041c\u043d\u043e\u0433\u0438\u0435 \u0438\u0437 \u044d\u0442\u0438\u0445 \u043d\u0430\u0431\u043b\u044e\u0434\u0435\u043d\u0438\u0439 \u0438 \u0440\u0430\u0437\u043c\u044b\u0448\u043b\u0435\u043d\u0438\u0439 \u0441\u043e\u0431\u0440\u0430\u043d\u044b \u0432 \u043c\u043e\u0435\u0439 \u043a\u043d\u0438\u0433\u0435 '
            '<em>Data-Driven Construction</em>, \u0438\u0437\u0434\u0430\u043d\u043d\u043e\u0439 \u043d\u0430 16 \u044f\u0437\u044b\u043a\u0430\u0445 \u2014 '
            + a(BOOK_URL, 'datadrivenconstruction.io/books') + '.'
        ),
        'para3': (
            '\u0418\u0441\u0441\u043b\u0435\u0434\u043e\u0432\u0430\u0442\u0435\u043b\u044c\u0441\u043a\u0438\u0439 \u043f\u0443\u0442\u044c \u043f\u0440\u0438\u0432\u0451\u043b \u043c\u0435\u043d\u044f \u0438 \u0432 \u043e\u0431\u043b\u0430\u0441\u0442\u0438, \u043a\u043e\u0442\u043e\u0440\u044b\u043c\u0438 '
            '\u043c\u0430\u043b\u043e \u043a\u0442\u043e \u0437\u0430\u043d\u0438\u043c\u0430\u0435\u0442\u0441\u044f \u0432\u0441\u0435\u0440\u044c\u0451\u0437: \u043e\u0431\u0440\u0430\u0442\u043d\u0430\u044f \u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u043a\u0430 \u0437\u0430\u043a\u0440\u044b\u0442\u044b\u0445 \u0444\u043e\u0440\u043c\u0430\u0442\u043e\u0432 '
            '\u0438 \u0441\u0438\u0441\u0442\u0435\u043c\u0430\u0442\u0438\u0437\u0430\u0446\u0438\u044f \u043e\u043f\u0438\u0441\u0430\u043d\u0438\u044f \u0441\u0442\u0440\u043e\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0445 \u0440\u0430\u0431\u043e\u0442 \u043d\u0430 \u043e\u0441\u043d\u043e\u0432\u0435 \u0440\u0435\u0441\u0443\u0440\u0441\u043d\u043e\u0439 \u043c\u043e\u0434\u0435\u043b\u0438. '
            '\u0420\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442\u043e\u043c \u044d\u0442\u0438\u0445 \u0443\u0441\u0438\u043b\u0438\u0439 \u0441\u0442\u0430\u043b\u0438 open-source \u0438\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442\u044b \u2014 '
            + a(CAD_URL, '\u043a\u043e\u043d\u0432\u0435\u0440\u0442\u0435\u0440\u044b \u0434\u0430\u043d\u043d\u044b\u0445 DDC CAD/BIM') + ' (Revit, IFC, DWG, DGN \u2192 \u0441\u0442\u0440\u0443\u043a\u0442\u0443\u0440\u0438\u0440\u043e\u0432\u0430\u043d\u043d\u044b\u0435 '
            '\u0434\u0430\u043d\u043d\u044b\u0435), \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u044b\u0435 \u043d\u0430 GitHub, \u0438 \u043c\u043d\u043e\u0433\u043e\u044f\u0437\u044b\u0447\u043d\u0430\u044f '
            + a(CWICR_URL, '\u0431\u0430\u0437\u0430 CWICR') + ' \u0441\u0442\u0440\u043e\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0445 \u0440\u0430\u0431\u043e\u0442 \u0438 \u0440\u0435\u0441\u0443\u0440\u0441\u043e\u0432 \u2014 \u0431\u043e\u043b\u0435\u0435 55 000 \u043f\u043e\u0437\u0438\u0446\u0438\u0439 '
            '\u043d\u0430 11 \u044f\u0437\u044b\u043a\u0430\u0445, \u043e\u043f\u0443\u0431\u043b\u0438\u043a\u043e\u0432\u0430\u043d\u043d\u0430\u044f \u043a\u0430\u043a '
            + a(CWICR_URL, 'OpenConstructionEstimate-DDC-CWICR', mono=True) + '. \u0412\u0441\u0451 \u044d\u0442\u043e \u0431\u044b\u043b\u043e \u043d\u0435\u043e\u0431\u0445\u043e\u0434\u0438\u043c\u044b\u043c '
            '\u0448\u0430\u0433\u043e\u043c \u043a \u0438\u0434\u0435\u0435, \u043a\u043e\u0442\u043e\u0440\u0443\u044e \u044f \u043d\u0435\u0441\u0443 \u0443\u0436\u0435 \u0434\u0435\u0441\u044f\u0442\u044c \u043b\u0435\u0442 \u2014 \u0441\u043e\u0437\u0434\u0430\u0442\u044c open-source ERP \u0434\u043b\u044f '
            '\u0441\u0442\u0440\u043e\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u0439 \u043e\u0442\u0440\u0430\u0441\u043b\u0438. \u041c\u043d\u043e\u0433\u0438\u0435, \u043a\u0442\u043e \u0441\u043f\u0440\u0430\u0448\u0438\u0432\u0430\u043b \u043c\u0435\u043d\u044f, \u043a\u0430\u043a\u0438\u0435 \u0438\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442\u044b \u044f '
            '\u0440\u0430\u0437\u0440\u0430\u0431\u0430\u0442\u044b\u0432\u0430\u044e, \u043d\u0435\u0438\u0437\u0431\u0435\u0436\u043d\u043e \u0441\u043b\u044b\u0448\u0430\u043b\u0438 \u043c\u043e\u0438 \u0438\u0434\u0435\u0438 \u043e \u0441\u043e\u0437\u0434\u0430\u043d\u0438\u0438 \u043e\u0442\u043a\u0440\u044b\u0442\u043e\u0439 \u043c\u043e\u0434\u0443\u043b\u044c\u043d\u043e\u0439 ERP-\u0441\u0438\u0441\u0442\u0435\u043c\u044b.'
        ),
        'para4': (
            '\u0418 \u043b\u0438\u0448\u044c \u0432 \u044d\u0442\u043e\u043c \u0433\u043e\u0434\u0443 \u043f\u043e\u044f\u0432\u043b\u0435\u043d\u0438\u0435 \u0438\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442\u043e\u0432 \u0438\u0441\u043a\u0443\u0441\u0441\u0442\u0432\u0435\u043d\u043d\u043e\u0433\u043e \u0438\u043d\u0442\u0435\u043b\u043b\u0435\u043a\u0442\u0430 \u043f\u043e\u0437\u0432\u043e\u043b\u0438\u043b\u043e \u043e\u0431\u044a\u0435\u0434\u0438\u043d\u0438\u0442\u044c '
            '\u043e\u0433\u0440\u043e\u043c\u043d\u044b\u0439 \u043f\u043b\u0430\u0441\u0442 \u0437\u043d\u0430\u043d\u0438\u0439, \u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u043e\u043a \u0438 \u0440\u0435\u0448\u0435\u043d\u0438\u0439, \u043d\u0430\u043a\u043e\u043f\u043b\u0435\u043d\u043d\u044b\u0445 \u0437\u0430 \u0434\u0435\u0441\u044f\u0442\u044c \u043b\u0435\u0442, \u0432 \u0435\u0434\u0438\u043d\u0443\u044e \u043f\u043b\u0430\u0442\u0444\u043e\u0440\u043c\u0443. '
            '\u0421\u0435\u0433\u043e\u0434\u043d\u044f \u044f \u043f\u0440\u0435\u0434\u0441\u0442\u0430\u0432\u043b\u044f\u044e \u0435\u0451 \u0441\u043e\u043e\u0431\u0449\u0435\u0441\u0442\u0432\u0443 \u2014 \u0432 \u043d\u0430\u0434\u0435\u0436\u0434\u0435, \u0447\u0442\u043e \u043e\u043d\u0430 \u043f\u043e\u043c\u043e\u0436\u0435\u0442 \u043a\u043e\u043c\u043f\u0430\u043d\u0438\u044f\u043c \u0438 \u0438\u0445 '
            '\u0437\u0430\u043a\u0430\u0437\u0447\u0438\u043a\u0430\u043c \u0432 \u0441\u0442\u0440\u043e\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u0439 \u043e\u0442\u0440\u0430\u0441\u043b\u0438 \u043f\u0435\u0440\u0435\u0439\u0442\u0438 \u043a \u0443\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u044e \u0441\u0442\u0440\u043e\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u043c\u0438 \u043f\u0440\u043e\u0435\u043a\u0442\u0430\u043c\u0438 \u043d\u0430 '
            '\u0443\u0440\u043e\u0432\u043d\u0435 \u043f\u0440\u043e\u0446\u0435\u0441\u0441\u043e\u0432. \u0418\u043c\u0435\u043d\u043d\u043e \u044d\u0442\u043e\u0442 \u043f\u0435\u0440\u0435\u0445\u043e\u0434, \u044f \u0443\u0431\u0435\u0436\u0434\u0451\u043d, \u0441\u043f\u043e\u0441\u043e\u0431\u0435\u043d \u043d\u0430\u043a\u043e\u043d\u0435\u0446 \u0440\u0430\u0441\u043a\u0440\u044b\u0442\u044c \u043f\u043e\u0442\u0435\u043d\u0446\u0438\u0430\u043b '
            '\u043f\u0440\u043e\u0438\u0437\u0432\u043e\u0434\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u0441\u0442\u0438 \u0438 \u043a\u0430\u0447\u0435\u0441\u0442\u0432\u0430 \u0434\u0430\u043d\u043d\u044b\u0445 \u0432 \u043e\u0442\u0440\u0430\u0441\u043b\u0438, \u043a\u043e\u0442\u043e\u0440\u0430\u044f \u0441\u043b\u0438\u0448\u043a\u043e\u043c \u0434\u043e\u043b\u0433\u043e \u0441\u0434\u0435\u0440\u0436\u0438\u0432\u0430\u043b\u0430\u0441\u044c '
            '\u0444\u0440\u0430\u0433\u043c\u0435\u043d\u0442\u0438\u0440\u043e\u0432\u0430\u043d\u043d\u044b\u043c\u0438 \u0440\u0435\u0448\u0435\u043d\u0438\u044f\u043c\u0438 \u0438 \u0440\u0430\u0437\u0440\u043e\u0437\u043d\u0435\u043d\u043d\u044b\u043c\u0438 \u043f\u043e\u0434\u0445\u043e\u0434\u0430\u043c\u0438.'
        ),
        'pull': (
            '\u041f\u0440\u043e\u0433\u0440\u0435\u0441\u0441 \u0440\u043e\u0436\u0434\u0430\u0435\u0442\u0441\u044f \u0432 \u0434\u0438\u0430\u043b\u043e\u0433\u0435 \u2014 \u0432 \u0441\u0442\u043e\u043b\u043a\u043d\u043e\u0432\u0435\u043d\u0438\u0438 \u0442\u043e\u0447\u0435\u043a \u0437\u0440\u0435\u043d\u0438\u044f \u0438 \u043e\u0442\u043a\u0440\u044b\u0442\u043e\u0441\u0442\u0438 '
            '\u043a \u043d\u043e\u0432\u044b\u043c \u043f\u043e\u0434\u0445\u043e\u0434\u0430\u043c. \u0411\u0443\u0434\u0443 \u043f\u0440\u0438\u0437\u043d\u0430\u0442\u0435\u043b\u0435\u043d, \u0435\u0441\u043b\u0438 \u0432\u044b \u043f\u0440\u0438\u043c\u0435\u0442\u0435 \u0443\u0447\u0430\u0441\u0442\u0438\u0435 \u0432 \u044d\u0442\u043e\u043c \u0440\u0430\u0437\u0433\u043e\u0432\u043e\u0440\u0435 \u2014 '
            '\u043e\u0431 \u043d\u0435\u0438\u0437\u0431\u0435\u0436\u043d\u043e\u0439 \u0443\u0431\u0435\u0440\u0438\u0437\u0430\u0446\u0438\u0438 \u0441\u0442\u0440\u043e\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u0439 \u043e\u0442\u0440\u0430\u0441\u043b\u0438 \u0438 \u043f\u0440\u043e\u0437\u0440\u0430\u0447\u043d\u043e\u0441\u0442\u0438 \u043f\u0440\u043e\u0446\u0435\u0441\u0441\u043e\u0432 '
            '\u043e\u0446\u0435\u043d\u043a\u0438 \u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u0438 \u0438 \u0441\u0440\u043e\u043a\u043e\u0432 \u0432 \u0441\u0442\u0440\u043e\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0445 \u043f\u0440\u043e\u0435\u043a\u0442\u0430\u0445.'
        ),
    },
}

for loc, blk in content.items():
    p = f"C:/Users/Artem Boiko/Desktop/CodeProjects/ERP_26030500/website-marketing/pro/breeze/locales/{loc}.json"
    d = json.load(open(p, encoding='utf-8'))
    v = d.setdefault('voices', {})
    for k, val in blk.items():
        v[k] = val
    json.dump(d, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print('updated', loc)
