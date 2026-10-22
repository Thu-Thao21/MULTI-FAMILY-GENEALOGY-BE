export type ServicePackageStatus = 'active' | 'draft' | 'disabled';

export interface ServicePackage {
  id: string;
  code: string;
  name: string;
  description: string;
  monthlyPrice: number;
  durationMonths: number;
  memberLimit: number;
  storageGb: number;
  subscriberCount: number;
  features: string[];
  status: ServicePackageStatus;
  updatedAt: string;
}

export const initialServicePackages: ServicePackage[] = [];


export type PaymentStatus = 'pending' | 'success' | 'failed' | 'refunded';
export type PaymentMethod = 'VNPay' | 'MoMo' | 'Chuyển khoản' | 'Thẻ quốc tế';

export interface PaymentTransaction {
  id: string;
  userName: string;
  userEmail: string;
  familyName: string;
  packageName: string;
  amount: number;
  method: PaymentMethod;
  createdAt: string;
  status: PaymentStatus;
  reference: string;
  note: string;
}

export const initialPaymentTransactions: PaymentTransaction[] = [];

export type ModerationStatus = 'pending' | 'reviewing' | 'resolved' | 'rejected';
export type ModerationPriority = 'high' | 'medium' | 'low';
export type ModerationContentType = 'Hồ sơ thành viên' | 'Lời tưởng niệm' | 'Tư liệu số' | 'Bình luận sự kiện';

export interface ModerationReport {
  id: string;
  contentType: ModerationContentType;
  contentTitle: string;
  reportedUser: string;
  reporter: string;
  reason: string;
  description: string;
  createdAt: string;
  status: ModerationStatus;
  priority: ModerationPriority;
  contentHidden: boolean;
}

export const initialModerationReports: ModerationReport[] = [];


export type PermissionAction = 'view' | 'create' | 'update' | 'delete';

export interface PermissionSet {
  view: boolean;
  create: boolean;
  update: boolean;
  delete: boolean;
}

export interface PermissionModule {
  id: string;
  label: string;
  description: string;
  category: 'Gia phả' | 'Đời sống dòng họ' | 'Nền tảng';
}

export interface RoleDefinition {
  id: string;
  name: string;
  description: string;
  memberCount: number;
  locked?: boolean;
  permissions: Record<string, PermissionSet>;
}

export const permissionModules: PermissionModule[] = [
  { id: 'members', label: 'Hồ sơ thành viên', description: 'Thông tin nhân khẩu và hồ sơ cá nhân.', category: 'Gia phả' },
  { id: 'tree', label: 'Cây gia phả', description: 'Cấu trúc phả hệ và quan hệ huyết thống.', category: 'Gia phả' },
  { id: 'relationships', label: 'Đề xuất quan hệ', description: 'Đề xuất và phê duyệt thay đổi quan hệ.', category: 'Gia phả' },
  { id: 'events', label: 'Sự kiện dòng họ', description: 'Lịch, người tham gia và nội dung sự kiện.', category: 'Đời sống dòng họ' },
  { id: 'funds', label: 'Quỹ dòng họ', description: 'Thu, chi và xác nhận giao dịch quỹ.', category: 'Đời sống dòng họ' },
  { id: 'archive', label: 'Kho tư liệu số', description: 'Ảnh, video, âm thanh và tài liệu lịch sử.', category: 'Đời sống dòng họ' },
  { id: 'worship', label: 'Không gian thờ số', description: 'Gian thờ, hương ảo và lời tưởng niệm.', category: 'Đời sống dòng họ' },
  { id: 'packages', label: 'Gói dịch vụ', description: 'Danh mục và trạng thái gói nền tảng.', category: 'Nền tảng' },
  { id: 'payments', label: 'Thanh toán', description: 'Đối soát và hoàn tiền giao dịch.', category: 'Nền tảng' },
  { id: 'moderation', label: 'Kiểm duyệt', description: 'Báo cáo nội dung và xử lý vi phạm.', category: 'Nền tảng' },
  { id: 'audit', label: 'Nhật ký hệ thống', description: 'Lịch sử thao tác và sự kiện bảo mật.', category: 'Nền tảng' },
];

const none = (): PermissionSet => ({ view: false, create: false, update: false, delete: false });
const read = (): PermissionSet => ({ view: true, create: false, update: false, delete: false });
const manage = (): PermissionSet => ({ view: true, create: true, update: true, delete: false });
const full = (): PermissionSet => ({ view: true, create: true, update: true, delete: true });

export const initialRoleDefinitions: RoleDefinition[] = [
  {
    id: 'system-admin',
    name: 'Quản trị viên hệ thống',
    description: 'Toàn quyền vận hành nền tảng. Vai trò lõi không thể chỉnh sửa.',
    memberCount: 0,
    locked: true,
    permissions: Object.fromEntries(permissionModules.map((module) => [module.id, full()])),
  },
  {
    id: 'family-head',
    name: 'Chủ dòng họ',
    description: 'Quản lý dữ liệu, thành viên và hoạt động trong dòng họ phụ trách.',
    memberCount: 0,
    permissions: {
      members: full(), tree: full(), relationships: manage(), events: full(), funds: manage(), archive: full(), worship: manage(),
      packages: read(), payments: read(), moderation: read(), audit: read(),
    },
  },
  {
    id: 'moderator',
    name: 'Điều phối viên nội dung',
    description: 'Xử lý báo cáo, duyệt tư liệu và hỗ trợ hoạt động cộng đồng.',
    memberCount: 0,
    permissions: {
      members: read(), tree: read(), relationships: manage(), events: manage(), funds: read(), archive: manage(), worship: manage(),
      packages: none(), payments: none(), moderation: manage(), audit: read(),
    },
  },
  {
    id: 'member',
    name: 'Thành viên',
    description: 'Xem dữ liệu được chia sẻ và đóng góp nội dung theo quyền riêng tư.',
    memberCount: 0,
    permissions: {
      members: read(), tree: read(), relationships: { view: true, create: true, update: false, delete: false },
      events: { view: true, create: false, update: false, delete: false }, funds: read(),
      archive: { view: true, create: true, update: false, delete: false }, worship: { view: true, create: true, update: false, delete: false },
      packages: read(), payments: none(), moderation: { view: true, create: true, update: false, delete: false }, audit: none(),
    },
  },
];

export function cloneRoleDefinitions(roles: RoleDefinition[]): RoleDefinition[] {
  return roles.map((role) => ({
    ...role,
    permissions: Object.fromEntries(
      Object.entries(role.permissions).map(([moduleId, permissions]) => [moduleId, { ...permissions }])
    ),
  }));
}
