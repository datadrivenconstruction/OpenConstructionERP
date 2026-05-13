# Mongolian Translation Guide

This guide defines preferred Mongolian terminology and translation rules for OpenConstructionERP.
Use it when editing locale files manually or reviewing machine-translated output.

## Preferred Terms

| English | Preferred Mongolian | Avoid |
|---|---|---|
| position (BOQ line item) | байрлал | албан тушаал, пост |
| positions | байрлалууд | албан тушаалууд |
| unit rate | нэгж ханш | үнэлгээ |
| overhead | нэмэгдэл зардал | толгой дээгүүр |
| setup wizard | тохиргооны заавар | setup wizard |
| common data environment | нэгдсэн өгөгдлийн орчин | common data environment |
| BIM viewer | BIM харагч | BIM viewer |
| standard deviation | стандарт хазайлт | std dev |
| tendering & bids | тендер ба үнийн санал | тендер ба тендер |
| award decision | гэрээ олгох шийдвэр | шагналын шийдвэр |
| opt-in | зөвхөн идэвхжүүлсэн үед | үргэлж хамрагддаг |

## Product Rules

- Keep product names and standards in English when they are identifiers: `OpenConstructionERP`, `BOQ`, `BIM`, `GAEB XML`, `LanceDB`, `Qdrant`, `SPI`, `CPI`.
- Translate UI labels and helper text, but do not over-localize technical acronyms that users need to match with documentation.
- Prefer concise UI wording over literal sentence structure copied from English.
- For buttons and action labels, use direct imperative wording such as `Нэмэх`, `Хадгалах`, `Нээх`, `BOQ-д нэмэх`.

## Placeholder Rules

- Preserve every placeholder exactly: `{{count}}`, `{{total}}`, `{position}`, `%s`, `%(name)s`, HTML tags.
- Placeholders may move within the sentence for natural Mongolian word order, but none may be removed or renamed.
- If a translated sentence becomes awkward, rewrite the sentence around the placeholders rather than translating word-for-word.

## Style Rules

- Prefer natural Mongolian product language over literal machine output.
- Use `байрлал` for BOQ rows, not employment/job terminology.
- Use `ханш` for pricing/rate language unless the UI explicitly means a broader evaluation or rating.
- Avoid leading fragments such as `дээр нээх`, `нэмнэ үү`, or mixed word order caused by machine translation.
- Avoid duplicated concepts such as `Тендер ба тендер`.

## Review Checklist

- Check that no placeholder tokens were lost.
- Check that no raw mask tokens like `__PH_0__` or `[[PH_0]]` appear in output.
- Check visible UI strings for English leftovers unless they are intentional product or standards names.
- Check that domain terms remain consistent across frontend and backend locale files.