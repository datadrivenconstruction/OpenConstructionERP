/**
 * StylesLabPage — visual showcase of modern style variants.
 *
 * All radii are tightened to Apple-current scale (iOS 17+/macOS Sequoia/
 * visionOS / WWDC25 Liquid Glass): 12px outer card, 8px inner preview,
 * 10px buttons & icon chips, 6px modern-SaaS-style block tags, 5px mono chip.
 * Pills (rounded-full) stay pill only where the semantic is genuinely
 * a pill (tags, dots, segmented tabs).
 *
 * Open at /styles-lab.
 */

import { useState, type ReactNode } from 'react';
import {
  Hammer, Building2, Calculator, Ruler, FileText, Layers, Sparkles,
  CircleDot, ChevronRight, Download, Plus, ArrowRight, ArrowUpRight, X, Check,
  AlertTriangle, Zap, Wand2, Box, Boxes, Settings, TrendingUp,
  Bell, Activity, Cpu, Lightbulb,
} from 'lucide-react';

/* ────────────────────────────────────────────────────────────────────────── */
/* Page shell                                                                 */
/* ────────────────────────────────────────────────────────────────────────── */

export function StylesLabPage() {
  const [section, setSection] = useState<'headings' | 'buttons' | 'icons' | 'tags' | 'backgrounds'>('headings');

  const tabs: Array<{ key: typeof section; label: string; count: number }> = [
    { key: 'headings',    label: 'Headings',    count: 12 },
    { key: 'buttons',     label: 'Buttons',     count: 14 },
    { key: 'icons',       label: 'Icons',       count: 12 },
    { key: 'tags',        label: 'Tags',        count: 13 },
    { key: 'backgrounds', label: 'Backgrounds', count: 13 },
  ];

  return (
    <div className="min-h-full bg-surface-secondary">
      {/* Hero header */}
      <div className="relative overflow-hidden border-b border-border-light bg-surface-primary">
        <div className="pointer-events-none absolute inset-0 opacity-60">
          <div className="absolute -top-20 -left-10 h-72 w-72 rounded-full bg-oe-blue/20 blur-3xl animate-float" />
          <div className="absolute -top-10 right-20 h-64 w-64 rounded-full bg-fuchsia-400/15 blur-3xl animate-float-delayed" />
          <div className="absolute top-20 left-1/3 h-56 w-56 rounded-full bg-cyan-400/15 blur-3xl animate-float-slow" />
        </div>
        <div className="relative mx-auto max-w-content px-8 py-10">
          <div className="text-2xs uppercase tracking-[0.18em] text-content-tertiary font-medium">
            Internal · Design exploration
          </div>
          <h1 className="mt-2 text-4xl font-semibold tracking-tight bg-gradient-to-r from-content-primary via-oe-blue to-fuchsia-500 bg-clip-text text-transparent bg-[length:200%_auto] animate-gradient-text">
            Styles Lab
          </h1>
          <p className="mt-3 max-w-2xl text-base text-content-secondary leading-relaxed">
            12-14 направлений по каждому элементу. Радиусы выровнены под
            Apple-current (iOS 17+ / macOS Sequoia / WWDC25 Liquid Glass) -
            6-12px вместо прежних 16-20px.
          </p>

          <div className="mt-7 flex flex-wrap gap-2">
            {tabs.map((t) => (
              <button
                key={t.key}
                onClick={() => setSection(t.key)}
                className={[
                  'h-9 px-4 rounded-full text-sm font-medium transition-all duration-normal ease-oe',
                  'border',
                  section === t.key
                    ? 'bg-content-primary text-content-inverse border-content-primary shadow-md'
                    : 'bg-surface-primary text-content-secondary border-border hover:border-content-tertiary',
                ].join(' ')}
              >
                {t.label}
                <span className={[
                  'ml-2 text-2xs',
                  section === t.key ? 'text-content-inverse/60' : 'text-content-tertiary',
                ].join(' ')}>
                  {t.count}
                </span>
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-content px-8 py-10">
        {section === 'headings'    && <HeadingsSection />}
        {section === 'buttons'     && <ButtonsSection />}
        {section === 'icons'       && <IconsSection />}
        {section === 'tags'        && <TagsSection />}
        {section === 'backgrounds' && <BackgroundsSection />}
      </div>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Reusable specimen frame                                                    */
/* ────────────────────────────────────────────────────────────────────────── */

function Specimen({
  no, name, family, note, children,
}: {
  no: number; name: string; family: string; note: string; children: ReactNode;
}) {
  return (
    <div className="group relative rounded-[12px] border border-border-light bg-surface-primary p-6 transition-all duration-normal ease-oe hover:border-border hover:shadow-md">
      <div className="flex items-center gap-2 text-2xs uppercase tracking-[0.16em] text-content-tertiary font-medium">
        <span className="tabular-nums">{String(no).padStart(2, '0')}</span>
        <span className="h-px flex-1 bg-border-light" />
        <span>{family}</span>
      </div>
      <div className="mt-2 text-sm font-semibold text-content-primary">{name}</div>
      <p className="mt-1 text-xs text-content-tertiary leading-relaxed min-h-[2.5em]">{note}</p>

      <div className="mt-5 flex min-h-[88px] items-center justify-center rounded-[8px] bg-surface-secondary/60 px-4 py-6 ring-1 ring-inset ring-border-light/60">
        {children}
      </div>
    </div>
  );
}

function Grid({ children }: { children: ReactNode }) {
  return <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">{children}</div>;
}

function SectionTitle({ children, sub }: { children: ReactNode; sub?: string }) {
  return (
    <div className="mb-6 flex items-baseline gap-3">
      <h2 className="text-xl font-semibold text-content-primary">{children}</h2>
      {sub && <span className="text-xs text-content-tertiary">{sub}</span>}
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════════════ */
/* HEADINGS                                                                  */
/* ════════════════════════════════════════════════════════════════════════ */

function HeadingsSection() {
  return (
    <>
      <SectionTitle sub="text-display family · 12 directions">Headings</SectionTitle>
      <Grid>
        <Specimen no={1} name="Apple Plain" family="Default" note="Текущий OE: крупный semibold, tight tracking. Спокойный baseline.">
          <h3 className="text-2xl font-semibold tracking-tight text-content-primary">Project overview</h3>
        </Specimen>

        <Specimen no={2} name="Gradient Sweep" family="Premium" note="Анимированный градиент через bg-clip-text. Для главных страниц и AI-фичей.">
          <h3 className="text-2xl font-semibold tracking-tight bg-gradient-to-r from-oe-blue via-fuchsia-500 to-cyan-500 bg-clip-text text-transparent bg-[length:200%_auto] animate-gradient-text">
            Project overview
          </h3>
        </Specimen>

        <Specimen no={3} name="Eyebrow + Display" family="Editorial" note="Маленький uppercase-лейбл + крупный заголовок. Журнальная типографика.">
          <div className="text-center">
            <div className="text-2xs uppercase tracking-[0.22em] text-oe-blue font-semibold">Phase 02 · Cost Plan</div>
            <h3 className="mt-2 text-2xl font-semibold tracking-tight text-content-primary">Project overview</h3>
          </div>
        </Specimen>

        <Specimen no={4} name="Accent Underline" family="Structural" note="Заголовок с цветной чертой снизу. Маркирует секции без иконок.">
          <div>
            <h3 className="text-2xl font-semibold tracking-tight text-content-primary">Project overview</h3>
            <div className="mt-2 h-1 w-12 rounded-full bg-gradient-to-r from-oe-blue to-cyan-400" />
          </div>
        </Specimen>

        <Specimen no={5} name="Numbered Watermark" family="Editorial" note="Огромная цифра-водяной-знак позади. Для wizard / пошаговых страниц.">
          <div className="relative">
            <span aria-hidden className="absolute -top-6 -left-2 text-7xl font-bold text-content-primary/5 leading-none select-none">03</span>
            <h3 className="relative text-2xl font-semibold tracking-tight text-content-primary">Project overview</h3>
          </div>
        </Specimen>

        <Specimen no={6} name="Icon + Heading + Meta" family="Functional" note="Иконка-чип, заголовок, мета-строка. Шаблон для dashboard-tile.">
          <div className="flex items-start gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-[10px] bg-oe-blue/10 text-oe-blue ring-1 ring-oe-blue/20">
              <Building2 className="h-5 w-5" />
            </div>
            <div>
              <h3 className="text-lg font-semibold tracking-tight text-content-primary leading-tight">Project overview</h3>
              <div className="text-xs text-content-tertiary">12 BOQs · 4 active phases</div>
            </div>
          </div>
        </Specimen>

        <Specimen no={7} name="Glow Halo" family="Hero" note="Текст с мягким размытым свечением. Для splash, hero, AI-страниц.">
          <h3 className="text-2xl font-semibold tracking-tight text-oe-blue [text-shadow:0_0_24px_rgb(0_113_227_/_45%)]">Project overview</h3>
        </Specimen>

        <Specimen no={8} name="Mono Fingerprint" family="Technical" note="Mono-префикс как code-метка + sans-заголовок. Для тех-страниц.">
          <div className="flex items-baseline gap-3">
            <span className="font-mono text-xs px-1.5 py-0.5 rounded-[5px] bg-surface-tertiary text-content-tertiary border border-border-light">v2.9.36</span>
            <h3 className="text-2xl font-semibold tracking-tight text-content-primary">Project overview</h3>
          </div>
        </Specimen>

        <Specimen no={9} name="Outline Stroke" family="Display" note="Только обводка, без заливки. Для hero и empty-state. -webkit-text-stroke.">
          <h3 className="text-3xl font-bold tracking-tight text-transparent [-webkit-text-stroke:1.5px_var(--oe-text-primary)] dark:[-webkit-text-stroke:1.5px_var(--oe-text-primary)]">
            Project overview
          </h3>
        </Specimen>

        <Specimen no={10} name="Mixed Weights" family="Editorial" note="Лёгкий вес для контекста + жирный градиент для имени. Заметнее, чем плоский semibold.">
          <h3 className="text-2xl tracking-tight">
            <span className="font-light text-content-tertiary">Project </span>
            <span className="font-bold bg-gradient-to-r from-oe-blue to-fuchsia-500 bg-clip-text text-transparent">overview</span>
          </h3>
        </Specimen>

        <Specimen no={11} name="Ultra Display" family="Hero" note="Максимальный размер + жирный вес + ультра-tight tracking. Только для splash/landing.">
          <h3 className="text-[44px] font-bold tracking-[-0.04em] leading-[1.02] text-content-primary">
            Build it<br/>brilliantly.
          </h3>
        </Specimen>

        <Specimen no={12} name="With Sparkline" family="Analytics" note="Заголовок + крошечный график рядом. Для аналитики и live-метрик.">
          <div className="flex items-end gap-3">
            <h3 className="text-2xl font-semibold tracking-tight text-content-primary">€2.4M</h3>
            <svg viewBox="0 0 60 24" className="h-6 w-16 text-semantic-success">
              <polyline points="0,18 10,15 20,16 30,10 40,12 50,5 60,7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            <span className="text-xs font-medium text-semantic-success">+12.4%</span>
          </div>
        </Specimen>
      </Grid>
    </>
  );
}

/* ════════════════════════════════════════════════════════════════════════ */
/* BUTTONS                                                                   */
/* ════════════════════════════════════════════════════════════════════════ */

function ButtonsSection() {
  return (
    <>
      <SectionTitle sub="14 directions · all r ≤ 10px">Buttons</SectionTitle>
      <Grid>
        <Specimen no={1} name="Apple Liquid (default)" family="Current" note="Текущий OE primary. Радиус снижен до 10px (было 20). Лёгкий scale на hover.">
          <button className="inline-flex h-10 items-center gap-2 px-5 rounded-[10px] text-sm font-medium bg-oe-blue text-white shadow-xs hover:shadow-md hover:bg-oe-blue-hover hover:scale-[1.02] active:scale-[0.98] transition-all duration-normal ease-oe">
            <Plus className="h-4 w-4" /> Create BOQ
          </button>
        </Specimen>

        <Specimen no={2} name="Liquid Glass (WWDC25)" family="Modern" note="Frosted glass + верхний rim-highlight + внутренняя тень. Apple iOS 26 / visionOS.">
          <div className="relative w-full">
            <div className="absolute inset-0 -z-10 rounded-[10px] bg-gradient-to-br from-oe-blue/30 via-fuchsia-400/20 to-cyan-400/30 blur-xl" />
            <button className="relative inline-flex h-10 items-center gap-2 px-5 rounded-[10px] text-sm font-medium text-content-primary bg-white/45 dark:bg-white/8 backdrop-blur-2xl ring-1 ring-white/50 dark:ring-white/15 shadow-[inset_0_1px_0_rgba(255,255,255,0.6),0_4px_16px_rgba(0,0,0,0.08)] hover:bg-white/55 transition-all duration-normal ease-oe">
              <Sparkles className="h-4 w-4 text-oe-blue" /> Create BOQ
            </button>
          </div>
        </Specimen>

        <Specimen no={3} name="Gradient Mesh" family="Premium" note="Анимированный градиент. Для главного CTA, AI-кнопок, Pro-плана.">
          <button className="inline-flex h-10 items-center gap-2 px-5 rounded-[10px] text-sm font-semibold text-white shadow-md hover:shadow-lg transition-all duration-normal ease-oe bg-[linear-gradient(120deg,#0071e3_0%,#7c3aed_45%,#06b6d4_100%)] bg-[length:200%_auto] hover:bg-[position:right_center] active:scale-[0.97]">
            <Wand2 className="h-4 w-4" /> Generate with AI
          </button>
        </Specimen>

        <Specimen no={4} name="Neon Glow" family="Futuristic" note="Тёмный solid + цветное свечение. На тёмном фоне - chat, advisor.">
          <div className="rounded-[10px] bg-[#0f1117] p-5 -m-5 w-full">
            <div className="grid place-items-center">
              <button className="relative inline-flex h-10 items-center gap-2 px-5 rounded-[10px] text-sm font-medium bg-[#1a1d2b] text-cyan-300 ring-1 ring-cyan-400/40 shadow-[0_0_0_1px_rgba(34,211,238,0.15),0_0_24px_rgba(34,211,238,0.35)] hover:shadow-[0_0_0_1px_rgba(34,211,238,0.3),0_0_36px_rgba(34,211,238,0.55)] transition-all duration-normal ease-oe">
                <Zap className="h-4 w-4" /> Run inference
              </button>
            </div>
          </div>
        </Specimen>

        <Specimen no={5} name="Brutalist Hard Shadow" family="Bold" note="Чёрный border + offset-shadow. Маркетинг, dev-инструменты. r=8px.">
          <button className="inline-flex h-10 items-center gap-2 px-5 rounded-[8px] text-sm font-bold bg-yellow-300 text-black border-2 border-black shadow-[3px_3px_0_0_#000] hover:shadow-[5px_5px_0_0_#000] hover:-translate-x-0.5 hover:-translate-y-0.5 active:shadow-[1px_1px_0_0_#000] active:translate-x-0.5 active:translate-y-0.5 transition-all duration-fast">
            <ArrowRight className="h-4 w-4" /> Ship it
          </button>
        </Specimen>

        <Specimen no={6} name="Animated Conic Border" family="Premium" note="Конический градиент вращается по периметру. Признак pro/premium.">
          <span className="relative inline-flex p-[1.5px] rounded-[10px] overflow-hidden">
            <span aria-hidden className="absolute inset-[-100%] animate-[spin_4s_linear_infinite] bg-[conic-gradient(from_0deg,#0071e3,#a855f7,#06b6d4,#0071e3)]" />
            <button className="relative inline-flex h-10 items-center gap-2 px-5 rounded-[8.5px] text-sm font-medium bg-surface-primary text-content-primary">
              <Sparkles className="h-4 w-4 text-fuchsia-500" /> Upgrade
            </button>
          </span>
        </Specimen>

        <Specimen no={7} name="Bevel Hairline" family="SaaS Modern" note="Тонкая верхняя hairline + inner bottom shadow. Modern SaaS style.">
          <button className="inline-flex h-10 items-center gap-2 px-5 rounded-[10px] text-sm font-medium text-white bg-content-primary shadow-[inset_0_1px_0_0_rgba(255,255,255,0.15),inset_0_-1px_0_0_rgba(0,0,0,0.4),0_1px_2px_rgba(0,0,0,0.2)] hover:bg-content-primary/90 active:translate-y-px transition-all duration-fast">
            <FileText className="h-4 w-4" /> Open report
          </button>
        </Specimen>

        <Specimen no={8} name="3D Press" family="Tactile" note="Тёмный bottom-edge даёт физическое нажатие. Stripe style.">
          <button className="inline-flex h-10 items-center gap-2 px-5 rounded-[10px] text-sm font-semibold text-white bg-oe-blue active:translate-y-[2px] transition-transform duration-fast shadow-[inset_0_-2px_0_0_rgba(0,0,0,0.25),0_2px_0_0_#005bb5] active:shadow-[inset_0_-1px_0_0_rgba(0,0,0,0.25),0_0px_0_0_#005bb5]">
            <Download className="h-4 w-4" /> Export GAEB
          </button>
        </Specimen>

        <Specimen no={9} name="Outline Refined" family="Minimal" note="Modern-SaaS-style тонкий border, мягкая заливка на hover. Для secondary actions.">
          <button className="inline-flex h-10 items-center gap-2 px-5 rounded-[10px] text-sm font-medium text-content-primary border border-border bg-surface-primary hover:bg-surface-secondary hover:border-content-tertiary transition-all duration-normal ease-oe">
            <FileText className="h-4 w-4" /> Open report
          </button>
        </Specimen>

        <Specimen no={10} name="Shimmer Sweep" family="Attention" note="Полоса света бежит по поверхности на hover. Для важного редкого CTA.">
          <button className="group relative inline-flex h-10 items-center gap-2 px-5 rounded-[10px] text-sm font-medium text-white bg-content-primary overflow-hidden">
            <span aria-hidden className="absolute inset-0 -translate-x-full group-hover:translate-x-full bg-gradient-to-r from-transparent via-white/30 to-transparent transition-transform duration-1000 ease-out" />
            <span className="relative inline-flex items-center gap-2"><Check className="h-4 w-4" /> Approve change order</span>
          </button>
        </Specimen>

        <Specimen no={11} name="Soft Inset (pressed)" family="Calm" note="Кнопка как будто утоплена в поверхность. Для toggle-like state, фильтров.">
          <button className="inline-flex h-10 items-center gap-2 px-5 rounded-[10px] text-sm font-medium text-content-primary bg-surface-secondary shadow-[inset_0_1px_2px_rgba(0,0,0,0.06),inset_0_-1px_0_rgba(255,255,255,0.5)] hover:bg-surface-tertiary transition-colors duration-normal">
            <Settings className="h-4 w-4 text-content-tertiary" /> Configure
          </button>
        </Specimen>

        <Specimen no={12} name="Pulse Attention" family="Alert" note="Пульсирующее цветное кольцо вокруг. Для notification-actions, новых фичей.">
          <button className="relative inline-flex h-10 items-center gap-2 px-5 rounded-[10px] text-sm font-medium text-white bg-oe-blue shadow-md animate-[pulseGlow_2s_ease_infinite]">
            <Bell className="h-4 w-4" /> 3 new updates
          </button>
        </Specimen>

        <Specimen no={13} name="Magnetic Underline" family="Text-only" note="Текстовая кнопка с анимированным подчёркиванием. Для inline CTA, ссылок-действий.">
          <button className="group inline-flex items-center gap-1.5 text-sm font-medium text-oe-blue">
            <span className="relative">
              View pricing details
              <span className="absolute -bottom-0.5 left-0 h-px w-0 group-hover:w-full bg-oe-blue transition-[width] duration-300 ease-oe" />
            </span>
            <ArrowUpRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
          </button>
        </Specimen>

        <Specimen no={14} name="Segmented Pill" family="iOS Native" note="iOS-style segmented control. Для view-switchers (List/Grid/Map).">
          <div className="inline-flex h-9 items-center rounded-[8px] bg-surface-tertiary p-0.5 ring-1 ring-inset ring-border-light">
            <button className="h-8 px-3 text-xs font-medium rounded-[6px] bg-surface-primary text-content-primary shadow-sm">List</button>
            <button className="h-8 px-3 text-xs font-medium rounded-[6px] text-content-tertiary hover:text-content-primary">Grid</button>
            <button className="h-8 px-3 text-xs font-medium rounded-[6px] text-content-tertiary hover:text-content-primary">Map</button>
          </div>
        </Specimen>
      </Grid>
    </>
  );
}

/* ════════════════════════════════════════════════════════════════════════ */
/* ICONS                                                                     */
/* ════════════════════════════════════════════════════════════════════════ */

function IconsSection() {
  return (
    <>
      <SectionTitle sub="12 treatments · r ≤ 10px on chips">Icons</SectionTitle>
      <Grid>
        <Specimen no={1} name="Plain Stroke" family="Default" note="Чистая Lucide-иконка, текущий стиль. Для inline-использования в тексте.">
          <Hammer className="h-6 w-6 text-content-secondary" strokeWidth={1.75} />
        </Specimen>

        <Specimen no={2} name="Soft Chip" family="Functional" note="Иконка в мягко-окрашенном квадрате. Dashboard tile, feature card.">
          <div className="grid h-12 w-12 place-items-center rounded-[10px] bg-oe-blue/10 text-oe-blue">
            <Building2 className="h-6 w-6" strokeWidth={1.75} />
          </div>
        </Specimen>

        <Specimen no={3} name="Gradient Chip" family="Premium" note="Цветной градиент + белая иконка. Для AI и premium-фичей.">
          <div className="grid h-12 w-12 place-items-center rounded-[10px] text-white shadow-md bg-[linear-gradient(135deg,#0071e3_0%,#7c3aed_100%)]">
            <Sparkles className="h-6 w-6" strokeWidth={1.75} />
          </div>
        </Specimen>

        <Specimen no={4} name="Ring Border" family="Status" note="Кольцо + цвет внутри. Для статусных индикаторов (passed, blocked).">
          <div className="grid h-12 w-12 place-items-center rounded-full bg-semantic-success-bg text-semantic-success ring-2 ring-semantic-success/30 ring-offset-2 ring-offset-surface-primary">
            <Check className="h-5 w-5" strokeWidth={2.5} />
          </div>
        </Specimen>

        <Specimen no={5} name="Glow Halo" family="Hero" note="Иконка + мягкое цветное свечение позади. Для splash и hero-блоков.">
          <div className="relative">
            <div aria-hidden className="absolute inset-0 -m-2 rounded-full bg-fuchsia-500/30 blur-xl" />
            <div className="relative grid h-12 w-12 place-items-center rounded-[10px] bg-surface-primary text-fuchsia-500 ring-1 ring-fuchsia-500/30">
              <Wand2 className="h-6 w-6" strokeWidth={1.75} />
            </div>
          </div>
        </Specimen>

        <Specimen no={6} name="Duotone Stack" family="Editorial" note="Две иконки наслоены со смещением. Декоративно, для empty states.">
          <div className="relative h-12 w-12">
            <Boxes className="absolute inset-0 m-auto h-10 w-10 text-oe-blue/30" strokeWidth={1.5} />
            <Box className="absolute inset-0 m-auto h-7 w-7 translate-x-1.5 translate-y-1.5 text-oe-blue" strokeWidth={1.75} />
          </div>
        </Specimen>

        <Specimen no={7} name="Pill with Label" family="Metadata" note="Иконка + текст в pill. Chips для типа файла, источника, тэга.">
          <span className="inline-flex h-8 items-center gap-1.5 rounded-full bg-surface-tertiary px-3 text-xs font-medium text-content-secondary ring-1 ring-inset ring-border-light">
            <Ruler className="h-3.5 w-3.5 text-oe-blue" strokeWidth={2} />
            243 m²
          </span>
        </Specimen>

        <Specimen no={8} name="Inset Depth" family="Tactile" note="Внутренняя тень даёт «выгравированную» глубину. Toggle/option-grid.">
          <div className="grid h-12 w-12 place-items-center rounded-[10px] bg-surface-secondary text-content-primary shadow-[inset_0_2px_4px_rgba(0,0,0,0.08),inset_0_-1px_0_rgba(255,255,255,0.6)]">
            <Calculator className="h-6 w-6" strokeWidth={1.75} />
          </div>
        </Specimen>

        <Specimen no={9} name="SF Symbol Ramp" family="iOS Native" note="Серый градиент-ramp с тёмным окантом. iOS Settings-icon style.">
          <div className="grid h-12 w-12 place-items-center rounded-[10px] text-white shadow-md bg-[linear-gradient(180deg,#8e8e93_0%,#48484a_100%)] ring-1 ring-inset ring-white/10">
            <Settings className="h-6 w-6" strokeWidth={1.75} />
          </div>
        </Specimen>

        <Specimen no={10} name="Glass Floating" family="Modern" note="Frosted-glass chip с rim highlight. Поверх изображений / 3D-вьюера.">
          <div className="relative w-full grid place-items-center">
            <div className="absolute inset-0 -z-10 rounded-[10px] bg-gradient-to-br from-oe-blue/30 to-fuchsia-400/30 blur-md" />
            <div className="grid h-12 w-12 place-items-center rounded-[10px] bg-white/45 dark:bg-white/8 backdrop-blur-xl ring-1 ring-white/50 dark:ring-white/15 text-content-primary shadow-[inset_0_1px_0_rgba(255,255,255,0.6),0_4px_12px_rgba(0,0,0,0.08)]">
              <Cpu className="h-6 w-6" strokeWidth={1.75} />
            </div>
          </div>
        </Specimen>

        <Specimen no={11} name="Stacked Layers (3D)" family="Editorial" note="Несколько слоёв со сдвигом - псевдо-3D глубина. Для feature-карточек.">
          <div className="relative h-12 w-12">
            <div className="absolute inset-0 rounded-[10px] bg-oe-blue/15 translate-x-2 translate-y-2" />
            <div className="absolute inset-0 rounded-[10px] bg-oe-blue/30 translate-x-1 translate-y-1" />
            <div className="absolute inset-0 grid place-items-center rounded-[10px] bg-oe-blue text-white shadow-md">
              <Layers className="h-6 w-6" strokeWidth={1.75} />
            </div>
          </div>
        </Specimen>

        <Specimen no={12} name="Pulse Ring" family="Realtime" note="Анимированное расходящееся кольцо. Live-status, активное соединение.">
          <div className="relative">
            <span aria-hidden className="absolute inset-0 rounded-full bg-semantic-success/40 animate-ping" />
            <div className="relative grid h-12 w-12 place-items-center rounded-full bg-semantic-success text-white shadow-md">
              <Activity className="h-5 w-5" strokeWidth={2.25} />
            </div>
          </div>
        </Specimen>
      </Grid>
    </>
  );
}

/* ════════════════════════════════════════════════════════════════════════ */
/* TAGS                                                                      */
/* ════════════════════════════════════════════════════════════════════════ */

function TagsSection() {
  return (
    <>
      <SectionTitle sub="13 directions · pills + squircles">Tags & Badges</SectionTitle>
      <Grid>
        <Specimen no={1} name="Soft Pill (current Badge)" family="Default" note="Текущий OE Badge: мягкий фон + текст в том же тоне. Универсальный.">
          <span className="inline-flex h-6 items-center gap-1.5 rounded-full px-2 text-xs font-medium bg-semantic-success-bg text-semantic-success">Approved</span>
        </Specimen>

        <Specimen no={2} name="Solid Bold" family="Emphatic" note="Насыщенный цвет, белый текст. Для жёстких алертов: blocked, overdue.">
          <span className="inline-flex h-6 items-center gap-1.5 rounded-full px-2.5 text-xs font-semibold bg-semantic-error text-white shadow-xs">
            <AlertTriangle className="h-3 w-3" /> Overdue
          </span>
        </Specimen>

        <Specimen no={3} name="Outline Ghost" family="Minimal" note="Только border + текст, прозрачный фон. Для второстепенных категорий.">
          <span className="inline-flex h-6 items-center gap-1.5 rounded-full px-2.5 text-xs font-medium text-content-secondary border border-border">Draft</span>
        </Specimen>

        <Specimen no={4} name="Dot + Label" family="Status" note="Цветная точка + plain текст. Минимум шума, читается как «status:value».">
          <span className="inline-flex h-6 items-center gap-2 text-xs font-medium text-content-primary">
            <span className="h-2 w-2 rounded-full bg-semantic-success ring-2 ring-semantic-success/20" />
            In progress
          </span>
        </Specimen>

        <Specimen no={5} name="Gradient Pill" family="Premium" note="Анимированный градиент. Для «AI-suggested», «Pro», «New».">
          <span className="inline-flex h-6 items-center gap-1 rounded-full px-2.5 text-xs font-semibold text-white bg-[linear-gradient(120deg,#0071e3,#a855f7,#06b6d4)] bg-[length:200%_auto] animate-gradient-text">
            <Sparkles className="h-3 w-3" /> AI suggested
          </span>
        </Specimen>

        <Specimen no={6} name="Live Pulse Dot" family="Realtime" note="Пульсирующая точка с расходящимся кольцом. «Live», «Running», presence.">
          <span className="inline-flex h-6 items-center gap-2 rounded-full bg-surface-tertiary px-2.5 text-xs font-medium text-content-secondary ring-1 ring-inset ring-border-light">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-semantic-success opacity-60" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-semantic-success" />
            </span>
            Live · 3 viewers
          </span>
        </Specimen>

        <Specimen no={7} name="Mono Code Chip" family="Technical" note="Monospace + рамка как kbd. r=5px. Версии, IDs, error codes.">
          <span className="inline-flex h-6 items-center rounded-[5px] px-1.5 font-mono text-2xs font-medium text-content-primary bg-surface-tertiary border border-border-light shadow-[inset_0_-1px_0_rgba(0,0,0,0.05)]">
            DIN-276/330
          </span>
        </Specimen>

        <Specimen no={8} name="Glass Frosted" family="Modern" note="Backdrop-blur на цветном фоне. Для overlays поверх 3D-вьюера.">
          <div className="relative w-full grid place-items-center">
            <div className="absolute inset-0 -z-10 rounded-[8px] bg-gradient-to-br from-oe-blue/30 to-fuchsia-400/30 blur-md" />
            <span className="inline-flex h-6 items-center gap-1.5 rounded-full px-2.5 text-xs font-medium text-content-primary bg-white/50 dark:bg-white/10 backdrop-blur-xl ring-1 ring-white/40 dark:ring-white/15">
              <Layers className="h-3 w-3" /> Level 02
            </span>
          </div>
        </Specimen>

        <Specimen no={9} name="Removable Chip" family="Functional" note="С кнопкой-крестиком. Фильтры, multi-select, applied search terms.">
          <span className="inline-flex h-7 items-center gap-1.5 rounded-full pl-3 pr-1 text-xs font-medium text-oe-blue bg-oe-blue/10 ring-1 ring-inset ring-oe-blue/20">
            <CircleDot className="h-3 w-3" /> Concrete C30/37
            <button className="grid h-5 w-5 place-items-center rounded-full hover:bg-oe-blue/20 transition-colors" aria-label="Remove filter">
              <X className="h-3 w-3" />
            </button>
          </span>
        </Specimen>

        <Specimen no={10} name="Squircle Solid" family="iOS Native" note="iOS Section-style: пастельный блок с r=6px. Для категорий и tag-таксономий.">
          <div className="flex items-center gap-1.5">
            <span className="inline-flex h-6 items-center rounded-[6px] px-2 text-2xs font-semibold uppercase tracking-wider bg-violet-100 text-violet-700 dark:bg-violet-500/20 dark:text-violet-300">Concrete</span>
            <span className="inline-flex h-6 items-center rounded-[6px] px-2 text-2xs font-semibold uppercase tracking-wider bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-300">Rebar</span>
            <span className="inline-flex h-6 items-center rounded-[6px] px-2 text-2xs font-semibold uppercase tracking-wider bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300">Finish</span>
          </div>
        </Specimen>

        <Specimen no={11} name="Trend Arrow" family="Analytics" note="Цифра + стрелка тренда. Для KPI-карточек: рост / падение / no change.">
          <div className="inline-flex items-center gap-1.5">
            <span className="inline-flex h-6 items-center gap-1 rounded-full px-2 text-xs font-semibold bg-semantic-success-bg text-semantic-success">
              <TrendingUp className="h-3 w-3" /> +12.4%
            </span>
            <span className="inline-flex h-6 items-center gap-1 rounded-full px-2 text-xs font-semibold bg-semantic-error-bg text-semantic-error">
              <TrendingUp className="h-3 w-3 rotate-180" /> −3.1%
            </span>
          </div>
        </Specimen>

        <Specimen no={12} name="Counter Pip" family="Notification" note="Круглый цифровой badge поверх иконки. Inbox, queue, pending count.">
          <div className="relative">
            <div className="grid h-10 w-10 place-items-center rounded-[10px] bg-surface-tertiary text-content-secondary">
              <Bell className="h-5 w-5" strokeWidth={1.75} />
            </div>
            <span className="absolute -top-1 -right-1 grid min-h-[18px] min-w-[18px] place-items-center rounded-full bg-semantic-error px-1 text-2xs font-bold text-white ring-2 ring-surface-primary">
              12
            </span>
          </div>
        </Specimen>

        <Specimen no={13} name="AI Thinking Shimmer" family="AI" note="Pill с пробегающим световым shimmer. «Thinking…», «Indexing…», «Processing…».">
          <span className="relative inline-flex h-6 items-center gap-1.5 overflow-hidden rounded-full px-2.5 text-xs font-medium text-fuchsia-700 dark:text-fuchsia-200 bg-fuchsia-100 dark:bg-fuchsia-500/15 ring-1 ring-inset ring-fuchsia-300/40">
            <span aria-hidden className="absolute inset-0 -translate-x-full animate-[shimmer_2s_linear_infinite] bg-gradient-to-r from-transparent via-white/40 to-transparent" />
            <Lightbulb className="relative h-3 w-3" /> <span className="relative">Thinking…</span>
          </span>
        </Specimen>
      </Grid>

      {/* Composite demo */}
      <div className="mt-10 rounded-[12px] border border-border-light bg-surface-primary p-6">
        <div className="text-2xs uppercase tracking-[0.16em] text-content-tertiary font-medium">Composition · realistic row</div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="inline-flex h-6 items-center gap-1.5 rounded-full bg-semantic-success-bg px-2 text-xs font-medium text-semantic-success">Approved</span>
          <span className="inline-flex h-6 items-center gap-2 text-xs font-medium text-content-primary"><span className="h-2 w-2 rounded-full bg-semantic-warning ring-2 ring-semantic-warning/20"/>Waiting client</span>
          <span className="inline-flex h-6 items-center rounded-[5px] px-1.5 font-mono text-2xs text-content-primary bg-surface-tertiary border border-border-light">v2.9.36</span>
          <span className="inline-flex h-6 items-center rounded-[6px] px-2 text-2xs font-semibold uppercase tracking-wider bg-violet-100 text-violet-700 dark:bg-violet-500/20 dark:text-violet-300">Concrete</span>
          <span className="inline-flex h-6 items-center gap-1 rounded-full px-2 text-xs font-semibold bg-semantic-success-bg text-semantic-success"><TrendingUp className="h-3 w-3"/> +12.4%</span>
          <span className="inline-flex h-6 items-center gap-1 rounded-full px-2.5 text-xs font-semibold text-white bg-[linear-gradient(120deg,#0071e3,#a855f7,#06b6d4)] bg-[length:200%_auto] animate-gradient-text">
            <Sparkles className="h-3 w-3"/> AI suggested
          </span>
          <span className="inline-flex h-6 items-center gap-1.5 rounded-full px-2.5 text-xs font-medium text-content-secondary border border-border">Draft</span>
          <ChevronRight className="h-3.5 w-3.5 text-content-quaternary" />
          <span className="text-xs text-content-tertiary">12 more</span>
        </div>
      </div>
    </>
  );
}

/* ════════════════════════════════════════════════════════════════════════ */
/* BACKGROUNDS                                                               */
/* ════════════════════════════════════════════════════════════════════════ */

function BgSpecimen({
  no, name, family, note, bgClass, bgStyle, dark = false, children,
}: {
  no: number;
  name: string;
  family: string;
  note: string;
  bgClass?: string;
  bgStyle?: React.CSSProperties;
  dark?: boolean;
  children?: ReactNode;
}) {
  return (
    <div className="rounded-[12px] border border-border-light bg-surface-primary overflow-hidden transition-all duration-normal ease-oe hover:border-border hover:shadow-md">
      <div className="px-6 pt-5 pb-3">
        <div className="flex items-center gap-2 text-2xs uppercase tracking-[0.16em] text-content-tertiary font-medium">
          <span className="tabular-nums">{String(no).padStart(2, '0')}</span>
          <span className="h-px flex-1 bg-border-light" />
          <span>{family}</span>
        </div>
        <div className="mt-2 text-sm font-semibold text-content-primary">{name}</div>
        <p className="mt-1 text-xs text-content-tertiary leading-relaxed min-h-[2.5em]">{note}</p>
      </div>
      <div
        className={['relative h-[240px] overflow-hidden border-t border-border-light', bgClass ?? ''].join(' ')}
        style={bgStyle}
      >
        {children ?? <SampleContent dark={dark} />}
      </div>
    </div>
  );
}

/** Realistic content overlay so we can judge readability against each background. */
function SampleContent({ dark = false }: { dark?: boolean }) {
  const titleColor   = dark ? 'text-white'                : 'text-content-primary';
  const subColor     = dark ? 'text-white/65'             : 'text-content-secondary';
  const cardBg       = dark ? 'bg-white/8 backdrop-blur-xl ring-white/15' : 'bg-surface-primary/85 backdrop-blur-md ring-border-light/60';
  const btnBg        = dark ? 'bg-white text-[#0f1117]'   : 'bg-content-primary text-content-inverse';

  return (
    <div className="relative h-full p-6 flex flex-col justify-between">
      <div>
        <div className={['text-2xs uppercase tracking-[0.18em] font-medium', dark ? 'text-white/55' : 'text-content-tertiary'].join(' ')}>
          Phase 02 · Cost plan
        </div>
        <h4 className={['mt-1.5 text-xl font-semibold tracking-tight', titleColor].join(' ')}>
          Berlin Mitte · Tower B
        </h4>
        <p className={['mt-1 text-xs leading-relaxed max-w-md', subColor].join(' ')}>
          AI-suggested BOQ ready for review. 1,284 positions across 12 sections.
        </p>
      </div>
      <div className="flex items-center gap-2">
        <button className={['inline-flex h-8 items-center gap-1.5 px-3 rounded-[8px] text-xs font-medium shadow-sm', btnBg].join(' ')}>
          <Sparkles className="h-3.5 w-3.5" /> Review estimate
        </button>
        <span className={['inline-flex h-6 items-center gap-1.5 rounded-full px-2.5 text-xs font-medium ring-1 ring-inset', cardBg].join(' ')}>
          €2.4M
        </span>
      </div>
    </div>
  );
}

function BackgroundsSection() {
  /* Reused SVG data URIs (kept inline for portability) */
  const noiseSvg =
    "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 200'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 0.35 0'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>";

  return (
    <>
      <SectionTitle sub="12 page-level treatments · content overlay shows readability">Backgrounds</SectionTitle>
      <div className="grid gap-5 lg:grid-cols-2">

        <BgSpecimen no={1} name="Plain Soft" family="Default"
          note="Текущий OE: однотонный surface-secondary. Безопасно для контент-плотных страниц (BOQ, tables)."
          bgClass="bg-surface-secondary"
        />

        <BgSpecimen no={2} name="Dot Grid (subtle)" family="Modern SaaS"
          note="Сетка точек 0.9px с прозрачностью 16%, шаг 24px. Едва видна - добавляет «текстуру», но не отвлекает от таблиц/BOQ."
          bgStyle={{
            backgroundColor: 'var(--oe-bg-secondary)',
            backgroundImage:
              'radial-gradient(circle, rgba(60,60,67,0.16) 0.9px, transparent 0.9px)',
            backgroundSize: '24px 24px',
          }}
        />

        <BgSpecimen no={3} name="Dot Grid + Spotlight" family="Combo (рекомендую)"
          note="Тот же subtle dot grid, но сверху мягкое синее пятно радиально расходится из верха страницы. Чувствуется фокус, но фон не давит."
          bgStyle={{
            backgroundColor: 'var(--oe-bg-secondary)',
            backgroundImage:
              'radial-gradient(80% 55% at 50% -10%, rgba(0,113,227,0.20) 0%, rgba(0,113,227,0.06) 35%, rgba(0,113,227,0) 65%),' +
              'radial-gradient(circle, rgba(60,60,67,0.16) 0.9px, transparent 0.9px)',
            backgroundSize: 'auto, 24px 24px',
            backgroundRepeat: 'no-repeat, repeat',
          }}
        />

        <BgSpecimen no={4} name="Line Grid (Graph Paper)" family="Technical"
          note="Тонкая координатная сетка. Подходит для инженерных страниц: Quantities, Takeoff, CAD-Explorer."
          bgStyle={{
            backgroundColor: 'var(--oe-bg-secondary)',
            backgroundImage:
              'linear-gradient(to right, var(--oe-border-light) 1px, transparent 1px),' +
              'linear-gradient(to bottom, var(--oe-border-light) 1px, transparent 1px)',
            backgroundSize: '32px 32px',
          }}
        />

        <BgSpecimen no={5} name="Radial Spotlight" family="Apple Hero"
          note="Мягкое цветное пятно сверху, расходящееся вниз. Apple-style hero / splash. Не для контентных страниц."
          bgStyle={{
            background:
              'radial-gradient(80% 60% at 50% 0%, rgba(0,113,227,0.18) 0%, rgba(0,113,227,0) 60%),' +
              'var(--oe-bg-secondary)',
          }}
        />

        <BgSpecimen no={6} name="Aurora Blobs" family="Premium"
          note="Три цветных размытых блоба, медленный float. Для premium-фичей, AI-страниц, advisor."
        >
          <div className="absolute inset-0 bg-surface-secondary" />
          <div className="absolute -top-8 -left-8 h-56 w-56 rounded-full bg-oe-blue/25 blur-3xl animate-float" />
          <div className="absolute top-1/3 right-0 h-56 w-56 rounded-full bg-fuchsia-400/20 blur-3xl animate-float-delayed" />
          <div className="absolute bottom-0 left-1/3 h-48 w-48 rounded-full bg-cyan-400/20 blur-3xl animate-float-slow" />
          <SampleContent />
        </BgSpecimen>

        <BgSpecimen no={7} name="Animated Mesh Gradient" family="Hero" dark
          note="Многоцветный анимированный градиент. Для splash, hero, маркетинг. Контент только белый."
          bgClass="text-white"
          bgStyle={{
            background:
              'linear-gradient(120deg, #0071e3 0%, #7c3aed 30%, #06b6d4 60%, #0071e3 100%)',
            backgroundSize: '300% 300%',
            animation: 'gradientShift 14s ease infinite',
          }}
        />

        <BgSpecimen no={8} name="Noise Grain" family="Premium"
          note="SVG-шум 35% поверх basesurface. Тёплый, плёночный premium-vibe. Безопасно для длинных текстов."
          bgStyle={{
            backgroundColor: 'var(--oe-bg-secondary)',
            backgroundImage: `url("${noiseSvg}")`,
          }}
        />

        <BgSpecimen no={9} name="Topographic Contours" family="Construction"
          note="Изогипсы - горизонтали высот. Прямая отсылка к стройке/гео. Для projects landing, BIM, /architecture."
        >
          <div className="absolute inset-0 bg-surface-secondary" />
          <svg className="absolute inset-0 h-full w-full text-oe-blue/15" viewBox="0 0 800 240" preserveAspectRatio="none" aria-hidden>
            <g fill="none" stroke="currentColor" strokeWidth="1">
              <path d="M-50 50 Q150 10, 350 60 T800 50" />
              <path d="M-50 80 Q150 40, 350 90 T800 80" />
              <path d="M-50 110 Q150 70, 350 120 T800 110" />
              <path d="M-50 140 Q150 100, 350 150 T800 140" />
              <path d="M-50 170 Q150 130, 350 180 T800 170" />
              <path d="M-50 200 Q150 160, 350 210 T800 200" />
            </g>
            <g fill="none" stroke="currentColor" strokeWidth="0.5" opacity="0.7">
              <path d="M-50 65 Q150 25, 350 75 T800 65" />
              <path d="M-50 95 Q150 55, 350 105 T800 95" />
              <path d="M-50 125 Q150 85, 350 135 T800 125" />
              <path d="M-50 155 Q150 115, 350 165 T800 155" />
              <path d="M-50 185 Q150 145, 350 195 T800 185" />
            </g>
          </svg>
          <SampleContent />
        </BgSpecimen>

        <BgSpecimen no={10} name="Soft Bottom Fade" family="Subtle"
          note="Низ страницы плавно окрашивается в брендовый оттенок. Маркирует контекст без шума."
          bgStyle={{
            background:
              'linear-gradient(180deg, var(--oe-bg-secondary) 0%, var(--oe-bg-secondary) 50%, rgba(0,113,227,0.08) 100%)',
          }}
        />

        <BgSpecimen no={11} name="Diagonal Stripes" family="Editorial"
          note="Repeating-linear-gradient под углом 45°. Заметный паттерн, для нестандартных секций (about, changelog)."
          bgStyle={{
            backgroundColor: 'var(--oe-bg-secondary)',
            backgroundImage:
              'repeating-linear-gradient(45deg, var(--oe-border-light) 0 1px, transparent 1px 14px)',
          }}
        />

        <BgSpecimen no={12} name="Cross-hatch (Drafting)" family="Construction"
          note="Двойная штриховка под 45°/135° - лист миллиметровки/чертёжного эскиза. Для CAD/BIM."
          bgStyle={{
            backgroundColor: 'var(--oe-bg-secondary)',
            backgroundImage:
              'repeating-linear-gradient(45deg, var(--oe-border-light) 0 1px, transparent 1px 12px),' +
              'repeating-linear-gradient(135deg, var(--oe-border-light) 0 1px, transparent 1px 12px)',
          }}
        />

        <BgSpecimen no={13} name="Dark Space" family="Chat / AI" dark
          note="Глубокий тёмный фон со звёздной россыпью. Для ERP-chat, advisor, dark-mode-only surfaces."
          bgStyle={{
            background:
              'radial-gradient(80% 60% at 50% 0%, rgba(124,58,237,0.18) 0%, rgba(124,58,237,0) 60%),' +
              'radial-gradient(60% 40% at 80% 100%, rgba(6,182,212,0.12) 0%, transparent 60%),' +
              '#0a0c14',
          }}
        >
          {/* Stars */}
          <div className="absolute inset-0" aria-hidden>
            {[
              ['12%','22%'], ['28%','60%'], ['44%','15%'], ['62%','75%'], ['78%','35%'],
              ['86%','12%'], ['22%','85%'], ['52%','45%'], ['72%','55%'], ['38%','78%'],
              ['8%','55%'], ['58%','22%'],
            ].map(([l, t], i) => (
              <span key={i} className="absolute h-px w-px rounded-full bg-white shadow-[0_0_4px_1px_rgba(255,255,255,0.6)]" style={{ left: l, top: t }} />
            ))}
          </div>
          <SampleContent dark />
        </BgSpecimen>

      </div>
    </>
  );
}
