import { useState, useEffect, useRef, useCallback } from 'react';
import { boqApi, type CostAutocompleteItem } from './api';

/**
 * Autocomplete suggestion for cost items.
 *
 * When the user types 2+ characters in a description cell, this component
 * fetches matching cost items and shows a dropdown. Selecting an item fills
 * the description, unit, and unit_rate fields.
 */

interface AutocompleteInputProps {
  /** Current value of the input field. */
  value: string;
  /** Called when the user commits a value (blur or Enter). */
  onCommit: (value: string) => void;
  /** Called when the user selects an autocomplete suggestion. */
  onSelectSuggestion: (item: CostAutocompleteItem) => void;
  /** Called when the user cancels editing (Escape). */
  onCancel: () => void;
  /** Placeholder text. */
  placeholder?: string;
}

export function AutocompleteInput({
  value,
  onCommit,
  onSelectSuggestion,
  onCancel,
  placeholder,
}: AutocompleteInputProps) {
  const [inputValue, setInputValue] = useState(value);
  const [suggestions, setSuggestions] = useState<CostAutocompleteItem[]>([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const [isLoading, setIsLoading] = useState(false);

  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
        onCommit(inputValue);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [inputValue, onCommit]);

  // Debounced fetch
  const fetchSuggestions = useCallback(async (query: string) => {
    if (query.length < 2) {
      setSuggestions([]);
      setShowDropdown(false);
      return;
    }

    setIsLoading(true);
    try {
      const items = await boqApi.autocomplete(query, 8);
      setSuggestions(items);
      setShowDropdown(items.length > 0);
      setSelectedIndex(-1);
    } catch {
      setSuggestions([]);
      setShowDropdown(false);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const handleInputChange = useCallback(
    (text: string) => {
      setInputValue(text);

      // Clear any pending debounce
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }

      // Debounce the API call by 300ms
      debounceRef.current = setTimeout(() => {
        fetchSuggestions(text);
      }, 300);
    },
    [fetchSuggestions],
  );

  // Cleanup debounce on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
    };
  }, []);

  const handleSelect = useCallback(
    (item: CostAutocompleteItem) => {
      setShowDropdown(false);
      setInputValue(item.description);
      onSelectSuggestion(item);
    },
    [onSelectSuggestion],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Escape') {
        if (showDropdown) {
          setShowDropdown(false);
        } else {
          onCancel();
        }
        return;
      }

      if (e.key === 'Enter') {
        const selected = suggestions[selectedIndex];
        if (showDropdown && selectedIndex >= 0 && selected) {
          e.preventDefault();
          handleSelect(selected);
        } else {
          onCommit(inputValue);
        }
        return;
      }

      if (e.key === 'Tab') {
        setShowDropdown(false);
        onCommit(inputValue);
        return;
      }

      if (showDropdown && suggestions.length > 0) {
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          setSelectedIndex((prev) => (prev < suggestions.length - 1 ? prev + 1 : 0));
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          setSelectedIndex((prev) => (prev > 0 ? prev - 1 : suggestions.length - 1));
        }
      }
    },
    [showDropdown, selectedIndex, suggestions, inputValue, onCommit, onCancel, handleSelect],
  );

  /** Format rate for display. */
  const fmtRate = (rate: number) =>
    new Intl.NumberFormat('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(
      rate,
    );

  return (
    <div ref={containerRef} className="relative">
      {/* Input field */}
      <input
        ref={inputRef}
        type="text"
        value={inputValue}
        onChange={(e) => handleInputChange(e.target.value)}
        onKeyDown={handleKeyDown}
        className="w-full bg-surface-elevated border border-oe-blue/40 rounded px-1.5 py-0.5 outline-none text-sm text-content-primary ring-2 ring-oe-blue/20"
        placeholder={placeholder}
      />

      {/* Loading indicator */}
      {isLoading && (
        <div className="absolute right-2 top-1/2 -translate-y-1/2">
          <div className="h-3 w-3 rounded-full border-2 border-oe-blue/30 border-t-oe-blue animate-spin" />
        </div>
      )}

      {/* Dropdown */}
      {showDropdown && suggestions.length > 0 && (
        <div className="absolute left-0 top-full mt-1 z-[100] w-[480px] max-h-[320px] overflow-y-auto rounded-lg border border-border-light bg-surface-elevated shadow-lg animate-fade-in">
          {suggestions.map((item, idx) => (
            <button
              key={item.code}
              type="button"
              onMouseDown={(e) => {
                // Use mouseDown to fire before blur
                e.preventDefault();
                handleSelect(item);
              }}
              onMouseEnter={() => setSelectedIndex(idx)}
              className={`flex w-full items-start gap-3 px-3 py-2.5 text-left transition-colors ${
                idx === selectedIndex
                  ? 'bg-oe-blue-subtle/40'
                  : 'hover:bg-surface-secondary'
              } ${idx > 0 ? 'border-t border-border-light' : ''}`}
            >
              {/* Main content */}
              <div className="min-w-0 flex-1">
                <p className="text-sm text-content-primary truncate">{item.description}</p>
                <p className="mt-0.5 text-2xs text-content-tertiary font-mono">{item.code}</p>
              </div>

              {/* Unit */}
              <span className="shrink-0 text-xs text-content-secondary font-mono uppercase bg-surface-secondary px-1.5 py-0.5 rounded">
                {item.unit}
              </span>

              {/* Rate */}
              <span className="shrink-0 text-sm text-content-primary tabular-nums font-medium w-20 text-right">
                {fmtRate(item.rate)}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
