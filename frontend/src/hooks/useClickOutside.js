import { useEffect, useRef } from 'react';

/**
 * useClickOutside — call `handler` when a click/touch lands outside the ref'd
 * element. Also closes on Escape. Used by the top-bar dropdowns.
 *
 * @param {boolean}  active  only listen while true (e.g. dropdown is open)
 * @param {Function} handler close callback
 */
export function useClickOutside(active, handler) {
  const ref = useRef(null);

  useEffect(() => {
    if (!active) return undefined;

    const onPointer = (e) => {
      if (ref.current && !ref.current.contains(e.target)) handler();
    };
    const onKey = (e) => {
      if (e.key === 'Escape') handler();
    };

    document.addEventListener('mousedown', onPointer);
    document.addEventListener('touchstart', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onPointer);
      document.removeEventListener('touchstart', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [active, handler]);

  return ref;
}
