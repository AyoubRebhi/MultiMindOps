import { useEffect, useMemo, useState } from 'react';
import ContentContainer from '@/components/layout/ContentContainer';
import PageHeader from '@/components/layout/PageHeader';
import Card from '@/components/common/Card';
import Avatar from '@/components/common/Avatar';
import RoleBadge from '@/components/common/RoleBadge';
import StatusBadge from '@/components/common/StatusBadge';
import Modal from '@/components/common/Modal';
import EmptyState from '@/components/common/EmptyState';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import InviteUserModal from '@/components/invitations/InviteUserModal';
import { useClickOutside } from '@/hooks/useClickOutside';
import { useUsers } from '@/hooks/useUsers';
import { userApi } from '@/services/api/userApi';
import { invitationApi } from '@/services/api/invitationApi';
import { ROLE_META } from '@/utils/constants';
import { formatDate } from '@/utils/formatters';

/** Per-row actions dropdown (View / Edit / Block / Unblock / Remove). */
function RowActions({ user, onAction }) {
  const [open, setOpen] = useState(false);
  const ref = useClickOutside(open, () => setOpen(false));
  const blocked = user.status === 'blocked';

  const choose = (action) => {
    setOpen(false);
    onAction(action, user);
  };

  return (
    <div style={{ position: 'relative' }} ref={ref}>
      <button
        className="boc d-flex align-items-center justify-content-center"
        style={{ width: 32, height: 32, padding: 0, borderRadius: 9 }}
        onClick={() => setOpen((o) => !o)}
        aria-label="Actions"
      >
        <i className="fa-solid fa-ellipsis-vertical" />
      </button>
      <div
        className={`db-dropdown ${open ? 'open' : ''}`.trim()}
        style={{ right: 0, minWidth: 170, padding: 8 }}
      >
        <button className="menu-item" onClick={() => choose('view')}>
          <i className="fa-regular fa-eye" /> View
        </button>
        <button className="menu-item" onClick={() => choose('edit')}>
          <i className="fa-solid fa-pen" /> Edit
        </button>
        {blocked ? (
          <button className="menu-item" onClick={() => choose('unblock')}>
            <i className="fa-solid fa-unlock" /> Unblock
          </button>
        ) : (
          <button className="menu-item" onClick={() => choose('block')}>
            <i className="fa-solid fa-ban" /> Block
          </button>
        )}
        <div style={{ height: 1, background: 'var(--bd)', margin: '6px 4px' }} />
        <button className="menu-item danger" onClick={() => choose('remove')}>
          <i className="fa-solid fa-trash" /> Remove
        </button>
      </div>
    </div>
  );
}

