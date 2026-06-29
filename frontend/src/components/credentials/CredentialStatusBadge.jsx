/**
 * CredentialStatusBadge — Connected / Missing pill for a provider.
 * Never renders any secret — only the configured state.
 */
export default function CredentialStatusBadge({ configured }) {
  if (configured) {
    return (
      <span className="badge-pill badge-success">
        <span className="dot" /> Connected
      </span>
    );
  }
  return (
    <span className="badge-pill badge-warning">
      <span className="dot" /> Missing
    </span>
  );
}
