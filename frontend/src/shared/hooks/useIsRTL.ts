import { useState, useEffect } from 'react';

/**
 * Returns true when the document is currently in RTL mode (dir="rtl" on <html>).
 * Re-renders the consumer whenever the direction changes at runtime.
 */
export function useIsRTL(): boolean {
  const [isRTL, setIsRTL] = useState<boolean>(
    () => document.documentElement.dir === 'rtl',
  );

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsRTL(document.documentElement.dir === 'rtl');
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['dir'],
    });
    return () => observer.disconnect();
  }, []);

  return isRTL;
}
