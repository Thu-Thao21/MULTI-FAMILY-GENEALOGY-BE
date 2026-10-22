import React, { useState, useEffect, useCallback } from 'react';
import { fetchAdminUsers, updateAdminUserStatus, type AdminUserItem } from '../../../services/admin.service';
import './AdminAccountMgmt.css';

export interface UserAccountItem {
  id: string;
  username?: string;
  email?: string;
  phone_e164?: string;
  display_name?: string;
  primary_role: 'admin' | 'member' | 'viewer' | string;
  status: 'active' | 'locked' | string;
  created_at?: string;
}

export const AdminAccountMgmt: React.FC = () => {
  const [accounts, setAccounts] = useState<UserAccountItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [roleFilter, setRoleFilter] = useState<string>('');
  const [selectedAcc, setSelectedAcc] = useState<UserAccountItem | null>(null);
  const [isEditModalOpen, setIsEditModalOpen] = useState<boolean>(false);
  const [editRole, setEditRole] = useState<string>('member');
  const [editStatus, setEditStatus] = useState<string>('active');
  const [editDisplayName, setEditDisplayName] = useState<string>('');
  const [msg, setMsg] = useState<string>('');

  const mapBackendUser = (u: AdminUserItem): UserAccountItem => ({
    id: u.user_id,
    email: u.email,
    display_name: u.display_name,
    username: u.email.split('@')[0],
    primary_role: u.display_name.toLowerCase().includes('admin') ? 'admin' : 'member',
    status: u.status.toLowerCase() === 'active' ? 'active' : 'locked',
    created_at: u.created_at ? new Date(u.created_at).toLocaleDateString('vi-VN') : undefined,
  });

  const fetchAccounts = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchAdminUsers({ q: searchTerm.trim() || undefined, page_size: 100 });
      if (res && Array.isArray(res.items)) {
        setAccounts(res.items.map(mapBackendUser));
      }
    } catch (err: any) {
      console.error('Lỗi khi tải danh sách người dùng:', err);
      setMsg('Không thể tải danh sách tài khoản từ máy chủ. Vui lòng kiểm tra quyền quản trị viên.');
    } finally {
      setLoading(false);
    }
  }, [searchTerm]);

  useEffect(() => {
    fetchAccounts();
  }, [fetchAccounts]);

  const handleToggleLock = async (acc: UserAccountItem) => {
    const nextStatus = acc.status === 'locked' ? 'ACTIVE' : 'LOCKED';
    try {
      await updateAdminUserStatus(acc.id, nextStatus, 'Thay đổi trạng thái tài khoản từ trang Quản trị');
      setAccounts((prev) =>
        prev.map((item) =>
          item.id === acc.id ? { ...item, status: nextStatus === 'ACTIVE' ? 'active' : 'locked' } : item
        )
      );
      setMsg(`Đã ${nextStatus === 'LOCKED' ? 'khóa' : 'mở khóa'} tài khoản ${acc.display_name || acc.email}`);
    } catch (err: any) {
      setMsg(`Không thể cập nhật trạng thái tài khoản: ${err?.response?.data?.message || err?.message || 'Lỗi thao tác'}`);
    }
    setTimeout(() => setMsg(''), 4000);
  };

  const handleDeleteAccount = (acc: UserAccountItem) => {
    if (window.confirm(`Bạn có chắc chắn muốn vô hiệu hóa tài khoản "${acc.display_name || acc.username}"?`)) {
      updateAdminUserStatus(acc.id, 'DISABLED', 'Vô hiệu hóa tài khoản').then(() => {
        setAccounts((prev) => prev.filter((item) => item.id !== acc.id));
        setMsg(`Đã vô hiệu hóa tài khoản thành công.`);
        setTimeout(() => setMsg(''), 3000);
      }).catch((err) => {
        setMsg(`Lỗi: ${err?.message}`);
      });
    }
  };

  const handleOpenEditModal = (acc: UserAccountItem) => {
    setSelectedAcc(acc);
    setEditRole(acc.primary_role);
    setEditStatus(acc.status);
    setEditDisplayName(acc.display_name || acc.username || '');
    setIsEditModalOpen(true);
  };

  const handleSaveAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedAcc) return;

    try {
      const targetStatus = editStatus === 'locked' ? 'LOCKED' : 'ACTIVE';
      await updateAdminUserStatus(selectedAcc.id, targetStatus, `Cập nhật thông tin bởi quản trị viên`);
      setAccounts((prev) =>
        prev.map((item) =>
          item.id === selectedAcc.id
            ? {
                ...item,
                display_name: editDisplayName,
                primary_role: editRole,
                status: editStatus,
              }
            : item
        )
      );
      setIsEditModalOpen(false);
      setMsg(`Cập nhật tài khoản "${editDisplayName}" thành công!`);
    } catch (err: any) {
      setMsg(`Lỗi khi cập nhật tài khoản: ${err?.response?.data?.message || err.message}`);
    }
    setTimeout(() => setMsg(''), 4000);
  };

  const filteredAccounts = accounts.filter((acc) => {
    const nameStr = (acc.display_name || '' ) + (acc.username || '') + (acc.email || '') + (acc.phone_e164 || '');
    const matchSearch = nameStr.toLowerCase().includes(searchTerm.toLowerCase());
    const matchRole = roleFilter ? acc.primary_role === roleFilter : true;
    return matchSearch && matchRole;
  });

  return (
    <div className="admin-account-container">
      {/* Header & Controls */}
      <div className="admin-account-header">
        <div>
          <h2 className="admin-account-title">Quản Lý Tài Khoản & Cấp Quyền Hệ Thống</h2>
          <p className="admin-account-subtitle">
            Khóa, mở khóa, gán vai trò (Admin, Thành viên, Người xem) và quản lý người dùng.
          </p>
        </div>

        <div className="admin-account-controls">
          <input
            type="text"
            className="admin-search-input"
            placeholder="Tìm theo tên, email, sđt..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
          <select
            className="admin-select-filter"
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value)}
          >
            <option value="">Tất cả vai trò</option>
            <option value="admin">Admin</option>
            <option value="family_head">Chủ dòng họ</option>
            <option value="member">Thành viên</option>
            <option value="viewer">Người xem</option>
          </select>
        </div>
      </div>

      {msg && <div className="admin-msg-box">{msg}</div>}

      {/* Table List */}
      <div className="admin-table-card">
        {loading ? (
          <p className="admin-table-loading">Đang tải danh sách tài khoản...</p>
        ) : filteredAccounts.length === 0 ? (
          <p className="admin-table-empty">Không tìm thấy tài khoản phù hợp.</p>
        ) : (
          <table className="admin-table">
            <thead>
              <tr>
                <th>Tài khoản / Người dùng</th>
                <th>Email / SĐT</th>
                <th>Vai trò hiện tại</th>
                <th>Trạng thái</th>
                <th>Ngày tạo</th>
                <th>Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {filteredAccounts.map((acc) => (
                <tr key={acc.id}>
                  <td>
                    <div className="admin-acc-name">{acc.display_name || acc.username}</div>
                    <div className="admin-acc-username">@{acc.username || acc.id.slice(0, 8)}</div>
                  </td>
                  <td>
                    <div className="admin-acc-email">{acc.email || '—'}</div>
                    {acc.phone_e164 && <div className="admin-acc-phone">{acc.phone_e164}</div>}
                  </td>
                  <td>
                    <span
                      className={`badge-role-pill ${
                        acc.primary_role === 'admin'
                          ? 'badge-role-admin'
                          : acc.primary_role === 'family_head'
                          ? 'badge-role-head'
                          : acc.primary_role === 'viewer'
                          ? 'badge-role-viewer'
                          : 'acc-role-member'
                      }`}
                    >
                      {acc.primary_role === 'admin'
                        ? 'Admin'
                        : acc.primary_role === 'family_head'
                        ? 'Chủ dòng họ'
                        : acc.primary_role === 'viewer'
                        ? 'Người xem'
                        : 'Thành viên'}
                    </span>
                  </td>
                  <td>
                    <span
                      className={
                        acc.status === 'locked' ? 'status-badge-locked' : 'status-badge-active'
                      }
                    >
                      {acc.status === 'locked' ? 'Đã khóa' : 'Hoạt động'}
                    </span>
                  </td>
                  <td className="admin-acc-date">{acc.created_at || 'Mới đây'}</td>
                  <td>
                    <div className="action-btn-row">
                      <button
                        className="btn-icon-action"
                        onClick={() => handleOpenEditModal(acc)}
                        title="Sửa thông tin & vai trò"
                      >
                        Sửa
                      </button>
                      <button
                        className={`btn-icon-action ${acc.status === 'locked' ? 'unlock' : 'lock'}`}
                        onClick={() => handleToggleLock(acc)}
                      >
                        {acc.status === 'locked' ? 'Mở' : 'Khóa'}
                      </button>
                      <button
                        className="btn-icon-action lock"
                        onClick={() => handleDeleteAccount(acc)}
                        title="Xóa tài khoản"
                      >
                        Xóa
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Edit Modal */}
      {isEditModalOpen && selectedAcc && (
        <div className="admin-modal-overlay">
          <div className="admin-modal-box">
            <div className="admin-modal-header">
              <h3>Chỉnh Sửa Tài Khoản & Vai Trò</h3>
              <button className="admin-modal-close" onClick={() => setIsEditModalOpen(false)}>✕</button>
            </div>

            <form onSubmit={handleSaveAccount}>
              <div className="form-group-admin">
                <label className="form-label-admin">Tên hiển thị</label>
                <input
                  type="text"
                  className="form-input-admin"
                  value={editDisplayName}
                  onChange={(e) => setEditDisplayName(e.target.value)}
                  required
                />
              </div>

              <div className="form-group-admin">
                <label className="form-label-admin">Cấp vai trò (Permissions)</label>
                <select
                  className="form-input-admin"
                  value={editRole}
                  onChange={(e) => setEditRole(e.target.value)}
                >
                  <option value="admin">Admin (Quản trị toàn bộ)</option>
                  <option value="family_head">Chủ dòng họ (Quản lý một gia phả)</option>
                  <option value="member">Thành viên (Xem & đóng góp)</option>
                  <option value="viewer">Người xem (Chỉ xem dữ liệu)</option>
                </select>
              </div>

              <div className="form-group-admin">
                <label className="form-label-admin">Trạng thái tài khoản</label>
                <select
                  className="form-input-admin"
                  value={editStatus}
                  onChange={(e) => setEditStatus(e.target.value)}
                >
                  <option value="active">Hoạt động</option>
                  <option value="locked">Khóa tài khoản</option>
                </select>
              </div>

              <div className="admin-modal-footer">
                <button
                  type="button"
                  className="btn-icon-action"
                  onClick={() => setIsEditModalOpen(false)}
                >
                  Hủy
                </button>
                <button type="submit" className="admin-btn-primary">
                  Lưu thay đổi
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default AdminAccountMgmt;
