import './BranchesPage.css';
import React, { useState } from 'react';
import PageHeader from '../../../shared/Layout/PageHeader';
import DataTable, { type Column } from '../../../shared/DataTable/DataTable';

interface Branch {
  id: string;
  name: string;
  leader: string;
  memberCount: number;
  location?: string;
  level: 'chi' | 'nhanh' | 'canh';
}

import { fetchMembers } from '../../../services/member.service';

export const BranchesPage: React.FC = () => {
  const [search, setSearch] = useState('');
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [data, setData] = useState<Branch[]>([]);

  React.useEffect(() => {
    fetchMembers({ limit: 500 }).then((res) => {
      const items = res.items || [];
      const branchCounts = new Map<string, number>();
      items.forEach((m: any) => {
        const b = m.branch || 'Chi Trưởng';
        branchCounts.set(b, (branchCounts.get(b) || 0) + 1);
      });
      const mapped: Branch[] = Array.from(branchCounts.entries()).map(([name, count], index) => ({
        id: `branch-${index + 1}`,
        name,
        leader: 'Trưởng chi',
        memberCount: count,
        location: 'Đang cập nhật',
        level: 'chi',
      }));
      setData(mapped);
    }).catch(() => setData([]));
  }, []);

  const getLevelLabel = (level: string) => {
    switch(level) {
      case 'chi': return 'Chi';
      case 'nhanh': return 'Nhánh';
      case 'canh': return 'Cành';
      default: return level;
    }
  }

  const columns: Column<Branch>[] = [
    { key: 'name', header: 'Tên Chi / Nhánh', render: (item) => <strong className="text-slate-800">{item.name}</strong> },
    { key: 'level', header: 'Cấp độ', render: (item) => (
      <span className="branch-badge-level">{getLevelLabel(item.level)}</span>
    )},
    { key: 'leader', header: 'Trưởng Chi/Nhánh', render: (item) => item.leader },
    { key: 'memberCount', header: 'Số lượng TV', render: (item) => `${item.memberCount} người` },
    { key: 'location', header: 'Địa bàn', render: (item) => item.location || '-' },
    { key: 'actions', header: 'Thao tác', render: () => (
      <div className="branch-actions">
        <button className="branch-btn-edit">Sửa</button>
        <button className="branch-btn-delete">Xoá</button>
      </div>
    )},
  ];

  const headerActions = (
    <button className="admin-btn-primary" onClick={() => setIsAddModalOpen(true)}>
      <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
      Thêm Chi/Nhánh
    </button>
  );

  return (
    <div className="admin-account-container">
      
      <div className="admin-account-header">
        <div>
          <h2 className="admin-account-title">Quản lý Chi / Nhánh</h2>
          <p className="admin-account-subtitle">Phân cấp hệ thống dòng họ theo Chi, Nhánh, Cành.</p>
        </div>
        <div className="admin-account-controls">
          {headerActions}
        </div>
      </div>
      
      <div className="branch-filter-bar">
        <input 
          type="text" 
          placeholder="Tìm kiếm tên chi nhánh, trưởng chi..." 
          className="branch-search-input form-input-admin flex-1"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select className="branch-filter-select form-input-admin w-48">
          <option value="">Tất cả cấp độ</option>
          <option value="chi">Chi</option>
          <option value="nhanh">Nhánh</option>
          <option value="canh">Cành</option>
        </select>
      </div>

      <div className="branch-table-container">
        <DataTable 
          columns={columns} 
          data={data} 
          keyExtractor={(item) => item.id} 
          emptyMessage="Chưa có dữ liệu phân Chi/Nhánh."
        />
      </div>

      {/* Add Modal */}
      {isAddModalOpen && (
        <div className="branch-modal-overlay">
          <div className="branch-modal-backdrop" onClick={() => setIsAddModalOpen(false)}></div>
          <div className="branch-modal-content relative bg-white rounded-xl shadow-2xl w-full max-w-lg overflow-hidden animate-fade-in">
            <div className="branch-modal-header">
              <h3 className="branch-modal-title">Thêm Chi / Nhánh mới</h3>
              <button className="branch-modal-close" onClick={() => setIsAddModalOpen(false)}>✕</button>
            </div>
            <div className="branch-modal-body">
              <div>
                <label className="branch-modal-label">Cấp độ <span className="text-red-500">*</span></label>
                <select className="branch-modal-input form-input-admin w-full">
                  <option value="chi">Chi</option>
                  <option value="nhanh">Nhánh</option>
                  <option value="canh">Cành</option>
                </select>
              </div>
              <div>
                <label className="branch-modal-label">Tên Chi/Nhánh <span className="text-red-500">*</span></label>
                <input type="text" className="branch-modal-input form-input-admin w-full" placeholder="Ví dụ: Chi 3, Nhánh 1.2..." />
              </div>
              <div>
                <label className="branch-modal-label">Trực thuộc (Parent)</label>
                <select className="branch-modal-input form-input-admin w-full">
                  <option value="">-- Không trực thuộc (Cấp cao nhất) --</option>
                  <option value="1">Chi 1 (Đại Tôn)</option>
                  <option value="3">Chi 2</option>
                </select>
              </div>
              <div>
                <label className="branch-modal-label">Người làm Trưởng Chi/Nhánh</label>
                <div className="branch-search-group">
                  <input type="text" className="branch-search-group-input form-input-admin flex-1" placeholder="Nhập ID hoặc Tên người đại diện..." />
                  <button className="branch-search-btn admin-btn-secondary whitespace-nowrap">Tìm kiếm</button>
                </div>
              </div>
              <div>
                <label className="branch-modal-label">Địa bàn / Quê quán</label>
                <input type="text" className="branch-modal-input form-input-admin w-full" placeholder="Ví dụ: Hải Phòng" />
              </div>
            </div>
            <div className="branch-modal-footer">
              <button className="admin-btn-secondary" onClick={() => setIsAddModalOpen(false)}>Huỷ</button>
              <button className="admin-btn-primary" onClick={() => { alert('Lưu thành công!'); setIsAddModalOpen(false); }}>Lưu dữ liệu</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default BranchesPage;
