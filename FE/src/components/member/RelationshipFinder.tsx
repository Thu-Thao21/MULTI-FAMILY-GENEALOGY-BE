import React, { useState, useEffect } from 'react';
import { fetchMembers } from '../../services/member.service';
import {
  fetchRelationshipCalculation,
  fetchPersonAncestors,
  fetchPersonDescendants,
} from '../../services/genealogy.service';
import type { Member } from '../../types/member';
import './RelationshipFinder.css';

export const RelationshipFinder: React.FC = () => {
  const [members, setMembers] = useState<Member[]>([]);
  const [personAId, setPersonAId] = useState<string>('');
  const [personBId, setPersonBId] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [calculating, setCalculating] = useState(false);
  const [activeTab, setActiveTab] = useState<'finder' | 'lineage'>('finder');

  // Result state
  const [result, setResult] = useState<{
    found: boolean;
    relationshipName: string;
    addressTitle: string;
    path: string[];
    description: string;
  } | null>(null);

  // Lineage lookup state
  const [lineagePersonId, setLineagePersonId] = useState<string>('');
  const [ancestors, setAncestors] = useState<Member[]>([]);
  const [descendants, setDescendants] = useState<Member[]>([]);

  useEffect(() => {
    fetchMembers({ limit: 500 }).then((res) => {
      const items = res?.items || [];
      setMembers(items);
      if (items.length >= 2) {
        setPersonAId(items[0].id);
        setPersonBId(items[1].id);
        setLineagePersonId(items[0].id);
      }
      setLoading(false);
    });
  }, []);

  const calculateRelationship = async () => {
    if (!personAId || !personBId) return;

    const pA = members.find((m) => m.id === personAId);
    const pB = members.find((m) => m.id === personBId);
    if (!pA || !pB) return;

    if (personAId === personBId) {
      setResult({
        found: true,
        relationshipName: 'Chính mình',
        addressTitle: 'Tôi',
        path: [pA.fullName],
        description: 'Hai đối tượng được chọn là cùng một người.',
      });
      return;
    }

    setCalculating(true);
    const familyId = (pA as any).familyId || (pA as any).clanId || 'default-family';

    try {
      const res = await fetchRelationshipCalculation(familyId, personAId, personBId);
      if (res.found) {
        setResult({
          found: true,
          relationshipName: res.kinshipName,
          addressTitle: res.addressTitle,
          path: res.path.length > 0 ? res.path.map((p) => p.fullName) : [pA.fullName, pB.fullName],
          description: res.description,
        });
      } else {
        setResult({
          found: false,
          relationshipName: res.kinshipName || 'Không xác định',
          addressTitle: res.addressTitle || 'N/A',
          path: [],
          description: res.description || 'Không tìm thấy liên kết quan hệ trong gia phả.',
        });
      }
    } catch {
      // Client-side fallback if server unreachable
      const genA = pA.generation || 1;
      const genB = pB.generation || 1;
      const diff = genA - genB;

      let relName = 'Họ hàng';
      let address = 'N/A';

      if (diff === 0) {
        relName = 'Anh chị em';
        address = (pA.birthDate || '') > (pB.birthDate || '') ? 'Em (xưng Anh/Chị)' : 'Anh/Chị (xưng Em)';
      } else if (diff === 1) {
        relName = 'Cha/Mẹ và Con';
        address = 'Cha/Mẹ (gọi Con)';
      } else if (diff === -1) {
        relName = 'Cha/Mẹ và Con';
        address = 'Con (gọi Cha/Mẹ)';
      } else if (diff === 2) {
        relName = 'Ông/Bà và Cháu';
        address = 'Ông/Bà (gọi Cháu)';
      } else if (diff === -2) {
        relName = 'Ông/Bà và Cháu';
        address = 'Cháu (gọi Ông/Bà)';
      }

      setResult({
        found: true,
        relationshipName: relName,
        addressTitle: address,
        path: [pA.fullName, `Thế hệ ${genA} ➔ Thế hệ ${genB}`, pB.fullName],
        description: `Kết nối giữa ${pA.fullName} (Đời ${genA}) và ${pB.fullName} (Đời ${genB}).`,
      });
    } finally {
      setCalculating(false);
    }
  };

  const handleLineageLookup = async () => {
    if (!lineagePersonId) return;

    const current = members.find((m) => m.id === lineagePersonId);
    if (!current) return;

    const familyId = (current as any).familyId || (current as any).clanId || 'default-family';

    try {
      const [ancRes, descRes] = await Promise.all([
        fetchPersonAncestors(familyId, lineagePersonId),
        fetchPersonDescendants(familyId, lineagePersonId),
      ]);

      const ancMembers: Member[] = ancRes.map((item) => ({
        id: item.person.id,
        fullName: item.person.fullName,
        gender: item.person.gender as any,
        generation: item.person.generation,
        isAlive: item.person.isLiving,
        status: item.person.status as any,
      }));

      const descMembers: Member[] = descRes.map((item) => ({
        id: item.person.id,
        fullName: item.person.fullName,
        gender: item.person.gender as any,
        generation: item.person.generation,
        isAlive: item.person.isLiving,
        status: item.person.status as any,
      }));

      setAncestors(ancMembers);
      setDescendants(descMembers);
    } catch {
      // Fallback to local filtering
      const anc = members.filter((m) => (m.generation || 1) < (current.generation || 1));
      const desc = members.filter((m) => (m.generation || 1) > (current.generation || 1));
      setAncestors(anc);
      setDescendants(desc);
    }
  };

  return (
    <div className="rel-finder-container">
      <div className="rel-finder-header">
        <h2 className="rel-finder-title">Tra Cứu Quan Hệ & Cách Xưng Hô Dòng Họ</h2>
        <p className="rel-finder-subtitle">
          Xác định chuỗi đường đi kết nối gia phả giữa 2 thành viên và gợi ý danh xưng chuẩn phong tục Việt Nam.
        </p>

        <div className="rel-finder-tabs">
          <button
            className={`rel-tab-btn ${activeTab === 'finder' ? 'active' : ''}`}
            onClick={() => setActiveTab('finder')}
          >
            🔍 Xác định quan hệ A → B & Xưng hô
          </button>
          <button
            className={`rel-tab-btn ${activeTab === 'lineage' ? 'active' : ''}`}
            onClick={() => setActiveTab('lineage')}
          >
            📜 Tra cứu Tổ tiên & Hậu duệ
          </button>
        </div>
      </div>

      {loading ? (
        <div className="rel-loading">Đang tải dữ liệu thành viên gia tộc...</div>
      ) : activeTab === 'finder' ? (
        <div className="rel-finder-body">
          <div className="rel-select-card">
            <div className="rel-select-group">
              <label className="rel-select-label">Thành viên A (Khởi đầu)</label>
              <select
                className="rel-select"
                value={personAId}
                onChange={(e) => setPersonAId(e.target.value)}
              >
                {members.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.fullName} (Đời {m.generation} - {m.gender === 'male' ? 'Nam' : 'Nữ'})
                  </option>
                ))}
              </select>
            </div>

            <div className="rel-arrow-icon">➔</div>

            <div className="rel-select-group">
              <label className="rel-select-label">Thành viên B (Đích đến)</label>
              <select
                className="rel-select"
                value={personBId}
                onChange={(e) => setPersonBId(e.target.value)}
              >
                {members.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.fullName} (Đời {m.generation} - {m.gender === 'male' ? 'Nam' : 'Nữ'})
                  </option>
                ))}
              </select>
            </div>

            <button className="rel-calc-btn" onClick={calculateRelationship}>
              Tính toán quan hệ
            </button>
          </div>

          {result && (
            <div className="rel-result-card">
              <div className="rel-result-header">
                <span className="rel-result-badge">{result.found ? 'ĐÃ XÁC ĐỊNH' : 'KẾT QUẢ'}</span>
                <h3 className="rel-result-title">{result.relationshipName}</h3>
              </div>

              <div className="rel-address-box">
                <span className="rel-address-label">Cách xưng hô đề xuất:</span>
                <span className="rel-address-value">{result.addressTitle}</span>
              </div>

              <div className="rel-path-box">
                <h4 className="rel-path-title">Chuỗi đường đi liên kết:</h4>
                <div className="rel-path-steps">
                  {result.path.map((step, idx) => (
                    <React.Fragment key={idx}>
                      <span className="rel-step-pill">{step}</span>
                      {idx < result.path.length - 1 && <span className="rel-step-arrow">➔</span>}
                    </React.Fragment>
                  ))}
                </div>
              </div>

              <p className="rel-description">{result.description}</p>
            </div>
          )}
        </div>
      ) : (
        <div className="rel-lineage-body">
          <div className="rel-select-card">
            <div className="rel-select-group" style={{ flex: 1 }}>
              <label className="rel-select-label">Chọn thành viên để tra cứu thế hệ</label>
              <select
                className="rel-select"
                value={lineagePersonId}
                onChange={(e) => setLineagePersonId(e.target.value)}
              >
                <option value="">-- Chọn thành viên --</option>
                {members.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.fullName} (Đời {m.generation})
                  </option>
                ))}
              </select>
            </div>
            <button className="rel-calc-btn" onClick={handleLineageLookup}>
              Tra cứu tổ tiên / hậu duệ
            </button>
          </div>

          {lineagePersonId && (
            <div className="rel-lineage-results-grid">
              <div className="lineage-column">
                <h3 className="lineage-col-title blue">
                  🏛️ Danh sách Tổ tiên ({ancestors.length})
                </h3>
                <div className="lineage-list">
                  {ancestors.length === 0 ? (
                    <div className="lineage-empty">Không có tổ tiên ở các đời trước trong dữ liệu.</div>
                  ) : (
                    ancestors.map((a) => (
                      <div key={a.id} className="lineage-item">
                        <span className="lineage-item-name">{a.fullName}</span>
                        <span className="lineage-item-badge">Đời {a.generation}</span>
                      </div>
                    ))
                  )}
                </div>
              </div>

              <div className="lineage-column">
                <h3 className="lineage-col-title purple">
                  🌱 Danh sách Hậu duệ ({descendants.length})
                </h3>
                <div className="lineage-list">
                  {descendants.length === 0 ? (
                    <div className="lineage-empty">Chưa có thông tin hậu duệ ở các đời sau.</div>
                  ) : (
                    descendants.map((d) => (
                      <div key={d.id} className="lineage-item">
                        <span className="lineage-item-name">{d.fullName}</span>
                        <span className="lineage-item-badge">Đời {d.generation}</span>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default RelationshipFinder;
