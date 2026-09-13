# Commercial License, Template

This document is a **template** for organisations that cannot accept the
AGPL-3.0 network-copyleft obligation (see §13 of the AGPL) and therefore
need a commercial licence to deploy OpenConstructionERP in a
closed-source context.

It is **not** itself a binding licence. Before any deployment under a
commercial arrangement, both parties must execute a signed agreement
based on this template with terms adapted to the specific engagement
(pricing, support tier, jurisdiction). Contact
`info@datadrivenconstruction.io` to request a final executable version.

---

## 1. Definitions

- **"Licensor"** means DataDrivenConstruction, represented by
  Artem Boiko, and any successor or assign.
- **"Licensee"** means the legal entity identified in the signed order
  form.
- **"Software"** means the OpenConstructionERP source code and binaries
  as of the version identified in the order form, plus any updates
  provided during the Subscription Term.
- **"Production Use"** means any deployment of the Software that is
  accessible to users outside the Licensee's internal IT and QA staff.
- **"Subscription Term"** means the period, starting on the Effective
  Date stated in the order form, for which the licence fee has been
  paid.

## 2. Grant

Subject to timely payment and the terms below, Licensor grants Licensee
a **non-exclusive, non-transferable, worldwide** licence during the
Subscription Term to:

1. Use the Software in Production for its own internal business or for
   providing services to its own customers;
2. Modify the Software and create derivative works;
3. Distribute the Software, in modified or unmodified form, as part of
   Licensee's own product or service, **without** being required to
   disclose the corresponding source code to third parties (this is the
   core deviation from AGPL §13).

The grant does not include the right to sublicense the Software as a
standalone product or to sell it under a name that implies it originates
from Licensor.

## 3. Restrictions

Licensee shall not:

1. Remove or alter copyright, trademark, or other proprietary notices in
   the Software;
2. Use the trademarks "OpenConstructionERP", "OpenEstimate",
   "DataDrivenConstruction", "CWICR", or related logos beyond the
   limited use described in §5;
3. Reverse-engineer or decompile compiled binaries except as permitted
   by law that cannot be contractually excluded (e.g., Directive
   2009/24/EC Art. 6 for interoperability);
4. Transfer this licence to a third party by assignment, merger, or
   change-of-control without Licensor's prior written consent (not to be
   unreasonably withheld).

## 4. Open-source components

The Software incorporates third-party open-source components listed in
the [NOTICE](NOTICE) file. Licensee must continue to comply with those
components' licences. The grant in §2 is a grant of Licensor's rights in
Licensor's own code. It is not, and cannot be, a grant of rights in code
Licensor does not own. Two kinds of copyleft component are in the
Software and they are not the same problem. §4a covers the one a
closed-source deployment has to deal with directly. §4b covers the LGPL
libraries, which are routine but should be stated rather than assumed.

## 4a. AGPL components inside the Software

**Read this section before deploying.** It is the one place where the
commercial licence does not, on its own, give a Licensee everything a
closed-source corporate deployment needs.

### What the position is

The Software depends on **PyMuPDF**, published by Artifex Software, Inc.
PyMuPDF is dual licensed: it is offered under **AGPL-3.0-or-later**, or
under a **separate commercial licence sold by Artifex**. Artifex sells
that licence actively and enforces it.

PyMuPDF is a **base dependency**. It is declared in the Software's
`[project] dependencies`, not in an optional extra, and it is present in
every artefact Licensor publishes: the Python wheel, the container image
and every desktop installer. There is no supported installation of the
Software that omits it, and no configuration switch that removes it.

This licence covers OpenConstructionERP. PyMuPDF is a separate work by a
different author, and nothing Licensor can sign changes the terms
Artifex offers it under. A Licensee who deploys the Software as shipped
is using PyMuPDF under the AGPL, whatever the terms of this Agreement
say about the rest.

### Which features are affected

A Licensee whose deployment never opens a PDF is affected in principle
only, because the package is installed rather than exercised. These are
the features that actually call it:

