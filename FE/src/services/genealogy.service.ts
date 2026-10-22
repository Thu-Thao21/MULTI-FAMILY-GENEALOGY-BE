import apiClient from '../api/axios';

export interface PersonItem {
  id: string;
  familyId: string;
  branchId?: string | null;
  fullName: string;
  gender: string;
  birthDate?: string | null;
  deathDate?: string | null;
  generation: number;
  avatarUrl?: string | null;
  isLiving: boolean;
  status: string;
}

export interface PersonCreatePayload {
  fullName: string;
  branchId?: string | null;
  gender?: string;
  birthDate?: string | null;
  deathDate?: string | null;
  avatarUrl?: string | null;
  isLiving?: boolean;
  status?: string;
}

export interface PersonUpdatePayload {
  fullName?: string;
  branchId?: string | null;
  gender?: string;
  birthDate?: string | null;
  deathDate?: string | null;
  avatarUrl?: string | null;
  isLiving?: boolean;
  status?: string;
}

export interface RelationshipItem {
  id: string;
  fromMemberId: string;
  toMemberId: string;
  relationshipType: string;
  notes?: string | null;
}

export interface RelationshipCreatePayload {
  fromMemberId: string;
  toMemberId: string;
  relationshipType: string;
  notes?: string | null;
}

export interface AncestorDescendantItem {
  person: PersonItem;
  depth: number;
}

export interface TreeDataResponse {
  nodes: Array<{
    id: string;
    fullName: string;
    gender: string;
    generation: number;
    branchId?: string | null;
    avatarUrl?: string | null;
    isLiving?: boolean;
    status: string;
  }>;
  edges: RelationshipItem[];
}

export interface FocusViewNode {
  id: string;
  fullName: string;
  gender: string;
  generation: number;
  branchId?: string | null;
  avatarUrl?: string | null;
  depth: number;
  isEgo: boolean;
  status: string;
}

export interface FocusViewResponse {
  ego: PersonItem;
  nodes: FocusViewNode[];
  edges: RelationshipItem[];
  maxDepth: number;
}

export interface RelationshipCalculationResponse {
  found: boolean;
  fromPerson?: PersonItem;
  toPerson?: PersonItem;
  path: PersonItem[];
  edges: RelationshipItem[];
  kinshipName: string;
  addressTitle: string;
  generationDiff: number;
  description: string;
}

export interface PublicClanItem {
  id: string;
  name: string;
  clan_code?: string;
  status: string;
  activated_at?: string;
}

/** GET /api/v1/families/{family_id}/persons */
export async function fetchFamilyPersons(
  familyId: string,
  params: {
    search?: string;
    gender?: string;
    branchId?: string;
    isLiving?: boolean;
    limit?: number;
    offset?: number;
  } = {}
): Promise<PersonItem[]> {
  const res = await apiClient.get<PersonItem[]>(`/api/v1/families/${familyId}/persons`, {
    params: {
      search: params.search || undefined,
      gender: params.gender || undefined,
      branchId: params.branchId || undefined,
      isLiving: params.isLiving,
      limit: params.limit ?? 100,
      offset: params.offset ?? 0,
    },
  });
  return res.data;
}

/** POST /api/v1/families/{family_id}/persons */
export async function createFamilyPerson(
  familyId: string,
  payload: PersonCreatePayload
): Promise<PersonItem> {
  const res = await apiClient.post<PersonItem>(`/api/v1/families/${familyId}/persons`, payload);
  return res.data;
}

/** GET /api/v1/families/{family_id}/persons/{person_id} */
export async function getFamilyPerson(
  familyId: string,
  personId: string
): Promise<PersonItem> {
  const res = await apiClient.get<PersonItem>(`/api/v1/families/${familyId}/persons/${personId}`);
  return res.data;
}

/** PATCH /api/v1/families/{family_id}/persons/{person_id} */
export async function updateFamilyPerson(
  familyId: string,
  personId: string,
  payload: PersonUpdatePayload
): Promise<PersonItem> {
  const res = await apiClient.patch<PersonItem>(`/api/v1/families/${familyId}/persons/${personId}`, payload);
  return res.data;
}

/** POST /api/v1/families/{family_id}/relationships */
export async function createFamilyRelationship(
  familyId: string,
  payload: RelationshipCreatePayload
): Promise<RelationshipItem> {
  const res = await apiClient.post<RelationshipItem>(`/api/v1/families/${familyId}/relationships`, payload);
  return res.data;
}

/** DELETE /api/v1/families/{family_id}/relationships/{relationship_id} */
export async function deleteFamilyRelationship(
  familyId: string,
  relationshipId: string
): Promise<void> {
  await apiClient.delete(`/api/v1/families/${familyId}/relationships/${relationshipId}`);
}

/** GET /api/v1/families/{family_id}/persons/{person_id}/ancestors */
export async function fetchPersonAncestors(
  familyId: string,
  personId: string
): Promise<AncestorDescendantItem[]> {
  const res = await apiClient.get<AncestorDescendantItem[]>(
    `/api/v1/families/${familyId}/persons/${personId}/ancestors`
  );
  return res.data;
}

/** GET /api/v1/families/{family_id}/persons/{person_id}/descendants */
export async function fetchPersonDescendants(
  familyId: string,
  personId: string
): Promise<AncestorDescendantItem[]> {
  const res = await apiClient.get<AncestorDescendantItem[]>(
    `/api/v1/families/${familyId}/persons/${personId}/descendants`
  );
  return res.data;
}

/** GET /api/v1/families/{family_id}/tree-data */
export async function fetchFamilyTreeData(
  familyId: string,
  params?: {
    branchId?: string;
    generation?: number;
    maxGeneration?: number;
  }
): Promise<TreeDataResponse> {
  const res = await apiClient.get<TreeDataResponse>(`/api/v1/families/${familyId}/tree-data`, {
    params: {
      branchId: params?.branchId || undefined,
      generation: params?.generation,
      maxGeneration: params?.maxGeneration,
    },
  });
  return res.data;
}

/** GET /api/v1/families/{family_id}/persons/{person_id}/focus-view */
export async function fetchFocusView(
  familyId: string,
  personId: string,
  depth: number = 2
): Promise<FocusViewResponse> {
  const res = await apiClient.get<FocusViewResponse>(
    `/api/v1/families/${familyId}/persons/${personId}/focus-view`,
    { params: { depth } }
  );
  return res.data;
}

/** GET /api/v1/families/{family_id}/relationship-path */
export async function fetchRelationshipCalculation(
  familyId: string,
  fromPersonId: string,
  toPersonId: string
): Promise<RelationshipCalculationResponse> {
  const res = await apiClient.get<RelationshipCalculationResponse>(
    `/api/v1/families/${familyId}/relationship-path`,
    {
      params: {
        fromPersonId,
        toPersonId,
      },
    }
  );
  return res.data;
}

/** GET /public/families (Khách tìm kiếm dòng họ công khai) */
export async function fetchPublicClans(search?: string): Promise<PublicClanItem[]> {
  const res = await apiClient.get<PublicClanItem[]>('/public/families', {
    params: { search: search || undefined },
  });
  return res.data;
}

/** GET /api/v1/families/{family_id}/public-tree (Cây công khai có che giấu dữ liệu riêng tư) */
export async function fetchPublicClanTree(familyId: string): Promise<TreeDataResponse> {
  const res = await apiClient.get<TreeDataResponse>(`/api/v1/families/${familyId}/public-tree`);
  return res.data;
}
