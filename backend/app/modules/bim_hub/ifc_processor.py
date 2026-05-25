"""‌⁠‍IFC/RVT file processor — uses DDC cad2data when available, text parser as fallback.

Processing pipeline:
1. Try DDC cad2data (external tool) → full DataFrame + COLLADA geometry
2. Fallback: text-based IFC STEP parser → extracts entities, properties, quantities
3. Generates simplified COLLADA boxes for 3D preview

For full geometry: install DDC cad2data or use Advanced Mode to upload CSV + DAE.

Identity mapping (DDC RvtExporter):
    The DDC COLLADA pass emits numeric ``<node id="N">`` values where ``N`` is
    the Revit ElementId (``Element.Id.IntegerValue``). The DDC Excel pass emits
    the same ElementId in its first column (header ``ID``). We use that ID as
    the element's ``mesh_ref`` so the 3D viewer can pair each BIM element row
    with its DAE node for filtering and isolation.
"""

import hashlib
import logging
import re
import xml.etree.ElementTree as ET  # noqa: S405 — tree building + types; all parsing goes through defusedxml
from pathlib import Path
from typing import Any

import defusedxml.ElementTree as safe_ET

_COLLADA_NS = "http://www.collada.org/2005/11/COLLADASchema"

logger = logging.getLogger(__name__)

# IFC entity types we care about — includes IFC2x3, IFC4, and IFC4x3 civil types
_ELEMENT_TYPES = {
    # ── Structural / architectural (IFC2x3+) ──
    "IFCWALL", "IFCWALLSTANDARDCASE", "IFCSLAB", "IFCCOLUMN", "IFCBEAM",
    "IFCDOOR", "IFCWINDOW", "IFCROOF", "IFCSTAIR", "IFCRAILING",
    "IFCCURTAINWALL", "IFCPLATE", "IFCMEMBER", "IFCFOOTING",
    "IFCPILE", "IFCBUILDINGELEMENTPROXY",
    # ── MEP ──
    "IFCFLOWSEGMENT", "IFCFLOWTERMINAL", "IFCFLOWFITTING",
    "IFCDISTRIBUTIONELEMENT", "IFCFURNISHINGELEMENT",
    "IFCCOVERING", "IFCSPACE",
    # ── Civil infrastructure (IFC4x3 + common proxies) ──
    "IFCALIGNMENT", "IFCALIGNMENTHORIZONTAL", "IFCALIGNMENTVERTICAL",
    "IFCALIGNMENTSEGMENT", "IFCALIGNMENTCANT",
    "IFCBRIDGE", "IFCBRIDGEPART",
    "IFCROAD", "IFCROADPART",
    "IFCRAILWAY", "IFCRAILWAYPART",
    "IFCFACILITY", "IFCFACILITYPART",
    "IFCPAVEMENT", "IFCKERB", "IFCCOURSE",
    "IFCEARTHWORKSFILL", "IFCEARTHWORKSCUT", "IFCEARTHWORKSELEMENT",
    "IFCREINFORCEDSOIL", "IFCGEOTECHNICELEMENT", "IFCGEOTECHNICSTRATUM",
    "IFCDEEPFOUNDATION", "IFCCAISSONFOOTING",
    "IFCBEARING", "IFCTENDON", "IFCTENDONANCHOR", "IFCTENDONCONDUIT",
    "IFCSURFACEFEATURE", "IFCVOIDINGELEMENT",
    # ── Generic / catch-all ──
    "IFCCIVILELEMENT", "IFCGEOGRAPHICELEMENT",
    "IFCTRANSPORTELEMENT", "IFCVIRTUALELEMENT",
    "IFCEXTERNALSPATIALELEMENT",
}

# Spatial structure types used as "storey" equivalents (IFC4x3 uses
# IfcFacilityPart for road stations, bridge spans, etc.)
_STOREY_TYPES = {"IFCBUILDINGSTOREY", "IFCFACILITYPART", "IFCBRIDGEPART", "IFCROADPART", "IFCRAILWAYPART"}

# Regex for IFC STEP line: #123= IFCWALL('guid', #owner, 'name', ...)
_LINE_RE = re.compile(r"^#(\d+)\s*=\s*(\w+)\s*\((.*)\)\s*;", re.DOTALL)
_STRING_RE = re.compile(r"'([^']*)'")

# Placeholder used to escape doubled apostrophes (''-style ISO-10303 escape)
# while parsing, then restored after _STRING_RE.findall. Without this an
# entity such as IFCWALL('22…','#5','O''Brien Tower','…') would have its
# GUID truncated to "O" because the first '' would terminate the second
# string. See audit C1 — affects every RVT export where someone typed an
# apostrophe in a name field. The placeholder is chosen so it can never
# legally appear inside a STEP P21 string (no \x00 in STEP serialisation).
_STEP_DOUBLE_QUOTE_PLACEHOLDER = "\x00DDC_STEP_DQ\x00"


def _decode_step_string(s: str) -> str:
    """Decode STEP-21 escape sequences inside a quoted string.

    Handles:
      * ``\\X\\NN``        → Latin-1 byte (one hex pair, ISO-10303-21)
      * ``\\X2\\NNNN\\X0\\`` → UTF-16BE codepoint block
      * ``\\S\\X``         → Latin-1 with high bit set (legacy)
      * ``''``             → single apostrophe (replaces our placeholder)
    Anything we cannot decode falls through unchanged. Non-ASCII text in
    Tekla/Allplan/SOFiSTiK exports survives intact instead of being kept
    as raw ``\\X2\\…`` escape sequences in BIMElement.name (audit C4).
    """
    if not s:
        return s
    # Restore doubled-apostrophes first so the rest of the decode sees
    # them as the user intended (single ' inside the string body).
    s = s.replace(_STEP_DOUBLE_QUOTE_PLACEHOLDER, "'")
    if "\\" not in s:
        return s
    # \X2\…\X0\ — UTF-16BE block (greedy until terminator)
    def _x2(match: "re.Match[str]") -> str:
        hexstr = match.group(1)
        try:
            return bytes.fromhex(hexstr).decode("utf-16-be", errors="replace")
        except ValueError:
            return match.group(0)
    s = re.sub(r"\\X2\\([0-9A-Fa-f]+)\\X0\\", _x2, s)
    # \X\NN — Latin-1 (single byte)
    def _x1(match: "re.Match[str]") -> str:
        try:
            return bytes.fromhex(match.group(1)).decode("latin-1", errors="replace")
        except ValueError:
            return match.group(0)
    s = re.sub(r"\\X\\([0-9A-Fa-f]{2})", _x1, s)
    # \S\X — Latin-1 high-bit (ASCII char + 0x80)
    def _ss(match: "re.Match[str]") -> str:
        ch = match.group(1)
        return chr(ord(ch) | 0x80) if len(ch) == 1 else match.group(0)
    s = re.sub(r"\\S\\(.)", _ss, s)
    return s


# ── Last-conversion failure context ───────────────────────────────────────
#
# The DDC subprocess can fail for many reasons (Wine crash, RVT version too
# new, license probe failed). When that happens, ``_try_cad2data`` returns
# None — and historically the caller had no way to know WHY. The router
# then shipped a generic "Converter Required" message that didn't help the
# user diagnose anything.
#
# We now stash the last failure's structured context here so the router can
# pick it up and surface it to the frontend (in ``model.error_message`` and
# ``model.metadata_``). Module-level state is fine because conversions are
# serialised per upload — the data is consumed immediately after the call.
_LAST_DDC_FAILURE: dict[str, Any] = {}


def last_ddc_failure() -> dict[str, Any]:
    """‌⁠‍Return the most recent DDC conversion failure context, if any.

    Keys are best-effort and may be missing:
      * ``reason`` — short tag: ``timeout`` / ``nonzero_exit`` / ``empty_output``
      * ``exit_code`` — int from the subprocess (may be missing on timeout)
      * ``stderr`` — last ~2 KB of stderr from the converter (decoded utf-8)
      * ``rvt_info`` — dict from ``read_rvt_revit_version`` (RVT only)
      * ``converter_info`` — dict from ``detect_converter_version``
      * ``extension`` — the file ext that failed (``rvt`` / ``ifc`` / …)

    Returns an empty dict if there has been no failure since startup.
    """
    return dict(_LAST_DDC_FAILURE)


_OUTDATED_CLI_STDERR_MARKERS = (
    "arguments were not expected",
    "unexpected argument",
    "unknown argument",
    "unknown option",
    "unrecognized argument",
    "unrecognised argument",
)


def _infer_failure_cause(
    *, reason: str, exit_code: int | None, stderr_text: str
) -> str:
    """‌⁠‍Map raw subprocess output to a stable ``cause`` enum for the UI.

    The frontend dispatches on this string — keep the values stable.
    Currently supported:
      * ``converter_outdated`` — CLI parse error (exit 15 + unknown-arg
        substring, or any exit with the substring).  Triggers the
        Reinstall CTA.
      * ``timeout`` — converter hung.
      * ``empty_output`` — converter ran, produced no rows.
      * ``unknown`` — anything else; UI shows the generic guidance.
    """
    lower = stderr_text.lower()
    if any(m in lower for m in _OUTDATED_CLI_STDERR_MARKERS):
        return "converter_outdated"
    if exit_code == 15:
        # Exit 15 from the DDC CLIs almost always means "argument parse
        # error".  Even with empty stderr, surfacing the Reinstall CTA is
        # the right call — a fresh install can only help.
        return "converter_outdated"
    if reason == "timeout":
        return "timeout"
    if reason == "empty_output":
        return "empty_output"
    return "unknown"


def _record_ddc_failure(
    extension: str,
    reason: str,
    *,
    exit_code: int | None = None,
    stderr: bytes | str = b"",
    ifc_path: Path | None = None,
    cause: str | None = None,
) -> None:
    """‌⁠‍Update the module-level failure record with everything the router
    needs to render an actionable error message.

    ``cause`` may be passed explicitly to skip the heuristic — used by
    the ``_run_ddc`` retry path which already knows the failure was a
    CLI mismatch.  When omitted, ``_infer_failure_cause`` looks at the
    exit code and stderr substrings to pick a value.
    """
    try:
        from app.modules.boq.cad_import import (
            detect_converter_version as _detect,
        )
        from app.modules.boq.cad_import import (
            read_rvt_revit_version as _read_rvt,
        )

        rvt_info: dict[str, str | None] = {}
        if extension == "rvt" and ifc_path is not None and ifc_path.exists():
            rvt_info = _read_rvt(ifc_path)
        conv_info = _detect(extension)
    except Exception:  # noqa: BLE001 — diagnostics must never raise
        rvt_info = {}
        conv_info = {}

    stderr_text = (
        stderr.decode("utf-8", errors="replace")
        if isinstance(stderr, (bytes, bytearray))
        else str(stderr)
    )
    # Keep the tail (where the actual error usually lives, not the boot
    # noise) up to 2 KB.
    stderr_tail = stderr_text[-2048:].strip()

    resolved_cause = cause or _infer_failure_cause(
        reason=reason, exit_code=exit_code, stderr_text=stderr_tail
    )

    _LAST_DDC_FAILURE.clear()
    _LAST_DDC_FAILURE.update(
        extension=extension,
        reason=reason,
        cause=resolved_cause,
        exit_code=exit_code,
        stderr=stderr_tail,
        rvt_info=rvt_info,
        converter_info=conv_info,
    )
    logger.warning(
        "DDC failure recorded: ext=%s reason=%s cause=%s rc=%s rvt=%s converter=%s",
        extension, reason, resolved_cause, exit_code,
        rvt_info.get("app_name") or rvt_info.get("format"),
        conv_info.get("version"),
    )


def _detect_converter_version_safe(extension: str) -> dict[str, str | None]:
    """‌⁠‍Best-effort wrapper around ``detect_converter_version``.

    Used by the ``_try_cad2data`` success path to attach a DDC version stamp
    to the BIM result. Re-exports the same dict shape as the underlying
    helper: ``{"version": str | None, "source": str | None,
    "binary_path": str | None}``. Never raises — diagnostics must not block
    a successful import.
    """
    try:
        from app.modules.boq.cad_import import detect_converter_version

        return detect_converter_version(extension)
    except Exception:  # noqa: BLE001
        return {"version": None, "source": None, "binary_path": None}


