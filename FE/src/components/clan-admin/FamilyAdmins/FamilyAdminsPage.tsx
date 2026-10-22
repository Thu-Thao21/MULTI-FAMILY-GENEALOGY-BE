import './FamilyAdminsPage.css';
import React, { useState } from 'react';
import PageHeader from '../../../shared/Layout/PageHeader';
import DataTable, { type Column } from '../../../shared/DataTable/DataTable';

interface FamilyAdmin {
  id: string;
  name: string;
  email: string;
  phone: string;
  branch: string;
  status: 'active' | 'inactive';
}

import { fetchAdminUsers } from '../../../services/admin.service';

export const FamilyAdminsPage: React.FC = () => {
  const [search, setSearch] = useState('');
  const [selectedAdmin, setSelectedAdmin] = useState<FamilyAdmin | null>(null);
  const [data, setData] = useState<FamilyAdmin[]>([]);

  React.useEffect(() => {
    fetchAdminUsers({ q: search || undefined, page_size: 50 }).then((res) => {
      const items = res?.items || [];
      const mapped: FamilyAdmin[] = items.map((u: any) => ({
        id: u.user_id,
        name: u.display_name || u.email,
        email: u.email,
        phone: u.phone || 'Chưa cập nhật',
        branch: 'Chi Trưởng',
        status: u.status === 'ACTIVE' ? 'active' : 'inactive',
      }));
      setData(mapped);
    }).catch(() => setData([]));
  }, [search]);

  const columns: Column<FamilyAdmin>[] = [
    { key: 'name', header: 'Họ và tên', render: (item) => <strong className="text-slate-800">{item.name}</strong> },
    { key: 'email', header: 'Email', render: (item) => item.email },
    { key: 'phone', header: 'Số điện thoại', render: (item) => item.phone },
    { key: 'branch', header: 'Quản lý Chi/Nhánh', render: (item) => item.branch },
    { key: 'status', header: 'Trạng thái', render: (item) => (
      <span className={`admin-status-badge ${item.status === 'active' ? 'status-active' : 'status-inactive'}`}>
        {item.status === 'active' ? 'Đang hoạt động' : 'Đã khoá'}
      </span>
    )},
    { key: 'actions', header: 'Thao tác', render: (item) => (
      <div className="fadmin-actions">
        <button 
          className="fadmin-btn-permission"
          onClick={() => setSelectedAdmin(item)}
        >
          Phân quyền
        </button>
      </div>
    )},
  ];

  const headerActions = (
    <button className="admin-btn-primary">
      <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
      Cấp quyền Admin mới
    </button>
  );

  const permissionGroups = [
    { id: 'tree', label: 'Cây Gia Phả', desc: 'Sửa chữa cấu trúc, thêm mới quan hệ' },
    { id: 'member', label: 'Nhân khẩu & Tài khoản', desc: 'Thêm, sửa hồ sơ, cấp tài khoản' },
    { id: 'fund', label: 'Quỹ dòng họ', desc: 'Xem số dư, tạo phiếu thu chi' },
    { id: 'event', label: 'Sự kiện & Ngày giỗ', desc: 'Tạo và gửi thông báo nhắc nhở' },
    { id: 'archive', label: 'Kho Tư liệu', desc: 'Tải lên, xóa ảnh và giấy tờ' },
    { id: 'interfamily', label: 'Liên họ', desc: 'Chấp nhận/từ chối yêu cầu kết nối' },
  ];

  return (
    <div className="admin-account-container">
      
      <div className="admin-account-header">
        <div>
          <h2 className="admin-account-title">Quản lý Family Admin</h2>
          <p className="admin-account-subtitle">Danh sách các thành viên được cấp quyền quản trị phụ trách Chi / Nhánh.</p>
        </div>
        <div className="admin-account-controls">
          {headerActions}
        </div>
      </div>
      
      <div className="fadmin-filter-bar">
        <input 
          type="text" 
          placeholder="Tìm kiếm tên, email, sđt..." 
          className="fadmin-search-input form-input-admin flex-1"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select className="fadmin-status-select form-input-admin w-48">
          <option value="">Tất cả trạng thái</option>
          <option value="active">Đang hoạt động</option>
          <option value="inactive">Đã khoá</option>
        </select>
      </div>

      <div className="fadmin-table-container">
        <DataTable 
          columns={columns} 
          data={data} 
          keyExtractor={(item) => item.id} 
          emptyMessage="Chưa có Family Admin nào được cấp quyền."
        />
      </div>

      {/* Permission Modal */}
      {selectedAdmin && (
        <div className="fadmin-modal-overlay">
          <div className="fadmin-modal-backdrop" onClick={() => setSelectedAdmin(null)}></div>
          
          <div className="fadmin-modal-content relative w-full max-w-2xl bg-white rounded-2xl shadow-2xl flex flex-col max-h-[90vh] animate-zoom-in overflow-hidden">
            <div className="fadmin-modal-header">
              <div className="fadmin-modal-header-left">
                <div className="fadmin-modal-avatar">
                  {selectedAdmin.name.charAt(0)}
                </div>
                <div>
                  <h2 className="fadmin-modal-title">{selectedAdmin.name}</h2>
                  <p className="fadmin-modal-subtitle">Quản lý: <strong>{selectedAdmin.branch}</strong></p>
                </div>
              </div>
              <button 
                className="fadmin-modal-close-btn"
                onClick={() => setSelectedAdmin(null)}
              >
                ✕
              </button>
            </div>

            <div className="fadmin-modal-body">
              <h3 className="fadmin-perm-title">Cấu hình Phân quyền (Permissions)</h3>
              
              <div className="fadmin-perm-grid">
                {permissionGroups.map(group => (
                  <label key={group.id} className="fadmin-perm-label">
                    <input type="checkbox" className="fadmin-perm-checkbox" defaultChecked={group.id === 'tree' || group.id === 'member'} />
                    <div>
                      <h4 className="fadmin-perm-item-title">{group.label}</h4>
                      <p className="fadmin-perm-item-desc">{group.desc}</p>
                    </div>
                  </label>
                ))}
              </div>

              <div className="fadmin-danger-zone">
                <h3 className="fadmin-danger-title">Vùng nguy hiểm</h3>
                <p className="fadmin-danger-desc">Hạ quyền quản trị viên này trở thành Member thông thường. Mọi quyền hạn sẽ bị thu hồi.</p>
                <button 
                  className="fadmin-btn-revoke"
                  onClick={() => {
                    alert('Đã thu hồi quyền Admin');
                    setSelectedAdmin(null);
                  }}
                >
                  Thu hồi quyền Family Admin
                </button>
              </div>
            </div>

            <div className="fadmin-modal-footer">
              <button className="admin-btn-secondary" onClick={() => setSelectedAdmin(null)}>Hủy bỏ</button>
              <button className="admin-btn-primary" onClick={() => {
                alert('Đã lưu cấu hình phân quyền');
                setSelectedAdmin(null);
              }}>Lưu thay đổi</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default FamilyAdminsPage;