1. **PDF drawing takeoff, vector recognition.** Reading vector geometry
   off a drawing page to propose quantities, and counting repeated
   symbols from one selected symbol.
2. **PDF drawing takeoff, page rendering and upload handling.** Turning
   a page into an image for the raster detector and for the optional
   online AI analysis, plus page counts and text on upload.
3. **Bill of quantities import from PDF.** The page-count check that
   rejects an oversized file, and text extraction where the primary
   reader cannot cope.
4. **File search.** Indexing the text of uploaded PDFs, and rendering
   pages of scanned PDFs for OCR.
5. **Geo Hub.** Rasterizing a PDF site plan for georeferencing and map
   overlay.

Every other part of the product, including all modules that do not
handle PDFs, is outside this question.

### The Licensee's options

Three, and a Licensee should pick one deliberately rather than by
default:

**Hold an Artifex commercial licence.** Buy a PyMuPDF commercial licence
directly from Artifex Software and deploy the Software unmodified. This
is the least engineering work and keeps every feature above. It is a
separate contract, a separate fee and a separate counterparty. Licensor
is not a party to it and does not resell it.

**Accept the AGPL for PyMuPDF.** Suitable where the deployment is
genuinely internal and the Licensee is content to meet AGPL-3.0
obligations for that component, including §13 if the Software is
operated over a network for anyone outside the organisation. Many
internal deployments can live with this. It is a legal assessment for
the Licensee's own counsel, not something this Agreement decides.

**Remove PyMuPDF.** Replace it with a permissively licensed reader, or
disable the five feature groups above and drop the dependency. In
practice: page rendering, page counting and plain text extraction are
ordinary operations that pypdfium2 (BSD-3-Clause and Apache-2.0, already
installed in every deployment beneath pdfplumber) performs directly, and
that part is a mechanical substitution. Vector recognition is the
substantial part: PyMuPDF supplies an already-decoded list of drawing
paths, and the equivalent elsewhere is a lower-level walk over page
objects that has to compose transformation matrices and flatten curves
itself, which is new code rather than a change of import. A Licensee who
needs this should raise it with Licensor before starting; Licensor
maintains a costed plan and the work is better done once, upstream, than
separately in each Licensee's fork.

### What Licensor undertakes

Licensor will state in writing, on request and before signature, whether
the version being licensed still carries PyMuPDF, and will give notice
in the release notes if that changes in either direction. Licensor does
not warrant that a Licensee's use of PyMuPDF under the AGPL is
compliant, and the warranty in §8 and the indemnity in §10 are given in
respect of the Software as defined in §1, which does not extend to
third-party components a Licensee obtains under those components' own
licences.

Questions about this section, including the current state of the
replacement work, go to `info@datadrivenconstruction.io`.

## 4b. LGPL components inside the Software

Unlike §4a, this one is routine. It is set out here so that a Licensee's
counsel finds it stated rather than having to discover it.

### What the position is

The Software carries several libraries under the GNU Lesser General
Public License. Two of them are in every artefact Licensor publishes:
**psycopg2-binary** (LGPL-3.0-or-later), the PostgreSQL driver, and
**FFmpeg** (LGPL-2.1-or-later), which is redistributed inside the
opencv-python-headless package rather than declared as one. The Linux
`.AppImage` additionally carries the GTK 3 and WebKitGTK desktop stack,
also LGPL-2.1. [NOTICE](NOTICE) lists them, names the licence texts that
ship with the code, and carries Licensor's offer of source.

**The same components on the same terms apply in both editions.** There
is no separate commercial build. A Licensee receives the identical
binaries the community edition ships, with the identical libraries
inside them, at the identical versions. This Agreement does not change
those libraries' terms and could not, because they are separate works by
other authors. Licensor modifies none of them and holds no fork or patch
of any of them.

### What it means for a Licensee

The LGPL exists precisely so that software under other terms, closed
source included, may use a library like this. Nothing in this section
obliges a Licensee to publish its own code, to buy anything, or to give
up a feature.

**A Licensee that deploys the Software** has nothing to do. The
libraries are used unmodified through their published interfaces, and
their licence texts travel inside the artefact.