def _try_cad2data(ifc_path: Path, output_dir: Path, *, conversion_depth: str = "standard") -> dict[str, Any] | None:
    """‌⁠‍Try to convert CAD files using DDC converters.

    Pipeline (tried in order):
    1. DDC Community Converter (RvtExporter.exe / IfcExporter.exe) → Excel → elements
    2. cad2data binary on PATH → CSV + DAE
    """
    ext = ifc_path.suffix.lower().lstrip(".")

    # --- Method 1: DDC Community Converter (same pipeline as Data Explorer) ---
    # The DDC RvtExporter / IfcExporter is dispatched by the OUTPUT FILE
    # EXTENSION: .xlsx/.xls → Excel, .dae → COLLADA, .pdf → PDF.
    # We invoke it TWICE so we get both:
    #   1. Element list as Excel (parsed into BIMElement records)
    #   2. Real 3D geometry as native COLLADA (saved as geometry.dae)
    # The second call replaces the simplified box-grid we used to generate
    # from element bounding boxes.
    #
    # CRITICAL: DDC needs cwd=converter.parent (Qt6Core.dll lives there),
    # so all paths must be absolute or the converter reports "File does not exist".
    try:
        from app.modules.boq.cad_import import (
            detect_converter_capabilities,
            find_converter,
            parse_cad_excel,
        )

        converter = find_converter(ext)
        if converter:
            import subprocess
            logger.info("Using DDC Community Converter: %s", converter)
            output_dir.mkdir(parents=True, exist_ok=True)

            input_abs = ifc_path.resolve()

            # Probe the binary once so we know which positional / flag
            # arguments it understands.  Old DDC builds reject ``standard``
            # and ``-no-collada`` with ``exit 15: The following arguments
            # were not expected``; the matrix below lets us suppress those
            # tokens up front and avoid the exit-15 trap entirely.
            caps = detect_converter_capabilities(ext)
            # Resolve the CLI profile up front so the args-builder and the
            # retry path can branch off it without re-reading the dict on
            # every call.  v18 binaries (flag-driven CLI) and v17/legacy
            # binaries (positional CLI) build completely different command
            # lines — see ``cad_import.build_ddc_args`` for the canonical
            # mapping.
            from app.modules.boq.cad_import import (
                CLI_PROFILE_LEGACY,
                CLI_PROFILE_V17_POSITIONAL,
                CLI_PROFILE_V18_FLAG,
                build_ddc_args,
            )
            cli_profile = caps.get("cli_profile", CLI_PROFILE_LEGACY)
            # Track whether the conservative path was taken for any reason
            # (probe-driven OR exit-15 retry) so callers can surface a
            # "converter_outdated" diagnostic to the UI.  v18 is the
            # current release — only v17_positional / legacy / no-flag
            # paths get the "outdated" badge.
            outdated_cli_observed = cli_profile not in (
                CLI_PROFILE_V18_FLAG,
                CLI_PROFILE_V17_POSITIONAL,
            )

            # Stderr substrings that prove the failure was specifically an
            # "unknown argument" rejection — keep these tight to avoid
            # false-retries on genuine conversion failures (license probe,
            # corrupt file, missing DLL, …).  Match is case-insensitive on
            # the decoded text.  Both phrasings have been observed across
            # DDC RvtExporter / IfcExporter versions.
            UNKNOWN_ARG_MARKERS = (
                "arguments were not expected",
                "unexpected argument",
                "unknown argument",
                "unknown option",
                "unrecognized argument",
                "unrecognised argument",
            )

            def _stderr_indicates_unknown_arg(stderr_bytes: bytes) -> bool:
                """‌⁠‍True iff stderr contains an 'unknown CLI arg' substring.

                Used in conjunction with exit-15 — *both* must be true for
                the retry-without-extras path to fire, so a normal
                conversion failure with a non-zero exit and unrelated
                stderr keeps the strict error report instead of being
                silently retried.
                """
                if not stderr_bytes:
                    return False
                try:
                    text = stderr_bytes.decode("utf-8", errors="replace").lower()
                except UnicodeError:
                    return False
                return any(marker in text for marker in UNKNOWN_ARG_MARKERS)

            def _build_args(
                out_path: Path,
                *,
                allow_depth_mode: bool,
                allow_no_collada: bool,
                extra: tuple[str, ...] = (),
            ) -> list[str]:
                """‌⁠‍Compose the CLI invocation honouring the capability flags.

                Routes through ``cad_import.build_ddc_args`` whenever the
                probe identified a v18 flag-driven binary — that path
                emits ``-x out.xlsx`` / ``-d out.dae`` / ``-m mode``
                / ``--force-path`` instead of the legacy positional
                ``output [mode] [-no-collada]`` shape that v18 rejects
                with exit 15.

                For v17 positional / legacy binaries the historical layout
                is preserved verbatim so the existing test contract (and
                any user with an old binary on disk) keeps working.

                Depth-mode is only appended when both the caller asked for
                it AND the binary advertises support.  ``extra`` is the
                tuple of caller-supplied flags (currently only
                ``-no-collada`` for the Excel pass) — those are filtered
                against ``allow_no_collada`` so a probe-confirmed legacy
                binary never sees the flag at all.
                """
                ddc_mode = "complete" if conversion_depth == "complete" else "standard"

                if cli_profile == CLI_PROFILE_V18_FLAG:
                    # The output extension picks which v18 flag we emit:
                    # .xlsx / .xls → ``-x`` and suppress DAE; .dae → ``-d``
                    # and suppress XLSX.  Suppressing the other output
                    # halves wall-time per pass (the bundled exporter
                    # writes both by default).
                    suffix = out_path.suffix.lower()
                    is_xlsx = suffix in (".xlsx", ".xls")
                    is_dae = suffix == ".dae"
                    # ``allow_depth_mode`` is gated on the legacy
                    # ``accepts_depth_mode`` boolean (v17 positional);
                    # v18 uses ``accepts_flag_mode`` (``-m``).  Honour
                    # caller intent across both: emit the mode whenever
                    # EITHER capability is on.
                    return build_ddc_args(
                        converter,
                        input_abs,
                        caps=caps,
                        xlsx_out=out_path if is_xlsx else None,
                        dae_out=out_path if is_dae else None,
                        mode=ddc_mode,
                        # Default-skip the *other* output on every v18
                        # single-output pass — saves a roundtrip and
                        # keeps the work on-spec.
                        include_no_dae=is_xlsx,
                        include_no_xlsx=is_dae,
                    )

                # Legacy / v17 positional path — unchanged historical behaviour.
                args_list = [str(converter), str(input_abs), str(out_path)]
                if ext in ("rvt", "ifc") and allow_depth_mode:
                    args_list.append(ddc_mode)
                for arg in extra:
                    if arg == "-no-collada" and not allow_no_collada:
                        continue
                    args_list.append(arg)
                return args_list

            def _invoke(args_list: list[str]) -> tuple[int, bytes, bytes]:
                """‌⁠‍Thin subprocess wrapper — separated so the retry path can
                rebuild the args list and call again without re-implementing
                the cwd/timeout/stdin plumbing."""
                logger.debug("DDC call: %s", args_list)
                proc = subprocess.run(
                    args_list,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=str(converter.parent),
                    input=b"\n",
                    timeout=600,
                )
                return proc.returncode, proc.stdout, proc.stderr

            def _run_ddc(out_path: Path, *extra_args: str) -> tuple[int, bytes, bytes]:
                """‌⁠‍Invoke RvtExporter / IfcExporter with the given output target.

                Two-stage logic:
                  1. Build args using the probed capability matrix and run.
                  2. If exit code is 15 AND stderr names an unknown
                     argument, rebuild args as bare ``[converter, input,
                     output]`` (no depth-mode, no flags) and retry once.
                     A success here records the binary as "outdated CLI"
                     so the UI can surface a Reinstall CTA.

                Why exit code 15 specifically: the bundled CLI parser
                (CLI11 / similar) emits 15 for "argument parse error".
                Other failure modes use different codes (file-not-found
                = 8, license error = 6, ...).  The substring guard is the
                belt-and-braces second condition so a coincidental exit-15
                from an unrelated cause doesn't trip the retry.
                """
                nonlocal outdated_cli_observed
                args_list = _build_args(
                    out_path,
                    allow_depth_mode=caps.get("accepts_depth_mode", False),
                    allow_no_collada=caps.get("accepts_no_collada_flag", False),
                    extra=tuple(extra_args),
                )
                rc, stdout, stderr = _invoke(args_list)
                if rc == 0:
                    return rc, stdout, stderr

                # Retry guard: only fire when the probe didn't already
                # downgrade us to the bare form (otherwise we'd retry the
                # same command), and the failure looks like a CLI parse
                # error.  Either both signals (exit 15 + stderr marker) or
                # any-exit + stderr marker is sufficient — DDC has shipped
                # at least one release that exits 64 for unknown args.
                #
                # "Already bare" is profile-dependent: on the v18 flag
                # CLI the minimum-acceptable call is
                # ``[exe, input, -x out, -m standard, --force-path]`` (or
                # ``-d`` for the COLLADA pass) — never the bare positional
                # ``[exe, input, output]`` that the v17/legacy bare branch
                # would emit.  Recognising this prevents a v18 binary from
                # retrying with a shape it doesn't understand, and prevents
                # a legacy binary from retrying with v18 flags it doesn't
                # understand.
                already_bare = (
                    cli_profile == CLI_PROFILE_LEGACY
                    and not (caps.get("accepts_depth_mode") or caps.get("accepts_no_collada_flag"))
                )
                stderr_hit = _stderr_indicates_unknown_arg(stderr)
                if already_bare:
                    return rc, stdout, stderr
                if rc == 15 or stderr_hit:
                    if cli_profile == CLI_PROFILE_V18_FLAG:
                        # v18 retry: keep the flag CLI but drop the
                        # output-suppression flags + mode preset — leaves
                        # ``[exe, input, -x out, --force-path]`` (or -d).
                        # If THIS still fails we surface the original
                        # error; falling through to the legacy positional
                        # bare shape would just trade one parse error for
                        # another.
                        suffix = out_path.suffix.lower()
                        is_xlsx = suffix in (".xlsx", ".xls")
                        bare_args = [str(converter), str(input_abs)]
                        if is_xlsx:
                            bare_args.extend(["-x", str(out_path)])
                        else:
                            bare_args.extend(["-d", str(out_path)])
                        if caps.get("accepts_flag_force_path"):
                            bare_args.append("--force-path")
                    else:
                        bare_args = _build_args(
                            out_path,
                            allow_depth_mode=False,
                            allow_no_collada=False,
                            extra=(),
                        )
                    logger.warning(
                        "DDC converter rejected modern CLI args (rc=%d, marker=%s, profile=%s) — "
                        "retrying with reduced invocation: %s",
                        rc, stderr_hit, cli_profile, bare_args,
                    )
                    rc2, stdout2, stderr2 = _invoke(bare_args)
                    if rc2 == 0:
                        # Latch the diagnostic so the caller can record
                        # cause="converter_outdated" once the conversion
                        # completes — the user keeps their result, but the
                        # next page-load nudges them to reinstall.
                        outdated_cli_observed = True
                        return rc2, stdout2, stderr2
                    # Second attempt also failed — surface the original
                    # error so the user sees the parse complaint, not a
                    # downstream "file not found" from a stripped-down
                    # invocation that the legacy CLI also couldn't run.
                    return rc, stdout, stderr
                return rc, stdout, stderr

            # ── Passes 1 + 2 in parallel: Excel + native COLLADA ──────
            # DDC RvtExporter has to load the entire RVT file from scratch
            # for each invocation (no shared state between processes), so
            # running the Excel and COLLADA passes sequentially used to
            # double the effective conversion time.  The two output files
            # are independent — both passes only read the input and write
            # to a different target — so we run them in parallel threads.
            # Wall-time drops to roughly max(Excel, COLLADA) instead of sum.
            #
            # The previously-present third synchronous pass for PDF sheet
            # export was removed: it triples upload latency, frequently
            # times out, and the PDF can be regenerated on demand from the
            # original RVT/IFC blob (which is already saved by the router
            # before this processor runs).
            import concurrent.futures

            output_xlsx = (output_dir / (ifc_path.stem + ".xlsx")).resolve()
            real_dae = (output_dir / "geometry.dae").resolve()

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as _pool:
                fut_xlsx = _pool.submit(_run_ddc, output_xlsx, "-no-collada")
                fut_dae = _pool.submit(_run_ddc, real_dae)

                try:
                    rc, _stdout, stderr = fut_xlsx.result()
                except subprocess.TimeoutExpired:
                    logger.error("DDC Excel pass timed out for %s", ifc_path.name)
                    _record_ddc_failure(ext, "timeout", ifc_path=ifc_path)
                    return None
                if rc != 0:
                    logger.warning(
                        "DDC Excel pass exit %d: %s",
                        rc, stderr.decode(errors="replace")[:300],
                    )
                    _record_ddc_failure(
                        ext, "nonzero_exit",
                        exit_code=rc, stderr=stderr, ifc_path=ifc_path,
                    )
                    return None

                excel_path: Path | None = None
                if output_xlsx.exists() and output_xlsx.stat().st_size > 0:
                    excel_path = output_xlsx
                else:
                    for f in output_dir.iterdir():
                        if f.suffix in (".xlsx", ".xls") and f.stat().st_size > 0:
                            excel_path = f
                            break
                if not excel_path:
                    logger.warning("DDC Excel pass produced no output file in %s", output_dir)
                    _record_ddc_failure(
                        ext, "no_output_file",
                        exit_code=rc, stderr=stderr, ifc_path=ifc_path,
                    )
                    return None

                raw_elements = parse_cad_excel(excel_path)
                if not raw_elements:
                    logger.warning("DDC Excel pass produced empty file")
                    _record_ddc_failure(
                        ext, "empty_output",
                        exit_code=rc, stderr=stderr, ifc_path=ifc_path,
                    )
                    return None
                logger.info(
                    "DDC converter extracted %d raw rows from %s",
                    len(raw_elements), ifc_path.name,
                )

                try:
                    rc2, _stdout2, stderr2 = fut_dae.result()
                except subprocess.TimeoutExpired:
                    logger.warning("DDC COLLADA pass timed out — will fall back to box geometry")
                    rc2 = -1
                    stderr2 = b""

            real_dae_path: Path | None = None
            if rc2 == 0 and real_dae.exists() and real_dae.stat().st_size > 0:
                real_dae_path = real_dae
                logger.info(
                    "DDC native COLLADA generated: %d bytes",
                    real_dae.stat().st_size,
                )
            else:
                logger.warning(
                    "DDC COLLADA pass failed (rc=%s, stderr=%s) — using box fallback",
                    rc2, stderr2.decode(errors="replace")[:200] if stderr2 else "",
                )

            result_excel = _excel_elements_to_bim_result(
                raw_elements,
                output_dir,
                real_dae_path=real_dae_path,
            )
            # Surface the converter version so the frontend can render a
            # "Processed with DDC v{X}" badge on the model card (Stream D
            # / v3.12.0). Detection is best-effort and never raises —
            # missing values silently degrade to ``None`` and the badge
            # hides. See ``detect_converter_version`` for the dpkg /
            # parent-dir resolution logic.
            try:
                conv_info = _detect_converter_version_safe(ext)
                if conv_info.get("version"):
                    result_excel["converter_version"] = conv_info["version"]
                if conv_info.get("source"):
                    result_excel["converter_source"] = conv_info["source"]
            except Exception:  # noqa: BLE001 — diagnostics must never block import
                pass
            # If the conversion only succeeded because we stripped modern
            # CLI args (or had to retry without them), flag the result so
            # the router can persist a "converter_outdated" warning in the
            # model metadata.  The data is good — but the user should be
            # nudged to reinstall before the next file fails.
            if outdated_cli_observed:
                result_excel["converter_cli_outdated"] = True
            return result_excel
    except ImportError:
        logger.debug("cad_import module not available")
    except Exception as e:
        logger.warning("DDC Community Converter error: %s", e, exc_info=True)

    # --- Method 2: cad2data binary on PATH ---
    import csv
    import shutil

    cad2data_bin = shutil.which("cad2data")
    if not cad2data_bin:
        return None

    logger.info("Using DDC cad2data for conversion: %s", cad2data_bin)
    try:
        import subprocess

        result = subprocess.run(
            [cad2data_bin, str(ifc_path), "--output-dir", str(output_dir), "--format", "csv,dae"],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            logger.warning("cad2data failed: %s", result.stderr[:500])
            return None

        csv_path = output_dir / "elements.csv"
        dae_path = output_dir / "geometry.dae"
        if not csv_path.exists():
            for p in output_dir.glob("*.csv"):
                csv_path = p
                break

        elements: list[dict[str, Any]] = []
        csv_raw_rows: list[dict[str, Any]] = []
        storeys_set: set[str] = set()
        disciplines_set: set[str] = set()

        if csv_path.exists():
            with open(csv_path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    csv_raw_rows.append(dict(row))
                    storey = row.get("storey", row.get("level", ""))
                    discipline = row.get("discipline", _classify_discipline(row.get("type", "")))
                    if storey:
                        storeys_set.add(storey)
                    disciplines_set.add(discipline)

                    quantities: dict[str, float] = {}
                    for qkey in ("area", "volume", "length", "width", "height"):
                        if qkey in row and row[qkey]:
                            try:
                                quantities[qkey.title()] = float(row[qkey])
                            except ValueError:
                                pass

                    elements.append({
                        "stable_id": row.get("global_id", row.get("id", str(len(elements)))),
                        "element_type": row.get("type", "Unknown"),
                        "name": row.get("name", ""),
                        "storey": storey or None,
                        "discipline": discipline,
                        "properties": {
                        k: v for k, v in row.items()
                        if k not in ("global_id", "id", "type", "name", "storey", "discipline")
                    },
                        "quantities": quantities,
                        "geometry_hash": hashlib.md5(str(row).encode()).hexdigest()[:16],
                        "bounding_box": None,
                    })

        has_geometry = dae_path.exists()
        # Validate the DAE file BEFORE the expensive trimesh GLB conversion.
        # If the converter (DDC cad2data or our text-IFC fallback) produced a
        # malformed COLLADA, both the GLB conversion AND the frontend
        # ColladaLoader/GLTFLoader will explode with the unhelpful
        # ``getAttribute`` JS error. Detect that here, drop the path, and
        # downgrade ``geometry_type`` to ``placeholder`` so the viewer falls
        # back to the bbox-only render instead of crashing.
        if has_geometry:
            ok, reason = _validate_geometry_file(dae_path)
            if not ok:
                logger.warning(
                    "Produced DAE failed validation (%s): %s — dropping geometry path",
                    dae_path.name, reason,
                )
                has_geometry = False

        # DAE → GLB post-processing
        glb_path: Path | None = None
        if has_geometry:
            glb_path = _convert_dae_to_glb(dae_path, output_dir)
            # Sanity-check the converter's output. trimesh occasionally
            # writes a header-only GLB on degenerate inputs; serving it
            # to the frontend would only confuse the loader.
            if glb_path is not None:
                ok, reason = _validate_geometry_file(glb_path)
                if not ok:
                    logger.warning(
                        "Produced GLB failed validation (%s): %s — dropping GLB path",
                        glb_path.name, reason,
                    )
                    glb_path = None

        result_cad2data: dict[str, Any] = {
            "elements": elements,
            "storeys": sorted(storeys_set),
            "disciplines": sorted(disciplines_set),
            "element_count": len(elements),
            "has_geometry": has_geometry,
            "geometry_path": str(dae_path) if has_geometry else None,
            "glb_path": str(glb_path) if glb_path else None,
            "bounding_box": None,
            "geometry_type": "real" if has_geometry else "placeholder",
            "geometry_quality": "real" if has_geometry else "placeholder",
            "raw_elements": csv_raw_rows,
        }
        # Same converter-version stamp the DDC RvtExporter / IfcExporter
        # success path applies — keeps the frontend badge consistent
        # regardless of which DDC method handled the file.
        try:
            conv_info = _detect_converter_version_safe(ext)
            if conv_info.get("version"):
                result_cad2data["converter_version"] = conv_info["version"]
            if conv_info.get("source"):
                result_cad2data["converter_source"] = conv_info["source"]
        except Exception:  # noqa: BLE001
            pass
        return result_cad2data
    except Exception as e:
        logger.warning("cad2data error: %s", e)
        return None


def _excel_elements_to_bim_result(
    raw_elements: list[dict[str, Any]],
    output_dir: Path,
    *,
    real_dae_path: Path | None = None,
) -> dict[str, Any]:
    """Convert parsed Excel elements (from DDC converter) into BIM result format.

    DDC RvtExporter produces Excel rows with Revit-specific columns:
    - ``category`` like "OST_Walls", "OST_Doors", "OST_PipeFitting"
    - ``name``, ``type name``, ``family name``
    - ``uniqueid`` (Revit GUID)
    - ``level`` for storey, ``length``/``area``/``volume`` for quantities
    - Many BuiltIn parameters like ``width``, ``height``, ``thickness``, etc.

    We filter out non-element rows (sun studies, materials, viewports, etc.)
    and map the meaningful Revit categories into our generic element model.

    If ``real_dae_path`` is provided (output of a separate RvtExporter call to
    .dae), we use the real Revit COLLADA geometry instead of the placeholder
    box-grid generated from element bounding boxes.
    """
    # Skip these categories — they're not building elements.
    # Expanded set covers views, sheets, materials, annotations, tags,
    # dimensions, analytical model, model groups, revisions, schedules,
    # legends, and other non-physical Revit categories.
    SKIP_CATEGORIES: set[str | None] = {
        None, "",
        # Views, sheets, materials, settings
        "ost_materials", "ost_sunstudy", "ost_views", "ost_viewports",
        "ost_grids", "ost_levels", "ost_sheets", "ost_titleblocks",
        "ost_phases", "ost_previewlegendcomponents", "ost_designoptions",
        "ost_paramelemelectricalloadclassification", "ost_hvac_load_space_types",
        "ost_hvac_load_building_types", "ost_filldrawcolor", "ost_filllinepattern",
        # Annotations, tags, dimensions
        "ost_dimensions", "ost_textnotes", "ost_genericannotation",
        "ost_doortags", "ost_windowtags", "ost_roomtags", "ost_walltags",
        "ost_areatags", "ost_keynotetags", "ost_materialtags",
        "ost_areaschemelines", "ost_sketchlines", "ost_weakdims",
        "ost_detailcomponents", "ost_colorfilllegends", "ost_colorfillschema",
        "ost_spotdimensions", "ost_spotcoordinates", "ost_spotslopes",
        "ost_spotelevsymbols", "ost_callouts", "ost_callouthead", "ost_calloutheads",
        "ost_elevationmarks", "ost_sectionmarks", "ost_sectionbox",
        "ost_scopeboxes", "ost_referencepoints", "ost_referenceplane",
        "ost_referenceline", "ost_gridheads", "ost_levelheads",
        "ost_matchline", "ost_viewportlabel",
        # Detail & drafting
        "ost_detailitems", "ost_lines", "ost_clines",
        "ost_rasterimages", "ost_schedulegraphics",
        "ost_tilepatterns", "ost_divisionrules",
        # Revision clouds & tags
        "ost_revisionclouds", "ost_revisioncloudtags",
        "ost_revisions", "ost_revisionnumberingsequences",
        # Analytical / structural analysis
        "ost_analyticalnodes", "ost_analyticalmember", "ost_analyticalsurface",
        "ost_analyticalfloor", "ost_analyticalwall",
        "ost_analyticalpipeconnections", "ost_linksanalytical",
        "ost_loadcases", "ost_constraints",
        # Model groups, design options, arrays
        "ost_iosmodelgroups", "ost_iosdetailgroups", "ost_editcuts",
        "ost_iossketchgrid", "ost_iosgeolocations", "ost_iosgeosite",
        "ost_iosarrays",
        # Schedules, legends
        "ost_schedules", "ost_legendcomponents",
        # Profile / reference / misc
        "ost_profilefamilies", "ost_profileplane",
        "ost_referenceviewersymbol", "ost_multireferenceannotations",
        "ost_sectionheads",
        # Project / system info (not physical)
        "ost_projectinformation", "ost_projectbasepoint",
        "ost_sharedbasepoint", "ost_coordinatesystem",
        "ost_eaconstructions", "ost_covertype",
        # Topography / site context (huge meshes that obscure the building)
        "ost_topography", "ost_toposurface", "ost_topo",
        "ost_site", "ost_sitepad", "ost_siteregion",
        "ost_buildingpad", "ost_pad",
        "ost_entourage", "ost_planting",
        # IFC spatial/project types (from DDC IfcExporter — not physical elements)
        "ifcproject", "ifcsite", "ifcbuilding", "ifcbuildingstorey",
        "ifcownerhistory", "ifcapplication", "ifcpersonandorganization",
        "ifcperson", "ifcorganization", "ifcunitassignment",
        "ifcgeometricrepresentationcontext",
        # HVAC schedules / load (analytical, not physical)
        "ost_hvacloadschedules", "ost_hvac_load_schedules",
        # Room/area separation (lines, not geometry)
        "ost_roomseparationlines", "ost_areaschemes",
    }

    elements: list[dict[str, Any]] = []
    storeys_set: set[str] = set()
    disciplines_set: set[str] = set()

    # Patch DDC COLLADA node names: DDC writes name="node" for every element
    # but the frontend ColladaLoader uses `name` (not `id`) for Object3D.name.
    # Without this patch, mesh_ref matching in the 3D viewer is 0%.
    if real_dae_path and real_dae_path.exists():
        _patch_collada_node_names(real_dae_path)

    # Pre-parse the DAE (if provided) to extract per-node bounding boxes
    # keyed by the numeric Revit ElementId written into <node id="...">.
    dae_bboxes: dict[int, dict[str, float]] = {}
    if real_dae_path and real_dae_path.exists():
        try:
            dae_bboxes = _extract_dae_bboxes_by_node_id(real_dae_path)
            logger.info(
                "Extracted %d per-element bounding boxes from DAE",
                len(dae_bboxes),
            )
        except Exception as exc:
            logger.warning("Failed to extract DAE bboxes: %s", exc)

    for i, row in enumerate(raw_elements):
        # Normalize keys to lowercase for tolerant lookup
        lc_row = {k.lower(): v for k, v in row.items()}

        category = lc_row.get("category")
        cat_lower = str(category or "").lower()

        # Skip non-element rows: those with no category at all (likely orphan
        # parameter rows from the DDC converter), and known non-element categories.
        # DDC writes the literal string "None" for elements without a Revit
        # category — treat it the same as Python None.
        if not category or cat_lower in SKIP_CATEGORIES or cat_lower in ("none", "null", "", "n/a"):
            continue

        # Friendly element type derived from OST_ category name.
        # DDC writes raw Revit built-in category names like
        # "OST_CurtainWallMullions" — we strip the prefix, split
        # CamelCase into words, and title-case the result so the
        # filter panel shows "Curtain Wall Mullions" instead of
        # "Curtainwallmullions".
        if cat_lower.startswith("ost_"):
            raw_name = str(category)[4:]  # preserve original casing
            # Split CamelCase: "CurtainWallMullions" → "Curtain Wall Mullions"
            spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", raw_name)
            spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
            etype = spaced.replace("_", " ").strip()
        else:
            etype = str(category) if category else "Unknown"

        # Best-effort name resolution
        name = (
            lc_row.get("name")
            or lc_row.get("type name")
            or lc_row.get("family name")
            or lc_row.get("mark")
            or f"{etype}-{i}"
        )
        name = str(name)[:200]

        # Storey: DDC writes the actual building level under "Level" for most
        # categories, but walls/columns sometimes only fill "Base Constraint"
        # or "Reference Level". Fall back through all known synonyms.
        storey = (
            lc_row.get("level")
            or lc_row.get("storey")
            or lc_row.get("buildingstorey")
            or lc_row.get("building storey")
            or lc_row.get("base constraint")
            or lc_row.get("base level")
            or lc_row.get("reference level")
            or lc_row.get("schedule level")
            or lc_row.get("associated level")
            or ""
        )
        storey = str(storey).strip() if storey else ""
        if storey.lower() == "none":
            storey = ""

        discipline = _classify_discipline(etype)
        if storey:
            storeys_set.add(storey)
        disciplines_set.add(discipline)

        # Numeric quantity fields — handle Revit native (mm/m²/m³) units.
        # DDC Excel columns have exact names; we map them all.
        quantities: dict[str, float] = {}
        for src_key, dest_key in (
            ("length", "Length"), ("area", "Area"), ("volume", "Volume"),
            ("width", "Width"), ("height", "Height"), ("thickness", "Thickness"),
            ("perimeter", "Perimeter"), ("count", "Count"),
            ("gross area", "Gross Area"), ("gross volume", "Gross Volume"),
            ("floor area", "Floor Area"), ("floor volume", "Floor Volume"),
            ("surface area", "Surface Area"),
            ("cut length", "Cut Length"), ("unconnected height", "Unconnected Height"),
            # DDC IfcExporter uses [BaseQuantities] prefix
            ("[basequantities] length", "Length"),
            ("[basequantities] width", "Width"),
            ("[basequantities] height", "Height"),
            ("[basequantities] area", "Area"),
            ("[basequantities] volume", "Volume"),
            ("overallwidth", "Width"), ("overallheight", "Height"),
        ):
            val = lc_row.get(src_key)
            if val is None:
                continue
            try:
                fval = float(val)
                if fval != 0.0:
                    quantities[dest_key] = fval
            except (ValueError, TypeError):
                pass

        # Stable ID — prefer Revit uniqueid, fall back to type ifcguid, then row index
        stable_id = str(
            lc_row.get("uniqueid")
            or lc_row.get("type ifcguid")
            or lc_row.get("globalid")
            or lc_row.get("id")
            or i
        )

        # mesh_ref — numeric Revit ElementId that matches the DAE <node id="...">.
        # DDC's Excel ``ID`` column IS ``Element.Id.IntegerValue``. If it is
        # missing we can still recover it from the last segment of ``UniqueId``
        # (which encodes the ElementId in hex).
        mesh_ref_int = _extract_revit_element_id(lc_row)
        mesh_ref: str | None = str(mesh_ref_int) if mesh_ref_int is not None else None

        # Bounding box — DDC RvtExporter Excel does NOT emit bbox columns at
        # all, so we compute bbox per element from the DAE geometry (in metres;
        # COLLADA is unit-normalised by DDC).
        bbox: dict[str, float] | None = None
        if mesh_ref_int is not None:
            bbox = dae_bboxes.get(mesh_ref_int)

        # Properties: preserve EVERY DDC column from the dataframe so the
        # viewer never loses information.  Only skip keys that are
        # genuinely duplicated as top-level fields (id → stable_id,
        # category → element_type, name → name) or in the dedicated
        # ``quantities`` map (length, area, volume, …).  Keys like
        # "design option", "workset", "versionguid" are intentionally kept
        # because designers do query them and dropping them silently
        # destroys data the user explicitly asked to preserve.
        DUPLICATE_PROP_KEYS = {
            # Already in stable_id
            "id", "uniqueid", "globalid", "type ifcguid",
            # Already in element_type
            "category",
            # Already in top-level name
            "name",
            # Already in quantities map (BuiltIn measurement params)
            "length", "area", "volume", "width", "height", "thickness",
            "perimeter", "count",
            "gross area", "gross volume", "floor area", "floor volume",
            "surface area", "cut length", "unconnected height",
            # IFC BaseQuantities mirrors of the above
            "[basequantities] length", "[basequantities] width",
            "[basequantities] height", "[basequantities] area",
            "[basequantities] volume",
        }
        properties: dict[str, str] = {}
        for k, v in row.items():
            if k.lower() in DUPLICATE_PROP_KEYS:
                continue
            if v is None:
                continue
            sval = str(v).strip()
            # Drop only truly empty values; keep "0" because for some Revit
            # parameters (e.g. counts, structural flags) zero is meaningful.
            if not sval or sval.lower() in ("none", "null", "n/a"):
                continue
            # Cap value length to keep payloads reasonable
            properties[k] = sval[:500]

        # Promote Revit hierarchy fields into properties under clean keys
        # so the frontend can build Category -> Family -> Type Name trees.
        # Use the friendly etype (with spaces) rather than the raw OST_ name.
        if etype and etype.lower() not in ("none", "null", "n/a", "-", "unknown"):
            properties["category"] = etype
        raw_family = lc_row.get("family name") or lc_row.get("familyname") or ""
        raw_family = str(raw_family).strip()
        if raw_family and raw_family.lower() not in ("none", "null", "n/a", "-"):
            properties["family"] = raw_family
        raw_type_name = lc_row.get("type name") or lc_row.get("typename") or ""
        raw_type_name = str(raw_type_name).strip()
        if raw_type_name and raw_type_name.lower() not in ("none", "null", "n/a", "-"):
            properties["type_name"] = raw_type_name

        # ENSURE critical DDC columns are stored in properties under clean keys,
        # even if the generic property loop above missed them (capped, filtered, etc.).
        _KEY_DDC_COLUMNS = {
            "level": "level", "base constraint": "base_constraint",
            "base level": "base_level", "top level": "top_level",
            "top constraint": "top_constraint",
            "fire rating": "fire_rating", "material": "material",
            "phase": "phase", "phase created": "phase_created",
            "assembly code": "assembly_code",
            "assembly description": "assembly_description",
            "type mark": "type_mark", "mark": "mark",
            "structural": "structural", "function": "function",
            "family and type": "family_and_type",
            "cost": "cost", "keynote": "keynote",
            "comments": "comments", "description": "description",
            "type comments": "type_comments",
        }
        for ddc_key, prop_key in _KEY_DDC_COLUMNS.items():
            if prop_key in properties:
                continue  # already populated by generic loop or hierarchy promotion
            val = lc_row.get(ddc_key)
            if val is not None:
                sval = str(val).strip()
                if sval and sval.lower() not in ("none", "0", ""):
                    properties[prop_key] = sval[:500]

        # Cap properties at 30 entries to keep per-element payloads small —
        # Revit/IFC exports often expose 100+ parameters, most irrelevant.
        # Priority order: critical DDC/hierarchy keys win, then remaining
        # properties by insertion order (stable output across runs).
        _PRIORITY_KEYS = (
            "category", "family", "type_name", "level",
            "material", "fire_rating", "phase",
            "assembly_code", "assembly_description", "mark", "type_mark",
        )
        if len(properties) > 30:
            priority = {k: properties[k] for k in _PRIORITY_KEYS if k in properties}
            remaining_budget = 30 - len(priority)
            extras: dict[str, str] = {}
            for k, v in properties.items():
                if k in priority:
                    continue
                if len(extras) >= remaining_budget:
                    break
                extras[k] = v
            properties = {**priority, **extras}

        elements.append({
            "stable_id": stable_id,
            "element_type": etype,
            "name": name,
            "storey": storey or None,
            "discipline": discipline,
            "properties": properties,
            "quantities": quantities,
            "geometry_hash": hashlib.md5(f"{stable_id}:{etype}:{name}".encode()).hexdigest()[:16],
            "bounding_box": bbox,
            "mesh_ref": mesh_ref,
        })

    # Geometry: prefer the real Revit COLLADA from the second DDC pass.
    # Fall back to the simplified box-grid only when the real .dae is missing.
    geometry_path: Path | None = None
    bounding_box = None
    if real_dae_path and real_dae_path.exists() and real_dae_path.stat().st_size > 0:
        # Already named geometry.dae in output_dir — use as-is.
        geometry_path = real_dae_path
        logger.info(
            "Using real Revit COLLADA geometry: %s (%d KB)",
            real_dae_path.name, real_dae_path.stat().st_size // 1024,
        )
    elif elements:
        try:
            geometry_path, bounding_box = _generate_collada_boxes(elements, output_dir)
            logger.info("Generated placeholder box geometry (no real COLLADA available)")
        except Exception as e:
            logger.warning("COLLADA box generation failed: %s", e)

    # Convert DAE → GLB for 2x smaller transfer + faster browser parsing.
    # trimesh loses COLLADA node names, but we patch them back into the
    # GLB JSON chunk using the original DAE node IDs (0.09s overhead).
    glb_path: Path | None = None
    if geometry_path and geometry_path.exists():
        # Pre-validate the DAE before conversion. A broken DAE (missing
        # <visual_scene>, malformed XML, etc.) produces a broken GLB and
        # a broken frontend load. Drop the geometry path and let the
        # viewer render the bbox placeholders instead.
        ok, reason = _validate_geometry_file(geometry_path)
        if not ok:
            logger.warning(
                "Generated DAE failed validation (%s): %s — dropping geometry path",
                geometry_path.name, reason,
            )
            geometry_path = None
        else:
            glb_path = _convert_dae_to_glb(geometry_path, output_dir)
            if glb_path is not None:
                ok, reason = _validate_geometry_file(glb_path)
                if not ok:
                    logger.warning(
                        "Generated GLB failed validation (%s): %s — dropping GLB path",
                        glb_path.name, reason,
                    )
                    glb_path = None

    # Re-check the real-dae flag after validation dropped invalid files.
    # If validation nuked the real DAE path above, ``geometry_path`` will
    # be None even though ``real_dae_path`` originally existed, so we
    # treat that as placeholder for the purpose of the metadata flag.
    is_real = bool(
        real_dae_path and real_dae_path.exists() and geometry_path == real_dae_path
    )
    if not is_real:
        # When DDC produced an Excel pass but no real .dae, we generated
        # placeholder boxes — tag the elements so downstream consumers can
        # warn the user.
        for elem in elements:
            elem["is_placeholder"] = True

    return {
        "elements": elements,
        "storeys": sorted(storeys_set),
        "disciplines": sorted(disciplines_set),
        "element_count": len(elements),
        "has_geometry": geometry_path is not None,
        "geometry_path": str(geometry_path) if geometry_path else None,
        "glb_path": str(glb_path) if glb_path else None,
        "bounding_box": bounding_box,
        "geometry_type": "real" if is_real else "placeholder",
        "geometry_quality": "real" if is_real else "placeholder",
        # Full DDC dataframe (all 1000+ columns) for Parquet cold storage.
        # The hot table only keeps ~12 indexed fields; analytical queries
        # run against the Parquet via DuckDB.
        "raw_elements": raw_elements,
    }


def _dae_element_bboxes(
    dae_path: Path,
) -> tuple[dict[str, tuple[float, float, float, float, float, float]], dict[str, str]]:
    """Parse a DDC COLLADA file and return per-element bounding boxes.

    Returns:
        element_bboxes: ``{element_id: (min_x, min_y, min_z, max_x, max_y, max_z)}``
        element_to_shape: ``{element_id: shape_id}`` (for diagnostics).

    The DDC ``RvtExporter`` writes one top-level
    ``<visual_scene>/<node id="{RevitElementId}">`` per element, each with a
    single ``<instance_geometry url="#shapeN-lib">`` pointing at the shape
    definition in ``<library_geometries>``.  We read every shape's
    ``<float_array>`` of positions to compute its axis-aligned bbox.  Under
    ``trimesh`` vertex-deduplication the count changes, but bbox is invariant
    (it's derived from coordinate extrema), which makes it a stable
    fingerprint for matching DAE shapes back to GLB meshes.
    """
    element_bboxes: dict[str, tuple[float, float, float, float, float, float]] = {}
    element_to_shape: dict[str, str] = {}
    try:
        tree = safe_ET.parse(str(dae_path))
    except ET.ParseError as exc:
        logger.debug("DAE bbox extraction: XML parse error: %s", exc)
        return element_bboxes, element_to_shape

    ns = {"c": _COLLADA_NS}
    geoms = {
        g.get("id", ""): g
        for g in tree.findall(".//c:library_geometries/c:geometry", ns)
    }

    def _shape_bbox(
        shape_id: str,
    ) -> tuple[float, float, float, float, float, float] | None:
        g = geoms.get(shape_id)
        if g is None:
            return None
        # DDC writes positions as the first <source>/<float_array> inside <mesh>.
        fa = g.find("c:mesh/c:source/c:float_array", ns)
        if fa is None or not fa.text:
            return None
        try:
            vals = [float(x) for x in fa.text.split()]
        except ValueError:
            return None
        if len(vals) < 3:
            return None
        xs = vals[0::3]
        ys = vals[1::3]
        zs = vals[2::3]
        return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))

    for node in tree.findall(".//c:visual_scene/c:node", ns):
        nid = node.get("id", "") or ""
        # Only numeric ids — Revit ElementId. Lights/cameras/named nodes skipped.
        if not nid.isdigit():
            continue
        ig = node.find("c:instance_geometry", ns)
        if ig is None:
            continue
        shape_id = (ig.get("url", "") or "").lstrip("#")
        if not shape_id:
            continue
        bb = _shape_bbox(shape_id)
        if bb is None:
            continue
        element_bboxes[nid] = bb
        element_to_shape[nid] = shape_id

    return element_bboxes, element_to_shape


