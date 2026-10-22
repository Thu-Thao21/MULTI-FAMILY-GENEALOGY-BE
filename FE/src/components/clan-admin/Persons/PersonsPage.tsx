import './PersonsPage.css';
import React, { useState } from 'react';
import PageHeader from '../../../shared/Layout/PageHeader';
import DataTable, { type Column } from '../../../shared/DataTable/DataTable';

interface Person {
  id: string;
  name: string;
  gender: 'Nam' | 'Nữ';
  dob: string;
  generation: number;
  branch: string;
  status: 'alive' | 'deceased';
}

import { fetchMembers } from '../../../services/member.service';

export const PersonsPage: React.FC = () => {
  const [search, setSearch] = useState('');
  const [selectedPerson, setSelectedPerson] = useState<Person | null>(null);
  const [detailTab, setDetailTab] = useState<'overview' | 'relationships' | 'account' | 'history'>('overview');
  const [data, setData] = useState<Person[]>([]);

  React.useEffect(() => {
    fetchMembers({ search: search || undefined, limit: 100 }).then((res) => {
      const mapped: Person[] = (res.items || []).map((m: any) => ({
        id: m.id,
        name: m.fullName || m.full_name || 'Thành viên',
        gender: m.gender === 'female' ? 'Nữ' : 'Nam',
        dob: m.birthDate ? String(m.birthDate).slice(0, 10) : m.birth_year ? String(m.birth_year) : '—',
        generation: m.generation || 1,
        branch: m.branch || 'Chi Trưởng',
        status: m.isAlive === false || m.is_alive === false ? 'deceased' : 'alive',
      }));
      setData(mapped);
    }).catch(() => setData([]));
  }, [search]);

  const columns: Column<Person>[] = [
    { key: 'name', header: 'Họ và tên', render: (item) => <strong className="text-slate-800">{item.name}</strong> },
    { key: 'gender', header: 'Giới tính', render: (item) => item.gender },
    { key: 'dob', header: 'Năm sinh', render: (item) => item.dob },
    { key: 'generation', header: 'Đời thứ', render: (item) => `Đời ${item.generation}` },
    { key: 'branch', header: 'Thuộc Chi/Nhánh', render: (item) => item.branch },
    { key: 'status', header: 'Trạng thái', render: (item) => (
      <span className={`person-status-badge ${item.status === 'alive' ? 'status-alive' : 'status-deceased'}`}>
        {item.status === 'alive' ? 'Còn sống' : 'Đã mất'}
      </span>
    )},
    { key: 'actions', header: 'Thao tác', render: (item) => (
      <div className="persons-actions">
        <button 
          className="persons-btn-detail"
          onClick={() => setSelectedPerson(item)}
        >
          Chi tiết
        </button>
      </div>
    )},
  ];

  const headerActions = (
    <div className="persons-header-actions">
      <button className="admin-btn-secondary">Import Excel</button>
      <button className="persons-btn-merge admin-btn-primary bg-slate-800 hover:bg-slate-900 border-slate-800 text-white flex gap-2 items-center">
        <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2" /><line x1="9" y1="3" x2="9" y2="21" /></svg>
        Gộp trùng lặp
      </button>
      <button className="admin-btn-primary">
        <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
        Thêm Nhân khẩu
      </button>
    </div>
  );

  return (
    <div className="admin-account-container">
      
      <div className="admin-account-header">
        <div>
          <h2 className="admin-account-title">Quản lý Person (Nhân khẩu)</h2>
          <p className="admin-account-subtitle">Danh sách toàn bộ nhân khẩu trong dòng họ.</p>
        </div>
        <div className="admin-account-controls">
          {headerActions}
        </div>
      </div>
      
      <div className="persons-filter-bar">
        <input 
          type="text" 
          placeholder="Tìm kiếm tên, CCCD..." 
          className="persons-search-input form-input-admin flex-1"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select className="persons-branch-select form-input-admin w-48">
          <option value="">Tất cả Chi/Nhánh</option>
          <option value="chi1">Chi 1</option>
        </select>
        <select className="persons-status-select form-input-admin w-48">
          <option value="">Trạng thái</option>
          <option value="alive">Còn sống</option>
        </select>
      </div>

      <div className="persons-table-container">
        <DataTable 
          columns={columns} 
          data={data} 
          keyExtractor={(item) => item.id} 
          emptyMessage="Không tìm thấy nhân khẩu nào."
        />
      </div>

      {/* Centered Modal for Person Detail */}
      {selectedPerson && (
        <div className="persons-modal-overlay">
          <div className="persons-modal-backdrop" onClick={() => setSelectedPerson(null)}></div>
          
          <div className="persons-modal-content relative w-full max-w-4xl bg-white rounded-2xl shadow-2xl flex flex-col max-h-[95vh] animate-zoom-in overflow-hidden">
            <div className="persons-modal-header">
              <div className="persons-modal-header-left">
                <div className="persons-modal-avatar">
                  {selectedPerson.name.charAt(0)}
                </div>
                <div>
                  <h2 className="persons-modal-name">{selectedPerson.name}</h2>
                  <p className="text-slate-500">Đời {selectedPerson.generation} • {selectedPerson.branch}</p>
                </div>
              </div>
              <button 
                className="persons-modal-close"
                onClick={() => setSelectedPerson(null)}
              >
                ✕
              </button>
            </div>

            <div className="persons-modal-tabs">
              <button className={`person-tab-btn ${detailTab === 'overview' ? 'tab-active' : 'tab-inactive'}`} onClick={() => setDetailTab('overview')}>Tổng quan</button>
              <button className={`person-tab-btn ${detailTab === 'relationships' ? 'tab-active' : 'tab-inactive'}`} onClick={() => setDetailTab('relationships')}>Quan hệ Gia đình</button>
              <button className={`person-tab-btn ${detailTab === 'account' ? 'tab-active' : 'tab-inactive'}`} onClick={() => setDetailTab('account')}>Tài khoản & Phân quyền</button>
              <button className={`person-tab-btn ${detailTab === 'history' ? 'tab-active' : 'tab-inactive'}`} onClick={() => setDetailTab('history')}>Lịch sử & Cập nhật</button>
            </div>

            <div className="persons-modal-body">
              {detailTab === 'overview' && (
                <div className="space-y-6">
                  <div className="persons-detail-section">
                    <h3 className="persons-detail-title">Thông tin cơ bản</h3>
                    <div className="persons-detail-grid">
                      <div><span className="persons-detail-label">Ngày sinh</span><strong className="text-slate-800">{selectedPerson.dob}</strong></div>
                      <div><span className="persons-detail-label">Giới tính</span><strong className="text-slate-800">{selectedPerson.gender}</strong></div>
                      <div><span className="persons-detail-label">Tình trạng</span><strong className="text-slate-800">{selectedPerson.status === 'alive' ? 'Còn sống' : 'Đã mất'}</strong></div>
                      <div><span className="persons-detail-label">Nơi ở hiện tại</span><strong className="text-slate-800">Hà Nội, Việt Nam</strong></div>
                    </div>
                    <div className="persons-detail-actions">
                      <button className="admin-btn-primary" onClick={() => alert('Tính năng Chỉnh sửa Hồ sơ đang được phát triển.')}>Chỉnh sửa Hồ sơ</button>
                      <button className="persons-btn-hide admin-btn-secondary border-blue-200 text-red-600 hover:bg-red-50" onClick={() => alert('Đã ẩn nhân khẩu này khỏi danh sách.')}>Ẩn Nhân khẩu (Hide)</button>
                    </div>
                  </div>
                </div>
              )}

              {detailTab === 'relationships' && (
                <div className="space-y-4">
                  <div className="persons-rel-row">
                    <div>
                      <span className="persons-rel-label">Cha mẹ</span>
                      <p className="persons-rel-value">Nguyễn Văn Cha <span className="persons-rel-meta">(Đời {selectedPerson.generation - 1})</span></p>
                    </div>
                    <button className="persons-btn-edit-rel" onClick={() => alert('Đang mở form chỉnh sửa quan hệ...')}>Sửa</button>
                  </div>
                  
                  <div className="persons-rel-row">
                    <div className="persons-rel-label-group">
                      <span className="persons-rel-label">Vợ / Chồng</span>
                      <button className="persons-btn-add-spouse" onClick={() => alert('Đang mở form thêm vợ/chồng...')}>+ Thêm Vợ/Chồng</button>
                    </div>
                    <p className="persons-rel-empty">Chưa có thông tin</p>
                  </div>

                  <button 
                    className="persons-btn-add-child"
                    onClick={() => alert('Đang mở form thêm con cái...')}
                  >
                    + Thêm Con cái
                  </button>
                  
                  <button 
                    className="persons-btn-view-tree"
                    onClick={() => window.location.href='/clan-admin/genealogy-tree'}
                  >
                    Xem vị trí trên Cây Gia phả
                  </button>
                </div>
              )}

              {detailTab === 'account' && (
                <div className="persons-account-section">
                  <div className="persons-account-icon-wrap">
                    <svg width="32" height="32" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0110 0v4" /></svg>
                  </div>
                  <h3 className="persons-account-title">Chưa liên kết Tài khoản</h3>
                  <p className="persons-account-desc">Cấp tài khoản đăng nhập cho nhân khẩu này để họ có thể xem gia phả và nhận thông báo sự kiện.</p>
                  
                  <button className="admin-btn-primary" onClick={() => alert('Đã tạo tài khoản cho thành viên này!')}>Tạo Account (Sinh user/pass tự động)</button>
                </div>
              )}
              
              {detailTab === 'history' && (
                <div className="persons-history-section">
                  <div className="persons-history-item relative flex items-center justify-between md:justify-normal md:odd:flex-row-reverse group is-active">
                    <div className="persons-history-icon-wrap flex items-center justify-center w-10 h-10 rounded-full border border-white bg-slate-300 group-[.is-active]:bg-blue-600 text-slate-50 group-[.is-active]:text-white shadow shrink-0 md:order-1 md:group-odd:-translate-x-1/2 md:group-even:translate-x-1/2">
                      <svg className="fill-current" viewBox="0 0 16 16" width="16" height="16"><path d="M8 0a8 8 0 1 0 8 8 8.009 8.009 0 0 0-8-8Zm0 12a4 4 0 1 1 0-8 4 4 0 0 1 0 8Z" /></svg>
                    </div>
                    <div className="persons-history-content">
                      <div className="persons-history-header">
                        <div className="persons-history-title">Thêm mới nhân khẩu</div>
                        <time className="persons-history-time">11/09/2026</time>
                      </div>
                      <div className="persons-history-author">Tạo bởi: Admin Trưởng tộc</div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default PersonsPage;
