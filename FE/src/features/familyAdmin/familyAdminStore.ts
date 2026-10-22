import { useSyncExternalStore } from 'react';
import {
  fetchFamilyPersons,
  fetchFamilyTreeData,
  createFamilyPerson,
  updateFamilyPerson,
  createFamilyRelationship,
  deleteFamilyRelationship,
} from '../../services/genealogy.service';

export type PersonVisibility = 'family' | 'admin' | 'private';
export type RelationType = 'father' | 'mother' | 'spouse' | 'adoptive_parent' | 'step_parent';
export type RequestStatus = 'pending' | 'approved' | 'rejected';

export interface FamilyPerson {
  id: string;
  fullName: string;
  gender: 'male' | 'female' | 'other';
  birthDate: string;
  deathDate: string;
  branchId: string;
  generation: number;
  phone: string;
  email: string;
  bio: string;
  hidden: boolean;
  visibility: PersonVisibility;
}

export interface FamilyRelation {
  id: string;
  type: RelationType;
  fromId: string;
  toId: string;
  since: string;
}

export interface FamilyBranch {
  id: string;
  name: string;
  founderId: string;
  description: string;
}

export interface FamilyAccount {
  id: string;
  personId: string;
  username: string;
  email: string;
  role: 'owner' | 'member';
  status: 'pending' | 'active' | 'locked';
  resetRequestedAt?: string;
}

export interface FamilyProposal {
  id: string;
  type: 'profile' | 'relationship';
  personId: string;
  proposer: string;
  summary: string;
  field?: 'fullName' | 'birthDate' | 'bio';
  proposedValue?: string;
  relation?: Pick<FamilyRelation, 'type' | 'fromId' | 'toId' | 'since'>;
  status: RequestStatus;
  reviewedAt?: string;
  note?: string;
}

export interface FamilyLinkRequest {
  id: string;
  targetFamily: string;
  reason: string;
  status: RequestStatus;
  createdAt: string;
}

export interface FamilyAdminState {
  familyName: string;
  persons: FamilyPerson[];
  relations: FamilyRelation[];
  branches: FamilyBranch[];
  accounts: FamilyAccount[];
  proposals: FamilyProposal[];
  linkRequests: FamilyLinkRequest[];
  audit: { id: string; at: string; action: string }[];
}

const STORAGE_KEY = 'mfgms.familyAdmin.frontend.v2';