def _validate_geometry_file(geom_path: Path) -> tuple[bool, str]:
    """Sanity-check a DAE or GLB file produced by the pipeline.

    Returns ``(ok, reason)``. When ``ok`` is False the caller should
    treat the file as corrupt and drop the path before returning it to
    the frontend — surfacing a broken file to the BIM viewer manifests
    as an opaque ``Cannot read properties of undefined (reading
    'getAttribute')`` JS error deep inside Three.js's loader, which the
    user cannot diagnose. We re-parse the file's surface structure here
    so that failure becomes a server-side ``geometry_type=placeholder``
    fallback instead.

    Checks (cheap, file-shape only — no full mesh re-parse):

    - File exists and size > 200 bytes (smaller than any legal output)
    - GLB: starts with the 4-byte magic ``glTF`` (0x67 0x6c 0x54 0x46)
      and the version field is 2
    - DAE: parses as XML via defusedxml and has a ``<COLLADA>`` root tag
      with at least one ``<visual_scene>`` descendant
    """
    if not geom_path.exists():
        return False, "file does not exist"
    size = geom_path.stat().st_size
    if size < 200:
        return False, f"file suspiciously small ({size} bytes)"

    ext = geom_path.suffix.lower()
    if ext == ".glb":
        try:
            with geom_path.open("rb") as fh:
                head = fh.read(12)
            if len(head) < 12:
                return False, "GLB header truncated"
            if head[:4] != b"glTF":
                return False, f"GLB magic mismatch (got {head[:4]!r})"
            import struct
            version = struct.unpack("<I", head[4:8])[0]
            if version != 2:
                return False, f"unsupported GLB version {version}"
            return True, "ok"
        except Exception as exc:
            return False, f"GLB inspect failed: {exc}"

    if ext == ".dae":
        try:
            # defusedxml protects against XXE/billion-laughs.
            tree = safe_ET.parse(str(geom_path))
            root = tree.getroot()
        except Exception as exc:
            return False, f"DAE not well-formed XML: {exc}"
        # COLLADA's root tag is namespaced. Compare the local-name only so
        # we tolerate any prefix and any schema version.
        local = root.tag.rsplit("}", 1)[-1].lower()
        if local != "collada":
            return False, f"root tag is <{local}>, expected <COLLADA>"
        # Require at least one visual_scene — a COLLADA with only
        # libraries and no scene is renderable as nothing.
        ns = {"c": _COLLADA_NS}
        if root.find(".//c:visual_scene", ns) is None:
            # Some exporters drop the namespace; check without it too.
            if root.find(".//visual_scene") is None:
                return False, "no <visual_scene> in DAE"
        return True, "ok"

    return True, "unknown extension; skipped checks"


