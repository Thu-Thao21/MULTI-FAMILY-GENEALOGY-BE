import React, { useEffect, useMemo, useState } from 'react';
import { auditLogMockData, type AuditLevel, type AuditLogRecord, type AuditStatus } from '../../../data/adminOperationsMockData';
import { AdminModal, AdminPageHeader, AdminPagination, AdminStatePanel, AdminStatusBadge, formatAdminDate } from '../Sprint6Admin/shared';
import '../Sprint6Admin/Sprint6Admin.css';

const PAGE_SIZE = 5;
const levelLabels: Record<AuditLevel, string> = { info: 'Thông tin', warning: 'Cảnh báo', security: 'Bảo mật', error: 'Lỗi' };

export const AdminAuditLogsMgmt: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [level, setLevel] = useState<'all' | AuditLevel>('all');
  const [status, setStatus] = useState<'all' | AuditStatus>('all');
  const [module, setModule] = useState('all');
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<AuditLogRecord | null>(null);

  useEffect(() => { const timer = window.setTimeout(() => setLoading(false), 360); return () => window.clearTimeout(timer); }, []);
  useEffect(() => setPage(1), [search, level, status, module, fromDate, toDate]);
  const modules = Array.from(new Set(auditLogMockData.map((item) => item.module)));
  const invalidRange = Boolean(fromDate && toDate && fromDate > toDate);
  const filtered = useMemo(() => auditLogMockData.filter((item) => {
    const needle = search.trim().toLowerCase();
    const text = `${item.id} ${item.user} ${item.action} ${item.module} ${item.ip} ${item.device}`.toLowerCase();
    const itemDate = item.timestamp.slice(0, 10);
    return text.includes(needle) && (level === 'all' || item.level === level) && (status === 'all' || item.status === status) && (module === 'all' || item.module === module) && (!fromDate || itemDate >= fromDate) && (!toDate || itemDate <= toDate);
  }), [search, level, status, module, fromDate, toDate]);
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const visible = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);
  const reset = () => { setSearch(''); setLevel('all'); setStatus('all'); setModule('all'); setFromDate(''); setToDate(''); };

  return <section className="s6a-page">
    <AdminPageHeader eyebrow="GIÁM SÁT & BẢO MẬT" title="Nhật ký hệ thống" description="Theo dõi thao tác, thiết bị và sự kiện bảo mật trong toàn bộ nền tảng." actions={<button type="button" className="s6a-button secondary" onClick={() => { const blob = new Blob([JSON.stringify(filtered, null, 2)], {type:'application/json'}); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href=url; a.download='system-logs-demo.json'; a.click(); URL.revokeObjectURL(url); }}>Xuất nhật ký</button>} />
    <div className="s6a-metric-grid"><article className="s6a-metric-card"><span>Tổng bản ghi</span><strong>{auditLogMockData.length}</strong><small>Nhật ký hệ thống</small></article><article className="s6a-metric-card"><span>Sự kiện bảo mật</span><strong>{auditLogMockData.filter((item) => item.level === 'security').length}</strong><small>Cần theo dõi</small></article><article className="s6a-metric-card"><span>Cảnh báo & lỗi</span><strong>{auditLogMockData.filter((item) => item.level === 'warning' || item.level === 'error').length}</strong><small>Trong 7 ngày</small></article><article className="s6a-metric-card"><span>Thành công</span><strong>{auditLogMockData.length ? Math.round(auditLogMockData.filter((item) => item.status === 'success').length / auditLogMockData.length * 100) : 100}%</strong><small>Tỷ lệ tác vụ hoàn tất</small></article></div>
    <div className="s6a-card"><div className="s6a-card-heading"><div><h2>Dòng sự kiện hệ thống</h2><p>Tìm theo người dùng, hành động, module, IP hoặc thiết bị.</p></div><span className="s6a-count-pill">{filtered.length} bản ghi</span></div><div className="s6a-filter-bar s6a-filter-grid"><label className="s6a-search-field wide"><span>Tìm kiếm</span><input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Mã log, tài khoản, hành động, IP..." /></label><label><span>Module</span><select value={module} onChange={(event) => setModule(event.target.value)}><option value="all">Tất cả</option>{modules.map((item) => <option key={item}>{item}</option>)}</select></label><label><span>Mức độ</span><select value={level} onChange={(event) => setLevel(event.target.value as typeof level)}><option value="all">Tất cả</option>{Object.entries(levelLabels).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select></label><label><span>Trạng thái</span><select value={status} onChange={(event) => setStatus(event.target.value as typeof status)}><option value="all">Tất cả</option><option value="success">Thành công</option><option value="failed">Thất bại</option></select></label><label><span>Từ ngày</span><input type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} /></label><label><span>Đến ngày</span><input type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} /></label><button type="button" className="s6a-button ghost align-end" onClick={reset}>Đặt lại</button></div>
      {invalidRange ? <AdminStatePanel kind="error" title="Khoảng ngày không hợp lệ" message="Ngày bắt đầu phải trước hoặc trùng ngày kết thúc." action={<button className="s6a-button secondary" onClick={() => setToDate('')}>Xóa ngày kết thúc</button>} /> : loading ? <AdminStatePanel kind="loading" message="Đang tải nhật ký hệ thống..." /> : !visible.length ? <AdminStatePanel kind="empty" title="Không có nhật ký phù hợp" message="Thử thay đổi bộ lọc hoặc khoảng thời gian." action={<button className="s6a-button secondary" onClick={reset}>Xóa bộ lọc</button>} /> : <><div className="s6a-table-wrap"><table className="s6a-table"><thead><tr><th>Thời gian / Mã</th><th>Người dùng</th><th>Hành động</th><th>Module</th><th>IP / Thiết bị</th><th>Mức độ</th><th>Trạng thái</th><th>Chi tiết</th></tr></thead><tbody>{visible.map((item) => <tr key={item.id}><td><strong>{formatAdminDate(item.timestamp,true)}</strong><span className="s6a-table-subline">{item.id}</span></td><td>{item.user}</td><td><strong>{item.action}</strong></td><td>{item.module}</td><td><span className="s6a-table-main">{item.ip}</span><span className="s6a-table-subline">{item.device}</span></td><td><AdminStatusBadge status={item.level} label={levelLabels[item.level]} /></td><td><AdminStatusBadge status={item.status} /></td><td><button className="s6a-link-button" onClick={() => setSelected(item)}>Xem</button></td></tr>)}</tbody></table></div><AdminPagination page={safePage} totalItems={filtered.length} pageSize={PAGE_SIZE} onPageChange={setPage} /></>}
    </div>
    <AdminModal open={Boolean(selected)} title={selected ? selected.action : ''} description={selected?.id} onClose={() => setSelected(null)} size="md" footer={<button type="button" className="s6a-button primary" onClick={() => setSelected(null)}>Đóng</button>}>{selected && <div className="s6a-detail-grid"><div><span>Thời gian</span><strong>{formatAdminDate(selected.timestamp,true)}</strong></div><div><span>Tài khoản</span><strong>{selected.user}</strong></div><div><span>Module</span><strong>{selected.module}</strong></div><div><span>IP / Thiết bị</span><strong>{selected.ip} · {selected.device}</strong></div><div><span>Mức độ</span><AdminStatusBadge status={selected.level} label={levelLabels[selected.level]} /></div><div><span>Trạng thái</span><AdminStatusBadge status={selected.status} /></div><div className="wide"><span>Nội dung chi tiết</span><p>{selected.detail}</p></div></div>}</AdminModal>
  </section>;
};

export default AdminAuditLogsMgmt;
