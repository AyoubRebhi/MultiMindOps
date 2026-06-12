import { useState } from 'react';
import { Link } from 'react-router-dom';
import ContentContainer from '@/components/layout/ContentContainer';
import PageHeader from '@/components/layout/PageHeader';
import StatsCard from '@/components/common/StatsCard';
import Card from '@/components/common/Card';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import WorkspaceCard from '@/components/workspace/WorkspaceCard';
import ActivityTimeline from '@/components/common/ActivityTimeline';
import MemberAvatarGroup from '@/components/common/MemberAvatarGroup';
import RoleBadge from '@/components/common/RoleBadge';
import StatusBadge from '@/components/common/StatusBadge';
import InviteUserModal from '@/components/invitations/InviteUserModal';
import { useWorkspace, useWorkspaceActivity } from '@/hooks/useWorkspace';
import { useUsers } from '@/hooks/useUsers';
import { invitationApi } from '@/services/api/invitationApi';

/**
 * AdminDashboardPage — workspace overview for the Admin: headline counts,
 * workspace card, members snapshot and the recent activity stream.
 */
export default function AdminDashboardPage() {
  const { data: workspace, loading } = useWorkspace();
  const { data: activity } = useWorkspaceActivity();
  const { data: members } = useUsers();
  const [inviteOpen, setInviteOpen] = useState(false);
  const [sending, setSending] = useState(false);

  const handleSend = async (payload) => {
    setSending(true);
    try {
      await invitationApi.create(payload);
      setInviteOpen(false);
    } finally {
      setSending(false);
    }
  };

  if (loading && !workspace) {
    return (
      <ContentContainer>
        <LoadingSpinner center label="Loading workspace…" />
      </ContentContainer>
    );
  }

  const stats = workspace?.stats || {};

  return (
    <ContentContainer>
      <PageHeader
        title="Workspace Overview"
        subtitle={`Welcome back — here's what's happening across ${workspace?.name || 'your workspace'}.`}
        actions={
          <button className="bgrd btn px-3 py-2" style={{ fontSize: '.85rem' }} onClick={() => setInviteOpen(true)}>
            <i className="fa-solid fa-user-plus me-2" />
            Invite Member
          </button>
        }
      />

      <div className="row g-3 mb-4">
        <div className="col-6 col-xl-3">
          <StatsCard label="Total Members" value={stats.totalMembers} icon="fa-users" accent="#a78bfa" gradientValue />
        </div>
        <div className="col-6 col-xl-3">
          <StatsCard label="Active Projects" value={stats.activeProjects} icon="fa-folder-tree" accent="#60a5fa" />
        </div>
        <div className="col-6 col-xl-3">
          <StatsCard label="Active Workflows" value={stats.activeWorkflows} icon="fa-diagram-project" accent="#34d399" />
        </div>
        <div className="col-6 col-xl-3">
          <StatsCard label="Pending Invitations" value={stats.pendingInvitations} icon="fa-paper-plane" accent="#fbbf24" />
        </div>
      </div>

      <div className="row g-3 mb-4">
        <div className="col-lg-7">
          <WorkspaceCard workspace={workspace} />
        </div>
        <div className="col-lg-5">
          <Card
            title="Members"
            icon="fa-users"
            action={
              <Link to="/members" className="card-link">
                Manage
              </Link>
            }
          >
            <div className="d-flex align-items-center justify-content-between mb-3">
              <MemberAvatarGroup members={members || []} max={6} size={38} />
              <span className="text-muted-3" style={{ fontSize: '.8rem' }}>
                {(members || []).length} total
              </span>
            </div>
            <div className="d-flex flex-column gap-2">
              {(members || []).slice(0, 4).map((m) => (
                <div
                  key={m.id}
                  className="d-flex align-items-center justify-content-between"
                  style={{ padding: '8px 10px', background: 'var(--bg3)', borderRadius: 10 }}
                >
                  <div style={{ fontSize: '.82rem', fontWeight: 600 }}>{m.name}</div>
                  <div className="d-flex align-items-center gap-2">
                    <RoleBadge role={m.role} short />
                    <StatusBadge status={m.status} showIcon={false} />
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>

      <Card title="Recent Activity" icon="fa-wave-square">
        <ActivityTimeline items={activity || []} max={6} />
      </Card>

      <InviteUserModal open={inviteOpen} onClose={() => setInviteOpen(false)} onSend={handleSend} sending={sending} />
    </ContentContainer>
  );
}