def _convert_dae_to_glb(dae_path: Path, output_dir: Path) -> Path | None:
    """Convert a COLLADA .dae file to binary glTF (.glb) using trimesh.

    For DAE files larger than ``MAX_DAE_FOR_GLB_BYTES`` (default 250 MB)
    we skip the conversion entirely: trimesh loads the whole mesh into
    Python memory and routinely OOMs on a 200+ MB DAE produced from a
    large Revit model (Hugo Lee / Glodon, 204MB RVT). The browser can
    still load the raw DAE — it's ~3x larger over the wire but parses
    fine in ColladaLoader on a modern desktop.

    Returns the GLB path on success, ``None`` on failure.  Failure is
    non-fatal — the DAE file remains available as a fallback.

    Trimesh handles DAE -> GLB natively (via collada-exporter + numpy).
    Typical conversion: 32 MB DAE -> 9.5 MB GLB (3.4x smaller).
    With server-side gzip the transfer shrinks to ~1.7 MB (19x smaller).

    **Important**: trimesh.load() on DAE files does NOT guarantee that GLB
    ``node.name`` still corresponds to the mesh at ``node.mesh``.  Trimesh
    internally reorders/regroups meshes by material, so the node-name and
    mesh-geometry pairing is unreliable (observed in the wild: node named
    "135248" pointing at the roof geometry of element 140056, and vice-versa).

    We therefore rebuild the name↔geometry pairing post-export by matching
    each GLB mesh's POSITION bbox against the per-element bboxes parsed
    directly from the DAE ``<visual_scene>/<node>/<instance_geometry>``
    chain.  Bounding boxes survive trimesh's vertex-deduplication /
    primitive-splitting unchanged, making them a robust fingerprint.
    """
    # Hard size guard — trimesh.load() materialises the entire mesh
    # graph into Python memory; on a 200+ MB DAE (typical for a 200+ MB
    # RVT through DDC) it routinely OOMs or thrashes for 5+ minutes.
    # Skip the conversion and let the frontend ColladaLoader stream the
    # DAE directly — slower over the wire, but it actually works.
    MAX_DAE_FOR_GLB_BYTES = 250 * 1024 * 1024  # 250 MB
    try:
        dae_size = dae_path.stat().st_size
    except OSError:
        dae_size = 0
    if dae_size > MAX_DAE_FOR_GLB_BYTES:
        logger.info(
            "DAE is %d MB (>%d MB threshold) — skipping GLB conversion "
            "and serving DAE directly to avoid trimesh OOM",
            dae_size // (1024 * 1024),
            MAX_DAE_FOR_GLB_BYTES // (1024 * 1024),
        )
        return None

    glb_target = (output_dir / "geometry.glb").resolve()
    try:
        import trimesh

        scene = trimesh.load(str(dae_path))
        glb_data: bytes = scene.export(file_type="glb")  # type: ignore[union-attr]

        # Post-process: reassign GLB node/mesh names using bbox matching
        # against DAE shapes.  This replaces the previous approach which
        # blindly trusted trimesh's scene-graph names.
        try:
            import json as _json
            import struct as _struct

            element_bboxes, _element_to_shape = _dae_element_bboxes(dae_path)
            if element_bboxes:
                # Parse GLB: header(12) + json_chunk_header(8) + json
                json_len = _struct.unpack("<I", glb_data[12:16])[0]
                gltf = _json.loads(glb_data[20 : 20 + json_len])
                glb_nodes = gltf.get("nodes", [])
                glb_meshes = gltf.get("meshes", [])
                accessors = gltf.get("accessors", [])

                def _mesh_bbox(
                    mesh_idx: int,
                ) -> tuple[float, float, float, float, float, float] | None:
                    """Union bbox over every primitive's POSITION accessor."""
                    if mesh_idx >= len(glb_meshes):
                        return None
                    primitives = glb_meshes[mesh_idx].get("primitives", [])
                    lo = [float("inf")] * 3
                    hi = [float("-inf")] * 3
                    any_found = False
                    for prim in primitives:
                        pos_idx = prim.get("attributes", {}).get("POSITION")
                        if pos_idx is None or pos_idx >= len(accessors):
                            continue
                        acc = accessors[pos_idx]
                        mn = acc.get("min")
                        mx = acc.get("max")
                        if not mn or not mx or len(mn) < 3 or len(mx) < 3:
                            continue
                        for i in range(3):
                            if mn[i] < lo[i]:
                                lo[i] = mn[i]
                            if mx[i] > hi[i]:
                                hi[i] = mx[i]
                        any_found = True
                    if not any_found:
                        return None
                    return (lo[0], lo[1], lo[2], hi[0], hi[1], hi[2])

                # Build a spatial bucket over DAE element bboxes keyed by
                # rounded bbox-center.  This turns O(N*M) into O(N+M) for
                # typical models (5k+ elements).  Collisions are resolved by
                # scoring all candidates in the bucket.
                def _key(
                    bb: tuple[float, float, float, float, float, float],
                ) -> tuple[int, int, int]:
                    # 0.5-unit bucket — trimesh preserves coords exactly, so
                    # the match is effectively exact; the bucket is only a
                    # prefilter for speed.
                    cx = (bb[0] + bb[3]) * 0.5
                    cy = (bb[1] + bb[4]) * 0.5
                    cz = (bb[2] + bb[5]) * 0.5
                    return (int(cx * 2), int(cy * 2), int(cz * 2))

                buckets: dict[tuple[int, int, int], list[str]] = {}
                for eid, bb in element_bboxes.items():
                    buckets.setdefault(_key(bb), []).append(eid)

                def _score(
                    a: tuple[float, float, float, float, float, float],
                    b: tuple[float, float, float, float, float, float],
                ) -> float:
                    return sum(abs(a[i] - b[i]) for i in range(6))

                # Size of a typical model is ~5k elements; searching all
                # buckets in a 1-unit radius is cheap and handles float
                # rounding at bucket boundaries.
                def _find_element(
                    bb: tuple[float, float, float, float, float, float],
                ) -> tuple[str | None, float]:
                    k = _key(bb)
                    best_eid: str | None = None
                    best_score = float("inf")
                    for dx in (-1, 0, 1):
                        for dy in (-1, 0, 1):
                            for dz in (-1, 0, 1):
                                neighbors = buckets.get((k[0] + dx, k[1] + dy, k[2] + dz))
                                if not neighbors:
                                    continue
                                for eid in neighbors:
                                    s = _score(bb, element_bboxes[eid])
                                    if s < best_score:
                                        best_score = s
                                        best_eid = eid
                    return best_eid, best_score

                # Tolerance: trimesh preserves coordinates exactly, so a
                # perfect match is ~0.  We accept up to 0.01 (1 cm summed
                # over 6 floats) to tolerate float round-trips.
                match_tol = 0.01
                matched = 0
                total_mesh_nodes = 0
                assigned_mesh: set[int] = set()
                for node in glb_nodes:
                    if "mesh" not in node:
                        continue
                    total_mesh_nodes += 1
                    mi = node["mesh"]
                    mb = _mesh_bbox(mi)
                    if mb is None:
                        continue
                    eid, s = _find_element(mb)
                    if eid is not None and s <= match_tol:
                        node["name"] = eid
                        if mi not in assigned_mesh and mi < len(glb_meshes):
                            glb_meshes[mi]["name"] = eid
                            assigned_mesh.add(mi)
                        matched += 1

                logger.info(
                    "GLB post-process: bbox-matched %d/%d mesh nodes to "
                    "DAE element ids (of %d DAE elements)",
                    matched,
                    total_mesh_nodes,
                    len(element_bboxes),
                )

                if matched > 0:
                    # Rebuild GLB with patched JSON
                    new_json = _json.dumps(gltf, separators=(",", ":")).encode("utf-8")
                    # Pad to 4-byte alignment
                    while len(new_json) % 4:
                        new_json += b" "
                    bin_offset = 20 + json_len
                    # Find binary chunk
                    bin_chunk = glb_data[bin_offset:]
                    total = 12 + 8 + len(new_json) + len(bin_chunk)
                    glb_data = (
                        _struct.pack("<III", 0x46546C67, 2, total)
                        + _struct.pack("<II", len(new_json), 0x4E4F534A)
                        + new_json
                        + bin_chunk
                    )
        except Exception as patch_err:  # noqa: BLE001 — non-fatal post-process
            logger.debug("GLB node-name patching skipped: %s", patch_err, exc_info=True)

        glb_target.write_bytes(glb_data)

        if glb_target.stat().st_size > 1000:
            logger.info(
                "GLB conversion: %d bytes DAE -> %d bytes GLB (%.1fx smaller)",
                dae_path.stat().st_size,
                glb_target.stat().st_size,
                dae_path.stat().st_size / max(glb_target.stat().st_size, 1),
            )
            return glb_target

        logger.warning(
            "GLB conversion produced a suspiciously small file (%d bytes)",
            glb_target.stat().st_size,
        )
    except ImportError:
        logger.warning("GLB conversion skipped: trimesh not installed (pip install trimesh)")
    except Exception as exc:
        logger.warning("GLB conversion failed: %s", exc, exc_info=True)
    return None


