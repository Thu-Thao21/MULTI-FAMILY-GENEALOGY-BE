import './AncestorsPage.css';
import React, { useState } from 'react';
import PageHeader from '../../../shared/Layout/PageHeader';
import DataTable, { type Column } from '../../../shared/DataTable/DataTable';

interface Ancestor {
  id: string;
  name: string;
  generation: number;
  birthYear?: number;
  deathYear?: number;
  title?: string;
  status: 'active' | 'inactive';
}

import { fetchMembers } from '../../../services/member.service';

export const AncestorsPage: React.FC = () => {
  const [search, setSearch] = useState('');
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [selectedAncestor, setSelectedAncestor] = useState<Ancestor | null>(null);
  const [data, setData] = useState<Ancestor[]>([]);

  React.useEffect(() => {
    fetchMembers({ search: search || undefined, limit: 100 }).then((res) => {
      const items = res.items || [];
      const ancestorsOnly = items.filter((m: any) => m.generation === 1 || m.isAlive === false || m.is_alive === false);
      const mapped: Ancestor[] = (ancestorsOnly.length ? ancestorsOnly : items).map((m: any) => ({
        id: m.id,
        name: m.fullName || m.full_name || 'Thuỷ tổ',
        generation: m.generation || 1,
        birthYear: m.birthDate ? new Date(m.birthDate).getFullYear() : m.birth_year || undefined,
        deathYear: m.deathDate ? new Date(m.deathDate).getFullYear() : m.death_year || undefined,
        title: m.otherName || m.other_name || 'Thuỷ tổ gia tộc',
        status: 'active',
      }));
      setData(mapped);
    }).catch(() => setData([]));
  }, [search]);

  const columns: Column<Ancestor>[] = [
    { key: 'name', header: 'Tên Thuỷ tổ / Tiên tổ', render: (item) => (
      <strong 
        className="ancestor-name-link"
        onClick={() => setSelectedAncestor(item)}
      >
        {item.name}
      </strong>
    )},
    { key: 'generation', header: 'Đời thứ', render: (item) => `Đời ${item.generation}` },
    { key: 'years', header: 'Năm sinh - mất', render: (item) => `${item.birthYear || '?'} - ${item.deathYear || '?'}` },
    { key: 'title', header: 'Tước hiệu / Biệt hiệu', render: (item) => item.title || '-' },
    { key: 'status', header: 'Trạng thái', render: (item) => (
      <span className={`ancestor-status-badge ${item.status === 'active' ? 'active' : 'inactive'}`}>
        {item.status === 'active' ? 'Hiển thị' : 'Đã ẩn'}
      </span>
    )},
    { key: 'actions', header: 'Thao tác', render: () => (
      <div className="ancestor-actions">
        <button className="ancestor-action-btn">Sửa</button>
      </div>
    )},
  ];

  const headerActions = (
    <button className="admin-btn-primary" onClick={() => setIsAddModalOpen(true)}>
      <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
      Thêm Thuỷ tổ
    </button>
  );

  return (
    <div className="admin-account-container">
      
      <div className="admin-account-header">
        <div>
          <h2 className="admin-account-title">Quản lý Thuỷ tổ</h2>
          <p className="admin-account-subtitle">Thông tin về Thuỷ tổ và các Tiên tổ đời đầu của dòng họ.</p>
        </div>
        <div className="admin-account-controls">
          {headerActions}
        </div>
      </div>
      
      <div className="ancestors-search-bar">
        <input 
          type="text" 
          placeholder="Tìm kiếm tên, tước hiệu..." 
          className="ancestors-search-input form-input-admin flex-1"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select className="ancestors-search-select form-input-admin w-48">
          <option value="">Tất cả các đời</option>
          <option value="1">Đời 1</option>
          <option value="2">Đời 2</option>
        </select>
      </div>

      <div className="ancestors-table-container">
        <DataTable 
          columns={columns} 
          data={data} 
          keyExtractor={(item) => item.id} 
          emptyMessage="Chưa có thông tin Thuỷ tổ nào được cập nhật."
        />
      </div>

      {/* Add Modal */}
      {isAddModalOpen && (
        <div className="ancestors-modal-overlay">
          <div className="ancestors-modal-backdrop" onClick={() => setIsAddModalOpen(false)}></div>
          <div className="ancestors-modal-content relative bg-white rounded-xl shadow-2xl w-full max-w-lg overflow-hidden animate-fade-in">
            <div className="ancestors-modal-header">
              <h3 className="ancestors-modal-title">Thêm Thuỷ tổ / Tiên tổ</h3>
              <button className="ancestors-modal-close" onClick={() => setIsAddModalOpen(false)}>✕</button>
            </div>
            <div className="ancestors-modal-body">
              <div>
                <label className="ancestors-form-label">Tên Thuỷ tổ <span className="text-red-500">*</span></label>
                <input type="text" className="form-input-admin w-full" placeholder="Ví dụ: Nguyễn Bặc" />
              </div>
              <div className="ancestors-form-grid">
                <div>
                  <label className="ancestors-form-label">Năm sinh</label>
                  <input type="number" className="form-input-admin w-full" placeholder="Ví dụ: 924" />
                </div>
                <div>
                  <label className="ancestors-form-label">Năm mất</label>
                  <input type="number" className="form-input-admin w-full" placeholder="Ví dụ: 979" />
                </div>
              </div>
              <div>
                <label className="ancestors-form-label">Tước hiệu / Biệt hiệu</label>
                <input type="text" className="form-input-admin w-full" placeholder="Ví dụ: Định Quốc Công" />
              </div>
              <div>
                <label className="ancestors-form-label">Tiểu sử tóm tắt</label>
                <textarea className="form-input-admin w-full" rows={3} placeholder="Mô tả công trạng..."></textarea>
              </div>
            </div>
            <div className="ancestors-modal-footer">
              <button className="admin-btn-secondary" onClick={() => setIsAddModalOpen(false)}>Huỷ</button>
              <button className="admin-btn-primary" onClick={() => { alert('Lưu thành công!'); setIsAddModalOpen(false); }}>Lưu Thuỷ tổ</button>
            </div>
          </div>
        </div>
      )}

      {/* Detail Modal */}
      {selectedAncestor && (
        <div className="ancestors-detail-modal-overlay">
          <div className="ancestors-modal-backdrop" onClick={() => setSelectedAncestor(null)}></div>
          <div className="ancestors-detail-modal-content relative w-full max-w-2xl bg-white rounded-2xl shadow-2xl flex flex-col max-h-[90vh] animate-zoom-in overflow-hidden">
            <div className="ancestors-modal-header">
              <h3 className="ancestors-modal-title">Chi tiết Tiên tổ</h3>
              <button className="ancestors-modal-close" onClick={() => setSelectedAncestor(null)}>✕</button>
            </div>
            <div className="ancestors-detail-modal-body">
              <div className="ancestors-detail-header">
                <div className="ancestors-detail-avatar">
                  {selectedAncestor.name.charAt(0)}
                </div>
                <h2 className="ancestors-detail-name">{selectedAncestor.name}</h2>
                <p className="ancestors-detail-title">{selectedAncestor.title || 'Không có tước hiệu'}</p>
                <span className="ancestors-detail-badge">Đời {selectedAncestor.generation}</span>
              </div>

              <div className="ancestors-detail-info-list">
                <div className="ancestors-detail-info-box">
                  <div className="ancestors-info-box-label">Năm sinh - Năm mất</div>
                  <div className="ancestors-info-box-value">{selectedAncestor.birthYear || '?'} - {selectedAncestor.deathYear || '?'}</div>
                </div>
                
                <div className="ancestors-detail-info-box">
                  <div className="ancestors-info-box-label">Tiểu sử & Công trạng</div>
                  <div className="ancestors-info-box-text">
                    Đây là phần nội dung chi tiết về tiểu sử, nguồn gốc và những công trạng của vị Thủy tổ đối với dòng họ và đất nước. Nội dung này sẽ được hiển thị trên không gian truyền thống để con cháu đời sau học tập.
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AncestorsPage;
