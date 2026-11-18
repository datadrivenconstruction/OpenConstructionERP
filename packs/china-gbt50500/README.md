# China Construction Pack (中国建筑工程包)

A pre-configured workspace for contractors and developers pricing work in
mainland China: Simplified Chinese interface, CNY, the VAT general tax method,
Shanghai cost data, and a Shanghai office-tower demo project priced to
GB 50500-2013.

```bash
pip install -e packs/china-gbt50500
```

## What makes a Chinese bill Chinese

Four things, and each of them is a place where a bill prepared to European or
North American habits comes out wrong rather than merely unfamiliar.

**A tender price is five bills, not one.** They are summed in a fixed order:
measured works (分部分项), measure items (措施项目), other items (其他项目),
statutory charges (规费) and tax (税金). Importing a Chinese tender as a flat
list of measured works loses the whole of the preliminaries and the whole of
the statutory content. On a building job that is not a rounding difference.

**Two of those five are not competitive.** The statutory charges and the safe
and civilised construction fee are set by the rules in force and may not be
discounted to win work, because both are money that leaves the contractor for
somebody else: social insurance for the workforce, and the physical safety
provisions on site. A bid that shaves them is non-responsive, not merely
aggressive. This is the commonest single way a foreign-prepared Chinese bid is
disqualified.

**The comprehensive unit rate is comprehensive in a limited sense.** 综合单价
carries labour, materials, plant, the enterprise management fee, profit and an
agreed slice of risk. It does not carry the statutory charges and it does not
carry the tax. Reading it as an all-in rate under-reads the tender by the whole
of bills four and five.

**The quantity is net.** It is computed by the calculation code and is the same
number for every tenderer. Waste, laps, working space and battering are priced
inside the rate, not added to the quantity. A tenderer who adds waste to the
quantity has changed a number that was supposed to be identical across bids.

## The item code

Twelve digits, of which only the first nine are national.

| digits | 中文 | what it is |
|---|---|---|
| 1-2 | 工程分类顺序码 | engineering category from the appendix; 01 is buildings and decoration |
| 3-4 | 专业工程顺序码 | professional works within that category |
| 5-6 | 分部工程顺序码 | division |
| 7-9 | 分项工程项目名称顺序码 | the national item name, and the end of the fixed part |
| 10-12 | 清单项目名称顺序码 | assigned by whoever compiles the bill, 001 upward, unique within it |

`010101001001` is site clearance and grading, first occurrence in this bill.
Two bills for the same work will legitimately carry different twelve-digit
codes and identical nine-digit prefixes, which is the part that surprises
readers used to a fixed national code.

Supplementary codes (补充项目) take the form `01B001`: the two-digit category,
`B`, and a three-digit serial. Shanghai adds its own codes prefixed `沪`, which
are accepted only on a project whose site is in Shanghai (CN-SH). A code is
used once per sub-project (单项工程); the same code in two sub-projects is fine.

Every bill item also needs five elements, and the third is the one that
matters: 项目编码, 项目名称, **项目特征**, 计量单位, 工程量. The rate is
priced against the characteristics, and a settlement dispute turns on them. An
item written without them is not a priced item, it is an argument deferred.

## Which edition

Each project stores its edition on its tax profile (Projects, China tax).

- **GB/T 50500-2024**, in force 2025-09-01, is the default for a project
  created on or after that day. A tender total is four heads: 分部分项, 措施项目,
  其他项目 and 增值税. 规费 is no longer a head; provinces fold it into labour and
  the management fee. 专业工程暂估价 is priced VAT-inclusive and stays out of the
  VAT base.
- **GB 50500-2013** is what a project created before that day reads as. It
  keeps its five heads, 规费 included, and its markup stack
  (`CN_GB50500_2013`).

Nothing re-prices a stored bill. Moving a 2013 project to 2024 is a person's
choice on the tax profile; a new bill seeded afterwards takes the 2024 stack,
and the 9-digit codes carry over unchanged. Shenzhen moved its tenders on
2026-01-01, so a 2013 bill tendered there after that day is flagged
(`cn.edition_mismatch`). No other switch date is shipped until a source states
one.

Note the prefix when reading the two. The 2013 edition is **GB**, a mandatory
code. The 2024 edition is **GB/T**, a recommended standard.

## Two spellings, one standard, and they are not interchangeable

`gbt50500` is the engine rule set: the rule ids, the `standard` attribute on
the rule classes, the validation message keys, and the entry in
`validation_rule_sets`.

`gb50500` is the classification standard: what the registry calls it, what
`classification_order` hands to the section path builder, and therefore the key
a cost item's `classification` dict has to use.

