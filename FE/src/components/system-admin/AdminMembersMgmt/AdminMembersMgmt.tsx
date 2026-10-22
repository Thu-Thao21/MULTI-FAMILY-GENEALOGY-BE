import React, { useState, useEffect } from 'react';
import apiClient from '../../../api/axios';
import { useToast } from '../../../shared/common/Toast';
import DataTable, { Column } from '../../../shared/DataTable/DataTable';
import './AdminMembersMgmt.css';

export interface MemberItem {
  id: string;
  full_name: string;
  other_name?: string;
  gender: 'male' | 'female' | string;
  birth_date?: string;
  death_date?: string;
  lunar_death_date?: string;
  is_alive: boolean;
  burial_place?: string;
  branch?: string;
  sub_branch?: string;
  generation: number;
  role: string;
  status: string;
  occupation?: string;
  education?: string;
  bio?: string;
  avatar_url?: string;
  phone?: string;
  email?: string;
  address?: string;
  skills?: string;
  contributions?: string;
}

const INITIAL_MEMBERS: MemberItem[] = [];

export const AdminMembersMgmt: React.FC = () => {
  const [members, setMembers] = useState<MemberItem[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [activeModalTab, setActiveModalTab] = useState<'basic' | 'bio' | 'contact' | 'skills'>('basic');
  const [editingMember, setEditingMember] = useState<MemberItem | null>(null);
  const [formData, setFormData] = useState<Partial<MemberItem>>({});
  const toast = useToast();

  const fetchMembers = async () => {
    try {
      const res = await apiClient.get<any>('/members');
      const dataList = Array.isArray(res.data) ? res.data : res.data?.items;
      if (Array.isArray(dataList)) {
        setMembers(dataList);
      } else {
        setMembers([]);
      }
    } catch (err) {
      console.error('Fetch members error from Neon DB:', err);
      setMembers([]);
    }
  };

  useEffect(() => {
    fetchMembers();
  }, []);

  const handleOpenAddModal = () => {
    setEditingMember(null);
    setFormData({
      full_name: '',
      gender: 'male',
      is_alive: true,
      generation: 1,
      branch: 'Chi Trưởng',
      role: 'member',
      status: 'active',
    });
    setActiveModalTab('basic');
    setIsModalOpen(true);
  };

  const handleOpenEditModal = (mem: MemberItem) => {
    setEditingMember(mem);
    setFormData({ ...mem });
    setActiveModalTab('basic');
    setIsModalOpen(true);
  };

  const handleDeleteMember = (mem: MemberItem) => {
    if (window.confirm(`Bạn có chắc chắn muốn xóa hồ sơ thành viên "${mem.full_name}"?`)) {
      setMembers((prev) => prev.filter((m) => m.id !== mem.id));
      toast.success('Đã xóa hồ sơ thành viên', `Hồ sơ "${mem.full_name}" đã được xóa khỏi hệ thống.`);
    }
  };

  const handleSaveMember = (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.full_name) return;

    if (editingMember) {
      setMembers((prev) =>
        prev.map((m) => (m.id === editingMember.id ? ({ ...m, ...formData } as MemberItem) : m))
      );
    } else {
      const newMem: MemberItem = {
        id: `mem_${Date.now()}`,
        full_name: formData.full_name,
        gender: formData.gender || 'male',
        is_alive: formData.is_alive ?? true,
        generation: formData.generation || 1,
        branch: formData.branch || 'Chi Trưởng',
        role: formData.role || 'member',
        status: 'active',
        ...formData,
      };
      setMembers((prev) => [newMem, ...prev]);
    }

    setIsModalOpen(false);
    if (editingMember) {
      toast.success('Cập nhật thành công!', `Hồ sơ "${formData.full_name}" đã được cập nhật.`);
    } else {
      toast.success('Thêm mới thành công!', `Thành viên "${formData.full_name}" đã được thêm vào hệ thống.`);
    }
  };

  const filteredMembers = members.filter((m) => {
    const matchSearch =
      m.full_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (m.occupation || '').toLowerCase().includes(searchTerm.toLowerCase()) ||
      (m.branch || '').toLowerCase().includes(searchTerm.toLowerCase());
    const matchStatus =
      statusFilter === 'alive'
        ? m.is_alive
        : statusFilter === 'deceased'
        ? !m.is_alive
        : true;
    return matchSearch && matchStatus;
  });

  const memberColumns: Column<MemberItem>[] = [
    {
      key: 'full_name',
      header: 'Họ & Tên Thành Viên',
      render: (m) => (
        <>
          <div style={{fontWeight: 600, color: '#0f172a'}}>{m.full_name}</div>
          {m.other_name && <div style={{fontSize: '0.85rem', color: '#64748b'}}>{m.other_name}</div>}
        </>
      )
    },
    {
      key: 'gender_gen',
      header: 'Giới tính / Đời thứ',
      render: (m) => (
        <>
          <div>{m.gender === 'male' ? 'Nam' : 'Nữ'}</div>
          <div style={{fontSize: '0.85rem', color: '#64748b'}}>Đời thứ {m.generation}</div>
        </>
      )
    },
    {
      key: 'branch',
      header: 'Chi / Nhánh',
      render: (m) => (
        <span className="perm-tag" style={{background: '#f1f5f9'}}>{m.branch || 'Chính tộc'}</span>
      )
    },
    {
      key: 'status',
      header: 'Trạng thái & Nơi An Táng',
      render: (m) => (
        <>
          <span className={m.is_alive ? 'status-badge-active' : 'status-badge-locked'} style={!m.is_alive ? {background: '#f1f5f9', color: '#475569'} : {}}>
            {m.is_alive ? 'Còn sống' : 'Đã mất'}
          </span>
          {!m.is_alive && m.burial_place && (
            <div style={{fontSize: '0.85rem', color: '#64748b', marginTop: '4px'}}>Mộ phần: {m.burial_place}</div>
          )}
        </>
      )
    },
    {
      key: 'occupation',
      header: 'Nghề nghiệp / Học vấn',
      render: (m) => (
        <>
          <div>{m.occupation || '—'}</div>
          <div style={{fontSize: '0.85rem', color: '#64748b'}}>{m.education || ''}</div>
        </>
      )
    },
    {
      key: 'actions',
      header: 'Thao tác',
      render: (m) => (
        <div className="action-btn-row">
          <button className="btn-icon-action" onClick={() => handleOpenEditModal(m)}>Chỉnh sửa</button>
          <button className="btn-icon-action lock" onClick={() => handleDeleteMember(m)}>Xóa</button>
        </div>
      )
    }
  ];

  return (
    <div className="admin-account-container">
      {/* Header Controls */}
      <div className="admin-account-header">
        <div>
          <h2 className="admin-account-title">Quản Lý Hồ Sơ & Thành Viên Toàn Gia Tộc</h2>
          <p className="admin-account-subtitle">
            Thêm, sửa, xóa hồ sơ thành viên, trạng thái an táng, tiểu sử, học vấn, thành tựu, liên hệ và năng lực đóng góp.
          </p>
        </div>

        <div className="admin-account-controls">
          <input
            type="text"
            className="admin-search-input"
            placeholder="Tìm tên, nghề nghiệp, chi nhánh..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
          <select
            className="admin-select-filter"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="">Tất cả trạng thái</option>
            <option value="alive">Còn sống</option>
            <option value="deceased">Đã mất</option>
          </select>
          <button className="admin-btn-primary" onClick={handleOpenAddModal}>
            Thêm Thành Viên Mới
          </button>
        </div>
      </div>

      {/* Table Directory */}
      <div className="admin-table-card">
        {loading ? (
          <div style={{padding: '24px', textAlign: 'center', color: '#64748b'}}>Đang tải danh sách thành viên...</div>
        ) : (
          <DataTable columns={memberColumns} data={filteredMembers} keyExtractor={(item) => item.id} emptyMessage="Không có thành viên nào phù hợp." />
        )}
      </div>

      {/* Full Modal with Tabs */}
      {isModalOpen && (
        <div className="admin-modal-overlay">
          <div className="admin-modal-box admin-modal-box-lg">
            <div className="admin-modal-header">
              <h3 className="admin-modal-title">{editingMember ? 'Chỉnh Sửa Hồ Sơ Thành Viên' : 'Thêm Thành Viên Mới'}</h3>
              <button className="admin-modal-close" onClick={() => setIsModalOpen(false)}>✕</button>
            </div>

            {/* Modal Tabs Navigation */}
            <div style={{ display: 'flex', gap: '8px', padding: '16px 24px', background: '#f8fafc', borderBottom: '1px solid #e2e8f0' }}>
              <button
                className={`admin-btn-secondary ${activeModalTab === 'basic' ? 'admin-btn-primary' : ''}`}
                style={activeModalTab === 'basic' ? {background: '#fff', color: '#0f172a', boxShadow: '0 1px 3px rgba(0,0,0,0.1)'} : {background: 'transparent'}}
                onClick={() => setActiveModalTab('basic')}
              >
                1. Thông tin cơ bản
              </button>
              <button
                className={`admin-btn-secondary ${activeModalTab === 'bio' ? 'admin-btn-primary' : ''}`}
                style={activeModalTab === 'bio' ? {background: '#fff', color: '#0f172a', boxShadow: '0 1px 3px rgba(0,0,0,0.1)'} : {background: 'transparent'}}
                onClick={() => setActiveModalTab('bio')}
              >
                2. Tiểu sử & Sự nghiệp
              </button>
              <button
                className={`admin-btn-secondary ${activeModalTab === 'contact' ? 'admin-btn-primary' : ''}`}
                style={activeModalTab === 'contact' ? {background: '#fff', color: '#0f172a', boxShadow: '0 1px 3px rgba(0,0,0,0.1)'} : {background: 'transparent'}}
                onClick={() => setActiveModalTab('contact')}
              >
                3. Liên hệ
              </button>
              <button
                className={`admin-btn-secondary ${activeModalTab === 'skills' ? 'admin-btn-primary' : ''}`}
                style={activeModalTab === 'skills' ? {background: '#fff', color: '#0f172a', boxShadow: '0 1px 3px rgba(0,0,0,0.1)'} : {background: 'transparent'}}
                onClick={() => setActiveModalTab('skills')}
              >
                4. Năng lực & Đóng góp
              </button>
            </div>

            <form onSubmit={handleSaveMember}>
              <div style={{ padding: '24px' }}>
              {activeModalTab === 'basic' && (
                <>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
                    <div className="form-group-admin" style={{margin: 0}}>
                      <label className="form-label-admin">Họ & Tên *</label>
                      <input
                        type="text"
                        className="form-input-admin"
                        value={formData.full_name || ''}
                        onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
                        required
                      />
                    </div>
                    <div className="form-group-admin" style={{margin: 0}}>
                      <label className="form-label-admin">Tên thường gọi / Tên tự</label>
                      <input
                        type="text"
                        className="form-input-admin"
                        value={formData.other_name || ''}
                        onChange={(e) => setFormData({ ...formData, other_name: e.target.value })}
                      />
                    </div>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '16px', marginBottom: '16px' }}>
                    <div className="form-group-admin" style={{margin: 0}}>
                      <label className="form-label-admin">Giới tính</label>
                      <select
                        className="form-input-admin"
                        value={formData.gender || 'male'}
                        onChange={(e) => setFormData({ ...formData, gender: e.target.value })}
                      >
                        <option value="male"> Nam</option>
                        <option value="female"> Nữ</option>
                      </select>
                    </div>

                    <div className="form-group-admin" style={{margin: 0}}>
                      <label className="form-label-admin">Thế hệ / Đời thứ</label>
                      <input
                        type="number"
                        className="form-input-admin"
                        value={formData.generation || 1}
                        onChange={(e) => setFormData({ ...formData, generation: parseInt(e.target.value) || 1 })}
                      />
                    </div>

                    <div className="form-group-admin" style={{margin: 0}}>
                      <label className="form-label-admin">Trạng thái còn sống</label>
                      <select
                        className="form-input-admin"
                        value={formData.is_alive ? 'true' : 'false'}
                        onChange={(e) => setFormData({ ...formData, is_alive: e.target.value === 'true' })}
                      >
                        <option value="true"> Còn sống</option>
                        <option value="false"> Đã mất</option>
                      </select>
                    </div>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
                    <div className="form-group-admin" style={{margin: 0}}>
                      <label className="form-label-admin">Ngày sinh (Dương lịch)</label>
                      <input
                        type="date"
                        className="form-input-admin"
                        value={formData.birth_date || ''}
                        onChange={(e) => setFormData({ ...formData, birth_date: e.target.value })}
                      />
                    </div>

                    {!formData.is_alive && (
                      <div className="form-group-admin" style={{margin: 0}}>
                        <label className="form-label-admin">Ngày mất (Dương lịch)</label>
                        <input
                          type="date"
                          className="form-input-admin"
                          value={formData.death_date || ''}
                          onChange={(e) => setFormData({ ...formData, death_date: e.target.value })}
                        />
                      </div>
                    )}
                  </div>

                  {!formData.is_alive && (
                    <div className="form-group-admin" style={{margin: 0}}>
                      <label className="form-label-admin">Nơi an táng / Mộ phần</label>
                      <input
                        type="text"
                        className="form-input-admin"
                        value={formData.burial_place || ''}
                        onChange={(e) => setFormData({ ...formData, burial_place: e.target.value })}
                        placeholder="Ví dụ: Khu nghĩa trang dòng họ, Thường Tín"
                      />
                    </div>
                  )}
                </>
              )}

              {activeModalTab === 'bio' && (
                <>
                  <div className="form-group-admin">
                    <label className="form-label-admin">Nghề nghiệp hiện tại / Cựu nghề nghiệp</label>
                    <input
                      type="text"
                      className="form-input-admin"
                      value={formData.occupation || ''}
                      onChange={(e) => setFormData({ ...formData, occupation: e.target.value })}
                    />
                  </div>

                  <div className="form-group-admin">
                    <label className="form-label-admin">Trình độ học vấn & Bằng cấp</label>
                    <input
                      type="text"
                      className="form-input-admin"
                      value={formData.education || ''}
                      onChange={(e) => setFormData({ ...formData, education: e.target.value })}
                    />
                  </div>

                  <div className="form-group-admin">
                    <label className="form-label-admin">Tiểu sử & Cột mốc sự nghiệp</label>
                    <textarea
                      className="form-input-admin"
                      rows={4}
                      value={formData.bio || ''}
                      onChange={(e) => setFormData({ ...formData, bio: e.target.value })}
                    />
                  </div>
                </>
              )}

              {activeModalTab === 'contact' && (
                <>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
                    <div className="form-group-admin" style={{margin: 0}}>
                      <label className="form-label-admin">Số điện thoại</label>
                      <input
                        type="text"
                        className="form-input-admin"
                        value={formData.phone || ''}
                        onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                      />
                    </div>
                    <div className="form-group-admin" style={{margin: 0}}>
                      <label className="form-label-admin">Địa chỉ Email</label>
                      <input
                        type="email"
                        className="form-input-admin"
                        value={formData.email || ''}
                        onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                      />
                    </div>
                  </div>

                  <div className="form-group-admin">
                    <label className="form-label-admin">Địa chỉ nơi ở hiện tại</label>
                    <input
                      type="text"
                      className="form-input-admin"
                      value={formData.address || ''}
                      onChange={(e) => setFormData({ ...formData, address: e.target.value })}
                    />
                  </div>
                </>
              )}

              {activeModalTab === 'skills' && (
                <>
                  <div className="form-group-admin">
                    <label className="form-label-admin">Kỹ năng & Năng lực đặc biệt</label>
                    <input
                      type="text"
                      className="form-input-admin"
                      value={formData.skills || ''}
                      onChange={(e) => setFormData({ ...formData, skills: e.target.value })}
                      placeholder="Ví dụ: Quản trị, Luật pháp, Công nghệ thông tin, Y tế..."
                    />
                  </div>

                  <div className="form-group-admin">
                    <label className="form-label-admin">Khả năng đóng góp cho dòng họ</label>
                    <textarea
                      className="form-input-admin"
                      rows={3}
                      value={formData.contributions || ''}
                      onChange={(e) => setFormData({ ...formData, contributions: e.target.value })}
                      placeholder="Nhập ghi chú đóng góp quỹ họ, trùng tu từ đường..."
                    />
                  </div>
                </>
              )}
              </div>

              <div className="admin-modal-footer">
                <button type="button" className="admin-btn-secondary" onClick={() => setIsModalOpen(false)}>Hủy</button>
                <button type="submit" className="admin-btn-primary">Lưu hồ sơ thành viên</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default AdminMembersMgmt;
