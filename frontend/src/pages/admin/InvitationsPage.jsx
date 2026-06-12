import { useEffect, useMemo, useState } from 'react';
import ContentContainer from '@/components/layout/ContentContainer';
import PageHeader from '@/components/layout/PageHeader';
import StatsCard from '@/components/common/StatsCard';
import EmptyState from '@/components/common/EmptyState';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import InvitationCard from '@/components/invitations/InvitationCard';
import InviteUserModal from '@/components/invitations/InviteUserModal';
import { useInvitations } from '@/hooks/useInvitations';
import { invitationApi } from '@/services/api/invitationApi';

const GROUPS = [
  { key: 'pending', label: 'Pending', icon: 'fa-hourglass-half' },
  { key: 'accepted', label: 'Accepted', icon: 'fa-circle-check' },
  { key: 'expired', label: 'Expired', icon: 'fa-hourglass-end' },
  { key: 'rejected', label: 'Rejected', icon: 'fa-circle-xmark' },
];

export default function InvitationsPage() {
  const { data, loading } = useInvitations();
  const [rows, setRows] = useState([]);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (data) setRows(data);
  }, [data]);

  const grouped = useMemo(() => {
    const g = { pending: [], accepted: [], expired: [], rejected: [] };
    rows.forEach((inv) => {
      if (g[inv.status]) g[inv.status].push(inv);
    });
    return g;
  }, [rows]);

  const handleSend = async (payload) => {
    setSending(true);
    try {
      const created = await invitationApi.create(payload);
      setRows((r) => [created, ...r]);
      setInviteOpen(false);
    } finally {
      setSending(false);
    }
  };

  const handleResend = async (inv) => {
    const res = await invitationApi.resend(inv.id);
    setRows((r) => r.map((i) => (i.id === inv.id ? { ...i, ...res } : i)));
  };

  const handleRevoke = async (inv) => {
    await invitationApi.revoke(inv.id);
    setRows((r) => r.filter((i) => i.id !== inv.id));
  };

  return (
    <ContentContainer>
      <PageHeader
        title="Invitations"
        subtitle="Track invitations across their lifecycle and invite new engineers."
        breadcrumbs={[{ label: 'Invitations' }]}
        actions={
          <button className="bgrd btn px-3 py-2" style={{ fontSize: '.85rem' }} onClick={() => setInviteOpen(true)}>
            <i className="fa-solid fa-paper-plane me-2" />
            Send Invitation
          </button>
        }
      />

      <div className="row g-3 mb-4">
        {GROUPS.map((g) => (
          <div className="col-6 col-xl-3" key={g.key}>
            <StatsCard
              label={g.label}
              value={grouped[g.key].length}
              icon={g.icon}
              accent={
                g.key === 'accepted' ? '#34d399' : g.key === 'pending' ? '#fbbf24' : g.key === 'rejected' ? '#f87171' : '#94a3b8'
              }
            />
          </div>
        ))}
      </div>

      {loading && !rows.length ? (
        <LoadingSpinner center label="Loading invitations…" />
      ) : (
        GROUPS.map((g) => (
          <section key={g.key} className="mb-4">
            <div className="d-flex align-items-center gap-2 mb-3">
              <h2 className="card-title">
                <i className={`fa-solid ${g.icon} me-2`} style={{ color: 'var(--tx3)' }} />
                {g.label}
              </h2>
              <span className="tag">{grouped[g.key].length}</span>
            </div>
            {grouped[g.key].length === 0 ? (
              <div
                className="text-muted-3"
                style={{ fontSize: '.82rem', padding: '12px 16px', background: 'var(--bg3)', borderRadius: 12 }}
              >
                No {g.label.toLowerCase()} invitations.
              </div>
            ) : (
              <div className="row g-3">
                {grouped[g.key].map((inv) => (
                  <div className="col-md-6 col-xl-4" key={inv.id}>
                    <InvitationCard
                      invitation={inv}
                      onResend={g.key === 'pending' || g.key === 'expired' ? handleResend : undefined}
                      onRevoke={g.key === 'pending' ? handleRevoke : undefined}
                    />
                  </div>
                ))}
              </div>
            )}
          </section>
        ))
      )}

      {!loading && rows.length === 0 && (
        <EmptyState icon="fa-paper-plane" title="No invitations yet" message="Invite your first engineer to get started." />
      )}

      <InviteUserModal open={inviteOpen} onClose={() => setInviteOpen(false)} onSend={handleSend} sending={sending} />
    </ContentContainer>
  );
}
