import React, { useState, useEffect } from 'react';
import apiClient from '../../../api/axios';
import './AdminFamiliesMgmt.css';

export interface FamilyItem {
  id: string;
  name: string;
  founder_name?: string;
  origin_place?: string;
  ancestral_house_address?: string;
  history?: string;
  description?: string;
  branches?: string[];
  status?: string;
}

export const AdminFamiliesMgmt: React.FC = () => {
  const [families, setFamilies] = useState<FamilyItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [editingFamily, setEditingFamily] = useState<FamilyItem | null>(null);
  const [formData, setFormData] = useState<Partial<FamilyItem>>({
    name: '',
    founder_name: '',
    origin_place: '',
    ancestral_house_address: '',
    history: '',
    description: '',
  });
  const [msg, setMsg] = useState<string>('');

  const fetchFamilies = async () => {
    setLoading(true);
    try {
      const res = await apiClient.get<any[]>('/families');
      if (Array.isArray(res.data)) {
        const mapped: FamilyItem[] = res.data.map((f: any) => ({
          id: f.id || f.clan_id,
          name: f.name || f.clan_name || 'Dòng họ',
          founder_name: f.founder_name || f.representative_name || 'Chưa cập nhật',
          origin_place: f.origin_place || 'Chưa cập nhật',
          ancestral_house_address: f.ancestral_house_address || f.address || 'Chưa cập nhật',
          history: f.history || '',
          description: f.description || (f.clan_code ? `Mã dòng họ: ${f.clan_code}` : ''),
          branches: f.branches || ['Chi Trưởng', 'Chi Thứ'],
          status: f.status || 'active',
        }));
        setFamilies(mapped);
      } else {
        setFamilies([]);
      }
    } catch (err: any) {
      console.error('Không thể tải danh sách dòng họ từ Neon DB:', err);
      setFamilies([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchFamilies();
  }, []);

  const handleOpenAddModal = () => {
    setEditingFamily(null);
    setFormData({
      name: '',
      founder_name: '',
      origin_place: '',
      ancestral_house_address: '',
      history: '',
      description: '',
    });
    setIsModalOpen(true);
  };

  const handleOpenEditModal = (fam: FamilyItem) => {
    setEditingFamily(fam);
    setFormData({ ...fam });
    setIsModalOpen(true);
  };

  const handleDeleteFamily = (fam: FamilyItem) => {
    if (window.confirm(`Bạn có chắc chắn muốn xóa dòng họ "${fam.name}"?`)) {
      setFamilies((prev) => prev.filter((f) => f.id !== fam.id));
      setMsg(`Đã xóa dòng họ thành công.`);
      setTimeout(() => setMsg(''), 3000);
    }
  };

  const handleSaveFamily = (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.name) return;

    if (editingFamily) {
      setFamilies((prev) =>
        prev.map((f) => (f.id === editingFamily.id ? ({ ...f, ...formData } as FamilyItem) : f))
      );
      setMsg(`Cập nhật dòng họ "${formData.name}" thành công!`);
    } else {
      const newFam: FamilyItem = {
        id: `fam_${Date.now()}`,
        name: formData.name,
        founder_name: formData.founder_name || 'Đang cập nhật',
        origin_place: formData.origin_place || 'Đang cập nhật',
        ancestral_house_address: formData.ancestral_house_address || 'Đang cập nhật',
        history: formData.history || '',
        description: formData.description || '',
        branches: ['Chi 1 (Trưởng)', 'Chi 2 (Thứ)'],
        status: 'active',
      };
      setFamilies((prev) => [newFam, ...prev]);
      setMsg(`Thêm mới dòng họ "${formData.name}" thành công!`);
    }

    setIsModalOpen(false);
    setTimeout(() => setMsg(''), 3000);
  };

  const filteredFamilies = families.filter((f) =>
    f.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    (f.founder_name || '').toLowerCase().includes(searchTerm.toLowerCase()) ||
    (f.origin_place || '').toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="admin-families-container">
      {/* Header */}
      <div className="admin-account-header">
        <div>
          <h2 className="admin-account-title">Quản Lý Danh Sách Dòng Họ & Thủy Tổ</h2>
          <p className="admin-account-subtitle">
            Tạo, sửa, xóa dòng họ, cây gia phả, thủy tổ, quê quán, lịch sử dòng họ và địa chỉ nhà thờ họ.
          </p>
        </div>

        <div className="admin-account-controls">
          <input
            type="text"
            className="admin-search-input"
            placeholder="Tìm dòng họ, quê quán, thủy tổ..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
          <button className="admin-btn-primary" onClick={handleOpenAddModal}>
            Thêm Dòng Họ Mới
          </button>
        </div>
      </div>

      {msg && <div className="admin-msg-box">{msg}</div>}

      {/* Cards List */}
      {loading ? (
        <p className="admin-table-loading">Đang tải danh sách dòng họ...</p>
      ) : filteredFamilies.length === 0 ? (
        <p className="admin-table-empty">Không tìm thấy dòng họ nào.</p>
      ) : (
        <div className="family-cards-grid">
          {filteredFamilies.map((fam) => (
            <div key={fam.id} className="family-card-item">
              <div>
                <div className="family-card-header">
                  <h3 className="family-name-title">{fam.name}</h3>
                  <span className="family-founder-badge">Dòng Họ Active</span>
                </div>

                <div className="family-info-line">
                  <strong>Thủy tổ:</strong> {fam.founder_name || 'Đang cập nhật'}
                </div>
                <div className="family-info-line">
                  <strong>Quê quán / Gốc họ:</strong> {fam.origin_place || 'Đang cập nhật'}
                </div>
                <div className="family-info-line">
                  <strong>Nhà thờ họ:</strong> {fam.ancestral_house_address || 'Đang cập nhật'}
                </div>
                {fam.branches && fam.branches.length > 0 && (
                  <div className="family-info-line admin-fam-branch-margin">
                    <strong>Chi / Nhánh ({fam.branches.length}):</strong>{' '}
                    {fam.branches.map((b, i) => (
                      <span key={i} className="admin-fam-branch-item">
                        {b}
                      </span>
                    ))}
                  </div>
                )}
                {fam.description && (
                  <p className="admin-fam-desc">
                    {fam.description}
                  </p>
                )}
              </div>

              <div className="family-card-footer">
                <span className="admin-fam-id">Mã dòng họ: #{fam.id}</span>
                <div className="action-btn-row">
                  <button className="btn-icon-action" onClick={() => handleOpenEditModal(fam)}>Sửa</button>
                  <button className="btn-icon-action lock" onClick={() => handleDeleteFamily(fam)}>Xóa</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Add / Edit Modal */}
      {isModalOpen && (
        <div className="admin-modal-overlay">
          <div className="admin-modal-box admin-modal-box-md">
            <div className="admin-modal-header">
              <h3>{editingFamily ? 'Chỉnh Sửa Dòng Họ' : 'Tạo Dòng Họ Mới'}</h3>
              <button className="admin-modal-close" onClick={() => setIsModalOpen(false)}>✕</button>
            </div>

            <form onSubmit={handleSaveFamily}>
              <div className="form-group-admin">
                <label className="form-label-admin">Tên Dòng Họ *</label>
                <input
                  type="text"
                  className="form-input-admin"
                  value={formData.name || ''}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  placeholder="Ví dụ: Dòng Họ Nguyễn Văn (Đại Tộc Tự Cốt)"
                  required
                />
              </div>

              <div className="admin-form-grid-2">
                <div className="form-group-admin">
                  <label className="form-label-admin">Thủy Tổ / Cụ Tổ Khởi Xướng</label>
                  <input
                    type="text"
                    className="form-input-admin"
                    value={formData.founder_name || ''}
                    onChange={(e) => setFormData({ ...formData, founder_name: e.target.value })}
                    placeholder="Ví dụ: Cụ Nguyễn Văn A (Đời thứ 1)"
                  />
                </div>

                <div className="form-group-admin">
                  <label className="form-label-admin">Quê Quán / Nguồn Gốc</label>
                  <input
                    type="text"
                    className="form-input-admin"
                    value={formData.origin_place || ''}
                    onChange={(e) => setFormData({ ...formData, origin_place: e.target.value })}
                    placeholder="Ví dụ: Làng Cổ, Thường Tín, Hà Nội"
                  />
                </div>
              </div>

              <div className="form-group-admin">
                <label className="form-label-admin">Địa Chỉ Nhà Thờ Họ / Từ Đường</label>
                <input
                  type="text"
                  className="form-input-admin"
                  value={formData.ancestral_house_address || ''}
                  onChange={(e) => setFormData({ ...formData, ancestral_house_address: e.target.value })}
                  placeholder="Ví dụ: Số 12 Đường Nhà Thờ Tổ, Thường Tín, Hà Nội"
                />
              </div>

              <div className="form-group-admin">
                <label className="form-label-admin">Lịch Sử Dòng Họ</label>
                <textarea
                  className="form-input-admin"
                  rows={3}
                  value={formData.history || ''}
                  onChange={(e) => setFormData({ ...formData, history: e.target.value })}
                  placeholder="Nhập tóm tắt lịch sử hình thành, niên đại..."
                />
              </div>

              <div className="admin-modal-footer">
                <button type="button" className="btn-icon-action" onClick={() => setIsModalOpen(false)}>Hủy</button>
                <button type="submit" className="admin-btn-primary">Lưu thông tin dòng họ</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default AdminFamiliesMgmt;
