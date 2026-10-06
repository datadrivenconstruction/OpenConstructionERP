// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Building a register, from "I need to keep track of X" to a working module.
 *
 * Three screens, each with one obvious next step, written for a site engineer
 * rather than for a developer:
 *
 * 1. **Describe** - a sentence (when an AI provider is connected), a template,
 *    or an empty start.
 * 2. **Review** - the register as a summary card, plus what the platform
 *    proposes on top: links to records other modules keep, and functions such
 *    as a status or reminders. Nothing proposed is applied until ticked.
 *    Every detail is reachable under "Fine-tune", the technical names under
 *    "Advanced" inside it.
 * 3. **Create** - a plain summary, the files and address one click away, and
 *    the button.
 *
 * The assistant, when there is one, only ever produces a specification - never
 * Python - so the worst a bad draft can do is describe a module that fails
 * validation. Everything after the first screen is the same whoever wrote it.
 *
 * Two promises the server enforces and this screen keeps visible: every module
 * has at least one check, and what is installed is exactly what was previewed.
 * The preview is re-run whenever the spec changed since the last one, and the
 * install carries that preview's review token.
 *
 * Given an installed module (`upgrade`), the same wizard adds to it instead:
 * it opens on Review with the installed spec, locks every part entries already
 * use, and ends on "Update module", which previews and applies through the
 * upgrade endpoints under the same key.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, ArrowLeft, ArrowRight, Check, Loader2, Wand2 } from 'lucide-react';
import clsx from 'clsx';

import { Button, WideModal } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

import {
  RUNTIME_MODULE_QUERY_KEY,
  draftSpec,
  fetchInstalledModules,
  fetchModuleUiSpec,
  fetchVocabulary,
  installModule,
  previewModule,
  previewUpgrade,
  suggestForSpec,
  supportsFeatures,
  upgradeModule,
  upgradeRefusalFrom,
  type InstalledModule,
  type ModuleSpec,
  type PreviewResponse,
  type Suggestion,
  type UpgradeRefusal,
  type UpgradeResult,
} from './api';
import {
  SCHEMA_VERSION,
  autoIdentifier,
  emptySpec,
  featuresOf,
  normaliseSpec,
  specProblems,
  toWireSpec,
} from './draft';
import { mergeSuggestions, suggestionSignature } from './suggestions';
import { buildFromTemplate, templateSuggestions, type ModuleTemplate } from './templates';
import { DescribeScreen, MIN_DESCRIPTION } from './wizard/DescribeScreen';
import { ProposalScreen } from './wizard/ProposalScreen';
import { CreateScreen, DoneScreen } from './wizard/CreateScreen';
import { UpdateScreen } from './wizard/UpdateScreen';
import { RefusalNotice } from './wizard/RefusalNotice';
import {
  additionsOf,
  baselineOf,
  editableFrom,
  hasAdditions,
  keepsBaseline,
  withRecordCount,
  type Baseline,
} from './upgrade';

type Screen = 'describe' | 'proposal' | 'create' | 'done';

const STEPS: Screen[] = ['describe', 'proposal', 'create'];
const UPGRADE_STEPS: Screen[] = ['proposal', 'create'];

/** The upgrade's answer as the installed entry the rest of the wizard reads, from the spec it applied. */
function upgradedAs(result: UpgradeResult, spec: ModuleSpec): InstalledModule {
  return {
    key: result.key,
    module_name: result.module_name,
    base_path: result.base_path,
    display_name: spec.display_name,
    version: spec.version,
    generated_at: '',
    entity: spec.entity.display_name,
    field_count: spec.entity.fields.length,
    rule_count: spec.rules.length,
  };
}

/** Wait this long after the last edit before asking the server for suggestions again. */
const SUGGEST_DEBOUNCE_MS = 300;

export interface ModuleBuilderWizardProps {
  open: boolean;
  onClose: () => void;
  /** Called once the module is installed and serving. */
  onInstalled?: (module: InstalledModule) => void;
  /**
   * An installed module to add fields and functions to, rather than building
   * a new one. Only what is new can be edited; the key stays.
   */
  upgrade?: { key: string; basePath: string } | null;
}

