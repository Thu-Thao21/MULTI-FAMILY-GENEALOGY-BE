import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { TopBar } from '../../components/dashboard/TopBar';
import { Sidebar } from '../../components/dashboard/Sidebar';
import { MemberList } from '../../components/profile/MemberList';
import { ProfileLayout } from '../../components/profile/ProfileLayout';
import { PrivacySettingsTab } from '../../components/profile/PrivacySettingsTab';
import { RelationshipFinder } from '../../components/member/RelationshipFinder';
import { MyProposalsModule } from '../../components/member/MyProposalsModule';
import { AnniversariesModule } from '../../components/member/AnniversariesModule';
import { ClanEventsModule } from '../../components/member/ClanEventsModule';
import { ClanFundsModule } from '../../components/member/ClanFundsModule';
import { ClanDocumentsModule } from '../../components/member/ClanDocumentsModule';
import { ClanAIAssistantModule } from '../../components/member/ClanAIAssistantModule';
import { DigitalAncestralHallModule } from '../../components/member/DigitalAncestralHallModule';
import { NotificationCenterModule } from '../../components/member/NotificationCenterModule';
import { AIConsentModule } from '../../components/member/AIConsentModule';
import { AncestralLibraryModule } from '../../components/member/AncestralLibraryModule';
import { DataExchangeModule } from '../../components/member/DataExchangeModule';
import { FirstLoginPasswordModal } from '../../components/auth/FirstLoginPasswordModal';
import { NotificationModal } from '../../components/common/NotificationModal';
import { FamilyPaternalTab } from '../../components/network/FamilyPaternalTab';
import { FamilyMaternalTab } from '../../components/network/FamilyMaternalTab';
import { InLawMarriagesTab } from '../../components/network/InLawMarriagesTab';
import { AffiliatedFamiliesTab } from '../../components/network/AffiliatedFamiliesTab';
import { TreeLayout } from '../../shared/tree/TreeLayout';
import { MemberDashboard, AdminDashboard } from '../../components/roles';

import AdminAccountMgmt from '../../components/admin/AdminAccountMgmt/AdminAccountMgmt';
import AdminFamiliesMgmt from '../../components/admin/AdminFamiliesMgmt/AdminFamiliesMgmt';
import AdminMembersMgmt from '../../components/admin/AdminMembersMgmt/AdminMembersMgmt';
import AdminFamilyLinksMgmt from '../../components/admin/AdminFamilyLinksMgmt/AdminFamilyLinksMgmt';
import AdminApprovalsMgmt from '../../components/admin/AdminApprovalsMgmt/AdminApprovalsMgmt';
import AdminAuditLogsMgmt from '../../components/admin/AdminAuditLogsMgmt/AdminAuditLogsMgmt';
import AdminDataBackupMgmt from '../../components/admin/AdminDataBackupMgmt/AdminDataBackupMgmt';
import { FamilyAdminModule, type FamilyAdminView } from '../../features/familyAdmin/FamilyAdminModule';
import {
  ServicePackageManagement,
  PaymentTransactionManagement,
  ModerationManagement,
  RolePermissionManagement
} from '../../components/admin/Sprint6Admin';

import { useAuth } from '../../hooks/useAuth';
import { ROUTES } from '../../config/routes';
import type { TreeViewMode } from '../../types/tree';
import './Dashboard.css';