def process_ifc_file(
    ifc_path: Path,
    output_dir: Path,
    conversion_depth: str = "standard",
) -> dict[str, Any]:
    """Process an IFC/RVT file.

    Pipeline:
    1. Try DDC cad2data (full conversion with geometry)
    2. Fallback: text-based IFC parser (elements only, box geometry)

    Args:
        conversion_depth: 'standard' (~15 key columns, faster) or
            'complete' (~1000+ Revit parameters, slower). Passed
            to the DDC converter as the export mode argument.

    Returns dict with elements, storeys, disciplines, geometry info.
    """
    # Step 1: Try cad2data
    cad_result = _try_cad2data(ifc_path, output_dir, conversion_depth=conversion_depth)
    if cad_result and cad_result["element_count"] > 0:
        logger.info("cad2data conversion successful: %d elements", cad_result["element_count"])
        return cad_result

    # Step 2: Fallback to text parser (IFC only)
    ext = ifc_path.suffix.lower()
    if ext != ".ifc":
        logger.warning("Text parser only supports IFC, not %s. Use cad2data for RVT.", ext)
        return _empty_result()

    try:
        content = ifc_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.error("Failed to read IFC file %s: %s", ifc_path, e)
        return _empty_result()

    # Verify it's IFC
    if not content.strip().startswith("ISO-10303-21") and "%PDF" not in content[:20]:
        # Try to detect if it's at least STEP format
        if "HEADER;" not in content[:500] and "DATA;" not in content[:2000]:
            logger.warning("File does not appear to be valid IFC: %s", ifc_path.name)
            return _empty_result()

    logger.info("Processing IFC (text parser): %s (%d bytes)", ifc_path.name, len(content))

    # Parse all entities.
    #
    # Bugfix (C5): split by ';' instead of '\n'. STEP-21 statements are
    # terminated by ';', and exporters routinely write multi-line entities
    # (large IFCRELAGGREGATES, IFCPOLYLOOP, IFCINDEXEDPOLYCURVE). Splitting
    # by newline lost those entities silently — only single-line
    # statements were ever parsed.
    #
    # Bugfix (C6): strip /* … */ comments before tokenising. Tekla/Allplan
    # exports embed comments with #N-style references that would otherwise
    # match _LINE_RE and produce false phantom entities.
    #
    # Bugfix (C1): replace '' (doubled apostrophe = escaped quote in
    # STEP-21) with a placeholder before regex tokenisation so apostrophes
    # inside string bodies do not terminate the match prematurely. The
    # placeholder is restored to a single ' by _decode_step_string when
    # individual fields are extracted.
    #
    # Get rid of inline /* */ blocks (multi-line safe).
    content_clean = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
    # Escape doubled-apostrophes so they survive regex tokenisation.
    content_clean = content_clean.replace("''", _STEP_DOUBLE_QUOTE_PLACEHOLDER)
    entities: dict[int, dict] = {}
    for raw in content_clean.split(";"):
        line = raw.strip()
        if not line.startswith("#"):
            continue
        # The closing ';' is now implicit (we split on it). Re-add for the
        # _LINE_RE pattern below.
        m = _LINE_RE.match(line + ";")
        if m:
            eid = int(m.group(1))
            etype = m.group(2).upper()
            args_str = m.group(3)
            entities[eid] = {
                "id": eid,
                "type": etype,
                "args_raw": args_str,
                "strings": [
                    _decode_step_string(s) for s in _STRING_RE.findall(args_str)
                ],
            }

    logger.info("Parsed %d IFC entities", len(entities))

    # Audit C2 v3 — full ISO 16739-1 §5.4.3 IFCUNITASSIGNMENT parser.
    #
    # The text-fallback used to only PROBE units (flag non-SI files,
    # refuse to roll their numbers into a BOQ).  As of v3.0.2 we
    # actually parse the unit assignment, resolve every per-dimension
    # unit through SI prefixes and IFCMEASUREWITHUNIT conversion
    # factors, and apply the resulting scale table to every IfcQuantity
    # so the output is always in canonical SI.  See _parse_unit_assignment.
    #
    # ``unit_uncertain`` is preserved for back-compat: it's now ``True``
    # iff the file shipped without an IFCUNITASSIGNMENT block at all
    # (legacy Allplan/Tekla exporter bug) — in that case we DO fall
    # back to metric defaults per ISO 16739, but downstream callers
    # may still want to flag the file for review.
    unit_ctx = _parse_unit_assignment(entities)
    unit_uncertain = not unit_ctx.had_assignment
    if unit_uncertain:
        logger.warning(
            "IFC text-fallback: file has no IFCUNITASSIGNMENT block. "
            "Falling back to ISO 16739 metric defaults (m, m^2, m^3, kg). "
            "Quantities will be marked unit_uncertain=True."
        )
    elif not unit_ctx.is_canonical:
        logger.info(
            "IFC text-fallback: declared units rescaled to canonical SI "
            "(unit_system=%s, length_scale=%.6g)",
            unit_ctx.unit_system,
            unit_ctx.scale_for.get("LENGTHUNIT", 1.0),
        )

    # Extract storeys (IFC2x3 IfcBuildingStorey + IFC4x3 facility parts)
    storeys: dict[int, str] = {}
    for eid, ent in entities.items():
        if ent["type"] in _STOREY_TYPES:
            name = ent["strings"][1] if len(ent["strings"]) > 1 else f"Storey-{eid}"
            storeys[eid] = name

    # Extract spatial containment (IfcRelContainedInSpatialStructure)
    element_to_storey: dict[int, str] = {}
    for ent in entities.values():
        if ent["type"] == "IFCRELCONTAINEDINSPATIALSTRUCTURE":
            # Last arg before closing is the spatial element ref
            refs = re.findall(r"#(\d+)", ent["args_raw"])
            if refs:
                spatial_id = int(refs[-1])
                storey_name = storeys.get(spatial_id, "")
                # All other refs (except first 4 standard args) are contained elements
                for ref_str in refs[:-1]:
                    ref_id = int(ref_str)
                    if ref_id in entities and storey_name:
                        element_to_storey[ref_id] = storey_name

    # Extract building elements
    elements: list[dict[str, Any]] = []
    storeys_set: set[str] = set()
    disciplines_set: set[str] = set()

    for eid, ent in entities.items():
        if ent["type"] in _ELEMENT_TYPES:
            strings = ent["strings"]
            global_id = strings[0] if strings else str(eid)
            name = strings[1] if len(strings) > 1 else ""

            ifc_type = ent["type"]
            discipline = _classify_discipline(ifc_type)
            storey = element_to_storey.get(eid, "")
            simplified_type = _simplify_type(ifc_type)

            if storey:
                storeys_set.add(storey)
            disciplines_set.add(discipline)

            # Extract quantities from related IfcElementQuantity (simplified).
            # Audit C2 — pass the unit context so values are returned in
            # canonical SI (m, m², m³, kg, s) regardless of declared units.
            quantities = _extract_quantities_for_element(eid, entities, unit_ctx)

            geo_hash = hashlib.md5(f"{global_id}:{ifc_type}:{name}".encode()).hexdigest()[:16]

            elements.append({
                "stable_id": global_id,
                "element_type": simplified_type,
                "name": name or simplified_type,
                "storey": storey or None,
                "discipline": discipline,
                "properties": {"ifc_type": ifc_type, "ifc_id": eid},
                "quantities": quantities,
                # Audit C2 — propagate the unit-assignment probe result
                # so downstream code (validation rules, BOQ aggregator,
                # frontend viewer) can decide whether to trust these
                # numbers. True when units are not canonical SI metres
                # OR when no LENGTHUNIT row is declared at all.
                "unit_uncertain": unit_uncertain,
                "geometry_hash": geo_hash,
                # Both bbox and mesh_ref are populated post-loop from the
                # placeholder COLLADA we generate (node id = "n{index}").
                "bounding_box": None,
                "mesh_ref": None,
            })

    # Try to extract real placement coordinates from IFC before generating geometry
    _extract_placements(elements, entities)

    # Generate simplified COLLADA
    geometry_path = None
    has_geometry = False
    bounding_box = None

    if elements:
        try:
            geometry_path, bounding_box = _generate_collada_boxes(elements, output_dir)
            has_geometry = geometry_path is not None
        except Exception as e:
            logger.warning("COLLADA generation failed: %s", e)

    logger.info(
        "IFC text-parsed: %d elements, %d storeys, %d disciplines",
        len(elements), len(storeys_set), len(disciplines_set),
    )

    # Tag every element with `is_placeholder=True` so downstream consumers
    # (frontend viewer, validation rules) can distinguish synthesized boxes
    # from real DDC-converted geometry. This branch is reached ONLY when
    # the DDC cad2data binary is unavailable AND the input is a text-IFC,
    # so every element here has a placeholder bounding box.
    for elem in elements:
        elem["is_placeholder"] = True

    # Audit C2 — surface the resolved unit system + scale table in
    # canonical.metadata.units so the BOQ aggregator, validation
    # rules, and the frontend viewer all see the same authoritative
    # answer.  ``unit_system`` is one of "metric" / "imperial" /
    # "mixed" / "unknown"; ``scale_table`` is the per-dimension
    # multiplier that was applied to extracted quantities (1.0
    # means the source was already in canonical SI).
    metadata_units = {
        "unit_system": unit_ctx.unit_system,
        "had_assignment": unit_ctx.had_assignment,
        "is_canonical": unit_ctx.is_canonical,
        "currency_code": unit_ctx.currency_code,
        "scale_table": dict(unit_ctx.scale_for),
        "label_table": dict(unit_ctx.label_for),
        "canonical_base": dict(_CANONICAL_SI_BASE),
    }

    return {
        "elements": elements,
        "storeys": sorted(storeys_set),
        "disciplines": sorted(disciplines_set),
        "element_count": len(elements),
        "has_geometry": has_geometry,
        "geometry_path": str(geometry_path) if geometry_path else None,
        "bounding_box": bounding_box,
        "geometry_type": "placeholder",
        # Top-level quality flag — read by the bim_hub router and copied
        # into BIMModel.metadata_ so the frontend can show a "placeholder
        # geometry" banner without having to inspect every element.
        "geometry_quality": "placeholder",
        # Audit C2 — back-compat flag.  True iff the file shipped
        # without any IFCUNITASSIGNMENT block (legacy exporter bug).
        # The new parser still produces canonical-SI quantities by
        # falling back to ISO 16739 defaults, but downstream consumers
        # may still want to flag the file for human review.
        "unit_uncertain": unit_uncertain,
        # Audit C2 v3 — full parsed unit context surfaced for
        # downstream consumers (frontend viewer label, validation
        # rules, BOQ aggregator).  Schema is documented on
        # canonical.metadata.units in bim_hub/schemas.py.
        "metadata": {
            "units": metadata_units,
        },
    }


# ─── IFC unit-assignment parser (audit C2 v3 — full ISO 16739-1 §5.4.3) ──
#
# Earlier revisions of this module shipped a "probe" that merely flagged
# files with non-SI-metre length units and refused to roll their numbers
# into a BOQ.  That was safe but useless: roughly a third of real-world
# Revit/Allplan exports ship in millimetres or feet and the UI ended up
# rejecting them all.
#
# This rewrite (per ISO 16739-1:2024 §5.4.3) parses IFCUNITASSIGNMENT in
# full, resolves every per-dimension unit through SI prefixes and
# IFCMEASUREWITHUNIT conversion factors, and applies the resulting scale
# table to every IfcQuantity*.  Result: extracted quantities are always
# expressed in canonical SI (m, m², m³, kg, s, rad, J, Pa, Hz) regardless
# of the source file's preference.
#
# The old ``_ifc_units_are_non_si_metres`` probe is kept around for
# backward compatibility (the v3.0.0 regression tests still call it) but
# is now a thin wrapper over the new ``_parse_unit_assignment``.

# IFC unit-type tokens (per ISO 16739-1 IfcUnitEnum + IfcDerivedUnitEnum).
_IFC_UNIT_TYPES: tuple[str, ...] = (
    "LENGTHUNIT", "AREAUNIT", "VOLUMEUNIT", "MASSUNIT",
    "TIMEUNIT", "PLANEANGLEUNIT", "SOLIDANGLEUNIT",
    # PLANEANGLEUNIT is the spec spelling; ANGLEUNIT is a common shorthand
    # that some exporters (older Tekla) emit. We accept both.
    "ANGLEUNIT",
    "TEMPERATUREUNIT", "THERMODYNAMICTEMPERATUREUNIT",
    "ELECTRICCURRENTUNIT", "AMOUNTOFSUBSTANCEUNIT",
    "LUMINOUSINTENSITYUNIT", "FREQUENCYUNIT",
    "ENERGYUNIT", "FORCEUNIT", "PRESSUREUNIT", "POWERUNIT",
    # Derived-unit enum values
    "VOLUMETRICFLOWRATEUNIT", "MASSDENSITYUNIT", "LINEARVELOCITYUNIT",
    "DYNAMICVISCOSITYUNIT", "ACCELERATIONUNIT", "ANGULARVELOCITYUNIT",
    "MOMENTOFINERTIAUNIT", "HEATFLUXDENSITYUNIT", "HEATINGVALUEUNIT",
)

# SI prefix multipliers (per ISO 80000-1).  An IfcSIUnit with no Prefix
# token ($) maps to the unity entry under ``""``.
_SI_PREFIX_FACTOR: dict[str, float] = {
    "":      1.0,
    "EXA":   1e18,
    "PETA":  1e15,
    "TERA":  1e12,
    "GIGA":  1e9,
    "MEGA":  1e6,
    "KILO":  1e3,
    "HECTO": 1e2,
    "DECA":  1e1,
    "DECI":  1e-1,
    "CENTI": 1e-2,
    "MILLI": 1e-3,
    "MICRO": 1e-6,
    "NANO":  1e-9,
    "PICO":  1e-12,
    "FEMTO": 1e-15,
    "ATTO":  1e-18,
}

# Imperial / customary conversion factors (canonical SI exponent = 1).
# All values are the conversion factor that turns one source unit into
# the canonical SI base for that dimension:
#   length  → metre              (1 inch = 0.0254 m)
#   area    → square metre       (1 sq ft = 0.09290304 m²)
#   volume  → cubic metre        (1 cu yd = 0.764554857984 m³)
#   mass    → kilogram           (1 lb    = 0.45359237 kg)
#   angle   → radian             (1 deg   = π/180)
#   time    → second             (1 hour  = 3600 s)
#   pressure→ pascal             (1 psi   = 6894.757293168 Pa)
#   energy  → joule              (1 BTU_IT = 1055.05585262 J)
#
# Keys are upper-cased Name fields from IFCCONVERSIONBASEDUNIT (the IFC
# specification fixes these strings — see ISO 16739-1 Table 75-77).
# Aliases (FT vs FOOT, etc.) handle exporter inconsistency.
_CONVERSION_BASED_FACTORS: dict[str, float] = {
    # ── Length ──
    "INCH":     0.0254,
    "INCHES":   0.0254,
    "IN":       0.0254,
    "FOOT":     0.3048,
    "FT":       0.3048,
    "FEET":     0.3048,
    "YARD":     0.9144,
    "YD":       0.9144,
    "MILE":     1609.344,
    "MILES":    1609.344,
    "NAUTICALMILE": 1852.0,
    # ── Area ──
    "SQUAREINCH":   0.00064516,
    "SQUAREFOOT":   0.09290304,
    "SQ FT":        0.09290304,
    "SQFT":         0.09290304,
    "SQUAREYARD":   0.83612736,
    "ACRE":         4046.8564224,
    "SQUAREMILE":   2589988.110336,
    # ── Volume ──
    "CUBICINCH":    0.000016387064,
    "CUBICFOOT":    0.028316846592,
    "CU FT":        0.028316846592,
    "CUFT":         0.028316846592,
    "CUBICYARD":    0.764554857984,
    "CU YD":        0.764554857984,
    "CUYD":         0.764554857984,
    "GALLON":       0.003785411784,   # US liquid gallon
    "USGALLON":     0.003785411784,
    "UKGALLON":     0.00454609,
    "LITRE":        0.001,
    "LITER":        0.001,
    # ── Mass ──
    "POUND":        0.45359237,
    "LB":           0.45359237,
    "LBS":          0.45359237,
    "OUNCE":        0.028349523125,
    "OZ":           0.028349523125,
    "TONNE":        1000.0,
    "TON":          907.18474,     # US short ton (ISO default)
    "STONE":        6.35029318,
    # ── Plane angle ──
    "DEGREE":       0.0174532925199432957692,    # π/180
    "DEG":          0.0174532925199432957692,
    "GRADIAN":      0.0157079632679489661923,    # π/200
    # ── Time ──
    "MINUTE":       60.0,
    "MIN":          60.0,
    "HOUR":         3600.0,
    "HR":           3600.0,
    "DAY":          86400.0,
    "WEEK":         604800.0,
    "YEAR":         31557600.0,    # Julian year (365.25 d)
    # ── Temperature offsets are handled separately; here are scale-only
    # entries used for differences (ΔT). Absolute conversions need a
    # bias term that is dimension-specific and is applied at quantity
    # extraction, not here.
    "FAHRENHEIT":   0.5555555555555556,   # 5/9 (scale only — bias 32 °F → 0 °C handled at extract)
    "RANKINE":      0.5555555555555556,   # 5/9
    # ── Pressure ──
    "PSI":          6894.757293168,
    "POUNDPERSQUAREINCH": 6894.757293168,
    "BAR":          100000.0,
    "ATMOSPHERE":   101325.0,
    "ATM":          101325.0,
    "TORR":         133.322387415,
    "MMHG":         133.322387415,
    # ── Energy ──
    "BTU":          1055.05585262,
    "BRITISHTHERMALUNIT": 1055.05585262,
    "CALORIE":      4.184,
    "CAL":          4.184,
    "KILOCALORIE":  4184.0,
    "KCAL":         4184.0,
    "KILOWATTHOUR": 3600000.0,
    "KWH":          3600000.0,
    # ── Power ──
    "HORSEPOWER":   745.6998715822702,
    "HP":           745.6998715822702,
    # ── Force ──
    "POUNDFORCE":   4.4482216152605,
    "LBF":          4.4482216152605,
    "KIP":          4448.2216152605,
}

# Map an IfcUnitEnum token to a tuple of (BOQ-relevant SI base unit, …)
# we report as the canonical destination so the metadata block can label
# what the scale-table is converting INTO.
_CANONICAL_SI_BASE: dict[str, str] = {
    "LENGTHUNIT":        "m",
    "AREAUNIT":          "m^2",
    "VOLUMEUNIT":        "m^3",
    "MASSUNIT":          "kg",
    "TIMEUNIT":          "s",
    "PLANEANGLEUNIT":    "rad",
    "ANGLEUNIT":         "rad",
    "SOLIDANGLEUNIT":    "sr",
    "TEMPERATUREUNIT":   "K",
    "THERMODYNAMICTEMPERATUREUNIT": "K",
    "FREQUENCYUNIT":     "Hz",
    "ENERGYUNIT":        "J",
    "FORCEUNIT":         "N",
    "PRESSUREUNIT":      "Pa",
    "POWERUNIT":         "W",
    "ELECTRICCURRENTUNIT": "A",
    "LUMINOUSINTENSITYUNIT": "cd",
    "AMOUNTOFSUBSTANCEUNIT": "mol",
    "MASSDENSITYUNIT":   "kg/m^3",
    "LINEARVELOCITYUNIT": "m/s",
    "ACCELERATIONUNIT":  "m/s^2",
    "ANGULARVELOCITYUNIT": "rad/s",
    "VOLUMETRICFLOWRATEUNIT": "m^3/s",
    "DYNAMICVISCOSITYUNIT": "Pa.s",
    "HEATFLUXDENSITYUNIT": "W/m^2",
}

