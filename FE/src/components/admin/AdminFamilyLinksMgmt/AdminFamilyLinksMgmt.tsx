import React, { useState } from 'react';
import apiClient from '../../../api/axios';
import './AdminFamilyLinksMgmt.css';

export interface LinkRequestItem {
  id: string;
  requester_family: string;
  target_family: string;
  link_type: 'paternal' | 'maternal' | 'in_law' | 'affiliated' | string;
  status: 'pending' | 'approved' | 'rejected' | string;
  notes?: string;
  created_at: string;
}

import { fetchPublicClans, type PublicClanItem } from '../../../services/genealogy.service';
import { sendLinkRequest, reviewLinkRequest } from '../../../services/network.service';

export const AdminFamilyLinksMgmt: React.FC = () => {
  const [requests, setRequests] = useState<LinkRequestItem[]>([]);
  const [availableClans, setAvailableClans] = useState<PublicClanItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);

  const fetchLinkRequests = async () => {
    setLoading(true);
    try {
      const res = await apiClient.get<any[]>('/networks/link-requests');
      if (Array.isArray(res.data)) {
        const mapped: LinkRequestItem[] = res.data.map((item) => ({
          id: item.id,
          requester_family: item.sourceFamilyName || item.source_family_name || 'Dòng họ nguồn',
          target_family: item.targetFamilyName || item.target_family_name || 'Dòng họ đối tác',
          link_type: 'affiliated',
          status: (item.status || 'pending').toLowerCase(),
          notes: item.message || '',
          created_at: (item.createdAt || item.created_at || '').slice(0, 10),
        }));
        setRequests(mapped);
      } else {
        setRequests([]);
      }
    } catch (err) {
      console.error('Fetch link requests error from Neon DB:', err);
      setRequests([]);
    } finally {
      setLoading(false);
    }
  };

  React.useEffect(() => {
    fetchLinkRequests();
    fetchPublicClans().then((clans) => {
      if (Array.isArray(clans)) {
        setAvailableClans(clans);
        if (clans.length > 0) setSendTargetFamily(clans[0].id);
      }
    });
  }, []);

  const [activeTypeTab, setActiveTypeTab] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('pending');
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [selectedRequest, setSelectedRequest] = useState<LinkRequestItem | null>(null);
  const [isSendModalOpen, setIsSendModalOpen] = useState<boolean>(false);
  const [sendTargetFamily, setSendTargetFamily] = useState<string>('');
  const [sendLinkType, setSendLinkType] = useState<string>('maternal');
  const [sendNotes, setSendNotes] = useState<string>('');
  const [msg, setMsg] = useState<string>('');

  const handleReview = async (id: string, newStatus: 'approved' | 'rejected') => {
    try {
      await reviewLinkRequest(id, newStatus === 'approved' ? 'APPROVE' : 'REJECT');
      await fetchLinkRequests();
      setMsg(`Đã ${newStatus === 'approved' ? 'chấp nhận & phê duyệt' : 'từ chối'} liên kết thành công.`);
    } catch (err: any) {
      setMsg(err?.response?.data?.detail || 'Thao tác phê duyệt thất bại.');
    }
    setTimeout(() => setMsg(''), 4000);
  };

  const handleUnlink = async (id: string) => {
    if (window.confirm('Bạn có chắc chắn muốn hủy liên kết giữa 2 dòng họ này?')) {
      try {
        await reviewLinkRequest(id, 'REJECT');
        await fetchLinkRequests();
        setMsg('Đã hủy liên kết dòng họ trên cơ sở dữ liệu.');
      } catch {
        setMsg('Hủy liên kết thất bại.');
      }
      setTimeout(() => setMsg(''), 3000);
    }
  };

  const handleSendRequest = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!sendTargetFamily) return;

    try {
      await sendLinkRequest(sendTargetFamily, sendLinkType, sendNotes);
      await fetchLinkRequests();
      setMsg('Đã gửi yêu cầu kết nối dòng họ thành công tới Neon DB!');
    } catch (err: any) {
      setMsg(err?.response?.data?.detail || 'Gửi yêu cầu thất bại. Vui lòng thử lại.');
    }

    setIsSendModalOpen(false);
    setSendNotes('');
    setTimeout(() => setMsg(''), 4000);
  };

  const filteredRequests = requests.filter((r) => {
    const matchType = activeTypeTab ? r.link_type === activeTypeTab : true;
    const matchStatus = statusFilter ? r.status === statusFilter : true;
    const text = `${r.id} ${r.requester_family} ${r.target_family} ${r.notes || ''}`.toLowerCase();
    return matchType && matchStatus && text.includes(searchTerm.trim().toLowerCase());
  });

  return (
    <div className="admin-links-container">
      {/* Header */}
      <div className="admin-account-header">
        <div>
          <h2 className="admin-account-title">Mạng Lưới & Phê Duyệt Liên Kết Nhiều Dòng Họ</h2>
          <p className="admin-account-subtitle">
            Gửi, tiếp nhận, chấp nhận, từ chối, phê duyệt hoặc hủy liên kết giữa các dòng họ (Nội, Ngoại, Dâu, Rể, Thông gia).
          </p>
        </div>

        <div className="admin-account-controls">
          <button className="admin-btn-primary" onClick={() => setIsSendModalOpen(true)}>
            Gửi Yêu Cầu Liên Kết Mới
          </button>
        </div>
      </div>

      {msg && <div className="admin-msg-box">{msg}</div>}

      {/* Type Classification Tabs */}
      <div className="admin-links-tabs-wrap">
        <button
          className={`filter-btn ${activeTypeTab === '' ? 'active' : ''}`}
          onClick={() => setActiveTypeTab('')}
        >
          Tất cả phân loại
        </button>
        <button
          className={`filter-btn ${activeTypeTab === 'paternal' ? 'active' : ''}`}
          onClick={() => setActiveTypeTab('paternal')}
        >
          Họ Nội
        </button>
        <button
          className={`filter-btn ${activeTypeTab === 'maternal' ? 'active' : ''}`}
          onClick={() => setActiveTypeTab('maternal')}
        >
          Họ Ngoại
        </button>
        <button
          className={`filter-btn ${activeTypeTab === 'in_law' ? 'active' : ''}`}
          onClick={() => setActiveTypeTab('in_law')}
        >
          Dâu & Rể
        </button>
        <button
          className={`filter-btn ${activeTypeTab === 'affiliated' ? 'active' : ''}`}
          onClick={() => setActiveTypeTab('affiliated')}
        >
          Họ Thông Gia
        </button>
      </div>

      {/* Filter Status */}
      <div className="admin-links-filter-row">
        <input className="admin-search-input admin-links-search" value={searchTerm} onChange={(event) => setSearchTerm(event.target.value)} placeholder="Tìm dòng họ hoặc mã yêu cầu..." aria-label="Tìm liên kết dòng họ" />
        <span className="admin-links-filter-label">Trạng thái yêu cầu:</span>
        <button
          className={`filter-btn ${statusFilter === 'pending' ? 'active' : ''}`}
          onClick={() => setStatusFilter('pending')}
        >
          Chờ duyệt ({requests.filter((r) => r.status === 'pending').length})
        </button>
        <button
          className={`filter-btn ${statusFilter === 'approved' ? 'active' : ''}`}
          onClick={() => setStatusFilter('approved')}
        >
          Đã phê duyệt ({requests.filter((r) => r.status === 'approved').length})
        </button>
        <button
          className={`filter-btn ${statusFilter === '' ? 'active' : ''}`}
          onClick={() => setStatusFilter('')}
        >
          Tất cả
        </button>
      </div>

      {/* Table */}
      <div className="admin-table-card">
        {filteredRequests.length === 0 ? (
          <p className="admin-table-empty">Không có yêu cầu liên kết nào.</p>
        ) : (
          <table className="admin-table">
            <thead>
              <tr>
                <th>Dòng họ gửi yêu cầu</th>
                <th>Dòng họ nhận yêu cầu</th>
                <th>Phân loại liên kết</th>
                <th>Lý do & Ghi chú</th>
                <th>Trạng thái</th>
                <th>Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {filteredRequests.map((req) => {
                let typeClass = '';
                if (req.link_type === 'paternal') typeClass = 'admin-links-type-paternal';
                else if (req.link_type === 'maternal') typeClass = 'admin-links-type-maternal';
                else if (req.link_type === 'in_law') typeClass = 'admin-links-type-in-law';
                else typeClass = 'admin-links-type-affiliated';

                return (
                  <tr key={req.id}>
                    <td className="admin-links-family-req">{req.requester_family}</td>
                    <td className="admin-links-family-tgt">{req.target_family}</td>
                    <td>
                      <span className={`admin-links-type-badge ${typeClass}`}>
                        {req.link_type === 'paternal'
                          ? 'Họ Nội'
                          : req.link_type === 'maternal'
                          ? 'Họ Ngoại'
                          : req.link_type === 'in_law'
                          ? 'Dâu & Rể'
                          : 'Thông Gia'}
                      </span>
                    </td>
                    <td className="admin-links-notes">{req.notes || '—'}</td>
                    <td>
                    <span
                      className={
                        req.status === 'approved'
                          ? 'status-badge-active'
                          : req.status === 'rejected'
                          ? 'status-badge-locked'
                          : 'badge-role-head'
                      }
                    >
                      {req.status === 'pending'
                        ? 'Chờ duyệt'
                        : req.status === 'approved'
                        ? 'Đã duyệt'
                        : 'Từ chối'}
                    </span>
                  </td>
                  <td>
                    <div className="action-btn-row">
                      <button className="btn-icon-action" onClick={() => setSelectedRequest(req)}>Chi tiết</button>
                      {req.status === 'pending' ? (
                        <>
                          <button
                            className="btn-icon-action unlock"
                            onClick={() => handleReview(req.id, 'approved')}
                          >
                            Duyệt
                          </button>
                          <button
                            className="btn-icon-action lock"
                            onClick={() => handleReview(req.id, 'rejected')}
                          >
                            Từ chối
                          </button>
                        </>
                      ) : (
                        <button className="btn-icon-action lock" onClick={() => handleUnlink(req.id)}>
                          Hủy liên kết
                        </button>
                      )}
                    </div>
                  </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Send Link Modal */}
      {selectedRequest && (
        <div className="admin-modal-overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelectedRequest(null); }}>
          <div className="admin-modal-box">
            <div className="admin-modal-header"><h3>Chi Tiết Liên Kết {selectedRequest.id}</h3><button className="admin-modal-close" onClick={() => setSelectedRequest(null)}>✕</button></div>
            <div className="admin-link-detail-grid"><div><span>Dòng họ gửi</span><strong>{selectedRequest.requester_family}</strong></div><div><span>Dòng họ nhận</span><strong>{selectedRequest.target_family}</strong></div><div><span>Loại kết nối</span><strong>{selectedRequest.link_type}</strong></div><div><span>Ngày gửi</span><strong>{selectedRequest.created_at}</strong></div><div className="wide"><span>Thông tin quan hệ</span><p>{selectedRequest.notes || 'Không có ghi chú.'}</p></div></div>
            <div className="admin-modal-footer"><button className="btn-icon-action" onClick={() => setSelectedRequest(null)}>Đóng</button>{selectedRequest.status === 'pending' && <><button className="btn-icon-action lock" onClick={() => { handleReview(selectedRequest.id,'rejected'); setSelectedRequest(null); }}>Từ chối</button><button className="admin-btn-primary" onClick={() => { handleReview(selectedRequest.id,'approved'); setSelectedRequest(null); }}>Phê duyệt</button></>}</div>
          </div>
        </div>
      )}

      {isSendModalOpen && (
        <div className="admin-modal-overlay">
          <div className="admin-modal-box">
            <div className="admin-modal-header">
              <h3>Gửi Yêu Cầu Liên Kết Dòng Họ</h3>
              <button className="admin-modal-close" onClick={() => setIsSendModalOpen(false)}>✕</button>
            </div>

            <form onSubmit={handleSendRequest}>
              <div className="form-group-admin">
                <label className="form-label-admin">Tên dòng họ muốn liên kết *</label>
                <input
                  type="text"
                  className="form-input-admin"
                  value={sendTargetFamily}
                  onChange={(e) => setSendTargetFamily(e.target.value)}
                  placeholder="Ví dụ: Dòng Họ Trần Nam Định"
                  required
                />
              </div>

              <div className="form-group-admin">
                <label className="form-label-admin">Phân loại quan hệ liên kết</label>
                <select
                  className="form-input-admin"
                  value={sendLinkType}
                  onChange={(e) => setSendLinkType(e.target.value)}
                >
                  <option value="paternal">Họ Nội (Trực hệ chính)</option>
                  <option value="maternal">Họ Ngoại (Bên mẹ / ngoại tộc)</option>
                  <option value="in_law">Dâu & Rể (Hôn nhân)</option>
                  <option value="affiliated">Họ Thông Gia (Liên kết kết nghĩa)</option>
                </select>
              </div>

              <div className="form-group-admin">
                <label className="form-label-admin">Ghi chú & Lý do liên kết</label>
                <textarea
                  className="form-input-admin"
                  rows={3}
                  value={sendNotes}
                  onChange={(e) => setSendNotes(e.target.value)}
                  placeholder="Nhập thông tin người đại diện hoặc mối quan hệ hôn nhân..."
                />
              </div>

              <div className="admin-modal-footer">
                <button type="button" className="btn-icon-action" onClick={() => setIsSendModalOpen(false)}>Hủy</button>
                <button type="submit" className="admin-btn-primary">Gửi yêu cầu ngay</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default AdminFamilyLinksMgmt;