// ===== Tab ID ↔ URL Route Mapping =====
const TAB_TO_ROUTE: Record<string, string> = {
  'dashboard':            '',
  'notifications':        ROUTES.USER.NOTIFICATIONS,
  'tree':                 ROUTES.USER.TREE_HORIZONTAL,
  'tree-vertical':        ROUTES.USER.TREE_VERTICAL,
  'tree-horizontal':      ROUTES.USER.TREE_HORIZONTAL,
  'tree-focus':           ROUTES.USER.TREE_FOCUS,
  'net-noi':              ROUTES.USER.NETWORK_NOI,
  'net-ngoai':            ROUTES.USER.NETWORK_NGOAI,
  'net-dau-re':           ROUTES.USER.NETWORK_DAU_RE,
  'net-thong-gia':        ROUTES.USER.NETWORK_THONG_GIA,
  'member-list':          ROUTES.USER.MEMBERS,
  'member-profile':       ROUTES.USER.MEMBER_PROFILE,
  'my-profile':           ROUTES.USER.MY_PROFILE,
  'my-proposals':         ROUTES.USER.PROPOSALS,
  'relationship-finder': ROUTES.USER.RELATIONSHIP,
  'anniversaries':        ROUTES.USER.ANNIVERSARIES,
  'events':               ROUTES.USER.EVENTS,
  'funds':                ROUTES.USER.FUNDS,
  'documents':            ROUTES.USER.DOCUMENTS,
  'ai-assistant':         ROUTES.USER.AI_ASSISTANT,
  'ai-consent':           ROUTES.USER.AI_CONSENT,
  'ancestral-hall':       ROUTES.USER.ANCESTRAL_HALL,
  'ancestral-library':    ROUTES.USER.ANCESTRAL_LIBRARY,
  'privacy-settings':     ROUTES.USER.PRIVACY_SETTINGS,
  'privacy-preview':      ROUTES.USER.PRIVACY_PREVIEW,
  'family-members':       ROUTES.USER.FAMILY_MANAGEMENT,
  'family-relations':     ROUTES.USER.FAMILY_RELATIONS,
  'family-tree':          ROUTES.USER.FAMILY_TREE,
  'family-search':        ROUTES.USER.FAMILY_SEARCH,
  'family-branches':      ROUTES.USER.FAMILY_BRANCHES,
  'family-approvals':     ROUTES.USER.FAMILY_APPROVALS,
  'family-accounts':      ROUTES.USER.FAMILY_ACCOUNTS,
  'family-links':         ROUTES.USER.FAMILY_LINKS,
  'family-import-export': ROUTES.USER.FAMILY_IMPORT_EXPORT,
  'family-logs':          ROUTES.USER.FAMILY_LOGS,
  // Admin tabs
  'admin-tree':           ROUTES.ADMIN.TREE,
  'admin-permissions':    ROUTES.ADMIN.ACCOUNTS,
  'admin-approval':       ROUTES.ADMIN.APPROVALS,
  'admin-logs':           ROUTES.ADMIN.SECURITY_LOGS,
  'admin-account-mgmt':   ROUTES.ADMIN.ACCOUNTS,
  'admin-families-mgmt':  ROUTES.ADMIN.FAMILIES,
  'admin-members-mgmt':   ROUTES.ADMIN.MEMBERS,
  'admin-family-links':   ROUTES.ADMIN.FAMILY_LINKS,
  'admin-approvals':      ROUTES.ADMIN.APPROVALS,
  'admin-security-logs':  ROUTES.ADMIN.SECURITY_LOGS,
  'admin-data-backup':    ROUTES.ADMIN.BACKUP,
  'admin-packages':       ROUTES.ADMIN.PACKAGES,
  'admin-payments':       ROUTES.ADMIN.PAYMENTS,
  'admin-moderation':     ROUTES.ADMIN.MODERATION,
  'admin-roles':          ROUTES.ADMIN.ROLES,
};