# IFCQUANTITY* → IfcUnitEnum dimension lookup.  Drives which scale we
# apply when rolling a value into the canonical element output.
_QUANTITY_KIND_TO_UNIT: dict[str, str] = {
    "IFCQUANTITYLENGTH":  "LENGTHUNIT",
    "IFCQUANTITYAREA":    "AREAUNIT",
    "IFCQUANTITYVOLUME":  "VOLUMEUNIT",
    "IFCQUANTITYWEIGHT":  "MASSUNIT",
    "IFCQUANTITYTIME":    "TIMEUNIT",
    "IFCQUANTITYCOUNT":   "",          # dimensionless — no scale
    "IFCQUANTITYNUMBER":  "",
}


def _step_args_top_level(args_raw: str) -> list[str]:
    """Split a STEP-21 argument list at top-level commas only.

    Commas inside (…) sets, '…' string literals, or .…. enum tokens
    must NOT split.  Returns the raw argument tokens with surrounding
    whitespace stripped but otherwise untouched (so callers can still
    inspect the original ``#42`` ref / ``.METRE.`` enum / ``'INCH'``
    string form).
    """
    out: list[str] = []
    depth = 0
    in_string = False
    buf: list[str] = []
    i = 0
    n = len(args_raw)
    while i < n:
        ch = args_raw[i]
        if in_string:
            buf.append(ch)
            if ch == "'":
                # STEP-21 escapes single quotes by doubling (the doubled-
                # apostrophe placeholder has already been substituted in
                # by the caller, so a lone ' here truly closes the literal).
                in_string = False
        else:
            if ch == "'":
                in_string = True
                buf.append(ch)
            elif ch == "(":
                depth += 1
                buf.append(ch)
            elif ch == ")":
                depth -= 1
                buf.append(ch)
            elif ch == "," and depth == 0:
                out.append("".join(buf).strip())
                buf.clear()
            else:
                buf.append(ch)
        i += 1
    if buf:
        out.append("".join(buf).strip())
    return out


def _resolve_ifc_si_unit(ent: dict[str, Any]) -> tuple[str, float, str] | None:
    """Resolve an IFCSIUNIT entity into ``(unit_type, scale, label)``.

    Returns ``None`` when the entity is malformed (no Name token, etc.) so
    the caller can fall back to defaults.  ``scale`` is the multiplier
    that converts a value expressed in this unit into the canonical SI
    base for the same dimension (so KILOMETRE → 1000.0).

    IfcSIUnit signature (ISO 16739-1 §8.10.3.4):
        IfcSIUnit(Dimensions, UnitType, Prefix, Name)
    """
    parts = _step_args_top_level(ent["args_raw"])
    if len(parts) < 4:
        return None
    unit_type_raw = parts[1].strip().strip(".").upper()
    prefix_raw = parts[2].strip()
    name_raw = parts[3].strip().strip(".").upper()
    # Unity prefix is encoded as '$' (or '*' on legacy exporters).
    if prefix_raw in ("$", "*", ""):
        prefix_name = ""
    else:
        prefix_name = prefix_raw.strip(".").upper()
    prefix_factor = _SI_PREFIX_FACTOR.get(prefix_name)
    if prefix_factor is None:
        # Unknown prefix → treat as unity but log; better than crashing.
        logger.debug("Unknown SI prefix %r — assuming unity", prefix_name)
        prefix_factor = 1.0
    # Dimensional scaling: for AREAUNIT the prefix applies to the LENGTH
    # part inside the area, so the area scale is prefix^2; for VOLUMEUNIT
    # it's prefix^3.  This is the rule that turns MILLI+SQUARE_METRE into
    # 1e-6 (mm² → m²) and MILLI+CUBIC_METRE into 1e-9 (mm³ → m³).
    exponent = 1
    if name_raw in ("SQUARE_METRE", "SQUAREMETRE"):
        exponent = 2
    elif name_raw in ("CUBIC_METRE", "CUBICMETRE"):
        exponent = 3
    scale = prefix_factor ** exponent
    label_prefix = prefix_name.lower() if prefix_name else ""
    label = f"{label_prefix}{name_raw.lower().replace('_', '')}"
    return unit_type_raw, scale, label


def _resolve_measure_with_unit(
    ent: dict[str, Any],
    entities: dict[int, dict],
    seen: set[int],
) -> float | None:
    """Read an IFCMEASUREWITHUNIT and return its numeric value times the
    referenced unit's own scale.

    Signature: IfcMeasureWithUnit(ValueComponent, UnitComponent)
    ``ValueComponent`` is a typed measure such as ``IFCLENGTHMEASURE(0.0254)``;
    ``UnitComponent`` is a #ref to an IFCSIUNIT or another IFCCONVERSIONBASEDUNIT.

    Returns ``None`` for malformed entities so callers can default.
    """
    parts = _step_args_top_level(ent["args_raw"])
    if len(parts) < 2:
        return None
    value_part = parts[0]
    unit_part = parts[1]

    # Pull the first numeric literal out of the value part. The typed
    # wrapper (``IFCLENGTHMEASURE(0.0254)``) parses identically.
    val_match = re.search(r"-?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?", value_part)
    if not val_match:
        return None
    try:
        value = float(val_match.group(0))
    except ValueError:
        return None

    # Resolve the unit reference recursively.  When unit_part is not a
    # #ref the value is taken as already in canonical SI.
    ref_match = re.search(r"#(\d+)", unit_part)
    unit_scale = 1.0
    if ref_match:
        ref_id = int(ref_match.group(1))
        ref_ent = entities.get(ref_id)
        if ref_ent and ref_id not in seen:
            seen.add(ref_id)
            t = ref_ent["type"]
            if t == "IFCSIUNIT":
                resolved = _resolve_ifc_si_unit(ref_ent)
                if resolved:
                    unit_scale = resolved[1]
            elif t == "IFCCONVERSIONBASEDUNIT":
                cb = _resolve_conversion_based_unit(ref_ent, entities, seen)
                if cb is not None:
                    unit_scale = cb[1]
    return value * unit_scale


def _resolve_conversion_based_unit(
    ent: dict[str, Any],
    entities: dict[int, dict],
    seen: set[int],
) -> tuple[str, float, str] | None:
    """Resolve an IFCCONVERSIONBASEDUNIT into ``(unit_type, scale, label)``.

    Signature (IFC4): IfcConversionBasedUnit(Dimensions, UnitType, Name,
    ConversionFactor).  ConversionFactor is a #ref to an
    IFCMEASUREWITHUNIT giving the equivalent in another (typically SI)
    unit.  Chained conversion-based units (referencing other
    conversion-based units) are dereferenced recursively via ``seen`` to
    guard against pathological cycles.
    """
    parts = _step_args_top_level(ent["args_raw"])
    if len(parts) < 4:
        return None
    unit_type_raw = parts[1].strip().strip(".").upper()
    name_raw = parts[2].strip().strip("'").upper()
    conv_part = parts[3]

    # The conversion factor is normally a #ref → IFCMEASUREWITHUNIT.
    ref_match = re.search(r"#(\d+)", conv_part)
    scale: float | None = None
    if ref_match:
        ref_id = int(ref_match.group(1))
        ref_ent = entities.get(ref_id)
        if ref_ent and ref_id not in seen:
            seen.add(ref_id)
            if ref_ent["type"] == "IFCMEASUREWITHUNIT":
                scale = _resolve_measure_with_unit(ref_ent, entities, seen)

    # Fall back to the hard-coded customary-unit table when the IFC
    # writer omitted or mangled the conversion factor.  Real-world IFC
    # files from older Tekla versions ship with the Name field but a
    # null conversion factor, expecting consumers to know the value.
    if scale is None or scale <= 0:
        normalised = name_raw.replace(" ", "").replace("_", "").upper()
        scale = _CONVERSION_BASED_FACTORS.get(normalised)
    if scale is None or scale <= 0:
        logger.debug(
            "Unresolvable IFCCONVERSIONBASEDUNIT %r — assuming SI canonical",
            name_raw,
        )
        scale = 1.0

    return unit_type_raw, scale, name_raw.lower()


def _resolve_derived_unit(
    ent: dict[str, Any],
    entities: dict[int, dict],
    seen: set[int],
) -> tuple[str, float, str] | None:
    """Resolve an IFCDERIVEDUNIT into ``(unit_type, scale, label)``.

    Signature: IfcDerivedUnit(Elements, UnitType, UserDefinedType?, Name?)
    Elements is a SET of IfcDerivedUnitElement, each carrying
    (Unit=#ref, Exponent=int).  The composite scale is the product of
    each element's own scale raised to its exponent — so for ``m³/h``
    (CubicMetre^+1, Hour^-1) we end up with 1.0 * (3600)^-1 = 1/3600.
    """
    parts = _step_args_top_level(ent["args_raw"])
    if len(parts) < 2:
        return None
    set_match = re.search(r"\((.*)\)", parts[0])
    if not set_match:
        return None
    elem_refs = [int(x) for x in re.findall(r"#(\d+)", set_match.group(1))]
    unit_type_raw = parts[1].strip().strip(".").upper()

    composite_scale = 1.0
    label_pieces: list[str] = []
    for elem_id in elem_refs:
        elem = entities.get(elem_id)
        if not elem or elem["type"] != "IFCDERIVEDUNITELEMENT":
            continue
        ep = _step_args_top_level(elem["args_raw"])
        if len(ep) < 2:
            continue
        unit_ref = re.search(r"#(\d+)", ep[0])
        try:
            exponent = int(ep[1])
        except ValueError:
            continue
        if not unit_ref:
            continue
        ref_id = int(unit_ref.group(1))
        ref_ent = entities.get(ref_id)
        if not ref_ent or ref_id in seen:
            continue
        seen.add(ref_id)
        unit_scale: float | None = None
        unit_label = ""
        if ref_ent["type"] == "IFCSIUNIT":
            r = _resolve_ifc_si_unit(ref_ent)
            if r:
                unit_scale = r[1]
                unit_label = r[2]
        elif ref_ent["type"] == "IFCCONVERSIONBASEDUNIT":
            r = _resolve_conversion_based_unit(ref_ent, entities, seen)
            if r:
                unit_scale = r[1]
                unit_label = r[2]
        elif ref_ent["type"] == "IFCDERIVEDUNIT":
            r = _resolve_derived_unit(ref_ent, entities, seen)
            if r:
                unit_scale = r[1]
                unit_label = r[2]
        if unit_scale is None or unit_scale <= 0:
            continue
        composite_scale *= unit_scale ** exponent
        sign = "" if exponent >= 0 else "-"
        label_pieces.append(f"{unit_label}^{sign}{abs(exponent)}")

    return unit_type_raw, composite_scale, "*".join(label_pieces) or "derived"


def _resolve_monetary_unit(ent: dict[str, Any]) -> tuple[str, float, str] | None:
    """Resolve an IFCMONETARYUNIT — currency code only, no scale.

    Signature (IFC4+): IfcMonetaryUnit(Currency)
    Legacy IFC2x3 used IfcMonetaryUnit(Currency=enum).  We extract the
    currency code string and report scale=1.0 because the canonical SI
    base for money is "the value as written" — currency conversion is
    out of scope for this parser.
    """
    parts = _step_args_top_level(ent["args_raw"])
    if not parts:
        return None
    code = parts[0].strip().strip("'").strip(".").upper()
    return "MONETARYUNIT", 1.0, code


class UnitContext:
    """Parsed view of an IFC file's IFCUNITASSIGNMENT block.

    Attributes:
        scale_for: {unit_type → multiplier to canonical SI}
        label_for: {unit_type → human-readable unit name}
        unit_system: "metric" | "imperial" | "mixed" | "unknown"
        currency_code: ISO 4217 currency code from IfcMonetaryUnit, if any
        is_canonical: True iff every unit in scale_for has scale=1.0
                      AND there are no non-metric units. UI uses this to
                      decide whether to display a "values rescaled" hint.
        had_assignment: True iff the file declared a non-empty
                        IFCUNITASSIGNMENT (vs falling back to defaults).
    """

    __slots__ = (
        "scale_for", "label_for", "unit_system",
        "currency_code", "is_canonical", "had_assignment",
    )

    def __init__(self) -> None:
        # Default scale = 1.0 (canonical SI) for every dimension we know
        # how to handle. When the IFC declares a unit we overwrite the
        # entry; when it doesn't we keep the SI default (ISO 16739-1
        # §5.4.3 explicitly says "metric SI" is the default).
        self.scale_for: dict[str, float] = dict.fromkeys(_IFC_UNIT_TYPES, 1.0)
        self.label_for: dict[str, str] = {
            "LENGTHUNIT": "metre",
            "AREAUNIT": "squaremetre",
            "VOLUMEUNIT": "cubicmetre",
            "MASSUNIT": "kilogram",
            "TIMEUNIT": "second",
            "PLANEANGLEUNIT": "radian",
            "ANGLEUNIT": "radian",
            "FREQUENCYUNIT": "hertz",
            "ENERGYUNIT": "joule",
            "PRESSUREUNIT": "pascal",
            "POWERUNIT": "watt",
            "FORCEUNIT": "newton",
        }
        self.unit_system: str = "metric"
        self.currency_code: str | None = None
        self.is_canonical: bool = True
        self.had_assignment: bool = False

    def scale(self, quantity_kind: str) -> float:
        """Return the canonical-SI scale for an IFCQUANTITY* entity type."""
        unit_type = _QUANTITY_KIND_TO_UNIT.get(quantity_kind.upper(), "")
        if not unit_type:
            return 1.0
        return self.scale_for.get(unit_type, 1.0)


def _parse_unit_assignment(entities: dict[int, dict]) -> UnitContext:
    """Build a UnitContext from a parsed IFC entity table.

    Walks every IFCUNITASSIGNMENT (there may be multiple — IFC4 attaches
    them via IfcContext.UnitsInContext; legacy IFC2x3 via
    IfcProject.UnitsInContext) and resolves each referenced unit entity.
    When no IFCUNITASSIGNMENT is found we fall back to ISO 16739-1
    metric defaults so legacy files without an explicit block still
    parse correctly.

    The result is always a non-empty UnitContext — callers don't need
    to guard against ``None``.
    """
    ctx = UnitContext()

    # Collect every unit ref mentioned by every IFCUNITASSIGNMENT block.
    unit_refs: set[int] = set()
    for ent in entities.values():
        if ent["type"] != "IFCUNITASSIGNMENT":
            continue
        ctx.had_assignment = True
        # Args is a single set literal: ((#1, #2, …)).
        for m in re.findall(r"#(\d+)", ent["args_raw"]):
            unit_refs.add(int(m))

    # Some exporters (older Allplan) emit no IFCUNITASSIGNMENT and
    # expect consumers to default to metric.  We honour that.
    if not unit_refs:
        # Still walk standalone IFCSIUNIT entities so we pick up
        # any explicit declarations (some Tekla exports define units
        # without bundling them into an assignment block).
        for ent in entities.values():
            if ent["type"] != "IFCSIUNIT":
                continue
            resolved = _resolve_ifc_si_unit(ent)
            if resolved:
                ctx.scale_for[resolved[0]] = resolved[1]
                ctx.label_for[resolved[0]] = resolved[2]
        # No assignment block = fall back to metric defaults.
        return ctx

    saw_imperial = False
    saw_metric = False
    for ref_id in unit_refs:
        ent = entities.get(ref_id)
        if not ent:
            continue
        t = ent["type"]
        seen: set[int] = {ref_id}
        if t == "IFCSIUNIT":
            r = _resolve_ifc_si_unit(ent)
            if r:
                ctx.scale_for[r[0]] = r[1]
                ctx.label_for[r[0]] = r[2]
                saw_metric = True
                if r[1] != 1.0:
                    ctx.is_canonical = False
        elif t == "IFCCONVERSIONBASEDUNIT":
            r = _resolve_conversion_based_unit(ent, entities, seen)
            if r:
                ctx.scale_for[r[0]] = r[1]
                ctx.label_for[r[0]] = r[2]
                ctx.is_canonical = False
                saw_imperial = True
        elif t == "IFCDERIVEDUNIT":
            r = _resolve_derived_unit(ent, entities, seen)
            if r:
                ctx.scale_for[r[0]] = r[1]
                ctx.label_for[r[0]] = r[2]
                if r[1] != 1.0:
                    ctx.is_canonical = False
        elif t == "IFCMONETARYUNIT":
            r = _resolve_monetary_unit(ent)
            if r:
                ctx.currency_code = r[2]
        else:
            # Some exporters reference IFCCONTEXTDEPENDENTUNIT here.
            # We don't have a scale for those (definition is opaque),
            # but we record the existence so is_canonical drops.
            ctx.is_canonical = False

    if saw_imperial and saw_metric:
        ctx.unit_system = "mixed"
    elif saw_imperial:
        ctx.unit_system = "imperial"
    else:
        # Pure SI (any prefix) OR no recognised units at all → metric default.
        ctx.unit_system = "metric"
    return ctx


