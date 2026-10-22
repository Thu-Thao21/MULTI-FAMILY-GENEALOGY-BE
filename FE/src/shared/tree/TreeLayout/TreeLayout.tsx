import React, { useEffect, useState } from 'react';
import { fetchFamilies } from '../../../services/member.service';
import { buildErgoTreeFromDB } from '../../../services/tree.service';
import type { Family, Member } from '../../../types/member';
import type { ErgoTreeNode, TreeContextMenuState } from '../../../types/tree';
import { ErgoTreeCanvas } from '../ErgoTreeCanvas';
import { TreeContextMenu } from '../TreeContextMenu';
import { NotificationModal } from '../../common/NotificationModal';
import '../Tree.css';
import './TreeLayout.css';

export interface TreeLayoutProps {
  onSelectMemberProfile?: (memberId: string) => void;
}

export const TreeLayout: React.FC<TreeLayoutProps> = ({
  onSelectMemberProfile,
}) => {
  const [families, setFamilies] = useState<Family[]>([]);
  const [selectedFamilyId, setSelectedFamilyId] = useState<string>('');
  const [allMembers, setAllMembers] = useState<Member[]>([]);
  const [treeNodes, setTreeNodes] = useState<ErgoTreeNode[]>([]);
  const [focusMemberId, setFocusMemberId] = useState<string | undefined>(undefined);
  const [treeDirection, setTreeDirection] = useState<'vertical' | 'horizontal'>('vertical');
  const [zoomScale, setZoomScale] = useState<number>(1);
  const [loading, setLoading] = useState<boolean>(true);

  // Context menu state
  const [contextMenu, setContextMenu] = useState<TreeContextMenuState>({
    isOpen: false,
    x: 0,
    y: 0,
    member: null,
  });

  // Toast state for action feedback
  const [isToastOpen, setIsToastOpen] = useState(false);

  const [selectedBranch, setSelectedBranch] = useState<string | undefined>(undefined);
  const [selectedGeneration, setSelectedGeneration] = useState<number | undefined>(undefined);

  useEffect(() => {
    fetchFamilies().then((fams) => {
      setFamilies(fams);
      if (fams.length > 0) {
        setSelectedFamilyId(fams[0].id);
      }
    });
  }, []);

  useEffect(() => {
    setLoading(true);
    buildErgoTreeFromDB(selectedFamilyId, focusMemberId).then(({ rootNodes, allMembers: mems }) => {
      setTreeNodes(rootNodes);
      setAllMembers(mems);
      setLoading(false);
    });
  }, [selectedFamilyId, focusMemberId]);

  const handleCardClick = (e: React.MouseEvent, node: ErgoTreeNode) => {
    e.stopPropagation();
    setContextMenu({
      isOpen: true,
      x: e.clientX,
      y: e.clientY,
      member: node,
    });
  };

  const handleContextMenu = (e: React.MouseEvent, node: ErgoTreeNode) => {
    e.stopPropagation();
    setContextMenu({
      isOpen: true,
      x: e.clientX,
      y: e.clientY,
      member: node,
    });
  };

  const handleSelectFocus = (node: ErgoTreeNode) => {
    setFocusMemberId(node.id);
    setContextMenu((prev) => ({ ...prev, isOpen: false }));
  };

  const handleViewBio = (node: ErgoTreeNode) => {
    setContextMenu((prev) => ({ ...prev, isOpen: false }));
    if (onSelectMemberProfile) {
      onSelectMemberProfile(node.id);
    }
  };

  const handleActionToast = () => {
    setContextMenu((prev) => ({ ...prev, isOpen: false }));
    setIsToastOpen(true);
  };

  // Quick stats calculation
  const maleCount = allMembers.filter((m) => m.gender === 'male').length;
  const femaleCount = allMembers.filter((m) => m.gender === 'female').length;
  const maxGen = allMembers.length > 0 ? Math.max(...allMembers.map((m) => m.generation || 1)) : 1;

  // Extract unique branches for filtering (FR-BO-44)
  const branches = Array.from(
    new Set(allMembers.map((m) => m.branch).filter((b): b is string => Boolean(b)))
  );

  // Filter nodes according to selected branch / generation
  const filterNodeRecursive = (node: ErgoTreeNode): ErgoTreeNode | null => {
    let match = true;
    if (selectedBranch && node.branch !== selectedBranch) match = false;
    if (selectedGeneration !== undefined && node.generation !== selectedGeneration) match = false;

    const filteredChildren = node.children
      .map(filterNodeRecursive)
      .filter((c): c is ErgoTreeNode => c !== null);

    if (match || filteredChildren.length > 0) {
      return {
        ...node,
        children: filteredChildren,
      };
    }
    return null;
  };

  const displayedTreeNodes = (selectedBranch || selectedGeneration !== undefined)
    ? treeNodes.map(filterNodeRecursive).filter((n): n is ErgoTreeNode => n !== null)
    : treeNodes;

  return (
    <div className="tree-page-layout">
      {/* Top Controls Toolbar */}
      <div className="tree-toolbar-card">
        <div className="tree-toolbar-header-info">
          <div className="tree-toolbar-title-row">
            <h2 className="tree-toolbar-title">
              Cây Gia Phả Trực Hệ
            </h2>
            <div className="tree-stats-pill-group">
              <span className="tree-stat-pill blue">{allMembers.length} Thành viên</span>
              <span className="tree-stat-pill purple">{maxGen} Thế hệ</span>
              <span className="tree-stat-pill teal">{maleCount} Nam</span>
              <span className="tree-stat-pill pink">{femaleCount} Nữ</span>
            </div>
          </div>
          <p className="tree-toolbar-subtitle">
            {focusMemberId
              ? 'Đang hiển thị phân nhánh sơ đồ theo người làm trung tâm (Focus View).'
              : selectedBranch || selectedGeneration !== undefined
              ? 'Đang áp dụng bộ lọc chi nhánh và thế hệ gia phả.'
              : 'Hiển thị sơ đồ trực hệ đa thế hệ kết nối gia tộc.'}
          </p>
        </div>

        <div className="tree-toolbar-right">
          {/* Tree Direction Toggle: Vertical (Dọc) vs Horizontal (Ngang) */}
          <div className="tree-dir-toggle-group">
            <button
              className={`tree-dir-btn ${treeDirection === 'vertical' ? 'active' : ''}`}
              onClick={() => setTreeDirection('vertical')}
              title="Chuyển sơ đồ dọc (Từ trên xuống)"
            >
               Dọc
            </button>
            <button
              className={`tree-dir-btn ${treeDirection === 'horizontal' ? 'active' : ''}`}
              onClick={() => setTreeDirection('horizontal')}
              title="Chuyển sơ đồ ngang (Từ trái sang phải)"
            >
              ➔ Ngang
            </button>
          </div>

          {/* Legend Badges */}
          <div className="tree-legend-group">
            <span className="tree-legend-item male">Nam</span>
            <span className="tree-legend-item female">Nữ (Dâu)</span>
            <span className="tree-legend-item focus">Đang chọn</span>
          </div>

          {/* Family Dropdown */}
          <select
            className="tree-control-select"
            value={selectedFamilyId}
            onChange={(e) => setSelectedFamilyId(e.target.value)}
          >
            {families.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name} ({f.memberCount || allMembers.length} thành viên)
              </option>
            ))}
          </select>

          {/* Branch Filter Dropdown (FR-BO-44) */}
          {branches.length > 0 && (
            <select
              className="tree-control-select"
              value={selectedBranch || ''}
              onChange={(e) => setSelectedBranch(e.target.value || undefined)}
            >
              <option value="">-- Tất cả chi nhánh --</option>
              {branches.map((b) => (
                <option key={b} value={b}>
                  Chi: {b}
                </option>
              ))}
            </select>
          )}

          {/* Generation Filter Dropdown (FR-BO-44) */}
          <select
            className="tree-control-select"
            value={selectedGeneration !== undefined ? String(selectedGeneration) : ''}
            onChange={(e) =>
              setSelectedGeneration(e.target.value ? Number(e.target.value) : undefined)
            }
          >
            <option value="">-- Tất cả thế hệ --</option>
            {Array.from({ length: maxGen }, (_, i) => i + 1).map((g) => (
              <option key={g} value={g}>
                Đời thứ {g}
              </option>
            ))}
          </select>

          {/* Focus Member Dropdown (FR-BO-41) */}
          <select
            className="tree-control-select focus-select"
            value={focusMemberId || ''}
            onChange={(e) => setFocusMemberId(e.target.value || undefined)}
          >
            <option value="">-- Người làm trung tâm (Focus) --</option>
            {allMembers.map((m) => (
              <option key={m.id} value={m.id}>
                {m.fullName} (Đời {m.generation})
              </option>
            ))}
          </select>

          {/* Zoom Buttons */}
          <div className="tree-zoom-btn-group">
            <button
              className="tree-control-btn"
              onClick={() => setZoomScale((z) => Math.min(1.6, z + 0.15))}
              title="Phóng to"
            >
              +
            </button>
            <button
              className="tree-control-btn"
              onClick={() => setZoomScale((z) => Math.max(0.5, z - 0.15))}
              title="Thu nhỏ"
            >
              -
            </button>
            <button
              className="tree-control-btn reset"
              onClick={() => {
                setZoomScale(1);
                setFocusMemberId(undefined);
                setSelectedBranch(undefined);
                setSelectedGeneration(undefined);
              }}
              title="Đặt lại góc nhìn và xóa bộ lọc"
            >
              {Math.round(zoomScale * 100)}%
            </button>
          </div>
        </div>
      </div>

      {/* Canvas Area */}
      {loading ? (
        <div className="tree-canvas-prompt-loading">
          Đang tính toán sơ đồ trực hệ gia phả...
        </div>
      ) : displayedTreeNodes.length === 0 ? (
        <div className="tree-canvas-prompt-empty">
          Chưa có dữ liệu cây gia phả phù hợp với điều kiện lọc.
        </div>
      ) : (
        <ErgoTreeCanvas
          nodes={displayedTreeNodes}
          onCardClick={handleCardClick}
          onContextMenu={handleContextMenu}
          zoomScale={zoomScale}
          direction={treeDirection}
        />
      )}

      {/* Popup Context Menu */}
      <TreeContextMenu
        isOpen={contextMenu.isOpen}
        x={contextMenu.x}
        y={contextMenu.y}
        node={contextMenu.member as ErgoTreeNode}
        onClose={() => setContextMenu((prev) => ({ ...prev, isOpen: false }))}
        onSelectFocus={handleSelectFocus}
        onViewBio={handleViewBio}
        onActionToast={handleActionToast}
      />

      {/* Notification Toast */}
      <NotificationModal
        isOpen={isToastOpen}
        onClose={() => setIsToastOpen(false)}
      />
    </div>
  );
};

export default TreeLayout;