const ROUTE_TO_TAB: Array<[string, string]> = [
  [ROUTES.ADMIN.TREE,              'admin-tree'],
  [ROUTES.ADMIN.ACCOUNTS,          'admin-permissions'],
  [ROUTES.ADMIN.FAMILIES,          'admin-families-mgmt'],
  [ROUTES.ADMIN.MEMBERS,           'admin-members-mgmt'],
  [ROUTES.ADMIN.FAMILY_LINKS,      'admin-family-links'],
  [ROUTES.ADMIN.APPROVALS,         'admin-approval'],
  [ROUTES.ADMIN.SECURITY_LOGS,     'admin-logs'],
  [ROUTES.ADMIN.BACKUP,            'admin-data-backup'],
  [ROUTES.ADMIN.PACKAGES,          'admin-packages'],
  [ROUTES.ADMIN.PAYMENTS,          'admin-payments'],
  [ROUTES.ADMIN.MODERATION,        'admin-moderation'],
  [ROUTES.ADMIN.ROLES,             'admin-roles'],
  [ROUTES.USER.NOTIFICATIONS,      'notifications'],
  [ROUTES.USER.TREE_VERTICAL,      'tree'],
  [ROUTES.USER.TREE_HORIZONTAL,    'tree'],
  [ROUTES.USER.TREE_FOCUS,         'tree'],
  [ROUTES.USER.TREE,               'tree'],
  [ROUTES.USER.NETWORK_NOI,        'net-noi'],
  [ROUTES.USER.NETWORK_NGOAI,      'net-ngoai'],
  [ROUTES.USER.NETWORK_DAU_RE,     'net-dau-re'],
  [ROUTES.USER.NETWORK_THONG_GIA,  'net-thong-gia'],
  [ROUTES.USER.MY_PROFILE,         'my-profile'],
  [ROUTES.USER.MEMBER_PROFILE,     'member-profile'],
  [ROUTES.USER.MEMBERS,            'member-list'],
  [ROUTES.USER.RELATIONSHIP,       'relationship-finder'],
  [ROUTES.USER.PROPOSALS,          'my-proposals'],
  [ROUTES.USER.ANNIVERSARIES,      'anniversaries'],
  [ROUTES.USER.EVENTS,             'events'],
  [ROUTES.USER.FUNDS,              'funds'],
  [ROUTES.USER.DOCUMENTS,          'documents'],
  [ROUTES.USER.AI_ASSISTANT,       'ai-assistant'],
  [ROUTES.USER.AI_CONSENT,         'ai-consent'],
  [ROUTES.USER.ANCESTRAL_HALL,     'ancestral-hall'],
  [ROUTES.USER.ANCESTRAL_LIBRARY,  'ancestral-library'],
  [ROUTES.USER.PRIVACY_SETTINGS,   'privacy-settings'],
  [ROUTES.USER.PRIVACY_PREVIEW,    'privacy-preview'],
  [ROUTES.USER.FAMILY_BRANCHES,    'family-branches'],
  [ROUTES.USER.FAMILY_RELATIONS,   'family-relations'],
  [ROUTES.USER.FAMILY_TREE,        'family-tree'],
  [ROUTES.USER.FAMILY_SEARCH,      'family-search'],
  [ROUTES.USER.FAMILY_APPROVALS,   'family-approvals'],
  [ROUTES.USER.FAMILY_ACCOUNTS,    'family-accounts'],
  [ROUTES.USER.FAMILY_LINKS,       'family-links'],
  [ROUTES.USER.FAMILY_IMPORT_EXPORT, 'family-import-export'],
  [ROUTES.USER.FAMILY_LOGS,        'family-logs'],
  [ROUTES.USER.FAMILY_MANAGEMENT,  'family-members'],
];

export interface DashboardProps {
  userName: string;
  onLogout: () => void;
}

