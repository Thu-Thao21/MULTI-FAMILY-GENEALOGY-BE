import React, { useState, useEffect } from 'react';
import { fetchFamilies } from '../../../services/member.service';
import { fetchPublicClans } from '../../../services/genealogy.service';
import type { Family } from '../../../types/member';
import { PublicLayout } from '../../../components/guest/PublicLayout';
import './PublicFamilySearchPage.css';

export const PublicFamilySearchPage: React.FC = () => {
  const [families, setFamilies] = useState<Family[]>([]);
  const [searchName, setSearchName] = useState('');
  const [searchRegion, setSearchRegion] = useState('');
  const [selectedPublicFamily, setSelectedPublicFamily] = useState<Family | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchPublicClans()
      .then((clans) => {
        if (Array.isArray(clans) && clans.length > 0) {
          setFamilies(
            clans.map((c) => ({
              id: c.id,
              name: c.name,
              code: c.clan_code,
              description: 'Dòng họ Việt Nam được xác thực công khai.',
              memberCount: 50,
            }))
          );
        } else {
          fetchFamilies().then((fams) => setFamilies(fams));
        }
      })
      .catch(() => {
        fetchFamilies().then((fams) => setFamilies(fams));
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  const filteredFamilies = families.filter((f) => {
    const matchesName = f.name.toLowerCase().includes(searchName.toLowerCase()) || (f.code || '').toLowerCase().includes(searchName.toLowerCase());
    const matchesRegion = !searchRegion || (f.description || '').toLowerCase().includes(searchRegion.toLowerCase());
    return matchesName && matchesRegion;
  });

  return (
    <PublicLayout>
      <div className="pub-search-container">
        <div className="pub-search-header">
          <h1 className="pub-search-title">Tra Cứu Dòng Họ Công Khai</h1>
          <p className="pub-search-subtitle">
            Tìm kiếm thông tin tổng quan các dòng họ Việt Nam công khai theo tên, mã dòng họ hoặc quê gốc.
          </p>

          <div className="pub-search-bar-row">
            <input
              type="text"
              className="pub-search-input"
              placeholder="Nhập tên dòng họ hoặc mã dòng họ (VD: Họ Nguyễn, FAM001)..."
              value={searchName}
              onChange={(e) => setSearchName(e.target.value)}
            />

            <input
              type="text"
              className="pub-search-input"
              placeholder="Địa phương / Quê gốc (VD: Hà Nội, Hải Dương)..."
              value={searchRegion}
              onChange={(e) => setSearchRegion(e.target.value)}
            />
          </div>
        </div>

        {loading ? (
          <div className="pub-search-loading">Đang tải danh sách dòng họ công khai...</div>
        ) : filteredFamilies.length === 0 ? (
          <div className="pub-search-empty">
            Không tìm thấy dòng họ nào phù hợp với từ khóa tìm kiếm.
          </div>
        ) : (
          <div className="pub-families-grid">
            {filteredFamilies.map((f) => (
              <div key={f.id} className="pub-family-card">
                <div className="pub-family-card-head">
                  <div className="family-avatar">🌿</div>
                  <div>
                    <h3 className="family-name">{f.name}</h3>
                    <span className="family-code">Mã dòng họ: {f.code || f.id}</span>
                  </div>
                </div>

                <p className="family-desc">{f.description || 'Dòng họ lâu đời gắn kết gia tộc.'}</p>

                <div className="family-stats-row">
                  <span>👥 {f.memberCount || 50}+ Thành viên</span>
                  <span>📍 Việt Nam</span>
                </div>

                <button
                  className="view-public-profile-btn"
                  onClick={() => setSelectedPublicFamily(f)}
                >
                  Xem hồ sơ công khai ➔
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Modal View Public Family Profile */}
        {selectedPublicFamily && (
          <div className="pub-profile-modal-overlay">
            <div className="pub-profile-modal-card">
              <div className="pub-profile-header">
                <div>
                  <span className="public-only-badge">🔒 CHỈ DỮ LIỆU CÔNG KHAI</span>
                  <h2 className="pub-profile-title">{selectedPublicFamily.name}</h2>
                  <span className="pub-profile-code">Mã định danh: {selectedPublicFamily.code || selectedPublicFamily.id}</span>
                </div>
                <button className="modal-close-btn" onClick={() => setSelectedPublicFamily(null)}>✕</button>
              </div>

              <div className="pub-profile-body">
                <div className="pub-info-box">
                  <h4 className="pub-box-title">Giới thiệu & Lịch sử dòng họ</h4>
                  <p className="pub-box-content">
                    {selectedPublicFamily.description || 'Dòng họ thành lập lâu đời với truyền thống hiếu học và đoàn kết.'}
                  </p>
                </div>

                <div className="pub-info-box">
                  <h4 className="pub-box-title">Thông tin quê gốc công khai</h4>
                  <p className="pub-box-content">
                    📍 Nhà thờ tổ / Từ đường chính đặt tại: Xã Kim Liên, Huyện Nam Đàn, Tỉnh Nghệ An.
                  </p>
                </div>

                <div className="privacy-strict-warning">
                  🔒 <strong>Lưu ý bảo mật:</strong> Khách vãng lai chỉ được xem tên, quê gốc và giới thiệu công khai. Các thông tin cây chi tiết, số điện thoại, địa chỉ cụ thể và tài chính dòng họ được ẩn tuyệt đối.
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </PublicLayout>
  );
};

export default PublicFamilySearchPage;
