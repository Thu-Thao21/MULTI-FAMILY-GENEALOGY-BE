import React, { useEffect, useMemo, useState, useCallback } from 'react';
import apiClient from '../../../api/axios';
import { fetchFamilyPersons, createFamilyPerson, updateFamilyPerson } from '../../../services/genealogy.service';
import './AdminMembersMgmt.css';

type MemberGender = 'male' | 'female' | 'other';
type MemberStatus = 'active' | 'hidden';

export interface MemberItem {
  id: string;
  full_name: string;
  other_name?: string;
  gender: MemberGender | string;
  birth_date?: string;
  is_alive: boolean;
  branch?: string;
  generation: number;
  relationship?: string;
  status: MemberStatus | string;
  avatar_url?: string;
  phone?: string;
  email?: string;
  has_account?: boolean;
}

type MemberFormData = Omit<MemberItem, 'id'>;
type ModalMode = 'add' | 'edit' | 'detail' | null;

const EMPTY_FORM: MemberFormData = {
  full_name: '', other_name: '', gender: 'male', birth_date: '', is_alive: true,
  branch: 'Chi Trưởng', generation: 1, relationship: '', status: 'active',
  phone: '', email: '', has_account: false,
};

const Icon = ({ name, size = 18 }: { name: string; size?: number }) => {
  const paths: Record<string, React.ReactNode> = {
    search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></>,
    plus: <><path d="M12 5v14" /><path d="M5 12h14" /></>,
    eye: <><path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z" /><circle cx="12" cy="12" r="2.5" /></>,
    edit: <><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4Z" /></>,
    hide: <><path d="m3 3 18 18" /><path d="M10.6 10.6A2 2 0 0 0 13.4 13.4" /><path d="M9.9 4.2A10.8 10.8 0 0 1 12 4c6 0 9.5 8 9.5 8a17 17 0 0 1-2.2 3.3" /><path d="M6.6 6.6C4 8.4 2.5 12 2.5 12S6 20 12 20c1.4 0 2.7-.4 3.8-1" /></>,
    restore: <><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5" /></>,
    key: <><circle cx="8" cy="15" r="4" /><path d="m11 12 8-8" /><path d="m16 7 2 2" /><path d="m14 9 2 2" /></>,
    close: <><path d="M18 6 6 18" /><path d="m6 6 12 12" /></>,
    users: <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.9" /><path d="M16 3.1a4 4 0 0 1 0 7.8" /></>,
    chevron: <path d="m9 18 6-6-6-6" />,
  };
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
};

const normalizeMember = (raw: any): MemberItem => ({
  id: String(raw.id), full_name: raw.full_name ?? raw.fullName ?? 'Chưa cập nhật',
  other_name: raw.other_name ?? raw.otherName, gender: raw.gender ?? 'other',
  birth_date: raw.birth_date ?? raw.birthDate, is_alive: raw.is_alive ?? raw.isAlive ?? true,
  branch: raw.branch ?? 'Chưa phân chi', generation: Number(raw.generation ?? 1),
  relationship: raw.relationship ?? raw.relation ?? 'Thành viên',
  status: raw.status === 'hidden' ? 'hidden' : 'active', avatar_url: raw.avatar_url ?? raw.avatarUrl,
  phone: raw.phone ?? raw.contact?.phone, email: raw.email ?? raw.contact?.email,
  has_account: Boolean(raw.has_account ?? raw.hasAccount ?? raw.user_id ?? raw.userId),
});

const formatDate = (date?: string) => date
  ? new Intl.DateTimeFormat('vi-VN').format(new Date(`${date}T00:00:00`))
  : 'Chưa cập nhật';

const getAge = (date?: string) => {
  if (!date) return null;
  const birth = new Date(`${date}T00:00:00`);
  const today = new Date();
  let age = today.getFullYear() - birth.getFullYear();
  if (today < new Date(today.getFullYear(), birth.getMonth(), birth.getDate())) age -= 1;
  return age;
};

