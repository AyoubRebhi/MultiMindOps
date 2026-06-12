import { useContext } from 'react';
import { ThemeContext } from '@/context/ThemeContext';

/** Convenience hook to read/toggle the active theme. */
export function useTheme() {
  return useContext(ThemeContext);
}
