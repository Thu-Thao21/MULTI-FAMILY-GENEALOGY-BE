import React, { useEffect, useState, useCallback } from 'react';
import {
  fetchAdminRegistrations,
  fetchAdminRegistrationDetail,
  reviewAdminRegistration,
  approveAndProvisionRegistration,
  type AdminRegistrationSummary,
  type AdminRegistrationDetail,
  type ApproveAndProvisionResponse,
} from '../../../services/admin.service';
import {
  AdminConfirmDialog,
  AdminModal,
  AdminPageHeader,
  AdminPagination,
  AdminStatePanel,
  AdminStatusBadge,
  AdminToast,
  useAdminToast,
} from '../Sprint6Admin/shared';
import '../Sprint6Admin/Sprint6Admin.css';

const PAGE_SIZE = 6;
const statusLabels: Record<string, string> = {
  PENDING: 'Chờ duyệt',
  APPROVED: 'Đã duyệt',
  REJECTED: 'Từ chối',
  NEED_SUPPLEMENT: 'Cần bổ sung',
  DRAFT: 'Bản nháp',
  CANCELLED: 'Đã hủy',
};

export const AdminApprovalsMgmt: React.FC = () => {
  const [registrations, setRegistrations] = useState<AdminRegistrationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<string>('PENDING');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);

  const [selectedDetail, setSelectedDetail] = useState<AdminRegistrationDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const [approveTarget, setApproveTarget] = useState<AdminRegistrationSummary | null>(null);
  const [provisionResult, setProvisionResult] = useState<ApproveAndProvisionResponse | null>(null);
  const [copiedPassword, setCopiedPassword] = useState(false);
  const [copiedEmail, setCopiedEmail] = useState(false);
  const [rejectTarget, setRejectTarget] = useState<AdminRegistrationSummary | null>(null);
  const [rejectNote, setRejectNote] = useState('');
  const [formError, setFormError] = useState('');
  const { toast, showToast, dismissToast } = useAdminToast();

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchAdminRegistrations({
        q: search.trim() || undefined,
        status: status === 'all' ? undefined : status,
        page,
        page_size: PAGE_SIZE,
      });
      setRegistrations(res.items || []);
      setTotal(res.total || 0);
    } catch (err: any) {
      console.error('Lỗi tải danh sách phê duyệt:', err);
      showToast('Không thể tải danh sách hồ sơ từ máy chủ.');
    } finally {
      setLoading(false);
    }
  }, [search, status, page, showToast]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const openDetail = async (reg: AdminRegistrationSummary) => {
    setLoadingDetail(true);
    try {
      const detail = await fetchAdminRegistrationDetail(reg.registration_id);
      setSelectedDetail(detail);
    } catch {
      showToast('Không thể tải chi tiết hồ sơ.');
    } finally {
      setLoadingDetail(false);
    }
  };

  const handleApprove = async (reg: AdminRegistrationSummary) => {
    try {
      const res = await approveAndProvisionRegistration(reg.registration_id);
      setProvisionResult(res);
      showToast(res.message || `Đã phê duyệt và cấp tài khoản cho dòng họ "${res.clan_name}"!`);
      setApproveTarget(null);
      if (selectedDetail?.registration_id === reg.registration_id) setSelectedDetail(null);
      loadData();
    } catch (err: any) {
      showToast(`Lỗi khi duyệt hồ sơ: ${err?.response?.data?.message || err.message}`);
    }
  };


  const submitReject = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!rejectTarget) return;
    if (rejectNote.trim().length < 5) {
      setFormError('Lý do từ chối cần có tối thiểu 5 ký tự.');
      return;
    }
    try {
      await reviewAdminRegistration(rejectTarget.registration_id, 'REJECTED', rejectNote.trim());
      showToast(`Đã từ chối hồ sơ "${rejectTarget.clan_name}".`);
      setRejectTarget(null);
      setRejectNote('');
      setFormError('');
      if (selectedDetail?.registration_id === rejectTarget.registration_id) setSelectedDetail(null);
      loadData();
    } catch (err: any) {
      showToast(`Lỗi khi từ chối hồ sơ: ${err?.response?.data?.message || err.message}`);
    }
  };

  const pendingCount = status === 'PENDING' ? total : 0;

  return (
    <section className="s6a-page">
      <AdminPageHeader
        eyebrow="PHÊ DUYỆT DOANH NGHIỆP / TỔ CHỨC"
        title="Trung tâm thẩm định & duyệt hồ sơ"
        description="Xem xét hồ sơ đăng ký dòng họ doanh nghiệp, phê duyệt kích hoạt tài khoản hoặc phản hồi lý do từ chối."
        actions={
          <button type="button" className="s6a-button secondary" onClick={() => setStatus('PENDING')}>
            Hồ sơ chờ duyệt ({pendingCount})
          </button>
        }
      />

      <div className="s6a-card">
        <div className="s6a-card-heading">
          <div>
            <h2>Danh sách hồ sơ đăng ký doanh nghiệp</h2>
            <p>Dữ liệu đồng bộ trực tiếp từ cổng đăng ký tổ chức dòng họ.</p>
          </div>
          <span className="s6a-count-pill">{total} kết quả</span>
        </div>

        <div className="s6a-filter-bar s6a-filter-grid">
          <label className="s6a-search-field wide">
            <span>Tìm kiếm</span>
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Tên dòng họ, người đại diện..."
            />
          </label>
          <label>
            <span>Trạng thái</span>
            <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
              <option value="all">Tất cả</option>
              <option value="PENDING">Chờ duyệt</option>
              <option value="APPROVED">Đã duyệt</option>
              <option value="REJECTED">Đã từ chối</option>
            </select>
          </label>
          <button
            type="button"
            className="s6a-button ghost align-end"
            onClick={() => { setSearch(''); setStatus('all'); setPage(1); }}
          >
            Đặt lại
          </button>
        </div>

        {loading ? (
          <AdminStatePanel kind="loading" message="Đang kết nối Backend để tải danh sách hồ sơ..." />
        ) : !registrations.length ? (
          <AdminStatePanel
            kind="empty"
            title="Không có hồ sơ nào"
            message="Chưa có yêu cầu đăng ký nào phù hợp với bộ lọc hiện tại."
          />
        ) : (
          <>
            <div className="s6a-table-wrap">
              <table className="s6a-table">
                <thead>
                  <tr>
                    <th>Mã / Dòng họ</th>
                    <th>Người đại diện</th>
                    <th>Gói dịch vụ</th>
                    <th>Ngày nộp</th>
                    <th>Trạng thái</th>
                    <th>Thao tác</th>
                  </tr>
                </thead>
                <tbody>
                  {registrations.map((item) => (
                    <tr key={item.registration_id}>
                      <td>
                        <button type="button" className="s6a-table-id" onClick={() => openDetail(item)}>
                          {item.registration_id.slice(0, 8)}...
                        </button>
                        <span className="s6a-table-subline">{item.clan_name}</span>
                      </td>
                      <td>
                        <strong>{item.representative_name}</strong>
                      </td>
                      <td>
                        <span className="s6a-table-main">{item.requested_plan_code}</span>
                      </td>
                      <td>{new Date(item.created_at).toLocaleDateString('vi-VN')}</td>
                      <td>
                        <AdminStatusBadge
                          status={item.status.toLowerCase() as any}
                          label={statusLabels[item.status] || item.status}
                        />
                      </td>
                      <td>
                        <div className="s6a-inline-actions">
                          <button
                            type="button"
                            className="s6a-link-button"
                            onClick={() => openDetail(item)}
                          >
                            Chi tiết
                          </button>
                          {item.status === 'PENDING' && (
                            <>
                              <button
                                type="button"
                                className="s6a-link-button success-text"
                                onClick={() => setApproveTarget(item)}
                              >
                                Duyệt
                              </button>
                              <button
                                type="button"
                                className="s6a-link-button danger-text"
                                onClick={() => {
                                  setRejectTarget(item);
                                  setRejectNote('');
                                  setFormError('');
                                }}
                              >
                                Từ chối
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <AdminPagination
              page={page}
              totalItems={total}
              pageSize={PAGE_SIZE}
              onPageChange={setPage}
            />
          </>
        )}
      </div>

      {/* Detail Modal */}
      <AdminModal
        open={Boolean(selectedDetail)}
        title={selectedDetail ? `Hồ sơ: ${selectedDetail.clan_name}` : ''}
        description="Thông tin chi tiết hồ sơ đăng ký doanh nghiệp và người đại diện."
        onClose={() => setSelectedDetail(null)}
        size="lg"
        footer={
          selectedDetail && (
            <>
              <button
                type="button"
                className="s6a-button secondary"
                onClick={() => setSelectedDetail(null)}
              >
                Đóng
              </button>
              {selectedDetail.status === 'PENDING' && (
                <>
                  <button
                    type="button"
                    className="s6a-button danger"
                    onClick={() => {
                      setRejectTarget(selectedDetail);
                      setRejectNote('');
                    }}
                  >
                    Từ chối
                  </button>
                  <button
                    type="button"
                    className="s6a-button primary"
                    onClick={() => setApproveTarget(selectedDetail)}
                  >
                    Phê duyệt
                  </button>
                </>
              )}
            </>
          )
        }
      >
        {selectedDetail && (
          <div className="s6a-detail-grid">
            <div>
              <span>Người đại diện</span>
              <strong>{selectedDetail.representative_name}</strong>
            </div>
            <div>
              <span>Email liên hệ</span>
              <strong>{selectedDetail.representative_email}</strong>
            </div>
            <div>
              <span>Số điện thoại</span>
              <strong>{selectedDetail.representative_phone || '—'}</strong>
            </div>
            <div>
              <span>Quê quán / Gốc họ</span>
              <strong>{selectedDetail.origin_place || '—'}</strong>
            </div>
            <div>
              <span>Gói đăng ký</span>
              <strong>{selectedDetail.requested_plan_code}</strong>
            </div>
            <div>
              <span>Ngày gửi</span>
              <strong>{new Date(selectedDetail.created_at).toLocaleString('vi-VN')}</strong>
            </div>
            {selectedDetail.rejection_reason && (
              <div className="wide">
                <span>Lý do từ chối</span>
                <p>{selectedDetail.rejection_reason}</p>
              </div>
            )}
          </div>
        )}
      </AdminModal>

      {/* Approve Confirm Dialog */}
      <AdminConfirmDialog
        open={Boolean(approveTarget)}
        title="Xác nhận phê duyệt hồ sơ?"
        message={
          approveTarget
            ? `Hồ sơ "${approveTarget.clan_name}" sẽ được chấp thuận, tự động tạo không gian dòng họ và cấp tài khoản Trưởng tộc gửi về email đại diện.`
            : ''
        }
        confirmLabel="Xác nhận phê duyệt"
        onCancel={() => setApproveTarget(null)}
        onConfirm={() => approveTarget && handleApprove(approveTarget)}
      />

      {/* Success Provision Modal with Credentials and Email Status */}
      <AdminModal
        open={Boolean(provisionResult)}
        title="Phê Duyệt & Cấp Tài Khoản Trưởng Tộc Thành Công"
        description="Thông tin tài khoản Quản trị không gian dòng họ đã được khởi tạo."
        onClose={() => setProvisionResult(null)}
        size="md"
        footer={
          <button
            type="button"
            className="s6a-button primary"
            onClick={() => setProvisionResult(null)}
          >
            Hoàn tất & Đóng
          </button>
        }
      >
        {provisionResult && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{
              padding: '12px 16px',
              borderRadius: '8px',
              backgroundColor: provisionResult.email_sent ? '#f0fdf4' : '#fffbeb',
              border: `1px solid ${provisionResult.email_sent ? '#bbf7d0' : '#fde68a'}`,
              color: provisionResult.email_sent ? '#166534' : '#92400e',
              fontSize: '14px',
              lineHeight: 1.5,
            }}>
              <strong>{provisionResult.email_sent ? '✅ Đã gửi email thông tin tài khoản thành công!' : '⚠️ Thông báo email:'}</strong>
              <div style={{ marginTop: '4px' }}>{provisionResult.message}</div>
            </div>

            <div style={{
              background: '#f8fafc',
              border: '1px solid #e2e8f0',
              borderRadius: '8px',
              padding: '16px',
              display: 'flex',
              flexDirection: 'column',
              gap: '12px',
              fontSize: '14px',
            }}>
              <div>
                <span style={{ color: '#64748b' }}>Dòng họ: </span>
                <strong style={{ color: '#0f172a' }}>{provisionResult.clan_name}</strong>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>Trưởng tộc (Người đại diện): </span>
                <strong style={{ color: '#0f172a' }}>{provisionResult.owner_display_name}</strong>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>Tài khoản Trưởng tộc (Hệ thống cấp): </span>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '4px' }}>
                  <code style={{
                    flex: 1,
                    padding: '8px 12px',
                    background: '#ffffff',
                    border: '1px solid #cbd5e1',
                    borderRadius: '6px',
                    fontSize: '15px',
                    fontWeight: 600,
                    color: '#0284c7',
                  }}>
                    {provisionResult.owner_email}
                  </code>
                  <button
                    type="button"
                    className="s6a-button secondary"
                    style={{ padding: '8px 16px', whiteSpace: 'nowrap' }}
                    onClick={() => {
                      navigator.clipboard.writeText(provisionResult.owner_email);
                      setCopiedEmail(true);
                      setTimeout(() => setCopiedEmail(false), 2000);
                    }}
                  >
                    {copiedEmail ? '✓ Đã sao chép' : 'Sao chép'}
                  </button>
                </div>
              </div>

              {provisionResult.temporary_password && (
                <div style={{ marginTop: '8px', paddingTop: '12px', borderTop: '1px dashed #cbd5e1' }}>
                  <label style={{ display: 'block', fontSize: '13px', color: '#64748b', marginBottom: '6px' }}>
                    Mật khẩu tạm thời (chỉ hiển thị một lần):
                  </label>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <code style={{
                      flex: 1,
                      padding: '8px 12px',
                      background: '#ffffff',
                      border: '1px solid #cbd5e1',
                      borderRadius: '6px',
                      fontSize: '16px',
                      fontFamily: 'Consolas, monospace',
                      fontWeight: 'bold',
                      color: '#dc2626',
                      letterSpacing: '1px',
                    }}>
                      {provisionResult.temporary_password}
                    </code>
                    <button
                      type="button"
                      className="s6a-button secondary"
                      style={{ padding: '8px 16px', whiteSpace: 'nowrap' }}
                      onClick={() => {
                        if (provisionResult.temporary_password) {
                          navigator.clipboard.writeText(provisionResult.temporary_password);
                          setCopiedPassword(true);
                          setTimeout(() => setCopiedPassword(false), 2000);
                        }
                      }}
                    >
                      {copiedPassword ? '✓ Đã sao chép' : 'Sao chép'}
                    </button>
                  </div>
                  <small style={{ display: 'block', marginTop: '6px', color: '#b45309', fontSize: '12px' }}>
                    * Mật khẩu có hiệu lực 72 giờ. Trưởng tộc sẽ được yêu cầu đổi mật khẩu mới ở lần đăng nhập đầu tiên.
                  </small>
                </div>
              )}
            </div>
          </div>
        )}
      </AdminModal>

      {/* Reject Modal */}
      <AdminModal
        open={Boolean(rejectTarget)}
        title="Từ chối hồ sơ đăng ký"
        description="Lý do từ chối sẽ hiển thị cho người đại diện khi tra cứu mã hồ sơ."
        onClose={() => setRejectTarget(null)}
        size="sm"
        footer={
          <>
            <button
              type="button"
              className="s6a-button secondary"
              onClick={() => setRejectTarget(null)}
            >
              Hủy
            </button>
            <button
              type="submit"
              form="reject-proposal-form"
              className="s6a-button danger"
            >
              Xác nhận từ chối
            </button>
          </>
        }
      >
        <form id="reject-proposal-form" className="s6a-form s6a-form-grid one-column" onSubmit={submitReject}>
          <label className="full">
            <span>Lý do từ chối *</span>
            <textarea
              value={rejectNote}
              onChange={(e) => setRejectNote(e.target.value)}
              placeholder="Nêu rõ lý do từ chối để người nộp bổ sung hồ sơ..."
              rows={4}
            />
            {formError && <small className="s6a-form-error">{formError}</small>}
          </label>
        </form>
      </AdminModal>

      <AdminToast toast={toast} onDismiss={dismissToast} />
    </section>
  );
};

export default AdminApprovalsMgmt;