const initialState: FamilyAdminState = {
  familyName: 'Gia đình A (Dòng họ Nguyễn)',
  branches: [
    { id: 'branch-1', name: 'Chi Trưởng', founderId: 'p-001', description: 'Chi trưởng dòng họ Nguyễn' },
    { id: 'branch-2', name: 'Chi Thứ', founderId: 'p-003', description: 'Chi thứ hai' },
  ],
  persons: [
    { id: 'p-001', fullName: 'Nguyễn Văn An', gender: 'male', birthDate: '1940-01-01', deathDate: '2010-05-20', branchId: 'branch-1', generation: 1, phone: '', email: '', bio: 'Thế hệ 1 - Tổ phụ', hidden: false, visibility: 'family' },
    { id: 'p-002', fullName: 'Trần Thị Bình', gender: 'female', birthDate: '1945-03-15', deathDate: '2015-08-10', branchId: 'branch-1', generation: 1, phone: '', email: '', bio: 'Thế hệ 1 - Vợ P001', hidden: false, visibility: 'family' },
    { id: 'p-003', fullName: 'Nguyễn Văn Cường', gender: 'male', birthDate: '1970-06-20', deathDate: '', branchId: 'branch-1', generation: 2, phone: '', email: '', bio: 'Thế hệ 2 - Con P001 và P002', hidden: false, visibility: 'family' },
    { id: 'p-004', fullName: 'Nguyễn Thị Dung', gender: 'female', birthDate: '1975-09-12', deathDate: '', branchId: 'branch-1', generation: 2, phone: '', email: '', bio: 'Thế hệ 2 - Con P001 và P002', hidden: false, visibility: 'family' },
    { id: 'p-005', fullName: 'Lê Thị Hoa', gender: 'female', birthDate: '1973-11-05', deathDate: '', branchId: 'branch-1', generation: 2, phone: '', email: '', bio: 'Thế hệ 2 - Vợ P003', hidden: false, visibility: 'family' },
    { id: 'p-006', fullName: 'Nguyễn Văn Minh', gender: 'male', birthDate: '2000-02-28', deathDate: '', branchId: 'branch-1', generation: 3, phone: '', email: '', bio: 'Thế hệ 3 - Cháu nội P001', hidden: false, visibility: 'family' },
    { id: 'p-007', fullName: 'Nguyễn Văn Nam', gender: 'male', birthDate: '1980-04-18', deathDate: '', branchId: 'branch-2', generation: 2, phone: '', email: '', bio: 'Người không có quan hệ với P001–P006', hidden: false, visibility: 'family' },
    { id: 'p-008', fullName: 'Nguyễn Văn An', gender: 'male', birthDate: '2005-12-01', deathDate: '', branchId: 'branch-1', generation: 3, phone: '', email: '', bio: 'Người trùng tên với P001 nhưng là người khác', hidden: false, visibility: 'family' },
    { id: 'p-009', fullName: 'Người chưa xác định cha mẹ', gender: 'male', birthDate: '1990-07-07', deathDate: '', branchId: 'branch-2', generation: 2, phone: '', email: '', bio: 'Kiểm tra dữ liệu thiếu', hidden: false, visibility: 'family' },
    { id: 'p-010', fullName: 'Người quan hệ phức tạp', gender: 'male', birthDate: '1988-08-08', deathDate: '', branchId: 'branch-2', generation: 2, phone: '', email: '', bio: 'Kiểm thử dữ liệu phức tạp', hidden: false, visibility: 'family' },
  ],
  relations: [
    { id: 'rel-1', type: 'spouse', fromId: 'p-001', toId: 'p-002', since: '1968-01-01' },
    { id: 'rel-2', type: 'father', fromId: 'p-001', toId: 'p-003', since: '' },
    { id: 'rel-3', type: 'mother', fromId: 'p-002', toId: 'p-003', since: '' },
    { id: 'rel-4', type: 'father', fromId: 'p-001', toId: 'p-004', since: '' },
    { id: 'rel-5', type: 'mother', fromId: 'p-002', toId: 'p-004', since: '' },
    { id: 'rel-6', type: 'spouse', fromId: 'p-003', toId: 'p-005', since: '1998-05-10' },
    { id: 'rel-7', type: 'father', fromId: 'p-003', toId: 'p-006', since: '' },
    { id: 'rel-8', type: 'mother', fromId: 'p-005', toId: 'p-006', since: '' },
  ],
  accounts: [],
  proposals: [],
  linkRequests: [
    { id: 'lr-1', targetFamily: 'Gia đình B (Dòng họ Trần)', reason: 'Liên kết thông gia thế hệ 2', status: 'pending', createdAt: '2026-10-15' },
  ],
  audit: [],
};

