import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import {
  BarChart3,
  ClipboardList,
  CalendarDays,
  ShieldCheck,
  AlertTriangle,
  CircleDollarSign,
  Sparkles,
  Lightbulb,
  Bot,
  MessageSquare,
  Calculator,
  ArrowUpRight,
  type LucideIcon,
} from 'lucide-react';

interface DataPanelEmptyProps {
  onSuggestion?: (text: string) => void;
}

/**
 * Rich empty state for the data panel — explains what the AI Chat can do,
 * shows tool categories with examples, and provides quick-start suggestions.
 *
 * All strings use i18next so the page is fully translated to all supported
 * languages. Theme colors come from CSS variables (--chat-*) which respect
 * the site-wide light/dark preference via [data-chat-theme].
 */
export default function DataPanelEmpty({ onSuggestion }: DataPanelEmptyProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  // AI tools cross-link strip (CONN-82) - reach the sibling AI surfaces
  // (Agents, Cost Advisor, Quick Estimate) from the chat empty state. The
  // chat page itself is the current surface, so it is dropped from the list.
  const AI_TOOLS: Array<{ to: string; icon: LucideIcon; label: string }> = [
    { to: '/ai-agents', icon: Bot, label: t('nav.ai_agents', { defaultValue: 'AI Agents' }) },
    {
      to: '/advisor',
      icon: MessageSquare,
      label: t('nav.ai_advisor', { defaultValue: 'AI Cost Advisor' }),
    },
    {
      to: '/ai-estimate',
      icon: Calculator,
      label: t('nav.ai_estimate', { defaultValue: 'AI Quick Estimate' }),
    },
  ];

  const TOOL_CATEGORIES: Array<{
    icon: LucideIcon;
    title: string;
    desc: string;
    examples: string[];
  }> = [
    {
      icon: BarChart3,
      title: t('chat.cat_projects_title', { defaultValue: 'Projects & Portfolio' }),
      desc: t('chat.cat_projects_desc', {
        defaultValue:
          'Compare projects, see portfolio overview, find at-risk work, generate executive summaries.',
      }),
      examples: [
        t('chat.ex_show_projects', { defaultValue: 'Show all my projects' }),
        t('chat.ex_compare_projects', { defaultValue: 'Compare Berlin and Munich projects' }),
        t('chat.ex_at_risk', { defaultValue: 'Which projects are over budget?' }),
      ],
    },
    {
      icon: ClipboardList,
      title: t('chat.cat_boq_title', { defaultValue: 'BOQ & Estimation' }),
      desc: t('chat.cat_boq_desc', {
        defaultValue:
          'Inspect bill of quantities, find missing prices, match items to CWICR cost database, calculate totals.',
      }),
      examples: [
        t('chat.ex_boq_zero', { defaultValue: 'Find BOQ items with zero price' }),
        t('chat.ex_boq_total', { defaultValue: 'What is my BOQ grand total?' }),
        t('chat.ex_match_prices', { defaultValue: 'Match my BOQ with CWICR prices' }),
      ],
    },
    {
      icon: CalendarDays,
      title: t('chat.cat_schedule_title', { defaultValue: 'Schedule & Critical Path' }),
      desc: t('chat.cat_schedule_desc', {
        defaultValue:
          'View Gantt timelines, identify the critical path, check progress, generate schedules from BOQs.',
      }),
      examples: [
        t('chat.ex_schedule_show', { defaultValue: 'Show project schedule' }),
        t('chat.ex_critical_path', { defaultValue: 'What is the critical path?' }),
        t('chat.ex_gen_schedule', { defaultValue: 'Generate a schedule from my BOQ' }),
      ],
    },
    {
      icon: ShieldCheck,
      title: t('chat.cat_validation_title', { defaultValue: 'Validation & Quality' }),
      desc: t('chat.cat_validation_desc', {
        defaultValue:
          'Run classification and quality-rule validation, find compliance issues, get fix suggestions.',
      }),
      examples: [
        t('chat.ex_validate', { defaultValue: 'Run validation on my BOQ' }),
        t('chat.ex_compliance', { defaultValue: 'Check classification compliance' }),
        t('chat.ex_errors', { defaultValue: 'Show all validation errors' }),
      ],
    },
    {
      icon: AlertTriangle,
      title: t('chat.cat_risk_title', { defaultValue: 'Risk & Cost Model' }),
      desc: t('chat.cat_risk_desc', {
        defaultValue:
          'Inspect the risk register, view 5×5 risk matrix, check EVM forecast metrics (EAC, CPI, SPI).',
      }),
      examples: [
        t('chat.ex_risks', { defaultValue: 'Show project risks' }),
        t('chat.ex_evm', { defaultValue: 'What is my EAC and CPI?' }),
        t('chat.ex_high_risk', { defaultValue: 'Find high-impact risks without mitigation' }),
      ],
    },
    {
      icon: CircleDollarSign,
      title: t('chat.cat_costs_title', { defaultValue: 'Cost Database (CWICR)' }),
      desc: t('chat.cat_costs_desc', {
        defaultValue:
          'Search 55,000+ construction cost items across 48 regions and 24 languages.',
      }),
      examples: [
        t('chat.ex_search_concrete', { defaultValue: 'Search CWICR for concrete C30/37' }),
        t('chat.ex_brick_uk', { defaultValue: 'Find brickwork prices for the UK' }),
        t('chat.ex_steel_de', { defaultValue: 'Steel rebar prices in Germany' }),
      ],
    },
  ];

  return (
    <div
      style={{
        height: '100%',
        overflowY: 'auto',
        fontFamily: 'var(--chat-font-body)',
      }}
    >
      <div
        style={{
          maxWidth: 800,
          margin: '0 auto',
          padding: '24px 14px 32px',
        }}
      >
        {/* Hero icon + headline */}
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <div
            style={{
              width: 64,
              height: 64,
              borderRadius: '50%',
              background: 'var(--chat-surface-2)',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--chat-accent)',
              marginBottom: 16,
            }}
          >
            <Sparkles size={28} strokeWidth={1.75} />
          </div>
          <h1
            style={{
              fontSize: 22,
              fontWeight: 600,
              color: 'var(--chat-text-primary)',
              margin: '0 0 8px',
            }}
          >
            {t('chat.empty_title', { defaultValue: 'Your construction ERP, in one conversation' })}
          </h1>
          <p
            style={{
              fontSize: 14,
              color: 'var(--chat-text-secondary)',
              margin: 0,
              lineHeight: 1.6,
              maxWidth: 520,
              marginInline: 'auto',
            }}
          >
            {t('chat.empty_subtitle', {
              defaultValue:
                'Ask anything about your projects in natural language. The AI uses 11 specialized tools to query real data from your ERP and renders interactive results here on the right.',
            })}
          </p>
        </div>

        {/* How it works (3 steps) */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gap: 12,
            marginBottom: 32,
          }}
        >
          {[
            {
              n: '1',
              title: t('chat.step1_title', { defaultValue: 'Ask in plain language' }),
              desc: t('chat.step1_desc', {
                defaultValue: 'Type a question or request - no special syntax needed.',
              }),
            },
            {
              n: '2',
              title: t('chat.step2_title', { defaultValue: 'AI picks the right tools' }),
              desc: t('chat.step2_desc', {
                defaultValue: 'Watch tool calls execute live with timing and details.',
              }),
            },
            {
              n: '3',
              title: t('chat.step3_title', { defaultValue: 'See live results' }),
              desc: t('chat.step3_desc', {
                defaultValue: 'Tables, charts, matrices - interactive, not screenshots.',
              }),
            },
          ].map((s) => (
            <div
              key={s.n}
              style={{
                background: 'var(--chat-surface-1)',
                border: '1px solid var(--chat-border-subtle)',
                borderRadius: 'var(--chat-radius)',
                padding: 14,
              }}
            >
              <div
                style={{
                  width: 24,
                  height: 24,
                  borderRadius: '50%',
                  background: 'var(--chat-accent)',
                  color: '#fff',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 12,
                  fontWeight: 600,
                  marginBottom: 8,
                }}
              >
                {s.n}
              </div>
              <div
                style={{
                  fontSize: 13,
                  fontWeight: 600,
                  color: 'var(--chat-text-primary)',
                  marginBottom: 4,
                }}
              >
                {s.title}
              </div>
              <div style={{ fontSize: 12, color: 'var(--chat-text-secondary)', lineHeight: 1.5 }}>
                {s.desc}
              </div>
            </div>
          ))}
        </div>

        {/* Tool category cards */}
        <h2
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: 'var(--chat-text-secondary)',
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            margin: '0 0 12px',
          }}
        >
          {t('chat.what_you_can_ask', { defaultValue: 'What you can ask' })}
        </h2>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gap: 10,
            marginBottom: 20,
          }}
        >
          {TOOL_CATEGORIES.map((cat) => {
            const CatIcon = cat.icon;
            return (
            <div
              key={cat.title}
              style={{
                background: 'var(--chat-surface-1)',
                border: '1px solid var(--chat-border-subtle)',
                borderRadius: 'var(--chat-radius)',
                padding: 14,
              }}
            >
              <div
                style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}
              >
                <span
                  style={{
                    width: 28,
                    height: 28,
                    borderRadius: 6,
                    background: 'var(--chat-surface-2)',
                    color: 'var(--chat-accent)',
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <CatIcon size={15} strokeWidth={1.85} />
                </span>
                <span
                  style={{
                    fontSize: 13,
                    fontWeight: 600,
                    color: 'var(--chat-text-primary)',
                  }}
                >
                  {cat.title}
                </span>
              </div>
              <p
                style={{
                  fontSize: 12,
                  color: 'var(--chat-text-secondary)',
                  lineHeight: 1.5,
                  margin: '0 0 10px',
                }}
              >
                {cat.desc}
              </p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {cat.examples.map((ex) => (
                  <button
                    key={ex}
                    type="button"
                    onClick={() => onSuggestion?.(ex)}
                    style={{
                      textAlign: 'left',
                      padding: '5px 10px',
                      fontSize: 11,
                      fontFamily: 'var(--chat-font-mono)',
                      color: 'var(--chat-text-secondary)',
                      background: 'var(--chat-surface-2)',
                      border: '1px solid var(--chat-border-subtle)',
                      borderRadius: 4,
                      cursor: 'pointer',
                      transition: 'all 0.15s',
                    }}
                    onMouseEnter={(e) => {
                      const el = e.currentTarget as HTMLButtonElement;
                      el.style.borderColor = 'var(--chat-accent)';
                      el.style.color = 'var(--chat-text-primary)';
                    }}
                    onMouseLeave={(e) => {
                      const el = e.currentTarget as HTMLButtonElement;
                      el.style.borderColor = 'var(--chat-border-subtle)';
                      el.style.color = 'var(--chat-text-secondary)';
                    }}
                  >
                    → {ex}
                  </button>
                ))}
              </div>
            </div>
            );
          })}
        </div>

        {/* Tip footer */}
        <div
          style={{
            padding: 12,
            background: 'var(--chat-surface-1)',
            border: '1px solid var(--chat-border-subtle)',
            borderRadius: 'var(--chat-radius)',
            fontSize: 12,
            color: 'var(--chat-text-secondary)',
            lineHeight: 1.6,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 8,
          }}
        >
          <Lightbulb size={14} strokeWidth={1.85} style={{ color: 'var(--chat-accent)', flexShrink: 0 }} />
          <span>
            {t('chat.empty_tip', {
              defaultValue:
                'Tip: Select a project at the top to scope the AI to that project. Without selection, the AI sees your whole portfolio.',
            })}
          </span>
        </div>

        {/* AI tools cross-link strip (CONN-82) */}
        <h2
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: 'var(--chat-text-secondary)',
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            margin: '24px 0 12px',
          }}
        >
          {t('ai.cross_strip_title', { defaultValue: 'Other AI tools' })}
        </h2>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gap: 10,
          }}
        >
          {AI_TOOLS.map((tool) => {
            const ToolIcon = tool.icon;
            return (
              <button
                key={tool.to}
                type="button"
                onClick={() => navigate(tool.to)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  textAlign: 'left',
                  padding: '10px 12px',
                  background: 'var(--chat-surface-1)',
                  border: '1px solid var(--chat-border-subtle)',
                  borderRadius: 'var(--chat-radius)',
                  cursor: 'pointer',
                  transition: 'border-color 0.15s',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = 'var(--chat-accent)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = 'var(--chat-border-subtle)';
                }}
              >
                <span
                  style={{
                    width: 28,
                    height: 28,
                    flexShrink: 0,
                    borderRadius: 6,
                    background: 'var(--chat-surface-2)',
                    color: 'var(--chat-accent)',
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <ToolIcon size={15} strokeWidth={1.85} />
                </span>
                <span
                  style={{
                    flex: 1,
                    minWidth: 0,
                    fontSize: 12,
                    fontWeight: 600,
                    color: 'var(--chat-text-primary)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {tool.label}
                </span>
                <ArrowUpRight
                  size={14}
                  strokeWidth={2}
                  style={{ color: 'var(--chat-text-tertiary)', flexShrink: 0 }}
                />
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