def _ifc_units_are_non_si_metres(entities: dict[int, dict]) -> bool:
    """Return True iff the IFC's length unit is anything other than SI metres.

    Backward-compatibility shim.  Older regression tests called this to
    obtain a single boolean "is the LENGTHUNIT non-canonical?" answer.
    The current parser computes a full UnitContext but we keep the
    helper for those tests — it now just inspects the context's
    LENGTHUNIT scale.

    Probe shape (IFC2x3 + IFC4 + IFC4x3 all use the same):

        #N= IFCSIUNIT($,.LENGTHUNIT.,$,.METRE.);            ← SI metres → False
        #N= IFCSIUNIT($,.LENGTHUNIT.,.MILLI.,.METRE.);      ← mm        → True
        #N= IFCCONVERSIONBASEDUNIT(...,.LENGTHUNIT.,'INCH',...);  ← imp  → True

    Behaviour preserved from v3.0.0:
      * Returns ``True`` when a non-SI length unit is declared.
      * Returns ``True`` when no IFCSIUNIT / IFCCONVERSIONBASEDUNIT row
        mentions LENGTHUNIT at all (conservative — exporter bug).
      * Returns ``True`` if BOTH an SI metre row AND a conversion-based
        length unit are declared (mixed-unit file is suspicious).
    """
    found_si_metre = False
    found_other = False
    for ent in entities.values():
        if ent["type"] not in ("IFCSIUNIT", "IFCCONVERSIONBASEDUNIT"):
            continue
        args_raw = ent["args_raw"].upper()
        if "LENGTHUNIT" not in args_raw:
            continue
        if ent["type"] == "IFCSIUNIT":
            # IFCSIUNIT(Dimensions, UnitType, Prefix, Name).
            # SI-metre = no prefix ($) + METRE.
            #
            # Splitting by ',' is approximate (we ignore parenthesised
            # sub-arguments) but for IFCSIUNIT every positional arg is
            # atomic so the simple split is safe.
            parts = [p.strip() for p in args_raw.split(",")]
            # Find the prefix arg — it's the one right before .METRE.
            # The canonical SI-metre row is:
            #   ($,.LENGTHUNIT.,$,.METRE.)
            # Anything with a non-$ prefix (MILLI, CENTI, …) is NOT
            # canonical SI-metre even though the name is still METRE.
            is_metre = ".METRE." in args_raw
            # Walk parts to find ".LENGTHUNIT." then take the next
            # positional element as the prefix.
            prefix: str | None = None
            for i, p in enumerate(parts):
                if ".LENGTHUNIT." in p and i + 1 < len(parts):
                    prefix = parts[i + 1]
                    break
            if is_metre and prefix == "$":
                found_si_metre = True
            else:
                found_other = True
        else:
            # IFCCONVERSIONBASEDUNIT is by definition non-SI (inch, ft, …).
            found_other = True
    if found_si_metre and not found_other:
        return False
    if found_other:
        return True
    # No length unit declared at all → conservative "uncertain".
    return True


def _extract_quantities_for_element(
    element_id: int,
    entities: dict[int, dict],
    unit_ctx: UnitContext | None = None,
) -> dict[str, float]:
    """Try to find quantities related to an element via IfcRelDefinesByProperties.

    When ``unit_ctx`` is supplied each extracted IfcQuantity value is
    multiplied by the scale appropriate to its dimension (length /
    area / volume / mass / time) so the output is always in canonical
    SI metres / square metres / cubic metres / kilograms / seconds.
    Callers that pass ``None`` get the raw IFC value (used by the
    legacy regression tests that build entities by hand).
    """
    quantities: dict[str, float] = {}

    for ent in entities.values():
        if ent["type"] != "IFCRELDEFINESBYPROPERTIES":
            continue
        # Bugfix (C8): IFCRELDEFINESBYPROPERTIES has the shape
        #   (GlobalId, OwnerHistory, Name, Description,
        #    RelatedObjects=(#a,#b,…), RelatingPropertyDefinition=#z)
        # The previous code took refs[:-1] which included OwnerHistory.
        # On at least one major exporter the OwnerHistory id collided with
        # element ids and we associated unrelated property sets to walls.
        # Real RelatedObjects live INSIDE the SET literal — pull them
        # explicitly. The relating definition is the very last #ref in the
        # statement.
        args_raw = ent["args_raw"]
        # RelatedObjects parenthesised list — non-greedy match.
        set_match = re.search(r"\(([^()]*)\)\s*,\s*#\d+\s*$", args_raw)
        related_ids: list[int] = []
        if set_match:
            related_ids = [int(x) for x in re.findall(r"#(\d+)", set_match.group(1))]
        if not related_ids:
            # Some exporters write a single ref instead of a parenthesised
            # list when there's only one related object. Fall through to
            # the legacy refs[:-1] for that case but skip the first 2
            # refs (OwnerHistory typically appears at position 0-1).
            all_refs = re.findall(r"#(\d+)", args_raw)
            related_ids = [int(x) for x in all_refs[2:-1]]
        if element_id not in related_ids:
            continue
        # Last ref in the entire statement is the property definition.
        all_refs = re.findall(r"#(\d+)", args_raw)
        if not all_refs:
            continue
        pdef_id = int(all_refs[-1])
        pdef = entities.get(pdef_id)
        if not pdef or pdef["type"] != "IFCELEMENTQUANTITY":
            continue
        # IFCELEMENTQUANTITY args: (GlobalId, OwnerHistory, Name,
        # Description, MethodOfMeasurement, Quantities=(#q1, #q2, …))
        q_refs = re.findall(r"#(\d+)", pdef["args_raw"])
        for qr in q_refs:
            q_ent = entities.get(int(qr))
            if not q_ent:
                continue
            if q_ent["type"] not in (
                "IFCQUANTITYLENGTH", "IFCQUANTITYAREA",
                "IFCQUANTITYVOLUME", "IFCQUANTITYWEIGHT", "IFCQUANTITYCOUNT",
                "IFCQUANTITYTIME", "IFCQUANTITYNUMBER",
            ):
                continue
            q_strings = q_ent["strings"]
            q_name = q_strings[0] if q_strings else "unknown"
            # Bugfix (C7): the old regex r"[\d.]+(?:E[+-]?\d+)?" also
            # matched the digit portion of #N references — so
            # IFCQUANTITYAREA('NetArea',$,$,#5,42.5) parsed as nums[0]="5"
            # and we recorded NetArea=5 m² instead of 42.5. Strip all
            # #N tokens first, then look for the trailing numeric literal.
            args_no_refs = re.sub(r"#\d+", "", q_ent["args_raw"])
            nums = re.findall(r"-?\d+\.?\d*(?:[Ee][+-]?\d+)?", args_no_refs)
            # The measurement value is the LAST positional argument of an
            # IFCQUANTITY* entity, so prefer the last numeric we found.
            for n in reversed(nums):
                try:
                    val = float(n)
                except ValueError:
                    continue
                if val > 0:
                    # Audit C2 — apply unit scale so the recorded value is
                    # always in canonical SI (m, m², m³, kg, s) regardless
                    # of whether the source IFC used millimetres, feet, or
                    # any other declared unit. unit_ctx is None for the
                    # legacy regression tests that pass entities by hand;
                    # we skip the scale in that case to preserve their
                    # expectations.
                    scale = unit_ctx.scale(q_ent["type"]) if unit_ctx else 1.0
                    quantities[q_name] = val * scale
                    break

    return quantities


def _classify_discipline(ifc_type: str) -> str:
    """Classify IFC type into a discipline."""
    t = ifc_type.lower()
    # Check architecture first — curtainwall contains "wall" so must precede structural
    if any(x in t for x in ["door", "window", "curtainwall", "covering", "furnishing"]):
        return "architecture"
    if any(x in t for x in ["wall", "slab", "column", "beam", "footing", "pile", "stair", "railing", "roof",
                             "plate", "member", "tendon", "bearing"]):
        return "structural"
    if any(x in t for x in ["flow", "distribution", "pipe", "duct", "cable"]):
        return "mep"
    if any(x in t for x in ["alignment", "road", "railway", "bridge", "pavement", "kerb", "course",
                             "earthworks", "civil", "facility", "geographic", "geotechnic",
                             "caisson", "deepfoundation", "surfacefeature", "transport",
                             "reinforcedsoil"]):
        return "civil"
    if "space" in t:
        return "architecture"
    return "other"


_TYPE_DISPLAY_MAP: dict[str, str] = {
    "IFCWALLSTANDARDCASE": "Wall",
    "IFCBUILDINGELEMENTPROXY": "Generic Element",
    "IFCALIGNMENT": "Alignment",
    "IFCALIGNMENTHORIZONTAL": "Horizontal Alignment",
    "IFCALIGNMENTVERTICAL": "Vertical Alignment",
    "IFCALIGNMENTSEGMENT": "Alignment Segment",
    "IFCALIGNMENTCANT": "Alignment Cant",
    "IFCBRIDGE": "Bridge",
    "IFCBRIDGEPART": "Bridge Part",
    "IFCROAD": "Road",
    "IFCROADPART": "Road Part",
    "IFCRAILWAY": "Railway",
    "IFCRAILWAYPART": "Railway Part",
    "IFCPAVEMENT": "Pavement",
    "IFCKERB": "Kerb",
    "IFCCOURSE": "Course",
    "IFCEARTHWORKSFILL": "Earthworks Fill",
    "IFCEARTHWORKSCUT": "Earthworks Cut",
    "IFCEARTHWORKSELEMENT": "Earthworks Element",
    "IFCREINFORCEDSOIL": "Reinforced Soil",
    "IFCGEOTECHNICELEMENT": "Geotechnic Element",
    "IFCGEOTECHNICSTRATUM": "Geotechnic Stratum",
    "IFCDEEPFOUNDATION": "Deep Foundation",
    "IFCCAISSONFOOTING": "Caisson Footing",
    "IFCBEARING": "Bearing",
    "IFCTENDON": "Tendon",
    "IFCTENDONANCHOR": "Tendon Anchor",
    "IFCTENDONCONDUIT": "Tendon Conduit",
    "IFCSURFACEFEATURE": "Surface Feature",
    "IFCCIVILELEMENT": "Civil Element",
    "IFCGEOGRAPHICELEMENT": "Geographic Element",
    "IFCFACILITY": "Facility",
    "IFCFACILITYPART": "Facility Part",
}


def _simplify_type(ifc_type: str) -> str:
    """Simplify IFC type name for display."""
    up = ifc_type.upper()
    if up in _TYPE_DISPLAY_MAP:
        return _TYPE_DISPLAY_MAP[up]
    return ifc_type.replace("IFC", "").title()


def _extract_placements(
    elements: list[dict[str, Any]],
    entities: dict[int, dict],
) -> None:
    """Try to extract real XYZ placement coordinates from IFC entities.

    Parses ``IfcLocalPlacement → IfcAxis2Placement3D → IfcCartesianPoint``
    and stores the result in ``elem["_placement"]`` as ``(x, y, z)``.
    Elements without recoverable placement keep ``_placement = None``.
    """
    # Build map: element_ifc_id → placement ref
    placement_map: dict[int, tuple[float, float, float]] = {}

    for eid, ent in entities.items():
        if ent["type"] == "IFCCARTESIANPOINT":
            nums = re.findall(r"[-\d.]+(?:E[+-]?\d+)?", ent["args_raw"])
            if len(nums) >= 3:
                try:
                    placement_map[eid] = (float(nums[0]), float(nums[1]), float(nums[2]))
                except ValueError as exc:
                    logger.debug(
                        "IFC placement skipped: malformed 3D coordinate at #%d (%r): %s",
                        eid, nums[:3], exc,
                    )
            elif len(nums) == 2:
                try:
                    placement_map[eid] = (float(nums[0]), float(nums[1]), 0.0)
                except ValueError as exc:
                    logger.debug(
                        "IFC placement skipped: malformed 2D coordinate at #%d (%r): %s",
                        eid, nums[:2], exc,
                    )

    # Build IfcAxis2Placement3D → location point
    axis_to_point: dict[int, tuple[float, float, float]] = {}
    for eid, ent in entities.items():
        if ent["type"] in ("IFCAXIS2PLACEMENT3D", "IFCAXIS2PLACEMENT2D"):
            refs = re.findall(r"#(\d+)", ent["args_raw"])
            if refs:
                pt_id = int(refs[0])
                if pt_id in placement_map:
                    axis_to_point[eid] = placement_map[pt_id]

    # Build IfcLocalPlacement → resolved point (simplified: only direct placements)
    local_placement_pt: dict[int, tuple[float, float, float]] = {}
    for eid, ent in entities.items():
        if ent["type"] == "IFCLOCALPLACEMENT":
            refs = re.findall(r"#(\d+)", ent["args_raw"])
            for ref_str in refs:
                ref_id = int(ref_str)
                if ref_id in axis_to_point:
                    local_placement_pt[eid] = axis_to_point[ref_id]
                    break

    # Map elements to their placements via ObjectPlacement ref (typically #N in arg index 5)
    for elem in elements:
        ifc_id = elem.get("properties", {}).get("ifc_id")
        if ifc_id is None:
            elem["_placement"] = None
            continue

        ent = entities.get(ifc_id)
        if not ent:
            elem["_placement"] = None
            continue

        # The ObjectPlacement reference is typically the 6th arg in IFC entity definition.
        # We look for any ref that points to a known IfcLocalPlacement.
        refs = re.findall(r"#(\d+)", ent["args_raw"])
        placed = False
        for ref_str in refs:
            ref_id = int(ref_str)
            if ref_id in local_placement_pt:
                elem["_placement"] = local_placement_pt[ref_id]
                placed = True
                break
        if not placed:
            elem["_placement"] = None

    placed_count = sum(1 for e in elements if e.get("_placement") is not None)
    logger.info("Placement extraction: %d/%d elements have coordinates", placed_count, len(elements))


def _assign_logical_grid_positions(elements: list[dict[str, Any]]) -> None:
    """Assign logical XYZ positions so placeholder boxes form a building-like layout.

    Layout rules:
    - **Z axis** = storey height.  Each storey is stacked vertically at
      ``storey_index * STOREY_HEIGHT``.  Elements without a storey go to Z=0.
    - **Y axis** = discipline lane.  Each discipline (structural, architecture,
      MEP, civil, other) occupies its own Y-offset lane within the storey.
    - **X axis** = sequential placement within the discipline lane.

    The result is a recognisable building silhouette: floors stacked
    vertically, trades separated horizontally, elements in reading order.
    """
    STOREY_HEIGHT = 3.5   # metres between storey base planes
    DISCIPLINE_SPACING = 6.0  # Y gap between discipline lanes
    ELEM_SPACING = 2.5        # X gap between elements in a lane
    MAX_PER_ROW = 25          # wrap to next sub-row after this many

    # Discover unique storeys in the order they appear, then sort
    storey_order: list[str] = []
    seen_storeys: set[str] = set()
    for elem in elements:
        s = elem.get("storey") or ""
        if s and s not in seen_storeys:
            storey_order.append(s)
            seen_storeys.add(s)
    storey_order.sort()  # alphabetical ≈ floor order for most naming schemes

    # Add a pseudo-storey for elements without one
    storey_index: dict[str, int] = {}
    for idx, name in enumerate(storey_order):
        storey_index[name] = idx + 1  # Z starts at STOREY_HEIGHT for first real storey
    storey_index[""] = 0  # unassigned → ground level

    discipline_order = ["structural", "architecture", "mep", "civil", "other"]
    discipline_lane: dict[str, int] = {d: i for i, d in enumerate(discipline_order)}

    # Counters: (storey, discipline) → next element index within that lane
    lane_counter: dict[tuple[str, str], int] = {}

    for elem in elements:
        storey = elem.get("storey") or ""
        disc = elem.get("discipline", "other")
        if disc not in discipline_lane:
            disc = "other"

        key = (storey, disc)
        idx = lane_counter.get(key, 0)
        lane_counter[key] = idx + 1

        q = elem.get("quantities", {})
        ln = max(float(q.get("Length", q.get("Laenge", 1.0))), 0.5)

        col = idx % MAX_PER_ROW
        sub_row = idx // MAX_PER_ROW

        x = col * max(ln + 0.5, ELEM_SPACING)
        y = discipline_lane[disc] * DISCIPLINE_SPACING + sub_row * 3.0
        z = storey_index.get(storey, 0) * STOREY_HEIGHT

        elem["_grid_pos"] = (x, y, z)