export const Dashboard: React.FC<DashboardProps> = ({ userName, onLogout }) => {
  const { account, firebaseUser } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [activeTab, setActiveTab] = useState('dashboard');
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(() => window.innerWidth <= 760);
  const [selectedMemberId, setSelectedMemberId] = useState<string | null>(null);
  const [isProcessingToastOpen, setIsProcessingToastOpen] = useState(false);
  const [showFirstLoginModal, setShowFirstLoginModal] = useState(false);
  const [selectedAncestorId, setSelectedAncestorId] = useState<string | undefined>();

  const displayUserName = account?.display_name || account?.username || firebaseUser?.displayName || userName || 'Người dùng';
  const primaryRole = account?.primary_role || 'member';
  const isFamilyManager = account?.roles?.some((role) => role.role === 'manager' && role.status === 'active') && !account?.roles?.some((role) => role.role === 'family_head' && role.status === 'active');
  const userRole = primaryRole === 'admin' ? 'Admin' : primaryRole === 'family_head' ? 'Chủ dòng họ' : isFamilyManager ? 'Family Admin' : 'Thành viên';
  const basePath = primaryRole === 'admin' ? ROUTES.ADMIN.ROOT : ROUTES.USER.ROOT;

  // Mandatory first password change check
  useEffect(() => {
    if (account && (account as any).must_change_password) {
      setShowFirstLoginModal(true);
    }
  }, [account]);

  // Sync URL → activeTab
  useEffect(() => {
    const path = location.pathname;
    for (const [route, tabId] of ROUTE_TO_TAB) {
      if (path === route || path.startsWith(route + '/')) {
        setActiveTab(tabId);
        return;
      }
    }
    setActiveTab('dashboard');
  }, [location.pathname]);

  // Navigate tab
  const handleSelectTab = useCallback((tabId: string) => {
    setActiveTab(tabId);

    // Clear selectedMemberId overlay when switching to non-profile tabs
    if (tabId !== 'member-profile' && tabId !== 'my-profile') {
      setSelectedMemberId(null);
    }

    const route = TAB_TO_ROUTE[tabId];
    if (route) {
      navigate(route, { replace: false });
    } else if (tabId === 'dashboard') {
      navigate(basePath, { replace: false });
    }
  }, [navigate, basePath]);

  const handleSelectMember = (memberId: string) => {
    setSelectedMemberId(memberId);
    setActiveTab('member-profile');
    navigate(ROUTES.USER.MEMBER_PROFILE, { replace: false });
  };

  const renderMainContent = () => {
    // ===== Branch for System Admin =====
    if (primaryRole === 'admin') {
      if (activeTab === 'admin-tree') {
        return (
          <TreeLayout
            initialMode="horizontal"
            onSelectMemberProfile={(memberId) => {
              setSelectedMemberId(memberId);
              handleSelectTab('admin-members-mgmt');
            }}
          />
        );
      }
      if (activeTab === 'admin-permissions' || activeTab === 'admin-account-mgmt') return <AdminAccountMgmt />;
      if (activeTab === 'admin-families-mgmt') return <AdminFamiliesMgmt />;
      if (activeTab === 'admin-members-mgmt') return <AdminMembersMgmt />;
      if (activeTab === 'admin-family-links') return <AdminFamilyLinksMgmt />;
      if (activeTab === 'admin-approval' || activeTab === 'admin-approvals') return <AdminApprovalsMgmt />;
      if (activeTab === 'admin-logs' || activeTab === 'admin-security-logs') return <AdminAuditLogsMgmt />;
      if (activeTab === 'admin-data-backup') return <AdminDataBackupMgmt />;
      if (activeTab === 'admin-packages') return <ServicePackageManagement />;
      if (activeTab === 'admin-payments') return <PaymentTransactionManagement />;
      if (activeTab === 'admin-moderation') return <ModerationManagement />;
      if (activeTab === 'admin-roles') return <RolePermissionManagement />;

      return (
        <AdminDashboard
          userName={displayUserName}
          onNavigateTab={handleSelectTab}
        />
      );
    }

    // ===== Branch for Member (38 FRs) =====
    const isFamilyHead = primaryRole === 'family_head';
    const canManageFamily = isFamilyHead || isFamilyManager;

    if (activeTab === 'notifications') return <NotificationCenterModule />;
    if (activeTab === 'relationship-finder') return canManageFamily ? <FamilyAdminModule view="search" /> : <RelationshipFinder />;
    if (activeTab === 'my-proposals') return <MyProposalsModule />;
    if (activeTab === 'anniversaries') return <AnniversariesModule />;
    if (activeTab === 'events') return <ClanEventsModule canManage={canManageFamily} />;
    if (activeTab === 'funds') return <ClanFundsModule canManage={canManageFamily} />;
    if (activeTab === 'documents') return <ClanDocumentsModule canManage={canManageFamily} />;
    if (activeTab === 'ai-assistant') return <ClanAIAssistantModule />;
    if (activeTab === 'ai-consent') return <AIConsentModule />;
    if (activeTab === 'ancestral-hall') return <DigitalAncestralHallModule onOpenLibrary={(ancestorId) => { setSelectedAncestorId(ancestorId); handleSelectTab('ancestral-library'); }} />;
    if (activeTab === 'ancestral-library') return <AncestralLibraryModule initialAncestorId={selectedAncestorId} onOpenWorship={(ancestorId) => { setSelectedAncestorId(ancestorId); handleSelectTab('ancestral-hall'); }} />;
    if (activeTab === 'privacy-settings' || activeTab === 'privacy-preview') return <PrivacySettingsTab />;
    if (activeTab.startsWith('family-') && !canManageFamily) {
      return <section className="dashboard-permission-page"><div className="dashboard-permission-icon">🔒</div><span>QUYỀN TRUY CẬP DỮ LIỆU</span><h1>Chức năng dành cho Quản trị viên dòng họ</h1><p>Tài khoản Thành viên có thể xem dữ liệu được chia sẻ nhưng không thể mở khu vực quản lý, phê duyệt hoặc xuất nhập dữ liệu.</p><button type="button" onClick={() => handleSelectTab('dashboard')}>Quay lại Trang chủ</button></section>;
    }
    const familyViews: Record<string, FamilyAdminView> = {
      'family-members': 'members', 'family-relations': 'relations', 'family-tree': 'tree',
      'family-search': 'search', 'family-branches': 'branches', 'family-approvals': 'approvals',
      'family-accounts': 'accounts', 'family-links': 'links',
      'family-import-export': 'exchange', 'family-logs': 'audit',
    };
    if (familyViews[activeTab]) {
      const tabs: Record<FamilyAdminView, string> = {
        overview: 'dashboard', members: 'family-members', relations: 'family-relations',
        tree: 'family-tree', search: 'family-search', branches: 'family-branches',
        approvals: 'family-approvals', accounts: 'family-accounts', links: 'family-links',
        exchange: 'family-import-export', audit: 'family-logs',
      };
      return <FamilyAdminModule view={familyViews[activeTab]} onNavigate={(view) => handleSelectTab(tabs[view])} />;
    }

    // Network tabs
    if (activeTab === 'net-noi') return <FamilyPaternalTab />;
    if (activeTab === 'net-ngoai') return <FamilyMaternalTab />;
    if (activeTab === 'net-dau-re') return <InLawMarriagesTab />;
    if (activeTab === 'net-thong-gia') return <AffiliatedFamiliesTab />;

    // Tree Layout
    if (activeTab.startsWith('tree')) {
      if (canManageFamily) return <FamilyAdminModule view="tree" onNavigate={() => handleSelectTab('family-relations')} />;
      const mode: TreeViewMode =
        activeTab === 'tree-horizontal'
          ? 'horizontal'
          : activeTab === 'tree-focus'
          ? 'focus'
          : 'vertical';
      return (
        <TreeLayout
          initialMode={mode}
          onSelectMemberProfile={(memberId) => {
            setSelectedMemberId(memberId);
            setActiveTab('member-profile');
            navigate(ROUTES.USER.MEMBER_PROFILE, { replace: false });
          }}
        />
      );
    }

    // Profile & Member List
    if (activeTab === 'my-profile') {
      return (
        <ProfileLayout
          memberId={(account as any)?.person_id || selectedMemberId || 'mem_001'}
          onBack={() => {
            setActiveTab('dashboard');
            navigate(ROUTES.USER.ROOT, { replace: false });
          }}
        />
      );
    }

    if (activeTab === 'member-profile') {
      return (
        <ProfileLayout
          memberId={selectedMemberId || 'mem_001'}
          onBack={() => {
            setSelectedMemberId(null);
            setActiveTab('member-list');
            navigate(ROUTES.USER.MEMBERS, { replace: false });
          }}
        />
      );
    }

    if (activeTab === 'member-list') {
      return <MemberList onSelectMember={handleSelectMember} />;
    }



    // Default Member Dashboard
    return (
      <MemberDashboard
        userName={displayUserName}
        userRole={userRole}
        onNavigateTab={handleSelectTab}
      />
    );
  };

  return (
    <div className="dashboard-page-container">
      <TopBar
        userName={displayUserName}
        userRole={userRole}
        onLogout={onLogout}
        isSidebarCollapsed={isSidebarCollapsed}
        onToggleSidebar={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onNavigateTab={handleSelectTab}
      />

      <div className="dashboard-body-row">
        <Sidebar
          activeTab={activeTab}
          onSelectTab={handleSelectTab}
          isCollapsed={isSidebarCollapsed}
          userRole={userRole}
        />

        <main
          className={`dashboard-main-content ${
            isSidebarCollapsed ? 'collapsed-sidebar' : 'expanded-sidebar'
          }`}
        >
          {renderMainContent()}
        </main>
      </div>

      <footer className="dashboard-footer">
        <div className="dashboard-footer-inner">
          <strong className="dashboard-footer-brand">MULTI-FAMILY GENEALOGY SYSTEM</strong> © 2026 •
          Số hóa & Gắn kết các dòng họ Việt Nam.
        </div>
      </footer>

      <NotificationModal
        isOpen={isProcessingToastOpen}
        onClose={() => setIsProcessingToastOpen(false)}
      />

      {/* Mandatory First-Time Password Modal */}
      <FirstLoginPasswordModal
        isOpen={showFirstLoginModal}
        onSuccess={() => setShowFirstLoginModal(false)}
        onCancel={onLogout}
      />
    </div>
  );
};

export default Dashboard;
