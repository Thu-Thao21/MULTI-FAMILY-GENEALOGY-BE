import './RelationshipsPage.css';
import React, { useState } from 'react';
import PageHeader from '../../../shared/Layout/PageHeader';
import DataTable, { type Column } from '../../../shared/DataTable/DataTable';

interface Relationship {
  id: string;
  person1: string;
  person2: string;
  type: string;
  details: string;
  status: 'verified' | 'pending';
}

import apiClient from '../../../api/axios';

export const RelationshipsPage: React.FC = () => {
  const [search, setSearch] = useState('');
  const [data, setData] = useState<Relationship[]>([]);

  React.useEffect(() => {
    apiClient.get<any[]>('/families').then((famsRes) => {
      const fams = Array.isArray(famsRes.data) ? famsRes.data : [];
      if (fams.length > 0) {
        const familyId = fams[0].id || fams[0].clan_id;
        apiClient.get<any>(`/api/v1/families/${familyId}/tree-data`).then((res) => {
          const edges = Array.isArray(res.data?.edges) ? res.data.edges : [];
          const nodes = Array.isArray(res.data?.nodes) ? res.data.nodes : [];
          const nodeMap = new Map<string, string>();
          nodes.forEach((n: any) => nodeMap.set(n.id, n.fullName || n.full_name || 'Thành viên'));

          const mapped: Relationship[] = edges.map((e: any, idx: number) => ({
            id: e.id || `rel-${idx}`,
            person1: nodeMap.get(e.source || e.fromMemberId) || e.source || 'Người A',
            person2: nodeMap.get(e.target || e.toMemberId) || e.target || 'Người B',
            type: e.relationshipType || e.relation_type || 'Quan hệ',
            details: e.notes || 'Quan hệ gia đình',
            status: 'verified',
          }));
          setData(mapped);
        }).catch(() => setData([]));
      }
    }).catch(() => setData([]));
  }, []);

  const columns: Column<Relationship>[] = [
    { key: 'person1', header: 'Người thứ nhất', render: (item) => <strong className="text-blue-700">{item.person1}</strong> },
    { key: 'type', header: 'Mối quan hệ', render: (item) => (
      <span className="rel-type-badge">
        {item.type}
      </span>
    )},
    { key: 'person2', header: 'Người thứ hai', render: (item) => <strong className="text-blue-700">{item.person2}</strong> },
    { key: 'details', header: 'Chi tiết', render: (item) => item.details },
    { key: 'status', header: 'Trạng thái', render: (item) => (
      <span className={`rel-status-badge ${item.status === 'verified' ? 'status-verified' : 'status-pending'}`}>
        {item.status === 'verified' ? 'Đã xác nhận' : 'Chờ duyệt'}
      </span>
    )},
    { key: 'actions', header: 'Thao tác', render: () => (
      <div className="rel-actions">
        <button className="rel-btn-edit">Sửa</button>
        <button className="rel-btn-delete">Xoá</button>
      </div>
    )},
  ];

  const headerActions = (
    <button className="admin-btn-primary">
      <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
      Tạo Quan hệ mới
    </button>
  );

  return (
    <div className="admin-account-container">
      
      <div className="admin-account-header">
        <div>
          <h2 className="admin-account-title">Quản lý Quan hệ</h2>
          <p className="admin-account-subtitle">Quản lý quan hệ Cha/Mẹ - Con, Vợ/Chồng, Anh/Chị/Em giữa các nhân khẩu.</p>
        </div>
        <div className="admin-account-controls">
          {headerActions}
        </div>
      </div>
      
      <div className="rel-filter-bar">
        <input 
          type="text" 
          placeholder="Tìm kiếm theo tên người..." 
          className="rel-search-input form-input-admin flex-1"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select className="rel-type-select form-input-admin w-48">
          <option value="">Tất cả loại quan hệ</option>
          <option value="parent">Cha/Mẹ - Con</option>
          <option value="spouse">Vợ - Chồng</option>
          <option value="sibling">Anh - Chị - Em</option>
        </select>
      </div>

      <DataTable 
        columns={columns} 
        data={data} 
        keyExtractor={(item) => item.id} 
        emptyMessage="Chưa có dữ liệu quan hệ nào được ghi nhận."
      />
    </div>
  );
};

export default RelationshipsPage;