const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T;
const now = () => new Date().toISOString();
const uid = (prefix: string) => `${prefix}-${typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`}`;
const normalize = (value: string) => value.trim().toLocaleLowerCase('vi');
const validDate = (value: string) => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split('-').map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() + 1 === month && date.getUTCDate() === day;
};

function load(): FamilyAdminState {
  if (typeof window === 'undefined') return clone(initialState);
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (!saved) return clone(initialState);
    const parsed = JSON.parse(saved) as FamilyAdminState;
    if (Array.isArray(parsed.persons) && Array.isArray(parsed.relations) && Array.isArray(parsed.branches) && Array.isArray(parsed.accounts) && Array.isArray(parsed.proposals) && Array.isArray(parsed.linkRequests) && Array.isArray(parsed.audit)) {
      parsed.accounts = parsed.accounts.map((account) => ({ ...account, role: account.role || (account.personId === 'person-1' ? 'owner' : 'member') }));
      return parsed;
    }
  } catch {
    // A damaged local preview should not prevent the page from loading.
  }
  return clone(initialState);
}

let state = load();
const listeners = new Set<() => void>();
const subscribe = (listener: () => void) => { listeners.add(listener); return () => listeners.delete(listener); };
const getSnapshot = () => state;

function commit(action: string, change: (draft: FamilyAdminState) => void): void {
  const next = clone(state);
  change(next);
  next.audit.unshift({ id: uid('audit'), at: now(), action });
  next.audit = next.audit.slice(0, 100);
  state = next;
  try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next)); } catch { /* The current tab still works. */ }
  listeners.forEach((listener) => listener());
}

if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (event.key === STORAGE_KEY) {
      state = load();
      listeners.forEach((listener) => listener());
    }
  });
}

export const useFamilyAdminState = () => useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
export const getFamilyAdminState = () => state;

export function savePerson(input: Omit<FamilyPerson, 'id'>, id?: string): void {
  const fullName = input.fullName.trim();
  if (!fullName) throw new Error('Vui lòng nhập họ tên.');
  if (!Number.isInteger(input.generation) || input.generation < 1) throw new Error('Đời thứ phải là số nguyên dương.');
  if (input.birthDate && !validDate(input.birthDate) || input.deathDate && !validDate(input.deathDate)) throw new Error('Ngày sinh hoặc ngày mất không hợp lệ.');
  if (input.deathDate && input.birthDate && input.deathDate < input.birthDate) throw new Error('Ngày mất không thể trước ngày sinh.');
  if (input.branchId && !state.branches.some((branch) => branch.id === input.branchId)) throw new Error('Chi/Nhánh không tồn tại.');
  const duplicate = state.persons.some((person) => person.id !== id && normalize(person.fullName) === normalize(fullName) && person.birthDate === input.birthDate);
  if (duplicate) throw new Error('Đã có Person trùng họ tên và ngày sinh; hãy kiểm tra trước khi lưu.');
  commit(id ? `Sửa Person: ${fullName}` : `Thêm Person: ${fullName}`, (draft) => {
    if (id) {
      const index = draft.persons.findIndex((person) => person.id === id);
      if (index < 0) throw new Error('Không tìm thấy Person.');
      draft.persons[index] = { ...input, id, fullName };
    } else draft.persons.push({ ...input, id: uid('person'), fullName });
  });
}

export function togglePersonHidden(id: string): void {
  const person = state.persons.find((item) => item.id === id);
  if (!person) throw new Error('Không tìm thấy Person.');
  commit(`${person.hidden ? 'Khôi phục' : 'Ẩn'} Person: ${person.fullName}`, (draft) => {
    const target = draft.persons.find((item) => item.id === id)!;
    target.hidden = !target.hidden;
  });
}

export function saveBranch(input: Omit<FamilyBranch, 'id'>, id?: string): void {
  const name = input.name.trim();
  if (!name) throw new Error('Vui lòng nhập tên Chi/Nhánh.');
  if (state.branches.some((branch) => branch.id !== id && normalize(branch.name) === normalize(name))) throw new Error('Tên Chi/Nhánh đã tồn tại.');
  if (input.founderId && !state.persons.some((person) => person.id === input.founderId)) throw new Error('Thủy tổ/Người lập chi không tồn tại.');
  commit(id ? `Sửa Chi/Nhánh: ${name}` : `Thêm Chi/Nhánh: ${name}`, (draft) => {
    if (id) {
      const index = draft.branches.findIndex((branch) => branch.id === id);
      if (index < 0) throw new Error('Không tìm thấy Chi/Nhánh.');
      draft.branches[index] = { ...input, id, name };
    } else draft.branches.push({ ...input, id: uid('branch'), name });
  });
}

const parentTypes: RelationType[] = ['father', 'mother', 'adoptive_parent', 'step_parent'];
export function saveRelation(input: Omit<FamilyRelation, 'id'>, id?: string): void {
  if (!state.persons.some((person) => person.id === input.fromId) || !state.persons.some((person) => person.id === input.toId)) throw new Error('Vui lòng chọn hai Person trong cùng dòng họ.');
  if (input.fromId === input.toId) throw new Error('Một Person không thể có quan hệ với chính mình.');
  const duplicate = state.relations.some((relation) => relation.id !== id && relation.type === input.type && (
    relation.fromId === input.fromId && relation.toId === input.toId ||
    input.type === 'spouse' && relation.fromId === input.toId && relation.toId === input.fromId
  ));
  if (duplicate) throw new Error('Quan hệ này đã tồn tại.');
  if (parentTypes.includes(input.type)) {
    const descendants = new Set([input.toId]);
    for (let changed = true; changed;) {
      changed = false;
      state.relations.filter((relation) => relation.id !== id && parentTypes.includes(relation.type)).forEach((relation) => {
        if (descendants.has(relation.fromId) && !descendants.has(relation.toId)) { descendants.add(relation.toId); changed = true; }
      });
    }
    if (descendants.has(input.fromId)) throw new Error('Quan hệ này tạo vòng tổ tiên.');
  }
  commit(id ? 'Sửa quan hệ gia phả' : 'Thêm quan hệ gia phả', (draft) => {
    if (id) {
      const index = draft.relations.findIndex((relation) => relation.id === id);
      if (index < 0) throw new Error('Không tìm thấy quan hệ.');
      draft.relations[index] = { ...input, id };
    } else draft.relations.push({ ...input, id: uid('relation') });
  });
}

export function removeRelation(id: string): void {
  if (!state.relations.some((relation) => relation.id === id)) return;
  commit('Gỡ quan hệ gia phả', (draft) => { draft.relations = draft.relations.filter((relation) => relation.id !== id); });
}

export function reviewProposal(id: string, decision: 'approved' | 'rejected', note: string): void {
  const proposal = state.proposals.find((item) => item.id === id);
  if (!proposal || proposal.status !== 'pending') throw new Error('Chỉ có thể xử lý đề xuất đang chờ duyệt.');
  if (decision === 'rejected' && note.trim().length < 5) throw new Error('Vui lòng nhập lý do từ chối ít nhất 5 ký tự.');
  if (decision === 'approved' && proposal.type === 'profile') {
    if (proposal.field === 'fullName' && !proposal.proposedValue?.trim()) throw new Error('Không thể duyệt họ tên trống.');
    if (proposal.field === 'birthDate' && proposal.proposedValue && !validDate(proposal.proposedValue)) throw new Error('Ngày sinh đề xuất không hợp lệ.');
  }
  if (decision === 'approved' && proposal.type === 'relationship' && proposal.relation) saveRelation(proposal.relation);
  commit(`${decision === 'approved' ? 'Duyệt' : 'Từ chối'} đề xuất ${id}`, (draft) => {
    const target = draft.proposals.find((item) => item.id === id)!;
    target.status = decision;
    target.reviewedAt = now();
    target.note = note.trim();
    if (decision === 'approved' && target.type === 'profile' && target.field) {
      const person = draft.persons.find((item) => item.id === target.personId);
      if (person) person[target.field] = target.proposedValue || '';
    }
  });
}

export function issueAccount(input: Pick<FamilyAccount, 'personId' | 'username' | 'email'>): void {
  const person = state.persons.find((item) => item.id === input.personId);
  if (!person) throw new Error('Person phải thuộc dòng họ hiện tại.');
  if (person.deathDate) throw new Error('Không cấp tài khoản cho Person đã mất.');
  if (state.accounts.some((account) => account.personId === input.personId)) throw new Error('Person này đã có tài khoản.');
  if (!/^[a-z0-9._-]{3,30}$/i.test(input.username.trim())) throw new Error('Username cần 3–30 ký tự, chỉ dùng chữ, số, dấu chấm, gạch dưới hoặc gạch ngang.');
  if (state.accounts.some((account) => normalize(account.username) === normalize(input.username))) throw new Error('Username đã tồn tại.');
  if (input.email && state.accounts.some((account) => normalize(account.email) === normalize(input.email))) throw new Error('Email đã có tài khoản.');
  commit(`Tạo bản nháp tài khoản: ${input.username}`, (draft) => { draft.accounts.push({ ...input, id: uid('account'), role: 'member', status: 'pending' }); });
}

export function toggleAccountLock(id: string): void {
  const account = state.accounts.find((item) => item.id === id);
  if (!account) return;
  if (account.role === 'owner') throw new Error('Family Admin không được khóa tài khoản Owner.');
  commit(`${account.status === 'locked' ? 'Mở khóa' : 'Khóa'} bản nháp tài khoản: ${account.username}`, (draft) => {
    const target = draft.accounts.find((item) => item.id === id)!;
    target.status = target.status === 'locked' ? 'active' : 'locked';
  });
}

export function requestAccountReset(id: string): void {
  const account = state.accounts.find((item) => item.id === id);
  if (!account) return;
  if (account.role === 'owner') throw new Error('Family Admin không được reset mật khẩu Owner.');
  commit(`Đánh dấu yêu cầu reset mật khẩu: ${account.username}`, (draft) => {
    draft.accounts.find((item) => item.id === id)!.resetRequestedAt = now();
  });
}

export function sendLinkRequest(targetFamily: string, reason: string): void {
  const target = targetFamily.trim();
  if (!target) throw new Error('Vui lòng nhập dòng họ muốn liên kết.');
  if (normalize(target) === normalize(state.familyName)) throw new Error('Không thể liên kết với chính dòng họ này.');
  if (state.linkRequests.some((item) => normalize(item.targetFamily) === normalize(target) && item.status === 'pending')) throw new Error('Đã có yêu cầu đang chờ đến dòng họ này.');
  commit(`Gửi bản nháp yêu cầu liên họ: ${target}`, (draft) => {
    draft.linkRequests.push({ id: uid('link'), targetFamily: target, reason: reason.trim(), status: 'pending', createdAt: now() });
  });
}

export function reviewLinkRequest(id: string, status: 'approved' | 'rejected'): void {
  if (!state.linkRequests.some((item) => item.id === id && item.status === 'pending')) throw new Error('Yêu cầu không còn chờ duyệt.');
  commit(`${status === 'approved' ? 'Duyệt' : 'Từ chối'} bản nháp liên họ`, (draft) => {
    draft.linkRequests.find((item) => item.id === id)!.status = status;
  });
}

export function importPersons(rows: Array<Pick<FamilyPerson, 'fullName' | 'gender' | 'birthDate' | 'branchId' | 'generation'>>): number {
  const seen = new Set(state.persons.map((person) => `${normalize(person.fullName)}|${person.birthDate}`));
  const validated = rows.map((row, index) => {
    const name = row.fullName.trim();
    const key = `${normalize(name)}|${row.birthDate}`;
    if (!name || !['male', 'female', 'other'].includes(row.gender) || row.birthDate && !validDate(row.birthDate) || !Number.isInteger(row.generation) || row.generation < 1 || !state.branches.some((branch) => branch.id === row.branchId)) throw new Error(`Dòng ${index + 2}: tên, giới tính, ngày sinh, đời thứ hoặc Chi/Nhánh không hợp lệ.`);
    if (seen.has(key)) throw new Error(`Dòng ${index + 2}: Person trùng tên và ngày sinh.`);
    seen.add(key);
    return { id: uid('person'), fullName: name, gender: row.gender, birthDate: row.birthDate, deathDate: '', branchId: row.branchId, generation: row.generation, phone: '', email: '', bio: '', hidden: false, visibility: 'family' } satisfies FamilyPerson;
  });
  commit(`Nhập ${validated.length} Person từ CSV`, (draft) => { draft.persons.push(...validated); });
  return validated.length;
}

export async function syncFamilyAdminFromBackend(clanId: string): Promise<void> {
  try {
    const [persons, tree] = await Promise.all([
      fetchFamilyPersons(clanId).catch(() => []),
      fetchFamilyTreeData(clanId).catch(() => ({ nodes: [], edges: [] })),
    ]);

    commit('Đồng bộ dữ liệu từ Backend', (draft) => {
      if (Array.isArray(persons) && persons.length > 0) {
        draft.persons = persons.map((p) => ({
          id: p.id,
          fullName: p.fullName,
          gender: (p.gender === 'female' ? 'female' : 'male') as any,
          birthDate: p.birthDate || '',
          deathDate: p.deathDate || '',
          branchId: p.branchId || '',
          generation: p.generation || 1,
          phone: '',
          email: '',
          bio: '',
          hidden: !p.isLiving,
          visibility: 'family',
        }));
      }

      if (tree && Array.isArray(tree.edges) && tree.edges.length > 0) {
        draft.relations = tree.edges.map((e) => ({
          id: e.id,
          type: (e.relationshipType === 'SPOUSE' ? 'spouse' : 'father') as any,
          fromId: e.fromMemberId,
          toId: e.toMemberId,
          since: '',
        }));
      }
    });
  } catch (err) {
    console.warn('Lỗi khi đồng bộ dữ liệu gia phả từ Backend:', err);
  }
}

