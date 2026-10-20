# cv-pipeline (reserved, not implemented)

This directory is a roadmap placeholder. It holds no service today, and nothing
in the platform starts, imports or calls anything from here. Several code
comments point at `services/cv-pipeline` as the future home of raster symbol
detection; this file exists so that anyone following one of those pointers
lands on the truth instead of an empty directory.

## What was planned

A standalone computer-vision service that would find repeated symbols (doors,
fixtures, sockets, sprinkler heads) on scanned drawings by template matching
against a user-drawn exemplar, returning candidate boxes for confirmation.

## Why it is not implemented

Symbol detection on scanned sheets is where CV pipelines quietly lose their
value. On a low-contrast scan, repeated symbols cluster unreliably: the
detector returns many boxes, most of them nearly right, and checking them costs
the estimator more than counting by hand would have. Shipping that would break
the rule that a proposal has to be cheaper to verify than to redo. Running it
as a separate service also breaks the lightweight deployment promise, since the
core is meant to run on a 3 GB dedicated server with PostgreSQL as the only
hard dependency.

So this is a deliberate hold rather than an oversight. The match-elements
module describes raster symbol detection as a roadmap item, and that is
accurate: it stays on the roadmap and off the release until proposals are good
enough that confirming them beats counting by hand.

## What actually ships instead

Raster detection that does work lives inside the takeoff module, not here:

- `backend/app/modules/takeoff/raster_recognize.py` finds rooms and walls on
  scanned pages using OpenCV morphology. It is a pure function, no service and
  no network. Counts are skipped on purpose, for the reason above.
- `backend/app/modules/takeoff/recognize.py` handles pages that still carry a
  vector layer, including counts, deterministically and without CV at all.
- Symbol signature matching for elements is in the match-elements module and
  works on extracted attributes rather than pixels.

OpenCV and pypdfium2 are base dependencies, so both detectors run in every
default install. Only the OCR engine, which reads dimension text, sits behind
the optional `cv` extra.

## If you pick this up

Prefer extending `raster_recognize.py` in-process over standing up a service.
The lightweight rule and the single-database rule both point that way, and the
existing detectors already carry the confidence and reason plumbing that any
proposal needs in order to reach a human for confirmation.