export default function UserManagementPage() {
  const { data, loading } = useUsers();
  const [rows, setRows] = useState([]);
  const [query, setQuery] = useState('');
  const [modal, setModal] = useState(null); // { type, user }
  const [inviteOpen, setInviteOpen] = useState(false);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (data) setRows(data);
  }, [data]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (u) => u.name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)
    );
  }, [rows, query]);

  const handleAction = async (action, user) => {
    if (action === 'block') {
      await userApi.block(user.id);
      setRows((r) => r.map((u) => (u.id === user.id ? { ...u, status: 'blocked' } : u)));
    } else if (action === 'unblock') {
      await userApi.unblock(user.id);
      setRows((r) => r.map((u) => (u.id === user.id ? { ...u, status: 'active' } : u)));
    } else {
      setModal({ type: action, user });
    }
  };

  const confirmRemove = async () => {
    await userApi.remove(modal.user.id);
    setRows((r) => r.filter((u) => u.id !== modal.user.id));
    setModal(null);
  };

  const saveEdit = async (changes) => {
    const updated = await userApi.update(modal.user.id, changes);
    setRows((r) => r.map((u) => (u.id === modal.user.id ? { ...u, ...updated } : u)));
    setModal(null);
  };

  const handleInvite = async (payload) => {
    setSending(true);
    try {
      await invitationApi.create(payload);
      setInviteOpen(false);
    } finally {
      setSending(false);
    }
  };

  return (
    <ContentContainer>
      <PageHeader
        title="Members"
        subtitle="Manage everyone in your workspace — roles, access and status."
        breadcrumbs={[{ label: 'Members' }]}
        actions={
          <button className="bgrd btn px-3 py-2" style={{ fontSize: '.85rem' }} onClick={() => setInviteOpen(true)}>
            <i className="fa-solid fa-user-plus me-2" />
            Invite Member
          </button>
        }
      />

      <Card
        title={`${rows.length} members`}
        icon="fa-users"
        action={
          <div className="db-top-search" style={{ maxWidth: 240 }}>
            <i className="fa-solid fa-magnifying-glass" />
            <input
              type="text"
              placeholder="Search members…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
        }
        bodyClassName=""
      >
        {loading && !rows.length ? (
          <LoadingSpinner center label="Loading members…" />
        ) : filtered.length === 0 ? (
          <EmptyState icon="fa-user-slash" title="No members found" />
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="db-table" style={{ width: '100%', minWidth: 760 }}>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Joined</th>
                  <th style={{ textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((u) => (
                  <tr key={u.id}>
                    <td>
                      <div className="d-flex align-items-center gap-2">
                        <Avatar name={u.name} color={u.avatarColor} size={32} />
                        <span style={{ fontWeight: 600 }}>{u.name}</span>
                      </div>
                    </td>
                    <td className="mono" style={{ fontSize: '.8rem' }}>
                      {u.email}
                    </td>
                    <td>
                      <RoleBadge role={u.role} />
                    </td>
                    <td>
                      <StatusBadge status={u.status} />
                    </td>
                    <td style={{ fontSize: '.8rem', color: 'var(--tx3)' }}>
                      {u.joinedDate ? formatDate(u.joinedDate) : '—'}
                    </td>
                    <td>
                      <div className="d-flex justify-content-end">
                        <RowActions user={u} onAction={handleAction} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* View / Edit / Remove modal */}
      {modal?.type === 'view' && <ViewMemberModal user={modal.user} onClose={() => setModal(null)} />}
      {modal?.type === 'edit' && (
        <EditMemberModal user={modal.user} onClose={() => setModal(null)} onSave={saveEdit} />
      )}
      {modal?.type === 'remove' && (
        <Modal
          open
          onClose={() => setModal(null)}
          title="Remove member"
          icon="fa-trash"
          footer={
            <>
              <button className="boc btn px-3 py-2" style={{ fontSize: '.85rem' }} onClick={() => setModal(null)}>
                Cancel
              </button>
              <button
                className="bgrd btn px-3 py-2"
                style={{ fontSize: '.85rem', background: '#f87171' }}
                onClick={confirmRemove}
              >
                Remove
              </button>
            </>
          }
        >
          <p style={{ fontSize: '.88rem', color: 'var(--tx2)' }}>
            Remove <strong>{modal.user.name}</strong> from the workspace? They will lose access
            immediately. This action is mock-only.
          </p>
        </Modal>
      )}

      <InviteUserModal open={inviteOpen} onClose={() => setInviteOpen(false)} onSend={handleInvite} sending={sending} />
    </ContentContainer>
  );
}

function ViewMemberModal({ user, onClose }) {
  return (
    <Modal open onClose={onClose} title="Member details" icon="fa-id-card">
      <div className="d-flex align-items-center gap-3 mb-3">
        <Avatar name={user.name} color={user.avatarColor} size={52} />
        <div>
          <div style={{ fontWeight: 700 }}>{user.name}</div>
          <div style={{ fontSize: '.8rem', color: 'var(--tx3)' }}>{user.email}</div>
        </div>
      </div>
      <div className="d-flex flex-column gap-2">
        <DetailRow label="Role"><RoleBadge role={user.role} /></DetailRow>
        <DetailRow label="Status"><StatusBadge status={user.status} /></DetailRow>
        <DetailRow label="Joined" value={user.joinedDate ? formatDate(user.joinedDate) : '—'} />
        <DetailRow label="Projects" value={String(user.projects)} />
      </div>
    </Modal>
  );
}

function EditMemberModal({ user, onClose, onSave }) {
  const [firstName, setFirstName] = useState(user.firstName);
  const [lastName, setLastName] = useState(user.lastName);
  const [role, setRole] = useState(user.role);

  const submit = () =>
    onSave({ firstName, lastName, role, name: `${firstName} ${lastName}`.trim() });

  return (
    <Modal
      open
      onClose={onClose}
      title="Edit member"
      icon="fa-pen"
      footer={
        <>
          <button className="boc btn px-3 py-2" style={{ fontSize: '.85rem' }} onClick={onClose}>
            Cancel
          </button>
          <button className="bgrd btn px-3 py-2" style={{ fontSize: '.85rem' }} onClick={submit}>
            Save changes
          </button>
        </>
      }
    >
      <div className="row g-2 mb-3">
        <div className="col-6">
          <label className="form-label-sm">First name</label>
          <input className="oinp" value={firstName} onChange={(e) => setFirstName(e.target.value)} />
        </div>
        <div className="col-6">
          <label className="form-label-sm">Last name</label>
          <input className="oinp" value={lastName} onChange={(e) => setLastName(e.target.value)} />
        </div>
      </div>
      <label className="form-label-sm">Role</label>
      <select className="oinp" value={role} onChange={(e) => setRole(e.target.value)}>
        {Object.entries(ROLE_META).map(([key, meta]) => (
          <option key={key} value={key}>
            {meta.label}
          </option>
        ))}
      </select>
    </Modal>
  );
}

function DetailRow({ label, value, children }) {
  return (
    <div
      className="d-flex align-items-center justify-content-between"
      style={{ padding: '9px 12px', background: 'var(--bg3)', borderRadius: 10 }}
    >
      <span style={{ fontSize: '.8rem', color: 'var(--tx3)' }}>{label}</span>
      {children || <span style={{ fontSize: '.84rem', fontWeight: 600 }}>{value}</span>}
    </div>
  );
}
