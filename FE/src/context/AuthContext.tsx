import React, { createContext, useContext, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { onAuthStateChanged, signOut, type User as FirebaseUser } from 'firebase/auth';
import { auth } from '../config/firebase';
import apiClient from '../api/axios';
import { readApiError } from '../api/apiError';
import { clearSession, hasSession, onSessionInvalid, setSession } from '../api/session';
import {
  changePassword as changePasswordRequest,
  establishSession,
  fetchCurrentAccount,
  loginWithEmailPassword,
  logoutSession,
} from '../services/auth.service';
import type { MembershipSummary, SessionCreateResponse } from '../types/auth';

export interface AccountRoleInfo {
  id: string;
  role: string;
  family_id?: string | null;
  status: string;
}

export interface AccountProfile {
  id: string;
  firebase_uid: string;
  username?: string | null;
  email?: string | null;
  phone_e164?: string | null;
  display_name?: string | null;
  email_verified: boolean;
  phone_verified: boolean;
  status: string;
  roles: AccountRoleInfo[];
  primary_role: 'admin' | 'member' | string;
  /** Từ GET /auth/me: true là phiên hạn chế, phải đổi mật khẩu trước. */
  requires_password_change?: boolean;
  /** Từ GET /auth/me: dòng họ, vai trò và quyền hiệu lực trong từng dòng họ. */
  memberships?: MembershipSummary[];
  /** Từ GET /auth/me: quyền cấp hệ thống (tạm thời, không hard-code). */
  permissions?: string[];
}

interface AuthContextType {
  firebaseUser: FirebaseUser | null;
  account: AccountProfile | null;
  isAuthenticated: boolean;
  loading: boolean;
  primaryRole: string;
  login: (payload: { emailOrPhone: string; password: string }) => Promise<AccountProfile>;
  refreshAccount: () => Promise<AccountProfile | null>;
  /** POST /auth/change-password; thành công thì phiên bị thu hồi và phải đăng nhập lại. */
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const navigate = useNavigate();
  const [firebaseUser, setFirebaseUser] = useState<FirebaseUser | null>(null);
  const [account, setAccount] = useState<AccountProfile | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  /**
   * Lấy người dùng từ GET /auth/me. Nếu Firebase đã đăng nhập mà chưa có phiên BE
   * (ví dụ vừa tải lại trang), đổi ID token lấy phiên qua POST /auth/session trước.
   */
  const fetchAccount = async (): Promise<AccountProfile | null> => {
    const user = auth.currentUser;
    if (!user) {
      clearSession();
      setAccount(null);
      return null;
    }
    try {
      if (!hasSession()) {
        await establishSession(user);
      }
      const profile = await fetchCurrentAccount();
      setAccount(profile);
      return profile;
    } catch (error) {
      // Không log nguyên đối tượng lỗi: nó chứa header Authorization.
      const info = readApiError(error);
      console.warn('Không lấy được phiên hoặc tài khoản từ Backend:', info.status, info.code, info.requestId);
      clearSession();
      setAccount(null);
      // Token không đổi được phiên (chưa được cấp, bị khóa, mật khẩu tạm hết hạn): đăng xuất Firebase.
      if (info.status === 401 || info.status === 403) {
        await signOut(auth).catch(() => undefined);
      }
      return null;
    }
  };

  const login = async (payload: { emailOrPhone: string; password: string }): Promise<AccountProfile> => {
    const ident = payload.emailOrPhone.trim().toLowerCase();
    const isDevIdent =
      ident === 'admin@test.com' ||
      ident === 'admin' ||
      ident === 'dev-sa@example.test' ||
      ident === 'dev-sa' ||
      ident === 'member@test.com' ||
      ident === 'member' ||
      ident === 'dev-member-a@example.test' ||
      ident === 'dev-member-a';

    if (isDevIdent) {
      const res = await apiClient.post<SessionCreateResponse>('/auth/dev-session', { email: ident });
      setSession({ accessToken: res.data.access_token, expiresAt: res.data.expires_at });
      const profile = await fetchCurrentAccount();
      setAccount(profile);
      return profile;
    }

    const profile = await loginWithEmailPassword({
      email: payload.emailOrPhone,
      password: payload.password,
    });
    setAccount(profile);
    return profile;
  };

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, async (user) => {
      setFirebaseUser(user);
      if (user) {
        // Firebase đã đăng nhập: tạo phiên BE (nếu chưa có) rồi lấy tài khoản từ /auth/me
        await fetchAccount();
      } else {
        clearSession();
        setAccount(null);
      }
      setLoading(false);
    });
    return () => unsubscribe();
  }, []);

  // BE trả 401 SESSION_INVALID: phiên đã bị xóa, đăng xuất Firebase và về trang đăng nhập.
  useEffect(() => {
    return onSessionInvalid(() => {
      setAccount(null);
      void signOut(auth).catch(() => undefined);
      navigate('/login', { replace: true });
    });
  }, [navigate]);

  const changePassword = async (currentPassword: string, newPassword: string) => {
    await changePasswordRequest(currentPassword, newPassword);
    // Mọi phiên đã bị thu hồi: phải đăng nhập lại bằng mật khẩu mới.
    setFirebaseUser(null);
    setAccount(null);
  };

  const logout = async () => {
    setLoading(true);
    try {
      await logoutSession();
    } catch (e) {
      console.error('Logout error:', e);
    } finally {
      clearSession();
      setFirebaseUser(null);
      setAccount(null);
      setLoading(false);
    }
  };

  const primaryRole = account?.primary_role || 'member';

  return (
    <AuthContext.Provider
      value={{
        firebaseUser,
        account,
        isAuthenticated: !!account,
        loading,
        primaryRole,
        login,
        refreshAccount: fetchAccount,
        changePassword,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );

};

export function useAuthContext() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuthContext must be used within an AuthProvider');
  }
  return context;
}
