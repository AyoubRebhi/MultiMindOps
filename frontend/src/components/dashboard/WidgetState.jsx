import ErrorState from '@/components/common/ErrorState';

/**
 * WidgetState — renders the right branch for a data widget's lifecycle:
 * Loading → Error → Empty → Success. Keeps every dashboard widget consistent
 * and guarantees no widget ever renders blank.
 *
 * Props:
 *  - loading: boolean        → render `skeleton`
 *  - error: object|null      → render <ErrorState> with a Retry button
 *  - isEmpty: boolean        → render `empty`
 *  - onRetry: fn             → passed to ErrorState
 *  - errorTitle: string      → ErrorState headline
 *  - skeleton: node          → loading placeholder
 *  - empty: node             → empty placeholder
 *  - children: node          → the success content
 */
export default function WidgetState({
  loading,
  error,
  isEmpty,
  onRetry,
  errorTitle,
  skeleton = null,
  empty = null,
  children,
}) {
  if (loading) return skeleton;
  if (error) {
    return (
      <ErrorState
        title={errorTitle}
        message={error.message || 'Unexpected error talking to the server.'}
        onRetry={onRetry}
        compact
      />
    );
  }
  if (isEmpty) return empty;
  return children;
}
