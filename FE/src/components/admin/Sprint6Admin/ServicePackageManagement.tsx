import React, { useEffect, useMemo, useState } from 'react';
import {
  initialServicePackages,
  type ServicePackage,
  type ServicePackageStatus,
} from './mockData';
import {
  AdminConfirmDialog,
  AdminModal,
  AdminPageHeader,
  AdminPagination,
  AdminStatePanel,
  AdminStatusBadge,
  AdminToast,
  formatAdminDate,
  formatVnd,
  useAdminToast,
} from './shared';
import './Sprint6Admin.css';

const PAGE_SIZE = 4;

interface PackageFormState {
  code: string;
  name: string;
  description: string;
  monthlyPrice: string;
  durationMonths: string;
  memberLimit: string;
  storageGb: string;
  features: string;
  status: ServicePackageStatus;
}

const emptyPackageForm: PackageFormState = {
  code: '',
  name: '',
  description: '',
  monthlyPrice: '',
  durationMonths: '12',
  memberLimit: '500',
  storageGb: '20',
  features: '',
  status: 'draft',
};

function packageToForm(item: ServicePackage): PackageFormState {
  return {
    code: item.code,
    name: item.name,
    description: item.description,
    monthlyPrice: String(item.monthlyPrice),
    durationMonths: String(item.durationMonths),
    memberLimit: String(item.memberLimit),
    storageGb: String(item.storageGb),
    features: item.features.join('\n'),
    status: item.status,
  };
}

import apiClient from '../../../api/axios';

