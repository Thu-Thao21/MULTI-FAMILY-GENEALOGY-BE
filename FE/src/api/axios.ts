import axios, { InternalAxiosRequestConfig, AxiosResponse, AxiosError } from 'axios';
import { API_HOST_CONFIG } from '../config/routes';
import { readApiError } from './apiError';
import { getAccessToken, notifySessionInvalid } from './session';

const API_BASE_URL = API_HOST_CONFIG.BASE_URL;
if (!API_BASE_URL) {
  console.error('VITE_API_BASE_URL chưa được cấu hình: không thể gọi Backend API.');
}

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30000,
});

// Chỉ gửi access_token của BE mới (lấy từ POST /auth/session); không gửi Firebase ID token.
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const accessToken = getAccessToken();
    if (accessToken && !config.headers.Authorization) {
      config.headers.Authorization = `Bearer ${accessToken}`;
    }
    return config;
  },
  (error: AxiosError) => Promise.reject(error)
);

apiClient.interceptors.response.use(
  (response: AxiosResponse) => response,
  (error: AxiosError) => {
    const { status, code } = readApiError(error);
    // Phiên hết hạn, đã đăng xuất hoặc bị thu hồi: xóa phiên và quay về trang đăng nhập.
    if (status === 401 && code === 'SESSION_INVALID' && error.config?.url !== '/auth/logout') {
      notifySessionInvalid();
    }
    return Promise.reject(error);
  }
);

export default apiClient;