export function ModuleBuilderWizard({ open, onClose, onInstalled, upgrade = null }: ModuleBuilderWizardProps) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [screen, setScreen] = useState<Screen>('describe');
  const [spec, setSpec] = useState<ModuleSpec>(() => emptySpec());
  const [sentence, setSentence] = useState('');
  const [drafting, setDrafting] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  /** True while the module name still steers the key, i.e. nobody typed one. */
  const [keyAuto, setKeyAuto] = useState(true);
  const [fineTuneOpen, setFineTuneOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  // Proposals, by where they came from. Merged in this order, first one wins.
  const [templateHints, setTemplateHints] = useState<Suggestion[]>([]);
  const [aiSuggestions, setAiSuggestions] = useState<Suggestion[]>([]);
  const [ruleSuggestions, setRuleSuggestions] = useState<Suggestion[]>([]);

  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [previewedFor, setPreviewedFor] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const failedFor = useRef<string | null>(null);
  const [installing, setInstalling] = useState(false);
  const [installed, setInstalled] = useState<InstalledModule | null>(null);
  const [baseline, setBaseline] = useState<Baseline | null>(null);
  const [upgradeRefusal, setUpgradeRefusal] = useState<UpgradeRefusal | null>(null);
  const upgradeKey = upgrade?.key ?? null;

  const vocabularyQuery = useQuery({
    queryKey: ['module-builder', 'vocabulary'],
    queryFn: fetchVocabulary,
    enabled: open,
    staleTime: 30 * 60_000,
  });
  const vocabulary = vocabularyQuery.data;
  const featuresSupported = supportsFeatures(vocabulary);
  const assistantAvailable = vocabulary?.assistant_available ?? false;
  const locale = (i18n?.language || 'en').split('-')[0] || 'en';

  // Shared with the module builder page, so the two read one answer.
  const installedQuery = useQuery({
    queryKey: ['module-builder', 'installed'],
    queryFn: fetchInstalledModules,
    enabled: open,
    staleTime: 5 * 60_000,
  });
  const takenKeys = useMemo(
    () =>
      [...(vocabulary?.reserved_keys ?? []), ...(installedQuery.data?.items.map((m) => m.key) ?? [])].filter(
        // Adding to a module keeps its own key, which is installed by definition.
        (key) => key !== upgradeKey,
      ),
    [vocabulary, installedQuery.data, upgradeKey],
  );

  // The installed spec, read from the module itself. The same query the
  // module's page uses, so an upgrade refreshes both at once.
  const installedSpecQuery = useQuery({
    queryKey: [RUNTIME_MODULE_QUERY_KEY, 'ui-spec', upgrade?.basePath ?? ''],
    queryFn: () => fetchModuleUiSpec(upgrade?.basePath ?? ''),
    enabled: open && upgrade !== null,
  });

  // A fresh wizard every time it opens. Reusing the last run's spec would be a
  // surprise, and reusing the last run's preview would be a lie.
  useEffect(() => {
    if (!open) return;
    setScreen('describe');
    setSpec(emptySpec());
    setSentence('');
    setRefusal(null);
    setKeyAuto(true);
    setFineTuneOpen(false);
    setAdvancedOpen(false);
    setTemplateHints([]);
    setAiSuggestions([]);
    setRuleSuggestions([]);
    setPreview(null);
    setPreviewedFor(null);
    failedFor.current = null;
    setInstalled(null);
    setBaseline(null);
    setUpgradeRefusal(null);
    // Adding to a module starts at Review: there is nothing to describe.
    if (upgrade) setScreen('proposal');
    // `upgrade` is read once per opening; the caller does not swap it while open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Start from the installed module once it has loaded.
  const installedSpec = installedSpecQuery.data;
  useEffect(() => {
    if (!open || !upgrade || !installedSpec || baseline) return;
    const base = editableFrom(installedSpec);
    setSpec(base);
    setBaseline(baselineOf(base));
    setKeyAuto(false);
    // Adding a field is the commonest reason to be here, and it lives in Fine-tune.
    setFineTuneOpen(true);
  }, [open, upgrade, installedSpec, baseline]);

  // How many records the module holds, from a preview of it unchanged. With
  // none, nothing can be lost and the screens unlock; until the answer is in,
  // or if it never comes, they stay locked.
  const probeSpec = useMemo(
    () => (installedSpec ? toWireSpec(normaliseSpec(editableFrom(installedSpec)), true) : null),
    [installedSpec],
  );
  const probeQuery = useQuery({
    queryKey: ['module-builder', 'upgrade-probe', upgrade?.key ?? '', probeSpec],
    queryFn: () => previewUpgrade(upgrade?.key ?? '', probeSpec as ModuleSpec),
    enabled: open && upgrade !== null && probeSpec !== null,
    retry: false,
    staleTime: 0,
    gcTime: 0,
  });
  const probedRecords = probeQuery.data?.record_count;
  useEffect(() => {
    if (typeof probedRecords !== 'number') return;
    setBaseline((current) => (current ? withRecordCount(current, probedRecords) : current));
  }, [probedRecords, baseline]);

  const problems = useMemo(() => specProblems(spec, vocabulary), [spec, vocabulary]);
  const wire = useMemo(() => toWireSpec(normaliseSpec(spec), featuresSupported), [spec, featuresSupported]);
  const wireKey = useMemo(() => JSON.stringify(wire), [wire]);
  const suggestions = useMemo(
    () => mergeSuggestions(templateHints, aiSuggestions, ruleSuggestions),
    [templateHints, aiSuggestions, ruleSuggestions],
  );

  // The server's rule-based suggestions, asked for on arriving at the review
  // screen and again when the fields change in fine-tuning. A failure is
  // silent: suggestions are a help, never a step that can block the flow.
  const signature = suggestionSignature(spec);
  const latestWire = useRef(wire);
  latestWire.current = wire;
  useEffect(() => {
    if (!open || screen !== 'proposal' || !featuresSupported) return undefined;
    let cancelled = false;
    const timer = setTimeout(() => {
      suggestForSpec(latestWire.current, locale)
        .then((result) => {
          if (!cancelled) setRuleSuggestions((prev) => mergeSuggestions(prev, result?.suggestions ?? []));
        })
        .catch(() => undefined);
    }, SUGGEST_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [open, screen, featuresSupported, signature, locale]);

  // Preview on arrival at the create screen, and again whenever the spec moved
  // on since the last preview. A preview that failed for this exact spec is not
  // retried in a loop; changing anything tries again.
  const additions = useMemo(() => (baseline ? additionsOf(baseline, spec) : null), [baseline, spec]);
  // An update needs something added or reworded, and must leave what entries
  // hold as it was; the screens make the second impossible, and this keeps it so.
  const upgradeBlocked =
    upgrade !== null && (!baseline || !additions || !hasAdditions(additions) || !keepsBaseline(baseline, spec));
  const blocked = problems.length > 0 || upgradeBlocked;
  useEffect(() => {
    if (!open || screen !== 'create' || blocked) return undefined;
    if (previewedFor === wireKey || failedFor.current === wireKey) return undefined;
    let cancelled = false;
    setPreviewing(true);
    setRefusal(null);
    setUpgradeRefusal(null);
    (upgradeKey ? previewUpgrade(upgradeKey, wire) : previewModule(wire))
      .then((result) => {
        if (cancelled) return;
        setPreview(result);
        setPreviewedFor(wireKey);
      })
      .catch((err) => {
        if (cancelled) return;
        failedFor.current = wireKey;
        const refused = upgradeRefusalFrom(err);
        if (refused) setUpgradeRefusal(refused);
        else setRefusal(getErrorMessage(err));
      })
      .finally(() => {
        if (!cancelled) setPreviewing(false);
      });
    return () => {
      cancelled = true;
      setPreviewing(false);
    };
    // `wire` follows `wireKey`; listing both would run this twice per change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, screen, blocked, wireKey, previewedFor]);

  const freshPreview = preview !== null && previewedFor === wireKey && !previewing;

  /** A key nobody else here has, so an install is not refused over a name the person never saw. */
  const uniqueKey = (candidate: ModuleSpec): ModuleSpec => {
    if (!takenKeys.includes(candidate.key)) return candidate;
    let n = 2;
    while (takenKeys.includes(`${candidate.key}_${n}`) && n < 100) n += 1;
    return { ...candidate, key: `${candidate.key}_${n}` };
  };

  const startProposal = (
    next: ModuleSpec,
    from: { hints?: Suggestion[]; ai?: Suggestion[]; keyAuto?: boolean; fineTune?: boolean },
  ) => {
    setSpec(next);
    setTemplateHints(from.hints ?? []);
    setAiSuggestions(from.ai ?? []);
    setRuleSuggestions([]);
    setKeyAuto(from.keyAuto ?? false);
    setFineTuneOpen(from.fineTune ?? false);
    setAdvancedOpen(false);
    setRefusal(null);
    setScreen('proposal');
  };

  const handleDraft = async () => {
    if (sentence.trim().length < MIN_DESCRIPTION) return;
    setDrafting(true);
    setRefusal(null);
    try {
      // The locale goes only to a server that knows the field: the old request
      // model refuses unknown keys.
      const result = featuresSupported ? await draftSpec(sentence, locale) : await draftSpec(sentence);
      const drafted = featuresSupported
        ? { ...result.spec, schema_version: SCHEMA_VERSION, features: featuresOf(result.spec) }
        : result.spec;
      startProposal(uniqueKey(drafted), { ai: result.suggestions ?? [] });
    } catch (err) {
      // A 422 here is the assistant declining to describe the module, which is
      // a real answer and not an error to bury in a toast.
      setRefusal(getErrorMessage(err));
    } finally {
      setDrafting(false);
    }
  };

  const handleTemplate = (template: ModuleTemplate) => {
    startProposal(buildFromTemplate(template, t, takenKeys), { hints: templateSuggestions(template, t) });
  };

  const handleScratch = () => {
    const blank = emptySpec();
    startProposal(
      {
        ...blank,
        entity: {
          ...blank.entity,
          name: 'entry',
          display_name: t('module_builder.default_entry', { defaultValue: 'Entry' }),
          plural_name: t('module_builder.default_entries', { defaultValue: 'Entries' }),
        },
      },
      { keyAuto: true, fineTune: true },
    );
  };

  const handleNameChange = (name: string) => {
    setSpec((prev) => ({
      ...prev,
      display_name: name,
      key: keyAuto ? (name.trim() ? autoIdentifier(name, 'register', takenKeys, 3) : '') : prev.key,
    }));
  };

  const handleInstall = async () => {
    // Install what was reviewed, carried with the token that proves it was
    // rendered. The token binds the previewed spec, so sending anything else is
    // refused by the server rather than quietly writing code nobody read.
    if (!preview || !freshPreview) return;
    setInstalling(true);
    setRefusal(null);
    setUpgradeRefusal(null);
    try {
      const result = upgradeKey
        ? upgradedAs(await upgradeModule(upgradeKey, preview.spec, preview.review_token), preview.spec)
        : await installModule(preview.spec, preview.review_token);
      setInstalled(result);
      setScreen('done');
      addToast({
        type: 'success',
        title: upgradeKey
          ? t('module_builder.updated_toast', {
              name: result.display_name,
              defaultValue: '{{name}} is updated',
            })
          : t('module_builder.installed_toast', {
              name: result.display_name,
              defaultValue: '{{name}} is installed and serving',
            }),
      });
      // The installed list is what every screen resolves a module's URL from.
      void qc.invalidateQueries({ queryKey: ['module-builder', 'installed'] });
      // An updated module serves new columns: its page reads them afresh.
      if (upgradeKey) void qc.invalidateQueries({ queryKey: [RUNTIME_MODULE_QUERY_KEY] });
      onInstalled?.(result);
    } catch (err) {
      const refused = upgradeRefusalFrom(err);
      if (refused) setUpgradeRefusal(refused);
      else setRefusal(getErrorMessage(err));
    } finally {
      setInstalling(false);
    }
  };

  const openInstalled = () => {
    if (!installed) return;
    onClose();
    navigate(`/modules/${installed.key}`);
  };

  const goTo = (next: Screen) => {
    setRefusal(null);
    setUpgradeRefusal(null);
    setScreen(next);
  };

  const upgrading = upgrade !== null;
  const loadingInstalled = upgrading && !baseline && !installedSpecQuery.isError;

  return (
    <WideModal
      open={open}
      onClose={onClose}
      size="xl"
      title={
        upgrading
          ? t('module_builder.extend_title', { defaultValue: 'Add fields and functions' })
          : t('module_builder.title', { defaultValue: 'Module builder' })
      }
      subtitle={
        upgrading
          ? spec.display_name
          : t('module_builder.subtitle_v2', {
              defaultValue: 'A register for whatever your site keeps track of, ready in a couple of minutes.',
            })
      }
      busy={drafting || installing}
      footer={
        <WizardFooter
          screen={screen}
          upgrading={upgrading}
          assistantAvailable={assistantAvailable}
          canDraft={sentence.trim().length >= MIN_DESCRIPTION}
          blocked={problems.length > 0}
          drafting={drafting}
          installing={installing}
          canInstall={freshPreview && !blocked}
          onDraft={() => void handleDraft()}
          onBack={() => (upgrading && screen === 'proposal' ? onClose() : goTo(screen === 'create' ? 'proposal' : 'describe'))}
          onNext={() => goTo('create')}
          onInstall={() => void handleInstall()}
          onOpen={openInstalled}
          onClose={onClose}
        />
      }
    >
      <div className="space-y-5" data-testid="module-builder-wizard">
        {screen !== 'done' && !drafting && !loadingInstalled && (
          <StepBar current={screen} onJump={goTo} steps={upgrading ? UPGRADE_STEPS : STEPS} upgrading={upgrading} />
        )}

        {upgrading && installedSpecQuery.isError && (
          <p role="alert" className="rounded-lg bg-semantic-error-bg px-3 py-2 text-sm text-semantic-error">
            {getErrorMessage(installedSpecQuery.error)}
          </p>
        )}
        {loadingInstalled && (
          <p className="flex items-center gap-2 py-8 text-sm text-content-tertiary" data-testid="module-builder-loading-installed">
            <Loader2 size={15} className="animate-spin" />
            {t('common.loading', { defaultValue: 'Loading...' })}
          </p>
        )}

        {refusal && (
          <p
            role="alert"
            className="flex items-start gap-2 rounded-lg bg-semantic-error-bg px-3 py-2 text-sm text-semantic-error"
          >
            <AlertTriangle size={15} className="mt-px shrink-0" />
            {refusal}
          </p>
        )}

        {screen === 'describe' && (
          <DescribeScreen
            sentence={sentence}
            setSentence={setSentence}
            drafting={drafting}
            assistantAvailable={assistantAvailable}
            onDraft={() => void handleDraft()}
            onTemplate={handleTemplate}
            onScratch={handleScratch}
            onClose={onClose}
          />
        )}

        {screen === 'proposal' && !loadingInstalled && !(upgrading && installedSpecQuery.isError) && (
          <ProposalScreen
            spec={spec}
            setSpec={setSpec}
            vocabulary={vocabulary}
            problems={problems}
            suggestions={suggestions}
            featuresSupported={featuresSupported}
            onNameChange={handleNameChange}
            fineTuneOpen={fineTuneOpen}
            setFineTuneOpen={setFineTuneOpen}
            advancedOpen={advancedOpen}
            setAdvancedOpen={setAdvancedOpen}
            onKeyEdited={() => setKeyAuto(false)}
            baseline={baseline}
          />
        )}

        {screen === 'create' && upgradeRefusal && <RefusalNotice refusal={upgradeRefusal} spec={spec} />}

        {screen === 'create' && !upgrading && (
          <CreateScreen spec={spec} preview={freshPreview ? preview : null} previewing={previewing} />
        )}
        {screen === 'create' && upgrading && additions && (
          <UpdateScreen
            spec={spec}
            additions={additions}
            empty={baseline?.empty ?? false}
            preview={freshPreview ? preview : null}
            previewing={previewing}
          />
        )}

        {screen === 'done' && installed && <DoneScreen installed={installed} updated={upgrading} />}
      </div>
    </WideModal>
  );
}

/**
 * Where am I, and how much is left. A finished step is a button back to
 * itself; a step ahead is not, because the footer refuses to move past a
 * screen that still has something to fix.
 */
function StepBar({
  current,
  onJump,
  steps,
  upgrading,
}: {
  current: Screen;
  onJump: (screen: Screen) => void;
  steps: Screen[];
  upgrading: boolean;
}) {
  const { t } = useTranslation();
  const labels: Record<Screen, string> = {
    describe: t('module_builder.step_describe', { defaultValue: 'Describe' }),
    proposal: t('module_builder.step_review', { defaultValue: 'Review' }),
    create: upgrading
      ? t('module_builder.step_update', { defaultValue: 'Update' })
      : t('module_builder.step_create', { defaultValue: 'Create' }),
    done: '',
  };
  const index = steps.indexOf(current);

  return (
    <nav aria-label={t('module_builder.steps_label', { defaultValue: 'Steps' })}>
      <ol className="mx-auto flex max-w-md items-center gap-2">
        {steps.map((step, i) => {
          const done = i < index;
          const here = i === index;
          const body = (
            <>
              <span
                className={clsx(
                  'flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold transition-colors',
                  done && 'bg-oe-blue text-white',
                  here && 'bg-oe-blue-subtle text-oe-blue-text ring-2 ring-oe-blue',
                  !done && !here && 'bg-surface-secondary text-content-quaternary ring-1 ring-border-light',
                )}
              >
                {done ? <Check size={12} strokeWidth={3} /> : i + 1}
              </span>
              <span
                className={clsx(
                  'truncate text-xs',
                  here ? 'font-medium text-content-primary' : 'text-content-tertiary',
                )}
              >
                {labels[step]}
              </span>
            </>
          );
          return (
            <li key={step} className="flex min-w-0 flex-1 items-center gap-2">
              {done ? (
                <button
                  type="button"
                  onClick={() => onJump(step)}
                  className="flex min-w-0 items-center gap-1.5 rounded-lg py-0.5 hover:text-content-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
                  data-testid={`module-builder-step-${step}`}
                >
                  {body}
                </button>
              ) : (
                <span className="flex min-w-0 items-center gap-1.5" aria-current={here ? 'step' : undefined}>
                  {body}
                </span>
              )}
              {i < steps.length - 1 && (
                <span
                  aria-hidden
                  className={clsx('h-px min-w-[1rem] flex-1', i < index ? 'bg-oe-blue' : 'bg-border-light')}
                />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

interface FooterProps {
  screen: Screen;
  upgrading: boolean;
  assistantAvailable: boolean;
  canDraft: boolean;
  blocked: boolean;
  drafting: boolean;
  installing: boolean;
  canInstall: boolean;
  onDraft: () => void;
  onBack: () => void;
  onNext: () => void;
  onInstall: () => void;
  onOpen: () => void;
  onClose: () => void;
}

function WizardFooter({
  screen,
  upgrading,
  assistantAvailable,
  canDraft,
  blocked,
  drafting,
  installing,
  canInstall,
  onDraft,
  onBack,
  onNext,
  onInstall,
  onOpen,
  onClose,
}: FooterProps) {
  const { t } = useTranslation();

  if (screen === 'done') {
    return (
      <div className="flex items-center justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          {t('common.close', { defaultValue: 'Close' })}
        </Button>
        <Button variant="primary" icon={<ArrowRight size={14} />} iconPosition="right" onClick={onOpen} data-testid="module-builder-open">
          {t('module_builder.open_module', { defaultValue: 'Open the module' })}
        </Button>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-between gap-2">
      <Button
        variant="ghost"
        icon={<ArrowLeft size={14} />}
        onClick={screen === 'describe' ? onClose : onBack}
        disabled={drafting || installing}
      >
        {screen === 'describe' || (upgrading && screen === 'proposal')
          ? t('common.cancel', { defaultValue: 'Cancel' })
          : t('common.back', { defaultValue: 'Back' })}
      </Button>
      {screen === 'describe' && assistantAvailable && (
        <Button
          variant="primary"
          icon={<Wand2 size={14} />}
          loading={drafting}
          disabled={!canDraft}
          onClick={onDraft}
          data-testid="module-builder-draft"
        >
          {t('module_builder.draft', { defaultValue: 'Draft it' })}
        </Button>
      )}
      {screen === 'proposal' && (
        <Button
          variant="primary"
          icon={<ArrowRight size={14} />}
          iconPosition="right"
          disabled={blocked}
          onClick={onNext}
          data-testid="module-builder-next"
        >
          {t('module_builder.continue', { defaultValue: 'Continue' })}
        </Button>
      )}
      {screen === 'create' && !upgrading && (
        <Button
          variant="primary"
          icon={<Check size={14} />}
          loading={installing}
          disabled={!canInstall}
          onClick={onInstall}
          data-testid="module-builder-install"
        >
          {t('module_builder.create_module', { defaultValue: 'Create module' })}
        </Button>
      )}
      {screen === 'create' && upgrading && (
        <Button
          variant="primary"
          icon={<Check size={14} />}
          loading={installing}
          disabled={!canInstall}
          onClick={onInstall}
          data-testid="module-builder-update"
        >
          {t('module_builder.update_module', { defaultValue: 'Update module' })}
        </Button>
      )}
    </div>
  );
}

export default ModuleBuilderWizard;
