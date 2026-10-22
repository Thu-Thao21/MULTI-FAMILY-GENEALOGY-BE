import apiClient from '../api/axios';
import type { FamilyLinkRequest, FamilyNetwork, InLawMarriage } from '../types/network';

export async function fetchFamilyNetwork(category: string = 'all'): Promise<FamilyNetwork[]> {
  try {
    const res = await apiClient.get('/networks/families', { params: { category } });
    const data = Array.isArray(res.data) ? res.data : Array.isArray(res.data?.items) ? res.data.items : [];
    return data;
  } catch (err) {
    console.error('API fetchFamilyNetwork error:', err);
    return [];
  }
}

export async function fetchInLawMarriages(): Promise<InLawMarriage[]> {
  try {
    const res = await apiClient.get('/networks/inlaw-marriages');
    const data = Array.isArray(res.data) ? res.data : Array.isArray(res.data?.items) ? res.data.items : [];
    return data;
  } catch (err) {
    console.error('API fetchInLawMarriages error:', err);
    return [];
  }
}

export async function fetchLinkRequests(): Promise<FamilyLinkRequest[]> {
  try {
    const res = await apiClient.get('/networks/link-requests');
    const data = Array.isArray(res.data) ? res.data : Array.isArray(res.data?.items) ? res.data.items : [];
    return data;
  } catch (err) {
    console.error('API fetchLinkRequests error:', err);
    return [];
  }
}

export async function sendLinkRequest(
  targetFamilyId: string,
  requestType: string = 'marriage',
  message?: string,
): Promise<FamilyLinkRequest> {
  const res = await apiClient.post('/networks/link-requests', {
    target_family_id: targetFamilyId,
    request_type: requestType,
    message,
  });
  return res.data;
}

export async function reviewLinkRequest(
  requestId: string,
  action: 'APPROVE' | 'REJECT',
  reason?: string
): Promise<{ status: string }> {
  const res = await apiClient.post(`/networks/link-requests/${requestId}/review`, {
    action,
    reason,
  });
  return res.data;
}