**A Licensee that redistributes the Software** under §2(3) becomes a
distributor of these libraries as well, and takes on three duties
towards its own recipients. Tell them the libraries are there and pass
on the licence texts, which happens by shipping the artefact unaltered.
Make the corresponding source available, for which the Licensee may
rely on and reproduce Licensor's offer in `NOTICE`, or make an offer of
its own. And leave the recipient able to run a modified build of the
library, which an unaltered artefact already allows by the routes
`NOTICE` describes for each artefact.

**A Licensee that modifies one of these libraries, or links one
statically into its own closed code,** is outside everything above and
should take its own advice. Licensor does neither.

### What Licensor undertakes

Licensor will supply the complete corresponding source of any LGPL
component in a released artefact, on the terms of the offer in `NOTICE`,
and will keep that offer alive for the period the offer states. Licensor
will give notice in the release notes if the set of LGPL components in
the shipped artefacts changes.

Questions go to `info@datadrivenconstruction.io`.

## 5. Trademarks

"OpenConstructionERP", "OpenEstimate", "DataDrivenConstruction", and
"CWICR" are trademarks of Licensor. Licensee may reference them
factually ("built on OpenConstructionERP") but may not imply endorsement
or co-branding without a separate written agreement.

## 6. Fees

Fees, payment schedule, and currency are stated in the order form.
Unless otherwise agreed, fees are net of VAT and paid within 30 days of
invoice.

## 7. Support and updates

The support tier (Community / Business / Enterprise) is stated in the
order form and defines response times, update cadence, and whether a
named technical contact is included.

## 8. Warranty

Licensor warrants that, to the best of its knowledge at the Effective
Date, the Software does not infringe third-party intellectual-property
rights. Licensor's sole obligation for breach of this warranty is to
replace the infringing portion or refund the pro-rata fee for the
remaining Subscription Term.

EXCEPT FOR THIS WARRANTY, THE SOFTWARE IS PROVIDED "AS IS" WITHOUT
WARRANTY OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, OR
NON-INFRINGEMENT.

## 9. Limitation of liability

TO THE MAXIMUM EXTENT PERMITTED BY LAW, EACH PARTY'S AGGREGATE LIABILITY
UNDER THIS AGREEMENT IS LIMITED TO THE FEES PAID BY LICENSEE IN THE
TWELVE MONTHS PRECEDING THE EVENT GIVING RISE TO THE CLAIM.

NEITHER PARTY IS LIABLE FOR INDIRECT, CONSEQUENTIAL, OR PUNITIVE
DAMAGES. Nothing in this clause limits liability for fraud, willful
misconduct, or death / personal injury caused by negligence.

## 10. Indemnification

Licensor will defend Licensee against third-party claims that the
Software, as provided, infringes a third party's copyright or patent
within a Covered Jurisdiction, subject to prompt notice, Licensor's
control of the defence, and Licensee's reasonable cooperation. This
obligation does not apply to modifications made by Licensee or
combinations with third-party software not supplied by Licensor.

## 11. Confidentiality

Each party shall protect the other's non-public information with the
same degree of care it uses for its own confidential information and in
no event less than reasonable care.

## 12. Term and termination

- The initial Subscription Term is stated in the order form.
- Either party may terminate for material breach after 30 days' written
  notice and failure to cure.
- Upon termination, Licensee shall stop distributing new copies;
  existing deployments may continue to operate under the AGPL licence
  that remains available to the Software, but cease to benefit from §2
  commercial terms.

## 13. Governing law

This Agreement is governed by the laws of the Federal Republic of
Germany, excluding conflict-of-laws rules. The competent courts of
Berlin have exclusive jurisdiction, subject to mandatory consumer-forum
rules.

## 14. Entire agreement

This Agreement, together with the order form and any exhibits, is the
entire agreement between the parties on its subject and supersedes any
prior discussion or proposal.

---

*To request a signed commercial licence tailored to your deployment,
contact `info@datadrivenconstruction.io` with your entity name,
deployment scale (users / tenants), and target go-live date.*