export const ServicePackageManagement: React.FC = () => {
  const [packages, setPackages] = useState<ServicePackage[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | ServicePackageStatus>('all');
  const [page, setPage] = useState(1);
  const [detailPackage, setDetailPackage] = useState<ServicePackage | null>(null);
  const [editorMode, setEditorMode] = useState<'create' | 'edit' | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<PackageFormState>(emptyPackageForm);
  const [formError, setFormError] = useState('');
  const [confirmPackage, setConfirmPackage] = useState<ServicePackage | null>(null);
  const { toast, showToast, dismissToast } = useAdminToast();

  useEffect(() => {
    setLoading(true);
    apiClient.get<any>('/service-plans')
      .then((res) => {
        const items = Array.isArray(res.data?.items) ? res.data.items : Array.isArray(res.data) ? res.data : [];
        const mapped: ServicePackage[] = items.map((p: any) => ({
          id: p.id || p.plan_id,
          code: p.code || p.plan_code || 'PLAN',
          name: p.name || 'Gói dịch vụ',
          description: p.description || '',
          monthlyPrice: p.price_cents ? p.price_cents / 100 : p.monthly_price || 0,
          durationMonths: p.duration_months || 12,
          memberLimit: p.member_limit || 500,
          storageGb: p.storage_gb || 20,
          subscriberCount: p.subscriber_count || 0,
          features: Array.isArray(p.features) ? p.features : ['Cây gia phả', 'Hồ sơ thành viên'],
          status: (p.status || 'active').toLowerCase(),
          updatedAt: p.updated_at ? p.updated_at.slice(0, 10) : new Date().toISOString().slice(0, 10),
        }));
        setPackages(mapped);
      })
      .catch(() => setPackages([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => setPage(1), [searchQuery, statusFilter]);

  const filteredPackages = useMemo(() => {
    const needle = searchQuery.trim().toLowerCase();
    return packages.filter((item) => {
      const matchesSearch = !needle || [item.name, item.code, item.description]
        .some((value) => value.toLowerCase().includes(needle));
      const matchesStatus = statusFilter === 'all' || item.status === statusFilter;
      return matchesSearch && matchesStatus;
    });
  }, [packages, searchQuery, statusFilter]);

  const pageCount = Math.max(1, Math.ceil(filteredPackages.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount);
  const visiblePackages = filteredPackages.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);
  const activeSubscribers = packages
    .filter((item) => item.status === 'active')
    .reduce((sum, item) => sum + item.subscriberCount, 0);

  const openCreate = () => {
    setEditingId(null);
    setForm({ ...emptyPackageForm });
    setFormError('');
    setEditorMode('create');
  };

  const openEdit = (item: ServicePackage) => {
    setEditingId(item.id);
    setForm(packageToForm(item));
    setFormError('');
    setEditorMode('edit');
    setDetailPackage(null);
  };

  const closeEditor = () => {
    setEditorMode(null);
    setEditingId(null);
    setFormError('');
  };

  const updateForm = <K extends keyof PackageFormState>(key: K, value: PackageFormState[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const handleSave = (event: React.FormEvent) => {
    event.preventDefault();
    const code = form.code.trim().toUpperCase().replace(/\s+/g, '-');
    const features = form.features.split('\n').map((item) => item.trim()).filter(Boolean);
    const price = Number(form.monthlyPrice);
    const duration = Number(form.durationMonths);
    const memberLimit = Number(form.memberLimit);
    const storage = Number(form.storageGb);

    if (!form.name.trim() || !code || !form.description.trim()) {
      setFormError('Vui lòng nhập đầy đủ tên, mã và mô tả gói dịch vụ.');
      return;
    }
    if ([price, duration, memberLimit, storage].some((value) => Number.isNaN(value) || value < 0)) {
      setFormError('Giá, thời hạn, giới hạn thành viên và dung lượng phải là số hợp lệ.');
      return;
    }
    if (features.length === 0) {
      setFormError('Gói dịch vụ cần có ít nhất một tính năng.');
      return;
    }
    if (packages.some((item) => item.code === code && item.id !== editingId)) {
      setFormError(`Mã gói ${code} đã tồn tại.`);
      return;
    }

    const nextPackage: ServicePackage = {
      id: editingId || `pkg-${Date.now()}`,
      code,
      name: form.name.trim(),
      description: form.description.trim(),
      monthlyPrice: price,
      durationMonths: duration,
      memberLimit,
      storageGb: storage,
      subscriberCount: editingId ? packages.find((item) => item.id === editingId)?.subscriberCount || 0 : 0,
      features,
      status: form.status,
      updatedAt: new Date().toISOString().slice(0, 10),
    };

    if (editingId) {
      setPackages((current) => current.map((item) => item.id === editingId ? nextPackage : item));
      showToast(`Đã cập nhật gói “${nextPackage.name}”.`);
    } else {
      setPackages((current) => [nextPackage, ...current]);
      showToast(`Đã tạo gói “${nextPackage.name}” ở trạng thái ${nextPackage.status === 'draft' ? 'bản nháp' : 'hoạt động'}.`);
    }
    closeEditor();
  };

  const handleToggleStatus = () => {
    if (!confirmPackage) return;
    const nextStatus: ServicePackageStatus = confirmPackage.status === 'active' ? 'disabled' : 'active';
    setPackages((current) => current.map((item) => item.id === confirmPackage.id
      ? { ...item, status: nextStatus, updatedAt: new Date().toISOString().slice(0, 10) }
      : item));
    showToast(nextStatus === 'active'
      ? `Đã bật gói “${confirmPackage.name}”.`
      : `Đã tắt gói “${confirmPackage.name}”.`, nextStatus === 'active' ? 'success' : 'info');
    setConfirmPackage(null);
  };

  return (
    <section className="s6a-page">
      <AdminToast toast={toast} onDismiss={dismissToast} />
      <AdminPageHeader
        eyebrow="QUẢN TRỊ NỀN TẢNG"
        title="Quản lý Gói Dịch vụ"
        description="Tạo, cấu hình và kiểm soát vòng đời các gói dịch vụ dành cho từng quy mô dòng họ."
        actions={<button type="button" className="s6a-button primary" onClick={openCreate}>+ Tạo gói mới</button>}
      />

      <div className="s6a-metric-grid three">
        <article className="s6a-metric-card">
          <span>Gói đang hoạt động</span>
          <strong>{packages.filter((item) => item.status === 'active').length}</strong>
          <small>Trên tổng số {packages.length} gói</small>
        </article>
        <article className="s6a-metric-card">
          <span>Thuê bao đang sử dụng</span>
          <strong>{activeSubscribers.toLocaleString('vi-VN')}</strong>
          <small>Thuộc các gói đang mở</small>
        </article>
        <article className="s6a-metric-card">
          <span>Doanh thu niêm yết/tháng</span>
          <strong>{formatVnd(packages.filter((item) => item.status === 'active').reduce((sum, item) => sum + item.monthlyPrice * item.subscriberCount, 0))}</strong>
          <small>Số liệu demo, chưa đối soát</small>
        </article>
      </div>

      <div className="s6a-content-card">
        <div className="s6a-card-heading">
          <div>
            <h2>Danh sách gói</h2>
            <p>Quản lý giá, thời hạn, giới hạn và trạng thái đăng ký.</p>
          </div>
          <span className="s6a-count-pill">{filteredPackages.length} kết quả</span>
        </div>

        <div className="s6a-filter-bar">
          <label className="s6a-search-field">
            <span className="s6a-visually-hidden">Tìm kiếm gói dịch vụ</span>
            <input
              type="search"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="Tìm theo tên, mã hoặc mô tả..."
            />
          </label>
          <label>
            <span>Trạng thái</span>
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as 'all' | ServicePackageStatus)}>
              <option value="all">Tất cả trạng thái</option>
              <option value="active">Đang hoạt động</option>
              <option value="draft">Bản nháp</option>
              <option value="disabled">Đã tắt</option>
            </select>
          </label>
          {(searchQuery || statusFilter !== 'all') && (
            <button type="button" className="s6a-button ghost" onClick={() => { setSearchQuery(''); setStatusFilter('all'); }}>
              Xóa bộ lọc
            </button>
          )}
        </div>

        {loading ? (
          <AdminStatePanel kind="loading" message="Đang tải cấu hình gói dịch vụ..." />
        ) : visiblePackages.length === 0 ? (
          <AdminStatePanel
            kind="empty"
            title="Không tìm thấy gói phù hợp"
            message="Thử thay đổi từ khóa hoặc bộ lọc trạng thái."
            action={<button type="button" className="s6a-button secondary" onClick={() => { setSearchQuery(''); setStatusFilter('all'); }}>Đặt lại bộ lọc</button>}
          />
        ) : (
          <>
            <div className="s6a-table-wrap">
              <table className="s6a-table">
                <thead>
                  <tr>
                    <th>Gói dịch vụ</th>
                    <th>Giá / thời hạn</th>
                    <th>Giới hạn</th>
                    <th>Thuê bao</th>
                    <th>Trạng thái</th>
                    <th className="s6a-actions-column">Thao tác</th>
                  </tr>
                </thead>
                <tbody>
                  {visiblePackages.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <div className="s6a-primary-cell">
                          <strong>{item.name}</strong>
                          <span>{item.code} · Cập nhật {formatAdminDate(item.updatedAt)}</span>
                        </div>
                      </td>
                      <td>
                        <div className="s6a-primary-cell compact">
                          <strong>{item.monthlyPrice === 0 ? 'Miễn phí' : formatVnd(item.monthlyPrice)}</strong>
                          <span>{item.durationMonths} tháng</span>
                        </div>
                      </td>
                      <td>{item.memberLimit.toLocaleString('vi-VN')} thành viên<br /><span className="s6a-muted">{item.storageGb} GB</span></td>
                      <td><strong>{item.subscriberCount.toLocaleString('vi-VN')}</strong></td>
                      <td><AdminStatusBadge status={item.status} /></td>
                      <td>
                        <div className="s6a-row-actions">
                          <button type="button" className="s6a-link-button" onClick={() => setDetailPackage(item)}>Chi tiết</button>
                          <button type="button" className="s6a-link-button" onClick={() => openEdit(item)}>Sửa</button>
                          <button
                            type="button"
                            className={`s6a-link-button ${item.status === 'active' ? 'danger-text' : 'success-text'}`}
                            onClick={() => setConfirmPackage(item)}
                          >
                            {item.status === 'active' ? 'Tắt' : 'Bật'}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <AdminPagination page={safePage} totalItems={filteredPackages.length} pageSize={PAGE_SIZE} onPageChange={setPage} />
          </>
        )}
      </div>

      <AdminModal
        open={Boolean(detailPackage)}
        title={detailPackage?.name || 'Chi tiết gói dịch vụ'}
        description={detailPackage ? `Mã gói ${detailPackage.code}` : undefined}
        onClose={() => setDetailPackage(null)}
        size="lg"
        footer={detailPackage && (
          <>
            <button type="button" className="s6a-button secondary" onClick={() => setDetailPackage(null)}>Đóng</button>
            <button type="button" className="s6a-button primary" onClick={() => openEdit(detailPackage)}>Chỉnh sửa gói</button>
          </>
        )}
      >
        {detailPackage && (
          <div className="s6a-detail-layout">
            <div className="s6a-detail-grid">
              <div><span>Trạng thái</span><AdminStatusBadge status={detailPackage.status} /></div>
              <div><span>Giá hàng tháng</span><strong>{detailPackage.monthlyPrice === 0 ? 'Miễn phí' : formatVnd(detailPackage.monthlyPrice)}</strong></div>
              <div><span>Thời hạn</span><strong>{detailPackage.durationMonths} tháng</strong></div>
              <div><span>Số thuê bao</span><strong>{detailPackage.subscriberCount.toLocaleString('vi-VN')}</strong></div>
              <div><span>Giới hạn thành viên</span><strong>{detailPackage.memberLimit.toLocaleString('vi-VN')}</strong></div>
              <div><span>Dung lượng</span><strong>{detailPackage.storageGb} GB</strong></div>
            </div>
            <div className="s6a-detail-section">
              <h3>Mô tả</h3>
              <p>{detailPackage.description}</p>
            </div>
            <div className="s6a-detail-section">
              <h3>Tính năng bao gồm</h3>
              <ul className="s6a-feature-list">{detailPackage.features.map((feature) => <li key={feature}>{feature}</li>)}</ul>
            </div>
          </div>
        )}
      </AdminModal>

      <AdminModal
        open={Boolean(editorMode)}
        title={editorMode === 'edit' ? 'Chỉnh sửa Gói Dịch vụ' : 'Tạo Gói Dịch vụ'}
        description="Các trường có dấu * là bắt buộc. Thay đổi chỉ được mô phỏng ở giao diện."
        onClose={closeEditor}
        size="lg"
        footer={
          <>
            <button type="button" className="s6a-button secondary" onClick={closeEditor}>Hủy</button>
            <button type="submit" form="s6a-package-form" className="s6a-button primary" disabled={!form.name.trim() || !form.code.trim()}>
              {editorMode === 'edit' ? 'Lưu thay đổi' : 'Tạo gói'}
            </button>
          </>
        }
      >
        <form id="s6a-package-form" className="s6a-form" onSubmit={handleSave}>
          {formError && <div className="s6a-inline-alert error" role="alert">{formError}</div>}
          <div className="s6a-form-grid two">
            <label><span>Tên gói <b>*</b></span><input value={form.name} onChange={(event) => updateForm('name', event.target.value)} placeholder="Ví dụ: Dòng họ Tiêu chuẩn" /></label>
            <label><span>Mã gói <b>*</b></span><input value={form.code} onChange={(event) => updateForm('code', event.target.value)} placeholder="STANDARD" /></label>
            <label><span>Giá mỗi tháng (VNĐ)</span><input type="number" min="0" value={form.monthlyPrice} onChange={(event) => updateForm('monthlyPrice', event.target.value)} /></label>
            <label><span>Thời hạn (tháng)</span><input type="number" min="1" value={form.durationMonths} onChange={(event) => updateForm('durationMonths', event.target.value)} /></label>
            <label><span>Giới hạn thành viên</span><input type="number" min="1" value={form.memberLimit} onChange={(event) => updateForm('memberLimit', event.target.value)} /></label>
            <label><span>Dung lượng lưu trữ (GB)</span><input type="number" min="1" value={form.storageGb} onChange={(event) => updateForm('storageGb', event.target.value)} /></label>
            <label className="span-two"><span>Trạng thái</span><select value={form.status} onChange={(event) => updateForm('status', event.target.value as ServicePackageStatus)}><option value="draft">Bản nháp</option><option value="active">Đang hoạt động</option><option value="disabled">Đã tắt</option></select></label>
            <label className="span-two"><span>Mô tả <b>*</b></span><textarea rows={3} value={form.description} onChange={(event) => updateForm('description', event.target.value)} placeholder="Mục đích và đối tượng sử dụng gói..." /></label>
            <label className="span-two"><span>Tính năng — mỗi dòng một mục <b>*</b></span><textarea rows={5} value={form.features} onChange={(event) => updateForm('features', event.target.value)} placeholder={'Cây gia phả đa chế độ\nKho tư liệu số\nNhắc lịch tự động'} /></label>
          </div>
        </form>
      </AdminModal>

      <AdminConfirmDialog
        open={Boolean(confirmPackage)}
        title={confirmPackage?.status === 'active' ? 'Tắt Gói Dịch vụ?' : 'Bật Gói Dịch vụ?'}
        message={confirmPackage?.status === 'active'
          ? `Gói “${confirmPackage?.name}” sẽ không nhận đăng ký mới. Thuê bao hiện hữu vẫn được giữ nguyên trong bản demo.`
          : `Gói “${confirmPackage?.name}” sẽ xuất hiện trong danh sách có thể đăng ký.`}
        confirmLabel={confirmPackage?.status === 'active' ? 'Tắt gói' : 'Bật gói'}
        tone={confirmPackage?.status === 'active' ? 'danger' : 'primary'}
        onCancel={() => setConfirmPackage(null)}
        onConfirm={handleToggleStatus}
      />
    </section>
  );
};

export default ServicePackageManagement;