The demo bills were keyed with the rule set name until 2026-08. The two rules
read them correctly and no Chinese cost item ever produced a section path,
because a missing section path is an empty string and an empty string is what
an unclassified line looks like. Bills stored before that change still
validate: the rules read either spelling.

## Tax

Priced tax-exclusive (除税价), with the VAT added as its own head. From
2026-01-01 the VAT Law and its implementing regulations apply.

| method | 中文 | rate | when |
|---|---|---|---|
| general | 一般计税方法 | 9% | construction works, input VAT credited |
| general | 一般计税方法 | 13% | goods, including goods sold with installation (from 2026-01-01) |
| general | 一般计税方法 | 6% | other services |
| simplified | 简易计税方法 | 3% | labour-only (清包工) and old projects (老项目, permit start before 2016-04-30), until 2027-12-31 |
| simplified | 简易计税方法 | 3% | employer-supplied works (甲供), only where elected before 2026-01-01 (grandfathered) |
| small taxpayer | 小规模纳税人 | 1% | 2026-01-01 to 2027-12-31 |

An election of the simplified method is kept for 36 months; the profile
refuses a change inside the lock. 甲供 materials are a bill line flagged
"supplied by employer, not invoiced": priced and taxed in the bill, deducted on
the payment application.

**预缴.** Where the site is outside the home region, tax is prepaid at the site:
(receipts - subcontract payments) / (1 + rate) x 2% (general) or 3%
(simplified). A negative base prepays nothing and carries forward. The
platform computes and reconciles; filing happens in the tax e-bureau.

**数电票.** The platform prepares the invoice data of a construction 数电票
(special-business tag 建筑服务, site location, project name) as JSON or XML for
import into the taxpayer's certified channel, and validates the 20-digit
number recorded back. It does not issue or red-letter invoices itself.

The 9 percent figure is the rate since 2019-04-01. It was 11 percent from 2016
and 10 percent from 2018-05-01, so an older bill carrying a different number is
not wrong.

## Verify against the standard

These items rest on our own reading or a secondary source. Check them against
the official text before relying on them for a tender:

- The appendix of national item codes and names under GB/T 50500-2024 and
  GB/T 50854-2024 (we ship patterns, not the appendix).
- Where each province folds 规费 (Guangdong is shipped; others are not).
- The 预缴 rates of 2% and 3% (secondary reading of MOF/STA 2026 No.14).
- Shanghai risk bands of 3/5/8 percent and the Shanghai tender switch date
  (not shipped).
- The 数电票 cross-region flag and the land-VAT project number fields.

## What ships

| | |
|---|---|
| Interface | Simplified Chinese (`zh`), English available |
| Currency | CNY |
| Tax | Not set by the pack |
| Methodology | `china`, derived from the regional markup table |
| Cost data | `cwicr-zh-shanghai` (global-market catalogue, Shanghai prices) and `cwicr-zh-china` (national Dinge base); Beijing, Shenzhen, Guangzhou and Chengdu are listed as preferred metros and arrive in marketplace updates |
| Demo project | `office-shanghai`, a 32-storey Grade A tower in Lujiazui, measured works approx. CNY 690 million |
| Engine rules | `gbt50500`: item code present, format per edition, unique per sub-project; `cn_vat`: fourteen VAT, 预缴 and 数电票 rules |
| Reference documents | seven, listed below |

## Reference documents

Read by a person, not by the engine. Each carries a `review_status` saying how
far it has been checked, because the reader is deciding whether to price a
tender against it.

| document | subject |
|---|---|
| `cn_gb50500_qingdan_bianma` | the twelve-digit item code and the five required elements |
| `cn_qingdan_wubu_jiegou` | the five bills a tender price is made of |
| `cn_zonghe_danjia` | what the comprehensive unit rate contains, and what it does not |
| `cn_gb50854_gongchengliang` | net measurement, and where the waste goes instead |
| `cn_guifei_anquanwenming` | the two fees that may not be discounted |
| `cn_zengzhishui_jianzhu` | VAT under the VAT Law: methods, elections, 预缴 |
| `cn_zhaobiao_jiesuan` | the bid ceiling, and how the price moves after award |

## How far this has been reviewed

The item code structure and the five-bill structure are derived from
GB 50500-2013 read in full for the structures it states. The remaining
documents are drawn from the published codes and from public statutory sources
and are marked as pending review by a Chinese cost engineer (造价工程师) before
they are relied on for a tender. The fee percentages offered in the onboarding
wizard are defaults for Shanghai practice and are not a substitute for the
provincial fee schedule in force, which is where the real numbers live.

Corrections are welcome at info@datadrivenconstruction.io.

## License

AGPL-3.0-or-later, the same as the platform.
