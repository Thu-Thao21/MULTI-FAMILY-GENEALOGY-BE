import apiClient from '../api/axios';
import type { Page } from './business.service';

export interface AdminUserItem {
  user_id: string;
  email: string;
  display_name: string;
  status: 'ACTIVE' | 'LOCKED' | 'SUSPENDED' | 'DISABLED' | string;
  last_login_at?: string | null;
  created_at: string;
}

export interface AdminUserDetail extends AdminUserItem {
  username?: string | null;
  phone?: string | null;
  email_verified: boolean;
  phone_verified: boolean;
  requires_password_change: boolean;
}

export interface AdminRegistrationSummary {
  registration_id: string;
  clan_name: string;
  representative_name: string;
  requested_plan_id: string;
  requested_plan_code: string;
  status: 'DRAFT' | 'PENDING' | 'APPROVED' | 'NEED_SUPPLEMENT' | 'REJECTED' | 'CANCELLED';
  created_at: string;
  reviewed_at?: string | null;
}

export interface AdminRegistrationDetail extends AdminRegistrationSummary {
  representative_email: string;
  representative_phone?: string | null;
  origin_place?: string | null;
  reviewed_by?: string | null;
  rejection_reason?: string | null;
  updated_at: string;
  clan_id?: string | null;
}

/** GET /admin/users */
export async function fetchAdminUsers(params: {
  q?: string;
  status?: string;
  page?: number;
  page_size?: number;
} = {}): Promise<Page<AdminUserItem>> {
  const res = await apiClient.get<Page<AdminUserItem>>('/admin/users', {
    params: {
      q: params.q || undefined,
      status: params.status || undefined,
      page: params.page ?? 1,
      page_size: params.page_size ?? 50,
    },
  });
  return res.data;
}

/** GET /admin/users/{user_id} */
export async function fetchAdminUserDetail(userId: string): Promise<AdminUserDetail> {
  const res = await apiClient.get<AdminUserDetail>(`/admin/users/${userId}`);
  return res.data;
}

/** PATCH /admin/users/{user_id}/status */
export async function updateAdminUserStatus(
  userId: string,
  status: 'ACTIVE' | 'LOCKED' | 'SUSPENDED' | 'DISABLED',
  reason: string = 'Thay đổi bởi quản trị viên hệ thống'
): Promise<{ user_id: string; status: string }> {
  const res = await apiClient.patch(`/admin/users/${userId}/status`, {
    status,
    reason,
  });
  return res.data;
}

/** GET /admin/business-registrations */
export async function fetchAdminRegistrations(params: {
  q?: string;
  status?: string;
  page?: number;
  page_size?: number;
} = {}): Promise<Page<AdminRegistrationSummary>> {
  const res = await apiClient.get<Page<AdminRegistrationSummary>>('/admin/business-registrations', {
    params: {
      q: params.q || undefined,
      status: params.status || undefined,
      page: params.page ?? 1,
      page_size: params.page_size ?? 50,
    },
  });
  return res.data;
}

/** GET /admin/business-registrations/{registration_id} */
export async function fetchAdminRegistrationDetail(registrationId: string): Promise<AdminRegistrationDetail> {
  const res = await apiClient.get<AdminRegistrationDetail>(`/admin/business-registrations/${registrationId}`);
  return res.data;
}

/** POST /admin/business-registrations/{registration_id}/review */
export async function reviewAdminRegistration(
  registrationId: string,
  decision: 'APPROVED' | 'REJECTED',
  reason?: string
): Promise<{ registration_id: string; status: string }> {
  const res = await apiClient.post(`/admin/business-registrations/${registrationId}/review`, {
    decision,
    reason: reason || undefined,
  });
  return res.data;
}

/** POST /admin/business-registrations/{registration_id}/business - tạo dòng họ từ hồ sơ duyệt */
export async function createClanFromRegistration(
  registrationId: string,
  clanCode?: string
): Promise<{ clan_id: string; status: string }> {
  const res = await apiClient.post(`/admin/business-registrations/${registrationId}/business`, {
    clan_code: clanCode || undefined,
  });
  return res.data;
}

/** POST /admin/clans/{clan_id}/activate */
export async function activateClan(clanId: string): Promise<{ clan_id: string; status: string }> {
  const res = await apiClient.post(`/admin/clans/${clanId}/activate`);
  return res.data;
}

export interface ApproveAndProvisionResponse {
  registration_id: string;
  clan_id: string;
  clan_name: string;
  status: string;
  clan_status: string;
  owner_email: string;
  owner_display_name: string;
  temporary_password?: string | null;
  temporary_password_expires_at?: string | null;
  email_sent: boolean;
  email_delivery_status?: string | null;
  message: string;
}

/** POST /admin/business-registrations/{registration_id}/approve-and-provision */
export async function approveAndProvisionRegistration(
  registrationId: string,
  clanCode?: string
): Promise<ApproveAndProvisionResponse> {
  const res = await apiClient.post<ApproveAndProvisionResponse>(
    `/admin/business-registrations/${registrationId}/approve-and-provision`,
    { clan_code: clanCode || undefined },
    { timeout: 35000 }
  );
  return res.data;
}

