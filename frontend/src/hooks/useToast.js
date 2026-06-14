import { useContext } from 'react';
import { ToastContext } from '@/context/ToastContext';

/**
 * useToast — access the global toast API.
 *   const toast = useToast();
 *   toast.success('Saved'); toast.error('Request failed');
 */
export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error('useToast must be used within a <ToastProvider>');
  }
  return ctx;
}