# IFC-type → typical placeholder extents (length × width × height in metres).
# Used only when real Width/Height/Length quantities are absent from the
# IFC quantity sets — otherwise the real values win in ``_generate_collada_boxes``.
# The numbers come from common building-element averages (rooms ~4×4×3, slabs
# wide-and-flat, doors slim-and-tall) so the resulting placeholder scene reads
# as a building rather than a uniform grid of identical rectangles.
_PLACEHOLDER_EXTENTS_BY_IFC_TYPE: dict[str, tuple[float, float, float]] = {
    # length, width, height
    "IFCSPACE":              (4.0, 4.0, 3.0),
    "IFCWALL":               (3.0, 0.24, 2.7),
    "IFCWALLSTANDARDCASE":   (3.0, 0.24, 2.7),
    "IFCSLAB":               (5.0, 5.0, 0.3),
    "IFCROOF":               (5.0, 5.0, 0.3),
    "IFCFLOOR":              (5.0, 5.0, 0.3),
    "IFCCOVERING":           (3.0, 3.0, 0.05),
    "IFCDOOR":               (0.9, 0.1, 2.1),
    "IFCWINDOW":             (1.2, 0.1, 1.5),
    "IFCCOLUMN":             (0.4, 0.4, 3.0),
    "IFCBEAM":               (4.0, 0.3, 0.5),
    "IFCSTAIR":              (3.0, 1.2, 3.0),
    "IFCSTAIRFLIGHT":        (3.0, 1.2, 1.5),
    "IFCRAILING":            (2.0, 0.05, 1.0),
    "IFCFURNISHINGELEMENT":  (1.0, 0.6, 0.8),
    "IFCBUILDINGELEMENTPROXY": (1.0, 1.0, 1.0),
    "IFCCURTAINWALL":        (5.0, 0.1, 3.0),
    "IFCMEMBER":             (2.0, 0.1, 0.1),
    "IFCPLATE":              (1.0, 1.0, 0.05),
}

_PLACEHOLDER_DEFAULT_EXTENTS: tuple[float, float, float] = (1.0, 0.3, 3.0)


def _placeholder_default_extents(ifc_type_upper: str) -> tuple[float, float, float]:
    """Return ``(length, width, height)`` placeholder defaults for an ifc_type.

    Falls back to the legacy ``(1.0, 0.3, 3.0)`` so historic behaviour
    is preserved for any ifc_type not listed above.
    """
    return _PLACEHOLDER_EXTENTS_BY_IFC_TYPE.get(
        ifc_type_upper, _PLACEHOLDER_DEFAULT_EXTENTS,
    )


def _generate_collada_boxes(
    elements: list[dict],
    output_dir: Path,
    *,
    max_elements: int = 2000,
) -> tuple[Path | None, dict | None]:
    """Generate simplified COLLADA with box placeholders per element.

    When real IFC placement coordinates are available (populated by
    ``_extract_placements``), elements are positioned at their actual
    locations.  Otherwise falls back to a grid layout.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    dae_path = output_dir / "geometry.dae"

    NS = "http://www.collada.org/2005/11/COLLADASchema"
    root = ET.Element("COLLADA", xmlns=NS, version="1.4.1")

    asset = ET.SubElement(root, "asset")
    ET.SubElement(asset, "up_axis").text = "Z_UP"

    lib_geom = ET.SubElement(root, "library_geometries")
    lib_scenes = ET.SubElement(root, "library_visual_scenes")
    vscene = ET.SubElement(lib_scenes, "visual_scene", id="Scene", name="Scene")

    # Check how many elements have real placements
    has_real_coords = sum(1 for e in elements if e.get("_placement")) > len(elements) * 0.3

    # ── Build logical layout when no real coordinates ──────────────────
    # Group elements by storey, then by discipline within each storey.
    # Each storey is placed at a different Z level (floor height).
    # Within a storey, disciplines are arranged along Y axis.
    # Elements within a discipline group run along X axis.
    if not has_real_coords:
        _assign_logical_grid_positions(elements[:max_elements])

    # Track global bounding box
    g_min_x = g_min_y = g_min_z = float("inf")
    g_max_x = g_max_y = g_max_z = float("-inf")

    for i, elem in enumerate(elements[:max_elements]):
        q = elem.get("quantities", {})
        # Per-ifc-type default extents so the placeholder scene reads as
        # a building rather than a uniform grid of identical rectangles
        # (audit P3 minor 2026-05-06). Real IFC quantities still win
        # when present — these are only used when Width/Height/Length
        # are missing or zero.
        ifc_type_raw = (elem.get("properties") or {}).get("ifc_type", "")
        ifc_type_upper = str(ifc_type_raw).upper()
        default_w, default_h, default_ln = _placeholder_default_extents(ifc_type_upper)
        w = max(float(q.get("Width", q.get("Breite", default_w))), 0.05)
        h = max(float(q.get("Height", q.get("Hoehe", default_h))), 0.05)
        ln = max(float(q.get("Length", q.get("Laenge", default_ln))), 0.05)

        # Use real placement if available, otherwise pre-computed logical grid
        placement = elem.get("_placement")
        if has_real_coords and placement:
            x, y, z = placement
        else:
            grid = elem.get("_grid_pos", (0.0, 0.0, 0.0))
            x, y, z = grid

        # Update global bbox
        g_min_x = min(g_min_x, x)
        g_min_y = min(g_min_y, y)
        g_min_z = min(g_min_z, z)
        g_max_x = max(g_max_x, x + ln)
        g_max_y = max(g_max_y, y + w)
        g_max_z = max(g_max_z, z + h)

        # Use the element's original mesh_ref (Revit ElementId) as the
        # COLLADA node id so the frontend viewer can match meshes to
        # elements by name. Fall back to stable_id or index.
        node_id = str(elem.get("mesh_ref") or elem.get("stable_id") or f"n{i}")
        elem["mesh_ref"] = node_id
        elem["bounding_box"] = {
            "min_x": float(x),
            "min_y": float(y),
            "min_z": float(z),
            "max_x": float(x + ln),
            "max_y": float(y + w),
            "max_z": float(z + h),
        }

        gid = f"g{i}"
        geom = ET.SubElement(lib_geom, "geometry", id=gid, name=elem.get("name", f"e{i}"))
        mesh_el = ET.SubElement(geom, "mesh")

        verts = [
            (0, 0, 0), (ln, 0, 0), (ln, w, 0), (0, w, 0),
            (0, 0, h), (ln, 0, h), (ln, w, h), (0, w, h),
        ]
        pos_str = " ".join(f"{v[0]:.4f} {v[1]:.4f} {v[2]:.4f}" for v in verts)

        src = ET.SubElement(mesh_el, "source", id=f"{gid}-p")
        fa = ET.SubElement(src, "float_array", id=f"{gid}-pa", count=str(len(verts) * 3))
        fa.text = pos_str
        tc = ET.SubElement(src, "technique_common")
        acc = ET.SubElement(tc, "accessor", source=f"#{gid}-pa", count=str(len(verts)), stride="3")
        ET.SubElement(acc, "param", name="X", type="float")
        ET.SubElement(acc, "param", name="Y", type="float")
        ET.SubElement(acc, "param", name="Z", type="float")

        vs = ET.SubElement(mesh_el, "vertices", id=f"{gid}-v")
        ET.SubElement(vs, "input", semantic="POSITION", source=f"#{gid}-p")

        tri = ET.SubElement(mesh_el, "triangles", count="12")
        ET.SubElement(tri, "input", semantic="VERTEX", source=f"#{gid}-v", offset="0")
        p = ET.SubElement(tri, "p")
        p.text = "0 1 2 0 2 3 4 6 5 4 7 6 0 4 5 0 5 1 2 6 7 2 7 3 0 3 7 0 7 4 1 5 6 1 6 2"

        node = ET.SubElement(vscene, "node", id=node_id, name=elem.get("name", f"e{i}"))
        mat = ET.SubElement(node, "matrix", sid="transform")
        mat.text = f"1 0 0 {x:.4f} 0 1 0 {y:.4f} 0 0 1 {z:.4f} 0 0 0 1"
        ET.SubElement(node, "instance_geometry", url=f"#{gid}")

    scene = ET.SubElement(root, "scene")
    ET.SubElement(scene, "instance_visual_scene", url="#Scene")

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(str(dae_path), xml_declaration=True, encoding="utf-8")

    n = min(len(elements), max_elements)
    if g_min_x == float("inf"):
        g_min_x = g_min_y = g_min_z = 0.0
        g_max_x = g_max_y = g_max_z = 10.0
    bb = {
        "min": {"x": g_min_x, "y": g_min_y, "z": g_min_z},
        "max": {"x": g_max_x, "y": g_max_y, "z": g_max_z},
    }

    logger.info(
        "Generated COLLADA boxes: %d elements (%s coordinates)",
        n,
        "real" if has_real_coords else "grid",
    )
    return dae_path, bb


def _extract_revit_element_id(lc_row: dict[str, Any]) -> int | None:
    """Pull the Revit ``Element.Id.IntegerValue`` out of a DDC Excel row.

    Tries, in order:
    1. The lowercase ``id`` column (DDC's first column, already an integer).
    2. The last hyphenated segment of ``uniqueid`` parsed as hex — the Revit
       UniqueId format is ``<EpisodeGUID>-<ElementIdHex>``.
    3. Any column whose normalised name matches one of the known aliases for
       "revit element id".

    Returns ``None`` if no numeric id can be recovered.
    """
    # 1) Direct ID column from DDC RvtExporter.
    raw = lc_row.get("id")
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError) as exc:
            logger.debug(
                "DDC id column not numeric (%r) — trying UniqueId fallback: %s",
                raw, exc,
            )

    # 2) UniqueId -> hex element id
    uid = lc_row.get("uniqueid")
    if isinstance(uid, str) and "-" in uid:
        last = uid.rsplit("-", 1)[-1]
        try:
            return int(last, 16)
        except ValueError as exc:
            logger.debug(
                "UniqueId tail not hex (%r) — trying alternate columns: %s",
                last, exc,
            )

    # 3) Alternate column names used by other CAD tools.
    for key in ("element_id", "elementid", "revit_id", "revitid", "elem_id"):
        val = lc_row.get(key)
        if val is None:
            continue
        try:
            return int(val)
        except (TypeError, ValueError):
            continue

    return None


def _extract_dae_bboxes_by_node_id(dae_path: Path) -> dict[int, dict[str, float]]:
    """Parse a COLLADA file and compute a bounding box per scene node.

    Returns a mapping ``{revit_element_id: {min_x, min_y, min_z,
    max_x, max_y, max_z}}`` keyed by the integer ``<node id="...">`` value
    (which DDC RvtExporter sets to the Revit ElementId).

    Non-numeric node ids are skipped — they correspond to lights, cameras,
    and other auxiliary scene entries that do not map to BIM elements.

    Coordinates are returned in the DAE's own units (DDC emits metres).
    """
    tree = safe_ET.parse(str(dae_path))
    root = tree.getroot()
    ns = {"c": _COLLADA_NS}

    # Index geometries by id so we can resolve <instance_geometry url="#gid">.
    geom_positions: dict[str, list[tuple[float, float, float]]] = {}
    for geom in root.findall(".//c:library_geometries/c:geometry", ns):
        gid = geom.get("id") or ""
        # Prefer the <vertices>-referenced <source> when present; otherwise
        # fall back to the first float_array in the mesh.
        fa = geom.find(".//c:mesh//c:float_array", ns)
        if fa is None or not fa.text:
            continue
        try:
            nums = [float(x) for x in fa.text.split()]
        except ValueError:
            continue
        # Positions are 3-tuples. Ignore trailing values.
        pts = [(nums[i], nums[i + 1], nums[i + 2]) for i in range(0, len(nums) - 2, 3)]
        if pts:
            geom_positions[gid] = pts

    result: dict[int, dict[str, float]] = {}

    def _parse_matrix(text: str) -> tuple[float, ...] | None:
        try:
            vals = tuple(float(v) for v in text.split())
        except ValueError:
            return None
        return vals if len(vals) == 16 else None

    def _apply_matrix(
        m: tuple[float, ...],
        pt: tuple[float, float, float],
    ) -> tuple[float, float, float]:
        x, y, z = pt
        # COLLADA matrices are row-major 4x4.
        nx = m[0] * x + m[1] * y + m[2] * z + m[3]
        ny = m[4] * x + m[5] * y + m[6] * z + m[7]
        nz = m[8] * x + m[9] * y + m[10] * z + m[11]
        return nx, ny, nz

    for node in root.findall(".//c:visual_scene//c:node", ns):
        nid = node.get("id") or ""
        if not nid.isdigit():
            continue
        elem_id = int(nid)

        # Collect parent-chain transforms — DDC usually flattens geometry,
        # but we still respect any direct <matrix> on the node.
        matrix: tuple[float, ...] | None = None
        mat_el = node.find("c:matrix", ns)
        if mat_el is not None and mat_el.text:
            matrix = _parse_matrix(mat_el.text)

        min_x = min_y = min_z = float("inf")
        max_x = max_y = max_z = float("-inf")

        for inst in node.findall("c:instance_geometry", ns):
            url = inst.get("url") or ""
            if not url.startswith("#"):
                continue
            pts = geom_positions.get(url[1:])
            if not pts:
                continue
            for pt in pts:
                tp = _apply_matrix(matrix, pt) if matrix else pt
                if tp[0] < min_x:
                    min_x = tp[0]
                if tp[1] < min_y:
                    min_y = tp[1]
                if tp[2] < min_z:
                    min_z = tp[2]
                if tp[0] > max_x:
                    max_x = tp[0]
                if tp[1] > max_y:
                    max_y = tp[1]
                if tp[2] > max_z:
                    max_z = tp[2]

        if min_x == float("inf"):
            continue  # No geometry attached — skip.

        result[elem_id] = {
            "min_x": round(min_x, 4),
            "min_y": round(min_y, 4),
            "min_z": round(min_z, 4),
            "max_x": round(max_x, 4),
            "max_y": round(max_y, 4),
            "max_z": round(max_z, 4),
        }

    return result


def _patch_collada_node_names(dae_path: Path) -> int:
    """Rewrite COLLADA ``<node name="...">`` to match ``<node id="...">``.

    DDC RvtExporter writes ``<node id="ELEMENT_ID" name="node">`` for every
    element. Three.js ColladaLoader uses the ``name`` attribute (not ``id``)
    to set ``Object3D.name``, so every mesh ends up with ``name="node"`` and
    the frontend element-to-mesh matching fails (0% match rate).

    This function rewrites each ``<node>`` so ``name`` equals ``id``, which
    lets the existing ``stableIdToElement.get(nodeName)`` lookup succeed.

    Returns the number of nodes patched.
    """
    try:
        tree = safe_ET.parse(str(dae_path))
    except ET.ParseError as exc:
        logger.warning("Cannot patch COLLADA node names: XML parse error: %s", exc)
        return 0

    root = tree.getroot()
    patched = 0

    for node in root.iter(f"{{{_COLLADA_NS}}}node"):
        nid = node.get("id") or ""
        nname = node.get("name") or ""
        # Only patch element nodes (numeric id from DDC) that have a generic
        # name like "node" — leave lights/cameras/named nodes alone.
        if nid and nid != nname and (nname in ("node", "") or nid.isdigit()):
            node.set("name", nid)
            patched += 1

    if patched > 0:
        ET.indent(tree, space="  ")
        # Register COLLADA namespace as the default (empty prefix) so
        # tree.write() emits <COLLADA xmlns="..."> instead of
        # <ns0:COLLADA xmlns:ns0="...">.  Python ET emits the ns0: form when
        # the namespace is not in the global prefix registry, which causes the
        # frontend's literal "<COLLADA" text-scan to reject the file with
        # "Not a COLLADA document".
        # NOTE: default_namespace= cannot be used here — Python ET rejects it
        # whenever any element or attribute carries a non-qualified name
        # (e.g. the `version` attribute on <COLLADA>): ValueError "cannot use
        # non-qualified names with default_namespace option".
        ET.register_namespace("", _COLLADA_NS)
        tree.write(str(dae_path), xml_declaration=True, encoding="utf-8")
        logger.info(
            "Patched %d COLLADA node name attributes to match id in %s",
            patched,
            dae_path.name,
        )
    return patched


def _empty_result() -> dict[str, Any]:
    return {
        "elements": [],
        "storeys": [],
        "disciplines": [],
        "element_count": 0,
        "has_geometry": False,
        "geometry_path": None,
        "bounding_box": None,
        "status": "error",
        "error_message": "No elements could be extracted. The converter may not support this file format.",
        "geometry_type": "unknown",
        "geometry_quality": "unknown",
    }
