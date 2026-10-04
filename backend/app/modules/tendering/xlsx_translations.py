# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""String catalogue for the tender workbooks: the bill sent to bidders and the price comparison.

Both sheets travel outside the company: the bill to subcontractors in any
country, the comparison to whoever signs the award. Their fixed text (column
headers, the footer rows, the legend) lives here, and the language is picked by
the shared rule in :mod:`app.core.document_locale`: ``?locale=`` first, then the
first ``Accept-Language`` tag the catalogue has, then English. The route
declares the language it actually wrote in ``Content-Language``.

A spreadsheet has no font problem, unlike the PDF catalogues, so the set of
languages is limited only by what is translated here. Regional variants
(``pt-BR``, ``es-MX``) read their base language. Numbers carry no text at all:
Excel formats them in the reader's own regional settings.
"""

from __future__ import annotations

from app.core.document_locale import resolve_document_locale, translate

__all__ = ["DEFAULT_XLSX_LOCALE", "SUPPORTED_XLSX_LOCALES", "resolve_xlsx_locale", "xt"]

DEFAULT_XLSX_LOCALE = "en"

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "comparison_title": "Price comparison",
        "comparison_sheet": "Comparison",
        "bidder_title": "Bill for pricing",
        "bidder_sheet": "Bill",
        "project": "Project",
        "package": "Package",
        "currency": "Currency",
        "date": "Date",
        "return_by": "Return by",
        "item": "Item",
        "description": "Description",
        "unit": "Unit",
        "quantity": "Quantity",
        "unit_price": "Unit price",
        "line_total": "Line total",
        "own_estimate": "Own estimate",
        "not_priced": "not priced",
        "sum_priced_lines": "Sum of priced lines",
        "bid_total": "Bid total as submitted",
        "lines_priced": "Lines priced",
        "lines_priced_value": "{priced} of {total}",
        "deviation": "Deviation from own estimate",
        "not_comparable": "n/a",
        "other_currency": "Quoted in {currency}, not ranked against bids in {reporting}.",
        "legend": "Legend",
        "legend_lowest": "Green: the lowest unit price on the line.",
        "legend_high": "▲ red: more than {pct}% above the median price on the line.",
        "legend_low": "▼ amber: more than {pct}% below the median price on the line.",
        "legend_missing": '"{marker}": the bidder gave no price for the line.',
        "legend_incomplete": 'A bid with unpriced lines is marked in "Lines priced" and is not ranked lowest on its total.',
        "legend_totals": (
            "The bid total is the figure the bidder submitted; it can differ from the sum of its priced lines."
        ),
        "bidder": "Bidder",
        "bidder_note": "Bidder note",
        "reference": "Reference (do not edit)",
        "total": "Total",
        "instructions": (
            "Enter a unit price for each line in the yellow cells. Quantities and descriptions are fixed, "
            "line totals and the total calculate themselves. Leave a cell empty if you do not price the line."
        ),
    },
    "de": {
        "comparison_title": "Preisspiegel",
        "comparison_sheet": "Preisspiegel",
        "bidder_title": "Leistungsverzeichnis zur Preiseintragung",
        "bidder_sheet": "LV",
        "project": "Projekt",
        "package": "Vergabeeinheit",
        "currency": "Währung",
        "date": "Datum",
        "return_by": "Abgabe bis",
        "item": "Pos.",
        "description": "Beschreibung",
        "unit": "Einheit",
        "quantity": "Menge",
        "unit_price": "Einheitspreis",
        "line_total": "Gesamtbetrag",
        "own_estimate": "Eigene Kalkulation",
        "not_priced": "nicht angeboten",
        "sum_priced_lines": "Summe der bepreisten Positionen",
        "bid_total": "Angebotssumme laut Angebot",
        "lines_priced": "Bepreiste Positionen",
        "lines_priced_value": "{priced} von {total}",
        "deviation": "Abweichung von der eigenen Kalkulation",
        "not_comparable": "k. A.",
        "other_currency": "In {currency} angeboten, nicht mit Angeboten in {reporting} verglichen.",
        "legend": "Legende",
        "legend_lowest": "Grün: niedrigster Einheitspreis der Position.",
        "legend_high": "▲ rot: mehr als {pct} % über dem Median der Position.",
        "legend_low": "▼ gelb: mehr als {pct} % unter dem Median der Position.",
        "legend_missing": '"{marker}": für diese Position hat der Bieter keinen Preis abgegeben.',
        "legend_incomplete": 'Ein Angebot mit nicht angebotenen Positionen ist bei "Bepreiste Positionen" markiert und wird bei der Angebotssumme nicht als niedrigstes gewertet.',
        "legend_totals": (
            "Die Angebotssumme ist der vom Bieter genannte Betrag; "
            "sie kann von der Summe der bepreisten Positionen abweichen."
        ),
        "bidder": "Bieter",
        "bidder_note": "Bemerkung des Bieters",
        "reference": "Referenz (nicht ändern)",
        "total": "Summe",
        "instructions": (
            "Tragen Sie für jede Position einen Einheitspreis in die gelben Zellen ein. Mengen und Texte "
            "sind fest, Gesamtbeträge und Summe rechnen sich selbst. Lassen Sie die Zelle leer, wenn Sie "
            "die Position nicht anbieten."
        ),
    },
    "fr": {
        "comparison_title": "Comparatif des offres",
        "comparison_sheet": "Comparatif",
        "bidder_title": "Bordereau à chiffrer",
        "bidder_sheet": "Bordereau",
        "project": "Projet",
        "package": "Lot",
        "currency": "Devise",
        "date": "Date",
        "return_by": "Remise avant le",
        "item": "N°",
        "description": "Désignation",
        "unit": "Unité",
        "quantity": "Quantité",
        "unit_price": "Prix unitaire",
        "line_total": "Montant",
        "own_estimate": "Estimation interne",
        "not_priced": "non chiffré",
        "sum_priced_lines": "Somme des lignes chiffrées",
        "bid_total": "Montant de l'offre remise",
        "lines_priced": "Lignes chiffrées",
        "lines_priced_value": "{priced} sur {total}",
        "deviation": "Écart par rapport à l'estimation interne",
        "not_comparable": "n.d.",
        "other_currency": "Offre en {currency}, non classée face aux offres en {reporting}.",
        "legend": "Légende",
        "legend_lowest": "Vert : prix unitaire le plus bas de la ligne.",
        "legend_high": "▲ rouge : plus de {pct} % au-dessus du prix médian de la ligne.",
        "legend_low": "▼ orange : plus de {pct} % en dessous du prix médian de la ligne.",
        "legend_missing": "« {marker} » : l'entreprise n'a pas donné de prix pour la ligne.",
        "legend_incomplete": "Une offre avec des lignes non chiffrées est signalée dans « Lignes chiffrées » et n'est pas classée la moins chère sur son montant.",
        "legend_totals": (
            "Le montant de l'offre est celui remis par l'entreprise ; "
            "il peut différer de la somme de ses lignes chiffrées."
        ),
        "bidder": "Entreprise",
        "bidder_note": "Remarque de l'entreprise",
        "reference": "Référence (ne pas modifier)",
        "total": "Total",
        "instructions": (
            "Saisissez un prix unitaire pour chaque ligne dans les cellules jaunes. Les quantités et les "
            "désignations sont fixes, les montants et le total se calculent seuls. Laissez la cellule vide "
            "si vous ne chiffrez pas la ligne."
        ),
    },
    "es": {
        "comparison_title": "Comparativo de ofertas",
        "comparison_sheet": "Comparativo",
        "bidder_title": "Presupuesto para cotizar",
        "bidder_sheet": "Presupuesto",
        "project": "Proyecto",
        "package": "Paquete",
        "currency": "Moneda",
        "date": "Fecha",
        "return_by": "Entregar antes de",
        "item": "Partida",
        "description": "Descripción",
        "unit": "Unidad",
        "quantity": "Cantidad",
        "unit_price": "Precio unitario",
        "line_total": "Importe",
        "own_estimate": "Estimación propia",
        "not_priced": "sin precio",
        "sum_priced_lines": "Suma de partidas con precio",
        "bid_total": "Total de la oferta presentada",
        "lines_priced": "Partidas con precio",
        "lines_priced_value": "{priced} de {total}",
        "deviation": "Desviación respecto a la estimación propia",
        "not_comparable": "n/d",
        "other_currency": "Cotizada en {currency}, no se compara con las ofertas en {reporting}.",
        "legend": "Leyenda",
        "legend_lowest": "Verde: el precio unitario más bajo de la partida.",
        "legend_high": "▲ rojo: más de un {pct} % por encima de la mediana de la partida.",
        "legend_low": "▼ ámbar: más de un {pct} % por debajo de la mediana de la partida.",
        "legend_missing": '"{marker}": el licitador no dio precio para la partida.',
        "legend_incomplete": 'Una oferta con partidas sin precio se marca en "Partidas con precio" y no se clasifica como la más baja por su total.',
        "legend_totals": (
            "El total de la oferta es la cifra presentada por el licitador; "
            "puede diferir de la suma de sus partidas con precio."
        ),
        "bidder": "Licitador",
        "bidder_note": "Nota del licitador",
        "reference": "Referencia (no editar)",
        "total": "Total",
        "instructions": (
            "Introduzca un precio unitario para cada partida en las celdas amarillas. Las cantidades y "
            "descripciones son fijas, los importes y el total se calculan solos. Deje la celda vacía si no "
            "cotiza la partida."
        ),
    },
    "it": {
        "comparison_title": "Confronto delle offerte",
        "comparison_sheet": "Confronto",
        "bidder_title": "Computo da quotare",
        "bidder_sheet": "Computo",
        "project": "Progetto",
        "package": "Lotto",
        "currency": "Valuta",
        "date": "Data",
        "return_by": "Consegna entro",
        "item": "N.",
        "description": "Descrizione",
        "unit": "Unità",
        "quantity": "Quantità",
        "unit_price": "Prezzo unitario",
        "line_total": "Importo",
        "own_estimate": "Stima interna",
        "not_priced": "non quotato",
        "sum_priced_lines": "Somma delle voci quotate",
        "bid_total": "Importo dell'offerta presentata",
        "lines_priced": "Voci quotate",
        "lines_priced_value": "{priced} di {total}",
        "deviation": "Scostamento dalla stima interna",
        "not_comparable": "n.d.",
        "other_currency": "Offerta in {currency}, non confrontata con le offerte in {reporting}.",
        "legend": "Legenda",
        "legend_lowest": "Verde: il prezzo unitario più basso della voce.",
        "legend_high": "▲ rosso: oltre il {pct}% sopra la mediana della voce.",
        "legend_low": "▼ ambra: oltre il {pct}% sotto la mediana della voce.",
        "legend_missing": '"{marker}": l\'offerente non ha indicato un prezzo per la voce.',
        "legend_incomplete": 'Un\'offerta con voci non quotate è segnalata in "Voci quotate" e non è considerata la più bassa sul totale.',
        "legend_totals": (
            "L'importo dell'offerta è quello indicato dall'offerente; può differire dalla somma delle voci quotate."
        ),
        "bidder": "Offerente",
        "bidder_note": "Nota dell'offerente",
        "reference": "Riferimento (non modificare)",
        "total": "Totale",
        "instructions": (
            "Inserire un prezzo unitario per ogni voce nelle celle gialle. Quantità e descrizioni sono "
            "fisse, importi e totale si calcolano da soli. Lasciare la cella vuota se non si quota la voce."
        ),
    },
    "nl": {
        "comparison_title": "Prijsvergelijking",
        "comparison_sheet": "Vergelijking",
        "bidder_title": "Bestek om te prijzen",
        "bidder_sheet": "Bestek",
        "project": "Project",
        "package": "Perceel",
        "currency": "Valuta",
        "date": "Datum",
        "return_by": "Indienen voor",
        "item": "Post",
        "description": "Omschrijving",
        "unit": "Eenheid",
        "quantity": "Hoeveelheid",
        "unit_price": "Eenheidsprijs",
        "line_total": "Bedrag",
        "own_estimate": "Eigen raming",
        "not_priced": "niet geprijsd",
        "sum_priced_lines": "Som van geprijsde posten",
        "bid_total": "Inschrijfsom zoals ingediend",
        "lines_priced": "Geprijsde posten",
        "lines_priced_value": "{priced} van {total}",
        "deviation": "Afwijking van eigen raming",
        "not_comparable": "n.v.t.",
        "other_currency": "Geprijsd in {currency}, niet vergeleken met inschrijvingen in {reporting}.",
        "legend": "Legenda",
        "legend_lowest": "Groen: de laagste eenheidsprijs van de post.",
        "legend_high": "▲ rood: meer dan {pct}% boven de mediaan van de post.",
        "legend_low": "▼ oranje: meer dan {pct}% onder de mediaan van de post.",
        "legend_missing": '"{marker}": de inschrijver gaf geen prijs voor de post.',
        "legend_incomplete": 'Een inschrijving met niet-geprijsde posten is gemarkeerd bij "Geprijsde posten" en telt niet als laagste op het totaal.',
        "legend_totals": (
            "De inschrijfsom is het bedrag dat de inschrijver opgaf; "
            "het kan afwijken van de som van de geprijsde posten."
        ),
        "bidder": "Inschrijver",
        "bidder_note": "Opmerking inschrijver",
        "reference": "Referentie (niet wijzigen)",
        "total": "Totaal",
        "instructions": (
            "Vul voor elke post een eenheidsprijs in de gele cellen in. Hoeveelheden en omschrijvingen "
            "liggen vast, bedragen en totaal rekenen zichzelf uit. Laat de cel leeg als u de post niet prijst."
        ),
    },
    "pl": {
        "comparison_title": "Porównanie ofert",
        "comparison_sheet": "Porównanie",
        "bidder_title": "Przedmiar do wyceny",
        "bidder_sheet": "Przedmiar",
        "project": "Projekt",
        "package": "Pakiet",
        "currency": "Waluta",
        "date": "Data",
        "return_by": "Termin złożenia",
        "item": "Poz.",
        "description": "Opis",
        "unit": "Jedn.",
        "quantity": "Ilość",
        "unit_price": "Cena jednostkowa",
        "line_total": "Wartość",
        "own_estimate": "Kosztorys własny",
        "not_priced": "brak ceny",
        "sum_priced_lines": "Suma wycenionych pozycji",
        "bid_total": "Wartość oferty wg oferenta",
        "lines_priced": "Wycenione pozycje",
        "lines_priced_value": "{priced} z {total}",
        "deviation": "Odchylenie od kosztorysu własnego",
        "not_comparable": "b.d.",
        "other_currency": "Oferta w {currency}, nieporównywana z ofertami w {reporting}.",
        "legend": "Legenda",
        "legend_lowest": "Zielony: najniższa cena jednostkowa w pozycji.",
        "legend_high": "▲ czerwony: ponad {pct}% powyżej mediany pozycji.",
        "legend_low": "▼ żółty: ponad {pct}% poniżej mediany pozycji.",
        "legend_missing": "„{marker}”: oferent nie podał ceny dla pozycji.",
        "legend_incomplete": "Oferta z pozycjami bez ceny jest oznaczona w „Wycenione pozycje” i nie jest uznawana za najtańszą pod względem wartości.",
        "legend_totals": (
            "Wartość oferty to kwota podana przez oferenta; może się różnić od sumy wycenionych pozycji."
        ),
        "bidder": "Oferent",
        "bidder_note": "Uwagi oferenta",
        "reference": "Identyfikator (nie zmieniać)",
        "total": "Razem",
        "instructions": (
            "Wpisz cenę jednostkową dla każdej pozycji w żółtych komórkach. Ilości i opisy są stałe, "
            "wartości i suma liczą się same. Pozostaw komórkę pustą, jeśli nie wyceniasz pozycji."
        ),
    },
    "pt": {
        "comparison_title": "Mapa comparativo de propostas",
        "comparison_sheet": "Comparativo",
        "bidder_title": "Orçamento para cotação",
        "bidder_sheet": "Orçamento",
        "project": "Projeto",
        "package": "Pacote",
        "currency": "Moeda",
        "date": "Data",
        "return_by": "Entregar até",
        "item": "Item",
        "description": "Descrição",
        "unit": "Unidade",
        "quantity": "Quantidade",
        "unit_price": "Preço unitário",
        "line_total": "Valor",
        "own_estimate": "Estimativa própria",
        "not_priced": "sem preço",
        "sum_priced_lines": "Soma dos itens com preço",
        "bid_total": "Valor total da proposta apresentada",
        "lines_priced": "Itens com preço",
        "lines_priced_value": "{priced} de {total}",
        "deviation": "Desvio em relação à estimativa própria",
        "not_comparable": "n/d",
        "other_currency": "Cotada em {currency}, não comparada com propostas em {reporting}.",
        "legend": "Legenda",
        "legend_lowest": "Verde: o menor preço unitário do item.",
        "legend_high": "▲ vermelho: mais de {pct}% acima da mediana do item.",
        "legend_low": "▼ âmbar: mais de {pct}% abaixo da mediana do item.",
        "legend_missing": '"{marker}": o proponente não indicou preço para o item.',
        "legend_incomplete": 'Uma proposta com itens sem preço é marcada em "Itens com preço" e não é classificada como a menor pelo total.',
        "legend_totals": (
            "O valor da proposta é o informado pelo proponente; pode diferir da soma dos itens com preço."
        ),
        "bidder": "Proponente",
        "bidder_note": "Observação do proponente",
        "reference": "Referência (não editar)",
        "total": "Total",
        "instructions": (
            "Informe um preço unitário para cada item nas células amarelas. Quantidades e descrições são "
            "fixas, valores e total calculam-se sozinhos. Deixe a célula vazia se não cotar o item."
        ),
    },
    "cs": {
        "comparison_title": "Porovnání nabídek",
        "comparison_sheet": "Porovnání",
        "bidder_title": "Výkaz výměr k ocenění",
        "bidder_sheet": "Výkaz",
        "project": "Projekt",
        "package": "Balíček",
        "currency": "Měna",
        "date": "Datum",
        "return_by": "Odevzdat do",
        "item": "Pol.",
        "description": "Popis",
        "unit": "MJ",
        "quantity": "Množství",
        "unit_price": "Jednotková cena",
        "line_total": "Cena celkem",
        "own_estimate": "Vlastní rozpočet",
        "not_priced": "neoceněno",
        "sum_priced_lines": "Součet oceněných položek",
        "bid_total": "Nabídková cena dle nabídky",
        "lines_priced": "Oceněné položky",
        "lines_priced_value": "{priced} z {total}",
        "deviation": "Odchylka od vlastního rozpočtu",
        "not_comparable": "n/a",
        "other_currency": "Oceněno v {currency}, neporovnáno s nabídkami v {reporting}.",
        "legend": "Legenda",
        "legend_lowest": "Zelená: nejnižší jednotková cena položky.",
        "legend_high": "▲ červená: o více než {pct} % nad mediánem položky.",
        "legend_low": "▼ žlutá: o více než {pct} % pod mediánem položky.",
        "legend_missing": "„{marker}“: uchazeč u položky neuvedl cenu.",
        "legend_incomplete": "Nabídka s neoceněnými položkami je označena v „Oceněné položky“ a podle celkové ceny se nehodnotí jako nejnižší.",
        "legend_totals": ("Nabídková cena je částka uvedená uchazečem; může se lišit od součtu oceněných položek."),
        "bidder": "Uchazeč",
        "bidder_note": "Poznámka uchazeče",
        "reference": "Reference (neměnit)",
        "total": "Celkem",
        "instructions": (
            "Vyplňte jednotkovou cenu každé položky do žlutých buněk. Množství a popisy jsou pevné, ceny "
            "celkem a součet se počítají samy. Pokud položku neoceňujete, nechte buňku prázdnou."
        ),
    },
    "ru": {
        "comparison_title": "Сравнение предложений",
        "comparison_sheet": "Сравнение",
        "bidder_title": "Ведомость объёмов для оценки",
        "bidder_sheet": "Ведомость",
        "project": "Проект",
        "package": "Пакет",
        "currency": "Валюта",
        "date": "Дата",
        "return_by": "Подать до",
        "item": "№",
        "description": "Наименование",
        "unit": "Ед. изм.",
        "quantity": "Количество",
        "unit_price": "Цена за единицу",
        "line_total": "Стоимость",
        "own_estimate": "Собственная смета",
        "not_priced": "нет цены",
        "sum_priced_lines": "Сумма оценённых позиций",
        "bid_total": "Сумма предложения по заявке",
        "lines_priced": "Оценено позиций",
        "lines_priced_value": "{priced} из {total}",
        "deviation": "Отклонение от собственной сметы",
        "not_comparable": "н/д",
        "other_currency": "Цены в {currency}, не сравниваются с предложениями в {reporting}.",
        "legend": "Обозначения",
        "legend_lowest": "Зелёный: самая низкая цена за единицу в позиции.",
        "legend_high": "▲ красный: более чем на {pct}% выше медианы по позиции.",
        "legend_low": "▼ жёлтый: более чем на {pct}% ниже медианы по позиции.",
        "legend_missing": "«{marker}»: участник не указал цену по позиции.",
        "legend_incomplete": "Предложение с позициями без цены отмечено в строке «Оценено позиций» и не считается самым дешёвым по сумме.",
        "legend_totals": ("Сумма предложения указана участником и может отличаться от суммы оценённых позиций."),
        "bidder": "Участник",
        "bidder_note": "Примечание участника",
        "reference": "Идентификатор (не изменять)",
        "total": "Итого",
        "instructions": (
            "Укажите цену за единицу для каждой позиции в жёлтых ячейках. Количества и наименования "
            "зафиксированы, стоимость и итог считаются сами. Оставьте ячейку пустой, если не оцениваете позицию."
        ),
    },
    "uk": {
        "comparison_title": "Порівняння пропозицій",
        "comparison_sheet": "Порівняння",
        "bidder_title": "Відомість обсягів для оцінки",
        "bidder_sheet": "Відомість",
        "project": "Проєкт",
        "package": "Пакет",
        "currency": "Валюта",
        "date": "Дата",
        "return_by": "Подати до",
        "item": "№",
        "description": "Найменування",
        "unit": "Од. вим.",
        "quantity": "Кількість",
        "unit_price": "Ціна за одиницю",
        "line_total": "Вартість",
        "own_estimate": "Власний кошторис",
        "not_priced": "немає ціни",
        "sum_priced_lines": "Сума оцінених позицій",
        "bid_total": "Сума пропозиції за заявкою",
        "lines_priced": "Оцінено позицій",
        "lines_priced_value": "{priced} з {total}",
        "deviation": "Відхилення від власного кошторису",
        "not_comparable": "н/д",
        "other_currency": "Ціни в {currency}, не порівнюються з пропозиціями в {reporting}.",
        "legend": "Позначення",
        "legend_lowest": "Зелений: найнижча ціна за одиницю в позиції.",
        "legend_high": "▲ червоний: більш ніж на {pct}% вище медіани позиції.",
        "legend_low": "▼ жовтий: більш ніж на {pct}% нижче медіани позиції.",
        "legend_missing": "«{marker}»: учасник не вказав ціну для позиції.",
        "legend_incomplete": "Пропозиція з позиціями без ціни позначена в рядку «Оцінено позицій» і не вважається найдешевшою за сумою.",
        "legend_totals": ("Сума пропозиції вказана учасником і може відрізнятися від суми оцінених позицій."),
        "bidder": "Учасник",
        "bidder_note": "Примітка учасника",
        "reference": "Ідентифікатор (не змінювати)",
        "total": "Разом",
        "instructions": (
            "Вкажіть ціну за одиницю для кожної позиції в жовтих клітинках. Кількості та найменування "
            "зафіксовані, вартість і підсумок рахуються самі. Залиште клітинку порожньою, якщо не оцінюєте позицію."
        ),
    },
    "zh": {
        "comparison_title": "报价对比表",
        "comparison_sheet": "报价对比",
        "bidder_title": "待报价工程量清单",
        "bidder_sheet": "清单",
        "project": "项目",
        "package": "标段",
        "currency": "币种",
        "date": "日期",
        "return_by": "截止日期",
        "item": "编号",
        "description": "项目名称",
        "unit": "单位",
        "quantity": "工程量",
        "unit_price": "综合单价",
        "line_total": "合价",
        "own_estimate": "自有预算",
        "not_priced": "未报价",
        "sum_priced_lines": "已报价项合计",
        "bid_total": "投标报价总额",
        "lines_priced": "已报价项",
        "lines_priced_value": "{priced} / {total}",
        "deviation": "与自有预算偏差",
        "not_comparable": "不适用",
        "other_currency": "以 {currency} 报价，不与 {reporting} 报价比较。",
        "legend": "图例",
        "legend_lowest": "绿色：该项最低单价。",
        "legend_high": "▲ 红色：高于该项中位价 {pct}% 以上。",
        "legend_low": "▼ 黄色：低于该项中位价 {pct}% 以上。",
        "legend_missing": "“{marker}”：投标人未对该项报价。",
        "legend_incomplete": "含未报价项的投标在“已报价项”中标出，其总额不参与最低价排名。",
        "legend_totals": "投标报价总额为投标人提交的金额，可能与已报价项合计不同。",
        "bidder": "投标人",
        "bidder_note": "投标人备注",
        "reference": "标识（请勿修改）",
        "total": "合计",
        "instructions": (
            "请在黄色单元格中填写每一项的单价。工程量和项目名称不可修改，合价和合计自动计算。不报价的项请留空。"
        ),
    },
}

SUPPORTED_XLSX_LOCALES: tuple[str, ...] = tuple(_STRINGS)


def resolve_xlsx_locale(locale_param: str | None, accept_language: str | None) -> str:
    """Pick the workbook language for an HTTP request.

    Args:
        locale_param: Explicit ``?locale=`` query value, if any.
        accept_language: Raw ``Accept-Language`` header value, if any.

    Returns:
        A member of :data:`SUPPORTED_XLSX_LOCALES`. ``"en"`` for a reader who
        asked for a language the catalogue lacks, which the route must declare
        in ``Content-Language``.
    """
    return resolve_document_locale(locale_param, accept_language, SUPPORTED_XLSX_LOCALES, DEFAULT_XLSX_LOCALE)


def xt(locale: str, key: str, **params: object) -> str:
    """Resolve ``key`` for ``locale``, English when the language or the key is missing."""
    return translate(_STRINGS, locale, key, DEFAULT_XLSX_LOCALE, **params)
