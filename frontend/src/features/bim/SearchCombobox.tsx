// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * SearchCombobox — a text input with a filtered option list underneath.
 *
 * Built for the BIM property search panel, where the property list of a DDC
 * export runs to 1000+ entries and a native <select> can neither be searched
 * nor scrolled comfortably. Typing narrows the list (case-insensitive
 * substring on label and value); opening it without typing shows everything.
 * Only the first `maxVisible` matches are rendered, with a note saying how
 * many more there are, so a huge list stays responsive.
 *
 * The input owns its text: the parent decides whether that text is free input
 * (a value) or only a search term that must end on an option (a property).
 * ARIA follows the WAI combobox pattern with `aria-activedescendant`. With no
 * options at all the list stays closed and the input is a plain text field.
 */

import { useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

export interface ComboOption {
  value: string;
  label: string;
  /** Right-aligned secondary text, e.g. an element count. */
  hint?: string;
}

interface SearchComboboxProps {
  inputValue: string;
  onInputChange: (text: string) => void;
  options: readonly ComboOption[];
  onSelect: (option: ComboOption) => void;
  /** Enter with no highlighted option (e.g. run the search). Runs after an
   *  option spelled like the typed text has been taken, too. */
  onEnter?: () => void;
  onBlur?: () => void;
  placeholder?: string;
  ariaLabel: string;
  disabled?: boolean;
  testId: string;
  /** Highlights the option whose value equals this. */
  selectedValue?: string;
  maxVisible?: number;
  /** Shown in the list when nothing matches the typed text. */
  emptyText?: ReactNode;
  className?: string;
}

export function SearchCombobox({
  inputValue,
  onInputChange,
  options,
  onSelect,
  onEnter,
  onBlur,
  placeholder,
  ariaLabel,
  disabled,
  testId,
  selectedValue,
  maxVisible = 200,
  emptyText,
  className,
}: SearchComboboxProps) {
  const { t } = useTranslation();
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  // Until the user types after opening, the list shows every option: the
  // input then holds the current choice, not a search term.
  const [typed, setTyped] = useState(false);
  const [active, setActive] = useState(-1);

  const matches = useMemo(() => {
    const q = typed ? inputValue.trim().toLowerCase() : '';
    if (!q) return options;
    return options.filter(
      (o) => o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q),
    );
  }, [options, inputValue, typed]);
  const visible = matches.slice(0, maxVisible);
  const hidden = matches.length - visible.length;

  const openList = () => {
    if (disabled) return;
    setOpen(true);
  };

  const close = () => {
    setOpen(false);
    setTyped(false);
    setActive(-1);
  };

  const choose = (option: ComboOption) => {
    onSelect(option);
    close();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (!open) {
        openList();
        setActive(visible.length > 0 ? 0 : -1);
        return;
      }
      setActive((i) => (visible.length === 0 ? -1 : Math.min(i + 1, visible.length - 1)));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      // A highlighted option is picked, as in any list. Otherwise an option
      // spelled exactly like the typed text (any case) is taken and Enter
      // carries on as Enter; anything else is the typed text itself, so
      // typing "Progetto" never searches for the first partial match.
      const highlighted = open && active >= 0 ? visible[active] : undefined;
      const typedText = inputValue.trim().toLowerCase();
      const exact =
        highlighted || !typedText
          ? undefined
          : options.find(
              (o) => o.label.trim().toLowerCase() === typedText || o.value.trim().toLowerCase() === typedText,
            );
      if (highlighted) {
        e.preventDefault();
        choose(highlighted);
      } else if (exact) {
        e.preventDefault();
        choose(exact);
        onEnter?.();
      } else {
        close();
        onEnter?.();
      }
    } else if (e.key === 'Escape') {
      if (open) {
        e.preventDefault();
        close();
      }
    }
  };

  const activeId = open && active >= 0 && visible[active] ? `${listId}-opt-${active}` : undefined;

  return (
    <div className={`relative min-w-0 ${className ?? ''}`}>
      <input
        ref={inputRef}
        type="text"
        role="combobox"
        aria-label={ariaLabel}
        aria-expanded={open && options.length > 0}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={activeId}
        value={inputValue}
        disabled={disabled}
        placeholder={placeholder}
        onFocus={(e) => {
          e.currentTarget.select();
          openList();
        }}
        onChange={(e) => {
          setTyped(true);
          // No auto-highlight while typing: Enter must not swap the typed
          // text for the first option. ArrowDown starts the highlight.
          setActive(-1);
          setOpen(true);
          onInputChange(e.target.value);
        }}
        onKeyDown={handleKeyDown}
        onBlur={() => {
          close();
          onBlur?.();
        }}
        className="w-full min-w-0 rounded border border-border-light bg-surface-primary px-2 py-1 text-[11px] focus:outline-none focus:ring-1 focus:ring-oe-blue disabled:opacity-50"
        data-testid={testId}
      />
      {open && options.length > 0 && (
        <ul
          id={listId}
          role="listbox"
          aria-label={ariaLabel}
          className="absolute z-40 mt-1 max-h-64 w-full overflow-auto rounded-md border border-border-light bg-surface-primary py-1 shadow-lg"
          data-testid={`${testId}-listbox`}
        >
          {visible.map((option, i) => {
            const isActive = i === active;
            const isSelected = selectedValue !== undefined && option.value === selectedValue;
            return (
              <li
                key={option.value}
                id={`${listId}-opt-${i}`}
                role="option"
                aria-selected={isSelected}
                // mousedown, not click: the input's blur would close the list first.
                onMouseDown={(e) => {
                  e.preventDefault();
                  choose(option);
                }}
                onMouseEnter={() => setActive(i)}
                className={`flex cursor-pointer items-center gap-2 px-2 py-1 text-[11px] ${
                  isActive ? 'bg-surface-secondary' : ''
                } ${isSelected ? 'text-oe-blue font-medium' : 'text-content-primary'}`}
              >
                <span className="min-w-0 flex-1 truncate" title={option.label}>
                  {option.label}
                </span>
                {option.hint !== undefined && (
                  <span className="shrink-0 text-[10px] tabular-nums text-content-tertiary">{option.hint}</span>
                )}
              </li>
            );
          })}
          {visible.length === 0 && (
            <li role="presentation" className="px-2 py-1.5 text-[11px] italic text-content-tertiary">
              {emptyText ?? t('bim.property_search_no_option', { defaultValue: 'Nothing matches what you typed.' })}
            </li>
          )}
          {hidden > 0 && (
            <li
              role="presentation"
              className="border-t border-border-light px-2 py-1.5 text-[10px] text-content-tertiary"
              data-testid={`${testId}-more`}
            >
              {t('bim.property_search_more_options', {
                defaultValue_one: '{{count}} more - type to narrow the list',
                defaultValue_other: '{{count}} more - type to narrow the list',
                count: hidden,
              })}
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