export const AdminMembersMgmt: React.FC = () => {
  const [members, setMembers] = useState<MemberItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | MemberStatus>('all');
  const [modalMode, setModalMode] = useState<ModalMode>(null);
  const [selectedMember, setSelectedMember] = useState<MemberItem | null>(null);
  const [formData, setFormData] = useState<MemberFormData>(EMPTY_FORM);
  const [toast, setToast] = useState('');
  const [clanId, setClanId] = useState<string>('c9a59088-7ad7-4b21-8cba-19e2ea46d15a');

  const loadMembers = useCallback(async (targetClanId: string) => {
    setLoading(true);
    try {
      // First fetch clans if clanId is not set
      let effectiveClanId = targetClanId;
      try {
        const clansRes = await apiClient.get<any[]>('/admin/clans');
        if (Array.isArray(clansRes.data) && clansRes.data.length > 0) {
          effectiveClanId = clansRes.data[0].id || clansRes.data[0].clan_id;
          setClanId(effectiveClanId);
        }
      } catch {
        // Fall back to default DEV clan A
      }

      const persons = await fetchFamilyPersons(effectiveClanId);
      if (Array.isArray(persons)) {
        setMembers(
          persons.map((p) => ({
            id: p.id,
            full_name: p.fullName,
            gender: p.gender || 'other',
            birth_date: p.birthDate || undefined,
            is_alive: p.isLiving,
            branch: 'Chi chính',
            generation: p.generation || 1,
            relationship: p.generation === 1 ? 'Thủy tổ / Cụ tổ' : `Đời thứ ${p.generation}`,
            status: p.isLiving ? 'active' : 'hidden',
            avatar_url: p.avatarUrl || undefined,
          }))
        );
      }
    } catch (err: any) {
      console.error('Lỗi khi tải thành viên từ BE:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadMembers(clanId);
  }, [loadMembers, clanId]);

  useEffect(() => {
    if (!modalMode) return;
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') setModalMode(null); };
    document.addEventListener('keydown', closeOnEscape);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', closeOnEscape);
      document.body.style.overflow = '';
    };
  }, [modalMode]);

  const filteredMembers = useMemo(() => {
    const query = searchTerm.trim().toLocaleLowerCase('vi');
    return members.filter((member) => {
      const haystack = [member.full_name, member.other_name, member.branch, member.relationship, member.phone, member.email].filter(Boolean).join(' ').toLocaleLowerCase('vi');
      return (!query || haystack.includes(query)) && (statusFilter === 'all' || member.status === statusFilter);
    });
  }, [members, searchTerm, statusFilter]);

  const activeCount = members.filter((member) => member.status === 'active').length;
  const accountCount = members.filter((member) => member.has_account).length;
  const showToast = (message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(''), 3200);
  };

  const openAddModal = () => {
    setSelectedMember(null);
    setFormData({ ...EMPTY_FORM });
    setModalMode('add');
  };

  const openEditModal = (member: MemberItem) => {
    setSelectedMember(member);
    setFormData({
      full_name: member.full_name, other_name: member.other_name ?? '', gender: member.gender,
      birth_date: member.birth_date ?? '', is_alive: member.is_alive, branch: member.branch ?? '',
      generation: member.generation, relationship: member.relationship ?? '', status: member.status,
      avatar_url: member.avatar_url, phone: member.phone ?? '', email: member.email ?? '',
      has_account: member.has_account ?? false,
    });
    setModalMode('edit');
  };

  const saveMember = async (event: React.FormEvent) => {
    event.preventDefault();
    const cleanedName = formData.full_name.trim();
    if (!cleanedName) return;

    try {
      if (modalMode === 'edit' && selectedMember) {
        await updateFamilyPerson(clanId, selectedMember.id, {
          fullName: cleanedName,
          gender: formData.gender,
          birthDate: formData.birth_date || null,
          isLiving: formData.is_alive,
        });
        showToast(`Đã cập nhật thông tin của ${cleanedName} trên Backend.`);
      } else {
        await createFamilyPerson(clanId, {
          fullName: cleanedName,
          gender: formData.gender,
          birthDate: formData.birth_date || null,
          isLiving: formData.is_alive,
        });
        showToast(`Đã thêm ${cleanedName} vào gia phả thành công.`);
      }
      setModalMode(null);
      loadMembers(clanId);
    } catch (err: any) {
      showToast(`Lỗi: ${err?.response?.data?.detail || err.message}`);
    }
  };

  const toggleVisibility = async (member: MemberItem) => {
    const nextStatus: MemberStatus = member.status === 'hidden' ? 'active' : 'hidden';
    try {
      await updateFamilyPerson(clanId, member.id, {
        isLiving: nextStatus === 'active',
      });
      setMembers((current) => current.map((item) => item.id === member.id ? { ...item, status: nextStatus, is_alive: nextStatus === 'active' } : item));
      showToast(`${member.full_name} đã được ${nextStatus === 'hidden' ? 'ẩn khỏi danh sách' : 'khôi phục'}.`);
    } catch (err: any) {
      showToast(`Lỗi: ${err?.response?.data?.detail || err.message}`);
    }
  };

  const resetPassword = (member: MemberItem) => {
    if (!member.has_account) {
      showToast(`${member.full_name} chưa có tài khoản để đặt lại mật khẩu.`);
      return;
    }
    showToast(`Đã gửi hướng dẫn đặt lại mật khẩu cho ${member.full_name}.`);
  };

  return (
    <section className="family-members-page" aria-labelledby="family-members-title">
      <div className="family-members-breadcrumb" aria-label="Đường dẫn"><span>Quản lý gia phả</span><Icon name="chevron" size={14} /><strong>Nhân khẩu</strong></div>

      <header className="family-members-hero">
        <div>
          <span className="family-members-eyebrow"><Icon name="users" size={15} /> Family Admin</span>
          <h1 id="family-members-title">Quản lý Nhân khẩu</h1>
          <p>Quản lý hồ sơ, quan hệ và tài khoản của các thành viên trong dòng họ.</p>
        </div>
        <button type="button" className="family-primary-button" onClick={openAddModal}><Icon name="plus" size={19} />Thêm thành viên</button>
      </header>

      <div className="family-members-stats" aria-label="Thống kê nhân khẩu">
        <div><span>Tổng thành viên</span><strong>{members.length}</strong></div>
        <div><span>Đang hiển thị</span><strong>{activeCount}</strong></div>
        <div><span>Có tài khoản</span><strong>{accountCount}</strong></div>
      </div>

      <div className="family-members-panel">
        <div className="family-members-toolbar">
          <label className="family-search-field">
            <span className="sr-only">Tìm kiếm thành viên</span><Icon name="search" size={19} />
            <input type="search" value={searchTerm} onChange={(event) => setSearchTerm(event.target.value)} placeholder="Tìm theo họ tên, chi nhánh, quan hệ..." />
          </label>
          <div className="family-status-filter" role="group" aria-label="Lọc trạng thái">
            {([['all', 'Tất cả'], ['active', 'Đang hiển thị'], ['hidden', 'Đã ẩn']] as const).map(([value, label]) => (
              <button key={value} type="button" className={statusFilter === value ? 'active' : ''} aria-pressed={statusFilter === value} onClick={() => setStatusFilter(value)}>{label}</button>
            ))}
          </div>
        </div>

        <div className="family-table-heading">
          <div><h2>Danh sách thành viên</h2><p>{filteredMembers.length} kết quả phù hợp</p></div>
          <span className="family-live-dot"><i /> Dữ liệu gia phả</span>
        </div>

        <div className="family-table-wrap">
          <table className="family-members-table">
            <thead><tr><th>Thành viên</th><th>Ngày sinh</th><th>Đời / Chi</th><th>Quan hệ</th><th>Trạng thái</th><th className="family-actions-heading">Thao tác</th></tr></thead>
            <tbody>
              {loading && members.length === 0 ? (
                <tr><td colSpan={6} className="family-table-message">Đang tải danh sách thành viên...</td></tr>
              ) : filteredMembers.length === 0 ? (
                <tr><td colSpan={6} className="family-table-message">Không tìm thấy thành viên phù hợp.</td></tr>
              ) : filteredMembers.map((member) => {
                const age = getAge(member.birth_date);
                const initials = member.full_name.split(' ').slice(-2).map((word) => word[0]).join('').toUpperCase();
                return (
                  <tr key={member.id} className={member.status === 'hidden' ? 'is-hidden' : ''}>
                    <td data-label="Thành viên"><div className="family-member-cell"><div className={`family-member-avatar gender-${member.gender}`}>{member.avatar_url ? <img src={member.avatar_url} alt="" /> : initials}</div><div><strong>{member.full_name}</strong><span>{member.other_name || member.email || 'Chưa liên kết email'}</span></div></div></td>
                    <td data-label="Ngày sinh"><strong className="family-table-primary">{formatDate(member.birth_date)}</strong><span className="family-table-secondary">{age === null ? 'Chưa rõ tuổi' : `${age} tuổi`}</span></td>
                    <td data-label="Đời / Chi"><strong className="family-table-primary">Đời thứ {member.generation}</strong><span className="family-branch-badge">{member.branch || 'Chưa phân chi'}</span></td>
                    <td data-label="Quan hệ"><span className="family-relation-text">{member.relationship || 'Thành viên'}</span></td>
                    <td data-label="Trạng thái"><span className={`family-status-badge ${member.status}`}><i />{member.status === 'hidden' ? 'Đã ẩn' : 'Hiển thị'}</span><span className={`family-account-state ${member.has_account ? 'linked' : ''}`}>{member.has_account ? 'Có tài khoản' : 'Chưa có tài khoản'}</span></td>
                    <td data-label="Thao tác"><div className="family-row-actions">
                      <button type="button" onClick={() => { setSelectedMember(member); setModalMode('detail'); }} aria-label={`Xem chi tiết ${member.full_name}`} data-tooltip="Xem chi tiết"><Icon name="eye" /></button>
                      <button type="button" onClick={() => openEditModal(member)} aria-label={`Sửa ${member.full_name}`} data-tooltip="Sửa"><Icon name="edit" /></button>
                      <button type="button" className={member.status === 'hidden' ? 'restore' : 'danger'} onClick={() => toggleVisibility(member)} aria-label={`${member.status === 'hidden' ? 'Khôi phục' : 'Ẩn'} ${member.full_name}`} data-tooltip={member.status === 'hidden' ? 'Khôi phục' : 'Ẩn'}><Icon name={member.status === 'hidden' ? 'restore' : 'hide'} /></button>
                      <button type="button" className="key" onClick={() => resetPassword(member)} aria-label={`Reset mật khẩu ${member.full_name}`} data-tooltip="Reset mật khẩu"><Icon name="key" /></button>
                    </div></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {toast && <div className="family-members-toast" role="status"><span>✓</span>{toast}</div>}

      {(modalMode === 'add' || modalMode === 'edit') && (
        <div className="family-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setModalMode(null); }}>
          <div className="family-modal" role="dialog" aria-modal="true" aria-labelledby="member-form-title">
            <div className="family-modal-header"><div><span>{modalMode === 'edit' ? 'Cập nhật hồ sơ' : 'Thành viên mới'}</span><h2 id="member-form-title">{modalMode === 'edit' ? 'Chỉnh sửa thành viên' : 'Thêm mới thành viên'}</h2></div><button type="button" onClick={() => setModalMode(null)} aria-label="Đóng"><Icon name="close" /></button></div>
            <form onSubmit={saveMember} className="family-member-form">
              <div className="family-form-grid">
                <label className="family-field family-field-wide"><span>Họ và tên <b>*</b></span><input autoFocus required value={formData.full_name} onChange={(event) => setFormData({ ...formData, full_name: event.target.value })} placeholder="Ví dụ: Võ Văn An" /></label>
                <label className="family-field"><span>Ngày sinh</span><input type="date" value={formData.birth_date} onChange={(event) => setFormData({ ...formData, birth_date: event.target.value })} /></label>
                <label className="family-field"><span>Giới tính</span><select value={formData.gender} onChange={(event) => setFormData({ ...formData, gender: event.target.value })}><option value="male">Nam</option><option value="female">Nữ</option><option value="other">Khác</option></select></label>
                <label className="family-field"><span>Quan hệ với chủ hộ <b>*</b></span><select required value={formData.relationship} onChange={(event) => setFormData({ ...formData, relationship: event.target.value })}><option value="">Chọn quan hệ</option><option value="Vợ / Chồng">Vợ / Chồng</option><option value="Con trai">Con trai</option><option value="Con gái">Con gái</option><option value="Con dâu">Con dâu</option><option value="Con rể">Con rể</option><option value="Anh / Chị / Em">Anh / Chị / Em</option><option value="Cháu">Cháu</option><option value="Thành viên khác">Thành viên khác</option></select></label>
                <label className="family-field"><span>Chi nhánh</span><select value={formData.branch} onChange={(event) => setFormData({ ...formData, branch: event.target.value })}><option>Chi Trưởng</option><option>Chi Hai</option><option>Chi Ba</option><option>Chưa phân chi</option></select></label>
                <label className="family-field"><span>Đời thứ</span><input type="number" min="1" max="30" value={formData.generation} onChange={(event) => setFormData({ ...formData, generation: Number(event.target.value) || 1 })} /></label>
                <label className="family-field"><span>Số điện thoại</span><input type="tel" value={formData.phone} onChange={(event) => setFormData({ ...formData, phone: event.target.value })} placeholder="090 000 0000" /></label>
                <label className="family-field family-field-wide"><span>Email tài khoản</span><input type="email" value={formData.email} onChange={(event) => setFormData({ ...formData, email: event.target.value, has_account: Boolean(event.target.value) })} placeholder="thanhvien@example.com" /><small>Để trống nếu thành viên chưa cần tài khoản đăng nhập.</small></label>
              </div>
              <div className="family-modal-footer"><button type="button" className="family-secondary-button" onClick={() => setModalMode(null)}>Hủy</button><button type="submit" className="family-primary-button"><Icon name={modalMode === 'edit' ? 'edit' : 'plus'} />{modalMode === 'edit' ? 'Lưu thay đổi' : 'Thêm thành viên'}</button></div>
            </form>
          </div>
        </div>
      )}

      {modalMode === 'detail' && selectedMember && (
        <div className="family-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setModalMode(null); }}>
          <div className="family-modal family-detail-modal" role="dialog" aria-modal="true" aria-labelledby="member-detail-title">
            <div className="family-modal-header"><div><span>Hồ sơ nhân khẩu</span><h2 id="member-detail-title">Chi tiết thành viên</h2></div><button type="button" onClick={() => setModalMode(null)} aria-label="Đóng"><Icon name="close" /></button></div>
            <div className="family-detail-profile"><div className={`family-member-avatar gender-${selectedMember.gender}`}>{selectedMember.full_name.split(' ').slice(-2).map((word) => word[0]).join('').toUpperCase()}</div><div><h3>{selectedMember.full_name}</h3><p>{selectedMember.other_name || selectedMember.relationship}</p></div></div>
            <dl className="family-detail-grid">
              <div><dt>Ngày sinh</dt><dd>{formatDate(selectedMember.birth_date)}</dd></div><div><dt>Giới tính</dt><dd>{selectedMember.gender === 'male' ? 'Nam' : selectedMember.gender === 'female' ? 'Nữ' : 'Khác'}</dd></div><div><dt>Thế hệ</dt><dd>Đời thứ {selectedMember.generation}</dd></div><div><dt>Chi nhánh</dt><dd>{selectedMember.branch || 'Chưa phân chi'}</dd></div><div><dt>Quan hệ</dt><dd>{selectedMember.relationship || 'Thành viên'}</dd></div><div><dt>Điện thoại</dt><dd>{selectedMember.phone || 'Chưa cập nhật'}</dd></div><div className="wide"><dt>Email</dt><dd>{selectedMember.email || 'Chưa liên kết tài khoản'}</dd></div>
            </dl>
            <div className="family-modal-footer"><button type="button" className="family-secondary-button" onClick={() => setModalMode(null)}>Đóng</button><button type="button" className="family-primary-button" onClick={() => openEditModal(selectedMember)}><Icon name="edit" />Chỉnh sửa</button></div>
          </div>
        </div>
      )}
    </section>
  );
};

export default AdminMembersMgmt;
