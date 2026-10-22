import React, { useEffect, useMemo, useState } from 'react';
import {
  getFamilyAdminState, importPersons, issueAccount, removeRelation, requestAccountReset,
  reviewLinkRequest, reviewProposal, saveBranch, savePerson, saveRelation, sendLinkRequest,
  toggleAccountLock, togglePersonHidden, useFamilyAdminState, syncFamilyAdminFromBackend,
  type FamilyBranch, type FamilyPerson, type FamilyRelation, type RelationType,
} from './familyAdminStore';
import './FamilyAdminModule.css';
import { downloadFamilyXlsx, downloadPersonTemplateXlsx, readPersonXlsx } from './familyAdminExcel';

export type FamilyAdminView = 'overview' | 'members' | 'relations' | 'branches' | 'tree' | 'search' | 'approvals' | 'accounts' | 'links' | 'exchange' | 'audit';
type Props = { view: FamilyAdminView; onNavigate?: (view: FamilyAdminView) => void };

const relationLabels: Record<RelationType, string> = {
  father: 'Cha → con', mother: 'Mẹ → con', spouse: 'Vợ/chồng',
  adoptive_parent: 'Cha/mẹ nuôi → con', step_parent: 'Cha/mẹ kế → con',
};
const genderLabels = { male: 'Nam', female: 'Nữ', other: 'Khác' };
const emptyPerson = (branchId: string): Omit<FamilyPerson, 'id'> => ({
  fullName: '', gender: 'male', birthDate: '', deathDate: '', branchId,
  generation: 1, phone: '', email: '', bio: '', hidden: false, visibility: 'family',
});
const emptyBranch: Omit<FamilyBranch, 'id'> = { name: '', founderId: '', description: '' };
const clean = (value: string) => value.trim().toLocaleLowerCase('vi');

function downloadFile(name: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob(['\ufeff', content], { type }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function csvEscape(value: string | number): string {
  const text = String(value);
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let quoted = false;
  const source = text.replace(/^\uFEFF/, '');
  for (let i = 0; i < source.length; i += 1) {
    const char = source[i];
    if (char === '"') {
      if (quoted && source[i + 1] === '"') { cell += '"'; i += 1; }
      else quoted = !quoted;
    } else if (char === ',' && !quoted) { row.push(cell); cell = ''; }
    else if ((char === '\n' || char === '\r') && !quoted) {
      if (char === '\r' && source[i + 1] === '\n') i += 1;
      row.push(cell); if (row.some((part) => part.trim())) rows.push(row);
      row = []; cell = '';
    } else cell += char;
  }
  if (quoted) throw new Error('Tệp CSV có dấu ngoặc kép chưa đóng.');
  row.push(cell);
  if (row.some((part) => part.trim())) rows.push(row);
  return rows;
}

export const FamilyAdminModule: React.FC<Props> = ({ view, onNavigate }) => {
  const data = useFamilyAdminState();
  const [notice, setNotice] = useState<{ text: string; error: boolean } | null>(null);

  useEffect(() => {
    // Tự động đồng bộ dữ liệu phả hệ thật từ Neon DB
    syncFamilyAdminFromBackend('c9a59088-7ad7-4b21-8cba-19e2ea46d15a');
  }, []);

  const [query, setQuery] = useState('');
  const [personForm, setPersonForm] = useState<Omit<FamilyPerson, 'id'> | null>(null);
  const [editPersonId, setEditPersonId] = useState<string | undefined>();
  const [branchForm, setBranchForm] = useState<Omit<FamilyBranch, 'id'> | null>(null);
  const [editBranchId, setEditBranchId] = useState<string | undefined>();
  const [relationForm, setRelationForm] = useState<Omit<FamilyRelation, 'id'>>({ type: 'father', fromId: '', toId: '', since: '' });
  const [editRelationId, setEditRelationId] = useState<string | undefined>();
  const [accountForm, setAccountForm] = useState({ personId: '', username: '', email: '' });
  const [linkForm, setLinkForm] = useState({ targetFamily: '', reason: '' });
  const [reviewNote, setReviewNote] = useState<Record<string, string>>({});
  const [treeBranch, setTreeBranch] = useState('all');
  const [treeGeneration, setTreeGeneration] = useState('all');
  const [treeFocus, setTreeFocus] = useState('');
  const [treeScale, setTreeScale] = useState(1);
  const [searchFrom, setSearchFrom] = useState('');
  const [searchTo, setSearchTo] = useState('');
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvPreview, setCsvPreview] = useState<Array<Pick<FamilyPerson, 'fullName' | 'gender' | 'birthDate' | 'branchId' | 'generation'>> | null>(null);
  const [xlsxPreview, setXlsxPreview] = useState<Array<Pick<FamilyPerson, 'fullName' | 'gender' | 'birthDate' | 'branchId' | 'generation'>> | null>(null);

  const personName = (id: string) => data.persons.find((person) => person.id === id)?.fullName || 'Không tìm thấy';
  const branchName = (id: string) => data.branches.find((branch) => branch.id === id)?.name || 'Chưa phân chi';
  const linkedCount = data.linkRequests.filter((item) => item.status === 'approved').length;
  const pendingCount = data.proposals.filter((item) => item.status === 'pending').length;

  const run = (action: () => void, success: string) => {
    try { action(); setNotice({ text: success, error: false }); }
    catch (error) { setNotice({ text: error instanceof Error ? error.message : 'Không thể hoàn tất thao tác.', error: true }); }
  };
  const go = (target: FamilyAdminView) => onNavigate?.(target);
  const filteredPersons = useMemo(() => data.persons.filter((person) =>
    [person.fullName, branchName(person.branchId), person.email].join(' ').toLocaleLowerCase('vi').includes(clean(query))), [data.persons, data.branches, query]);

  const activeRelations = data.relations.filter((relation) =>
    data.persons.some((person) => person.id === relation.fromId && !person.hidden) &&
    data.persons.some((person) => person.id === relation.toId && !person.hidden));

  const relationshipPath = useMemo(() => {
    if (!searchFrom || !searchTo) return null;
    if (searchFrom === searchTo) return [searchFrom];
    const queue: string[][] = [[searchFrom]];
    const visited = new Set([searchFrom]);
    while (queue.length) {
      const path = queue.shift()!;
      const last = path[path.length - 1];
      for (const relation of activeRelations) {
        const next = relation.fromId === last ? relation.toId : relation.toId === last ? relation.fromId : null;
        if (!next || visited.has(next)) continue;
        const candidate = [...path, next];
        if (next === searchTo) return candidate;
        visited.add(next);
        queue.push(candidate);
      }
    }
    return [];
  }, [activeRelations, searchFrom, searchTo]);

  const relationshipHint = (() => {
    if (!searchFrom || !searchTo || !relationshipPath?.length) return '';
    if (searchFrom === searchTo) return 'Đây là cùng một Person.';
    if (relationshipPath.length === 2) {
      const relation = data.relations.find((item) => item.fromId === searchFrom && item.toId === searchTo || item.fromId === searchTo && item.toId === searchFrom);
      if (!relation) return '';
      if (relation.type === 'spouse') return `${personName(searchFrom)} là vợ/chồng của ${personName(searchTo)}.`;
      const forward = relation.fromId === searchFrom;
      const label = relation.type === 'father' ? (forward ? 'cha' : 'con')
        : relation.type === 'mother' ? (forward ? 'mẹ' : 'con')
        : relation.type === 'adoptive_parent' ? (forward ? 'cha/mẹ nuôi' : 'con nuôi')
        : (forward ? 'cha/mẹ kế' : 'con riêng');
      return `${personName(searchFrom)} là ${label} của ${personName(searchTo)}.`;
    }
    const firstParents = data.relations.filter((relation) => relation.toId === searchFrom && relation.type !== 'spouse').map((relation) => relation.fromId);
    const secondParents = data.relations.filter((relation) => relation.toId === searchTo && relation.type !== 'spouse').map((relation) => relation.fromId);
    if (firstParents.some((id) => secondParents.includes(id))) return `${personName(searchFrom)} và ${personName(searchTo)} là anh/chị/em theo dữ liệu cha mẹ chung.`;
    return `Có đường kết nối ${relationshipPath.length - 1} bước, nhưng chưa đủ dữ liệu để khẳng định xưng hô cụ thể.`;
  })();

  const title = ({ overview: 'Tổng quan dòng họ', members: 'Quản lý Person', relations: 'Quản lý quan hệ', branches: 'Quản lý Chi & Nhánh', tree: 'Cây gia phả', search: 'Tìm quan hệ', approvals: 'Phê duyệt đề xuất', accounts: 'Tài khoản thành viên', links: 'Liên kết dòng họ', exchange: 'Nhập & xuất dữ liệu', audit: 'Nhật ký thao tác' } satisfies Record<FamilyAdminView, string>)[view];

  return <section className="fa-workspace" aria-labelledby="fa-title">
    <header className="fa-header">
      <div><span className="fa-eyebrow">FAMILY ADMIN · {data.familyName}</span><h1 id="fa-title">{title}</h1><p>Dữ liệu bản xem trước lưu trong trình duyệt, chưa đồng bộ máy chủ. Không nhập thông tin nhạy cảm thật.</p></div>
      <span className="fa-preview-tag">FRONTEND PREVIEW</span>
    </header>
    {notice && <div className={`fa-notice ${notice.error ? 'error' : 'success'}`} role="status">{notice.text}<button type="button" onClick={() => setNotice(null)} aria-label="Đóng thông báo">×</button></div>}

    {view === 'overview' && <>
      <div className="fa-stat-grid">
        <article><span>Person đang hiển thị</span><strong>{data.persons.filter((person) => !person.hidden).length}</strong><small>{data.branches.length} Chi/Nhánh</small></article>
        <article><span>Quan hệ đã ghi</span><strong>{data.relations.length}</strong><small>Cha mẹ, hôn nhân và quan hệ khác</small></article>
        <article><span>Đề xuất chờ duyệt</span><strong>{pendingCount}</strong><small>Cần xem trước khi áp dụng</small></article>
        <article><span>Dòng họ đã liên kết</span><strong>{linkedCount}</strong><small>Chỉ là trạng thái bản xem trước</small></article>
      </div>
      <div className="fa-panel"><h2>Đi tới chức năng</h2><div className="fa-quick-grid">
        {([['members', 'Quản lý Person'], ['relations', 'Quan hệ gia phả'], ['branches', 'Chi & Nhánh'], ['approvals', 'Duyệt đề xuất'], ['accounts', 'Tài khoản Member'], ['links', 'Liên họ'], ['exchange', 'Nhập xuất CSV']] as [FamilyAdminView, string][]).map(([target, label]) => <button type="button" key={target} onClick={() => go(target)}>{label}<span>→</span></button>)}
      </div></div>
      <div className="fa-panel"><h2>Thao tác gần đây</h2>{data.audit.length ? <ul className="fa-audit-list">{data.audit.slice(0, 5).map((item) => <li key={item.id}><span>{item.action}</span><time>{new Date(item.at).toLocaleString('vi-VN')}</time></li>)}</ul> : <p className="fa-muted">Chưa có thao tác trong bản xem trước.</p>}</div>
    </>}

    {view === 'members' && <>
      <div className="fa-panel"><div className="fa-panel-heading"><div><h2>Danh sách Person</h2><p>Thêm, sửa, ẩn và khôi phục hồ sơ trong dòng họ.</p></div><button type="button" className="fa-primary" onClick={() => { setEditPersonId(undefined); setPersonForm(emptyPerson(data.branches[0]?.id || '')); }}>+ Thêm Person</button></div>
        <div className="fa-toolbar"><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Tìm tên, Chi/Nhánh hoặc email" aria-label="Tìm Person" /><span>{filteredPersons.length} kết quả</span></div>
        <div className="fa-table-wrap"><table><thead><tr><th>Họ tên</th><th>Đời / Chi</th><th>Ngày sinh</th><th>Hiển thị</th><th>Tài khoản</th><th>Thao tác</th></tr></thead><tbody>{filteredPersons.map((person) => <tr key={person.id}><td><div className="person-avatar-cell" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}><div className={`avatar avatar-placeholder ${person.gender}`} aria-label={`Avatar ${person.gender}`} style={{ width: 28, height: 28, borderRadius: '50%', background: '#e2e8f0', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '14px', flexShrink: 0 }}>{person.gender === 'female' ? '👩' : '👨'}</div><div><strong>{person.fullName}</strong><small>{person.bio || genderLabels[person.gender]}</small></div></div></td><td>Đời {person.generation}<small>{branchName(person.branchId)}</small></td><td>{person.birthDate || 'Chưa rõ'}</td><td><span className={`fa-status ${person.hidden ? 'muted' : 'approved'}`}>{person.hidden ? 'Đã ẩn' : 'Hiển thị'}</span></td><td>{data.accounts.some((account) => account.personId === person.id) ? 'Có bản nháp' : 'Chưa có'}</td><td><div className="fa-actions"><button type="button" onClick={() => { setEditPersonId(person.id); setPersonForm({ ...person }); }}>Sửa</button><button type="button" onClick={() => run(() => togglePersonHidden(person.id), 'Đã cập nhật trạng thái Person.')}>{person.hidden ? 'Khôi phục' : 'Ẩn'}</button></div></td></tr>)}</tbody></table></div>
      </div>
      {personForm && <div className="fa-modal-backdrop"><div className="fa-modal" role="dialog" aria-modal="true" aria-labelledby="fa-person-form"><div className="fa-modal-title"><h2 id="fa-person-form">{editPersonId ? 'Sửa Person' : 'Thêm Person'}</h2><button type="button" onClick={() => setPersonForm(null)} aria-label="Đóng">×</button></div><form onSubmit={(event) => { event.preventDefault(); try { savePerson(personForm, editPersonId); setPersonForm(null); setNotice({ text: 'Đã lưu Person trong bản xem trước.', error: false }); } catch (error) { setNotice({ text: error instanceof Error ? error.message : 'Không thể lưu Person.', error: true }); } }}><div className="fa-form-grid">
        <label>Họ và tên *<input required value={personForm.fullName} onChange={(event) => setPersonForm({ ...personForm, fullName: event.target.value })} /></label>
        <label>Giới tính<select value={personForm.gender} onChange={(event) => setPersonForm({ ...personForm, gender: event.target.value as FamilyPerson['gender'] })}><option value="male">Nam</option><option value="female">Nữ</option><option value="other">Khác</option></select></label>
        <label>Ngày sinh<input type="date" value={personForm.birthDate} onChange={(event) => setPersonForm({ ...personForm, birthDate: event.target.value })} /></label>
        <label>Ngày mất<input type="date" value={personForm.deathDate} onChange={(event) => setPersonForm({ ...personForm, deathDate: event.target.value })} /></label>
        <label>Chi/Nhánh<select value={personForm.branchId} onChange={(event) => setPersonForm({ ...personForm, branchId: event.target.value })}>{data.branches.map((branch) => <option key={branch.id} value={branch.id}>{branch.name}</option>)}</select></label>
        <label>Đời thứ<input type="number" min="1" value={personForm.generation} onChange={(event) => setPersonForm({ ...personForm, generation: Number(event.target.value) })} /></label>
        <label>Email<input type="email" value={personForm.email} onChange={(event) => setPersonForm({ ...personForm, email: event.target.value })} /></label>
        <label>Điện thoại<input value={personForm.phone} onChange={(event) => setPersonForm({ ...personForm, phone: event.target.value })} /></label>
        <label>Quyền xem hồ sơ<select value={personForm.visibility} onChange={(event) => setPersonForm({ ...personForm, visibility: event.target.value as FamilyPerson['visibility'] })}><option value="family">Trong dòng họ</option><option value="admin">Người quản lý</option><option value="private">Riêng tư (không công khai)</option></select></label>
        <label className="fa-wide">Tiểu sử<textarea value={personForm.bio} onChange={(event) => setPersonForm({ ...personForm, bio: event.target.value })} rows={3} /></label>
      </div><div className="fa-modal-actions"><button type="button" onClick={() => setPersonForm(null)}>Hủy</button><button type="submit" className="fa-primary">Lưu Person</button></div></form></div></div>}
    </>}

    {view === 'branches' && <div className="fa-panel"><div className="fa-panel-heading"><div><h2>Chi/Nhánh của {data.familyName}</h2><p>Quản lý tên chi, người lập chi và số Person trực thuộc.</p></div><button className="fa-primary" type="button" onClick={() => { setEditBranchId(undefined); setBranchForm({ ...emptyBranch }); }}>+ Thêm Chi/Nhánh</button></div><div className="fa-card-grid">{data.branches.map((branch) => <article className="fa-card" key={branch.id}><span className="fa-card-eyebrow">CHI/NHÁNH</span><h3>{branch.name}</h3><p>{branch.description || 'Chưa có mô tả'}</p><dl><div><dt>Người lập chi</dt><dd>{branch.founderId ? personName(branch.founderId) : 'Chưa chọn'}</dd></div><div><dt>Person</dt><dd>{data.persons.filter((person) => person.branchId === branch.id).length}</dd></div></dl><button type="button" onClick={() => { setEditBranchId(branch.id); setBranchForm({ ...branch }); }}>Chỉnh sửa</button></article>)}</div>
      {branchForm && <div className="fa-modal-backdrop"><div className="fa-modal" role="dialog" aria-modal="true" aria-labelledby="fa-branch-form"><div className="fa-modal-title"><h2 id="fa-branch-form">{editBranchId ? 'Sửa Chi/Nhánh' : 'Thêm Chi/Nhánh'}</h2><button type="button" onClick={() => setBranchForm(null)} aria-label="Đóng">×</button></div><form onSubmit={(event) => { event.preventDefault(); try { saveBranch(branchForm, editBranchId); setBranchForm(null); setNotice({ text: 'Đã lưu Chi/Nhánh trong bản xem trước.', error: false }); } catch (error) { setNotice({ text: error instanceof Error ? error.message : 'Không thể lưu Chi/Nhánh.', error: true }); } }}><div className="fa-form-grid"><label>Tên Chi/Nhánh *<input required value={branchForm.name} onChange={(event) => setBranchForm({ ...branchForm, name: event.target.value })} /></label><label>Người lập chi<select value={branchForm.founderId} onChange={(event) => setBranchForm({ ...branchForm, founderId: event.target.value })}><option value="">Chưa chọn</option>{data.persons.map((person) => <option key={person.id} value={person.id}>{person.fullName}</option>)}</select></label><label className="fa-wide">Mô tả<textarea rows={3} value={branchForm.description} onChange={(event) => setBranchForm({ ...branchForm, description: event.target.value })} /></label></div><div className="fa-modal-actions"><button type="button" onClick={() => setBranchForm(null)}>Hủy</button><button className="fa-primary" type="submit">Lưu Chi/Nhánh</button></div></form></div></div>}
    </div>}

    {view === 'relations' && <><div className="fa-panel"><h2>{editRelationId ? 'Sửa quan hệ' : 'Thêm quan hệ'}</h2><p className="fa-muted">Kiểm tra trùng, tự liên kết và vòng tổ tiên trước khi lưu.</p><form className="fa-form-grid" onSubmit={(event) => { event.preventDefault(); try { saveRelation(relationForm, editRelationId); setRelationForm({ type: 'father', fromId: '', toId: '', since: '' }); setEditRelationId(undefined); setNotice({ text: 'Đã lưu quan hệ trong bản xem trước.', error: false }); } catch (error) { setNotice({ text: error instanceof Error ? error.message : 'Không thể lưu quan hệ.', error: true }); } }}><label>Loại quan hệ<select value={relationForm.type} onChange={(event) => setRelationForm({ ...relationForm, type: event.target.value as RelationType })}>{Object.entries(relationLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>Người thứ nhất<select required value={relationForm.fromId} onChange={(event) => setRelationForm({ ...relationForm, fromId: event.target.value })}><option value="">Chọn Person</option>{data.persons.filter((person) => !person.hidden).map((person) => <option key={person.id} value={person.id}>{person.fullName}</option>)}</select></label><label>Người thứ hai<select required value={relationForm.toId} onChange={(event) => setRelationForm({ ...relationForm, toId: event.target.value })}><option value="">Chọn Person</option>{data.persons.filter((person) => !person.hidden).map((person) => <option key={person.id} value={person.id}>{person.fullName}</option>)}</select></label><label>Từ ngày (nếu có)<input type="date" value={relationForm.since} onChange={(event) => setRelationForm({ ...relationForm, since: event.target.value })} /></label><div className="fa-wide fa-actions"><button className="fa-primary" type="submit">Lưu quan hệ</button>{editRelationId && <button type="button" onClick={() => { setEditRelationId(undefined); setRelationForm({ type: 'father', fromId: '', toId: '', since: '' }); }}>Hủy sửa</button>}</div></form></div><div className="fa-panel"><h2>Quan hệ đã ghi</h2><div className="fa-table-wrap"><table><thead><tr><th>Loại</th><th>Người thứ nhất</th><th>Người thứ hai</th><th>Từ ngày</th><th>Thao tác</th></tr></thead><tbody>{data.relations.map((relation) => <tr key={relation.id}><td>{relationLabels[relation.type]}</td><td>{personName(relation.fromId)}</td><td>{personName(relation.toId)}</td><td>{relation.since || '—'}</td><td><div className="fa-actions"><button type="button" onClick={() => { setEditRelationId(relation.id); setRelationForm({ ...relation }); window.scrollTo({ top: 0, behavior: 'smooth' }); }}>Sửa</button><button type="button" onClick={() => { if (window.confirm('Gỡ quan hệ này khỏi bản xem trước?')) run(() => removeRelation(relation.id), 'Đã gỡ quan hệ.'); }}>Gỡ</button></div></td></tr>)}</tbody></table></div></div></>}

    {view === 'tree' && <div className="fa-panel"><div className="fa-panel-heading"><div><h2>Cây theo quan hệ cha/mẹ–con</h2><p>Chọn chi, đời hoặc một Person để tập trung.</p></div><button type="button" onClick={() => go('relations')}>Quản lý quan hệ →</button></div><div className="fa-toolbar"><select aria-label="Lọc Chi/Nhánh" value={treeBranch} onChange={(event) => setTreeBranch(event.target.value)}><option value="all">Tất cả Chi/Nhánh</option>{data.branches.map((branch) => <option key={branch.id} value={branch.id}>{branch.name}</option>)}</select><select aria-label="Lọc đời thứ" value={treeGeneration} onChange={(event) => setTreeGeneration(event.target.value)}><option value="all">Tất cả đời</option>{[...new Set(data.persons.map((person) => person.generation))].sort((a, b) => a - b).map((generation) => <option key={generation} value={generation}>Đời {generation}</option>)}</select><select aria-label="Tập trung Person" value={treeFocus} onChange={(event) => setTreeFocus(event.target.value)}><option value="">Toàn cây</option>{data.persons.filter((person) => !person.hidden).map((person) => <option key={person.id} value={person.id}>{person.fullName}</option>)}</select><div className="fa-zoom"><button type="button" onClick={() => setTreeScale((value) => Math.max(0.8, value - 0.1))}>−</button><span>{Math.round(treeScale * 100)}%</span><button type="button" onClick={() => setTreeScale((value) => Math.min(1.3, value + 0.1))}>+</button></div></div><div className="fa-tree-list" style={{ fontSize: `${treeScale}rem` }}>{data.persons.filter((person) => !person.hidden && (treeBranch === 'all' || person.branchId === treeBranch) && (treeGeneration === 'all' || String(person.generation) === treeGeneration) && (!treeFocus || person.id === treeFocus || data.relations.some((relation) => (relation.fromId === treeFocus && relation.toId === person.id || relation.toId === treeFocus && relation.fromId === person.id) && relation.type !== 'spouse'))).sort((a, b) => a.generation - b.generation).map((person) => { const parents = data.relations.filter((relation) => relation.toId === person.id && relation.type !== 'spouse'); const spouses = data.relations.filter((relation) => relation.type === 'spouse' && (relation.fromId === person.id || relation.toId === person.id)); return <article key={person.id} className="fa-tree-person" style={{ marginLeft: `${Math.max(0, person.generation - Math.min(...data.persons.map((item) => item.generation))) * 24}px` }}><div><strong>{person.fullName}</strong><span>Đời {person.generation} · {branchName(person.branchId)}</span></div><small>{parents.length ? `Cha/mẹ: ${parents.map((item) => personName(item.fromId)).join(', ')}` : 'Gốc nhánh / chưa ghi cha mẹ'}{spouses.length ? ` · Vợ/chồng: ${spouses.map((item) => personName(item.fromId === person.id ? item.toId : item.fromId)).join(', ')}` : ''}</small></article>; })}</div></div>}

    {view === 'search' && <div className="fa-panel"><h2>Đường quan hệ giữa hai Person</h2><p className="fa-muted">Dựa trên các cạnh cha/mẹ–con, hôn nhân, con nuôi và con riêng đã được ghi.</p><div className="fa-form-grid"><label>Person thứ nhất<select value={searchFrom} onChange={(event) => setSearchFrom(event.target.value)}><option value="">Chọn Person</option>{data.persons.filter((person) => !person.hidden).map((person) => <option key={person.id} value={person.id}>{person.fullName}</option>)}</select></label><label>Person thứ hai<select value={searchTo} onChange={(event) => setSearchTo(event.target.value)}><option value="">Chọn Person</option>{data.persons.filter((person) => !person.hidden).map((person) => <option key={person.id} value={person.id}>{person.fullName}</option>)}</select></label></div>{relationshipPath && <div className="fa-result">{relationshipPath.length ? <><strong>Đường kết nối ngắn nhất: {relationshipPath.length - 1} bước</strong><ol>{relationshipPath.map((id, index) => <li key={`${id}-${index}`}>{personName(id)}{index < relationshipPath.length - 1 && <small>{(() => { const nextId = relationshipPath[index + 1]; const relation = data.relations.find((item) => item.fromId === id && item.toId === nextId || item.fromId === nextId && item.toId === id); return relation ? ` — ${relationLabels[relation.type]}` : ''; })()}</small>}</li>)}</ol></> : <p>Chưa xác định được quan hệ từ dữ liệu hiện có.</p>}</div>}</div>}
    {view === 'search' && relationshipHint && <div className="fa-panel"><h2>Gợi ý xưng hô</h2><p>{relationshipHint}</p><p className="fa-muted">Kết quả suy từ dữ liệu quan hệ đã ghi; cần người quản lý xác minh trước khi dùng chính thức.</p></div>}

    {view === 'approvals' && <div className="fa-panel"><h2>Đề xuất chờ xử lý</h2><p className="fa-muted">Khi duyệt, thay đổi được áp dụng vào dữ liệu bản xem trước. Từ chối giữ nguyên dữ liệu.</p>{data.proposals.length ? <div className="fa-proposals">{data.proposals.map((proposal) => <article className="fa-proposal" key={proposal.id}><div className="fa-proposal-top"><div><span className="fa-card-eyebrow">{proposal.type === 'profile' ? 'HỒ SƠ' : 'QUAN HỆ'} · {proposal.proposer}</span><h3>{proposal.summary}</h3></div><span className={`fa-status ${proposal.status}`}>{proposal.status === 'pending' ? 'Chờ duyệt' : proposal.status === 'approved' ? 'Đã duyệt' : 'Từ chối'}</span></div><p>Person: <strong>{personName(proposal.personId)}</strong>{proposal.type === 'profile' ? ` · Giá trị đề xuất: ${proposal.proposedValue}` : proposal.relation ? ` · ${relationLabels[proposal.relation.type]}: ${personName(proposal.relation.fromId)} → ${personName(proposal.relation.toId)}` : ''}</p>{proposal.status === 'pending' ? <><label>Lý do / ghi chú<textarea rows={2} value={reviewNote[proposal.id] || ''} onChange={(event) => setReviewNote({ ...reviewNote, [proposal.id]: event.target.value })} placeholder="Bắt buộc khi từ chối" /></label><div className="fa-actions"><button type="button" className="fa-primary" onClick={() => run(() => reviewProposal(proposal.id, 'approved', reviewNote[proposal.id] || ''), 'Đã duyệt và cập nhật dữ liệu bản xem trước.')}>Phê duyệt</button><button type="button" onClick={() => run(() => reviewProposal(proposal.id, 'rejected', reviewNote[proposal.id] || ''), 'Đã từ chối đề xuất.')}>Từ chối</button></div></> : <small>{proposal.note || 'Không có ghi chú'}{proposal.reviewedAt ? ` · ${new Date(proposal.reviewedAt).toLocaleString('vi-VN')}` : ''}</small>}</article>)}</div> : <p>Chưa có đề xuất.</p>}</div>}

    {view === 'accounts' && <><div className="fa-panel"><h2>Cấp bản nháp tài khoản cho Person</h2><p className="fa-muted">Chưa tạo tài khoản đăng nhập thật, chưa gửi email và không lưu mật khẩu trong trình duyệt.</p><form className="fa-form-grid" onSubmit={(event) => { event.preventDefault(); try { issueAccount(accountForm); setAccountForm({ personId: '', username: '', email: '' }); setNotice({ text: 'Đã tạo bản nháp tài khoản. Backend chưa cấp quyền đăng nhập.', error: false }); } catch (error) { setNotice({ text: error instanceof Error ? error.message : 'Không thể tạo bản nháp.', error: true }); } }}><label>Person *<select required value={accountForm.personId} onChange={(event) => setAccountForm({ ...accountForm, personId: event.target.value })}><option value="">Chọn Person</option>{data.persons.filter((person) => !person.deathDate && !data.accounts.some((account) => account.personId === person.id)).map((person) => <option key={person.id} value={person.id}>{person.fullName}</option>)}</select></label><label>Username *<input required value={accountForm.username} onChange={(event) => setAccountForm({ ...accountForm, username: event.target.value })} /></label><label>Email<input type="email" value={accountForm.email} onChange={(event) => setAccountForm({ ...accountForm, email: event.target.value })} /></label><div className="fa-wide"><button className="fa-primary" type="submit">Tạo bản nháp tài khoản</button></div></form></div><div className="fa-panel"><h2>Danh sách tài khoản bản xem trước</h2><div className="fa-table-wrap"><table><thead><tr><th>Username</th><th>Person</th><th>Vai trò</th><th>Email</th><th>Trạng thái</th><th>Thao tác</th></tr></thead><tbody>{data.accounts.map((account) => <tr key={account.id}><td><strong>{account.username}</strong></td><td>{personName(account.personId)}</td><td>{account.role === 'owner' ? 'Owner' : 'Member'}</td><td>{account.email || '—'}</td><td><span className={`fa-status ${account.status === 'locked' ? 'rejected' : account.status === 'active' ? 'approved' : 'pending'}`}>{account.status === 'locked' ? 'Đã khóa' : account.status === 'active' ? 'Hoạt động (mẫu)' : 'Chờ kích hoạt'}</span>{account.resetRequestedAt && <small>Đã đánh dấu reset</small>}</td><td>{account.role === 'owner' ? <small>Không được quản lý Owner</small> : <div className="fa-actions"><button type="button" onClick={() => run(() => toggleAccountLock(account.id), 'Đã đổi trạng thái bản nháp. Không ảnh hưởng phiên đăng nhập thật.')}>{account.status === 'locked' ? 'Mở khóa' : 'Khóa'}</button><button type="button" onClick={() => run(() => requestAccountReset(account.id), 'Đã đánh dấu yêu cầu reset; chưa gửi email hoặc đổi mật khẩu thật.')}>Reset</button></div>}</td></tr>)}</tbody></table></div></div></>}

    {view === 'links' && <><div className="fa-panel"><h2>Yêu cầu liên kết dòng họ</h2><p className="fa-muted">Yêu cầu và kết quả phê duyệt ở đây chỉ tồn tại trong bản xem trước; không chia sẻ dữ liệu với dòng họ khác.</p><form className="fa-form-grid" onSubmit={(event) => { event.preventDefault(); try { sendLinkRequest(linkForm.targetFamily, linkForm.reason); setLinkForm({ targetFamily: '', reason: '' }); setNotice({ text: 'Đã lưu bản nháp yêu cầu liên họ.', error: false }); } catch (error) { setNotice({ text: error instanceof Error ? error.message : 'Không thể tạo yêu cầu.', error: true }); } }}><label>Dòng họ đích *<input required value={linkForm.targetFamily} onChange={(event) => setLinkForm({ ...linkForm, targetFamily: event.target.value })} placeholder="Ví dụ: Dòng họ Trần" /></label><label>Lý do / quan hệ<input value={linkForm.reason} onChange={(event) => setLinkForm({ ...linkForm, reason: event.target.value })} placeholder="Thông gia, bên ngoại..." /></label><div className="fa-wide"><button className="fa-primary" type="submit">Gửi bản nháp yêu cầu</button></div></form></div><div className="fa-panel"><h2>Danh sách yêu cầu</h2>{data.linkRequests.length ? <div className="fa-table-wrap"><table><thead><tr><th>Dòng họ đích</th><th>Lý do</th><th>Ngày tạo</th><th>Trạng thái</th><th>Thao tác</th></tr></thead><tbody>{data.linkRequests.map((request) => <tr key={request.id}><td><strong>{request.targetFamily}</strong></td><td>{request.reason || '—'}</td><td>{new Date(request.createdAt).toLocaleDateString('vi-VN')}</td><td><span className={`fa-status ${request.status}`}>{request.status === 'pending' ? 'Chờ duyệt' : request.status === 'approved' ? 'Đã duyệt (mẫu)' : 'Từ chối'}</span></td><td>{request.status === 'pending' && <div className="fa-actions"><button type="button" onClick={() => run(() => reviewLinkRequest(request.id, 'approved'), 'Đã đổi trạng thái bản nháp; chưa tạo liên kết thật.')}>Duyệt mẫu</button><button type="button" onClick={() => run(() => reviewLinkRequest(request.id, 'rejected'), 'Đã từ chối bản nháp.')}>Từ chối</button></div>}</td></tr>)}</tbody></table></div> : <p className="fa-muted">Chưa có yêu cầu liên họ.</p>}</div></>}

    {view === 'exchange' && <><div className="fa-panel"><h2>Nhập và xuất Excel (.xlsx)</h2><p className="fa-muted">Xử lý hoàn toàn trong trình duyệt. File Person phải có các cột fullName, gender, birthDate, branch, generation. Nhập sẽ hủy toàn bộ nếu có dòng lỗi hoặc trùng.</p><div className="fa-actions"><button type="button" onClick={async () => { try { await downloadPersonTemplateXlsx(); } catch { setNotice({ text: 'Không thể tạo file Excel mẫu.', error: true }); } }}>Tải mẫu Excel</button><input type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" aria-label="Chọn tệp Excel" onChange={async (event) => { try { const file = event.target.files?.[0]; setXlsxPreview(null); if (!file) return; if (file.size > 2_000_000) throw new Error('Tệp vượt quá 2 MB.'); const rows = await readPersonXlsx(file); if (rows.length < 2) throw new Error('File Excel chưa có dữ liệu Person.'); const header = rows[0].map(clean); const required = ['fullname', 'gender', 'birthdate', 'branch', 'generation']; if (!required.every((name) => header.includes(name))) throw new Error('Thiếu cột bắt buộc: fullName, gender, birthDate, branch, generation.'); const index = (name: string) => header.indexOf(name); const parsed = rows.slice(1).map((row, rowIndex) => { const branchText = row[index('branch')]?.trim() || ''; const branch = data.branches.find((item) => clean(item.name) === clean(branchText) || item.id === branchText); const gender = clean(row[index('gender')] || ''); const birthDate = row[index('birthdate')]?.trim() || ''; const generation = Number(row[index('generation')]); if (!branch || !['male', 'female', 'other'].includes(gender) || birthDate && !/^\d{4}-\d{2}-\d{2}$/.test(birthDate) || !Number.isInteger(generation) || generation < 1) throw new Error(`Dòng ${rowIndex + 2}: giới tính, ngày sinh, Chi/Nhánh hoặc đời thứ không hợp lệ.`); return { fullName: row[index('fullname')]?.trim() || '', gender: gender as FamilyPerson['gender'], birthDate, branchId: branch.id, generation }; }); setXlsxPreview(parsed); setNotice({ text: `Đã đọc ${parsed.length} dòng Excel. Xác nhận để nhập cục bộ.`, error: false }); } catch (error) { setNotice({ text: error instanceof Error ? error.message : 'Không đọc được file Excel.', error: true }); } }} /><button type="button" className="fa-primary" disabled={!xlsxPreview?.length} onClick={() => { try { const count = importPersons(xlsxPreview || []); setXlsxPreview(null); setNotice({ text: `Đã nhập ${count} Person từ Excel vào dữ liệu cục bộ.`, error: false }); } catch (error) { setNotice({ text: error instanceof Error ? error.message : 'Không thể nhập Excel.', error: true }); } }}>Xác nhận nhập Excel</button><button type="button" onClick={async () => { try { await downloadFamilyXlsx(getFamilyAdminState()); } catch { setNotice({ text: 'Không thể xuất file Excel.', error: true }); } }}>Xuất Excel Person & Quan hệ</button></div>{xlsxPreview && <p className="fa-muted">Sẵn sàng nhập {xlsxPreview.length} Person. Hãy kiểm tra tên Chi/Nhánh và bản ghi trùng trước khi xác nhận.</p>}</div><div className="fa-panel"><h2>Nhập Person từ CSV</h2><p className="fa-muted">CSV UTF-8 là lựa chọn nhẹ hơn Excel; nhập tất cả hoặc không nhập dòng nào khi có lỗi.</p><div className="fa-actions"><button type="button" onClick={() => downloadFile('mau-person-family-admin.csv', 'fullName,gender,birthDate,branch,generation\n"Võ Văn Mẫu",male,1990-01-01,"Chi Trưởng",6\n', 'text/csv;charset=utf-8')}>Tải file mẫu</button><input type="file" accept=".csv,text/csv" aria-label="Chọn tệp CSV" onChange={(event) => { setCsvFile(event.target.files?.[0] || null); setCsvPreview(null); }} /></div>{csvFile && <p className="fa-muted">Đã chọn: {csvFile.name}</p>}<div className="fa-actions"><button type="button" onClick={async () => { try { if (!csvFile) throw new Error('Vui lòng chọn tệp CSV.'); if (csvFile.size > 2_000_000) throw new Error('Tệp vượt quá 2 MB.'); const rows = parseCsv(await csvFile.text()); if (rows.length < 2) throw new Error('Tệp chưa có dữ liệu Person.'); const header = rows[0].map(clean); const required = ['fullname', 'gender', 'birthdate', 'branch', 'generation']; if (!required.every((name) => header.includes(name))) throw new Error('Thiếu cột bắt buộc: fullName, gender, birthDate, branch, generation.'); const index = (name: string) => header.indexOf(name); const parsed = rows.slice(1).map((row, rowIndex) => { const branchText = row[index('branch')]?.trim() || ''; const branch = data.branches.find((item) => clean(item.name) === clean(branchText) || item.id === branchText); const gender = clean(row[index('gender')] || ''); const birthDate = row[index('birthdate')]?.trim() || ''; const generation = Number(row[index('generation')]); if (!branch || !['male', 'female', 'other'].includes(gender) || birthDate && !/^\d{4}-\d{2}-\d{2}$/.test(birthDate) || !Number.isInteger(generation) || generation < 1) throw new Error(`Dòng ${rowIndex + 2}: giới tính, ngày sinh, Chi/Nhánh hoặc đời thứ không hợp lệ.`); return { fullName: row[index('fullname')]?.trim() || '', gender: gender as FamilyPerson['gender'], birthDate, branchId: branch.id, generation }; }); setCsvPreview(parsed); setNotice({ text: `Đã kiểm tra định dạng ${parsed.length} dòng. Xác nhận để nhập cục bộ.`, error: false }); } catch (error) { setCsvPreview(null); setNotice({ text: error instanceof Error ? error.message : 'Không đọc được tệp CSV.', error: true }); } }}>Kiểm tra tệp</button><button type="button" className="fa-primary" disabled={!csvPreview?.length} onClick={() => { try { const count = importPersons(csvPreview || []); setCsvPreview(null); setCsvFile(null); setNotice({ text: `Đã nhập ${count} Person vào dữ liệu cục bộ.`, error: false }); } catch (error) { setNotice({ text: error instanceof Error ? error.message : 'Không thể nhập dữ liệu.', error: true }); } }}>Xác nhận nhập</button></div>{csvPreview && <div className="fa-table-wrap"><table><thead><tr><th>Họ tên</th><th>Giới tính</th><th>Ngày sinh</th><th>Chi/Nhánh</th><th>Đời</th></tr></thead><tbody>{csvPreview.slice(0, 10).map((person, index) => <tr key={`${person.fullName}-${index}`}><td>{person.fullName}</td><td>{genderLabels[person.gender]}</td><td>{person.birthDate || '—'}</td><td>{branchName(person.branchId)}</td><td>{person.generation}</td></tr>)}</tbody></table>{csvPreview.length > 10 && <p className="fa-muted">Đang xem 10/{csvPreview.length} dòng.</p>}</div>}</div><div className="fa-panel"><h2>Xuất dữ liệu cục bộ</h2><p className="fa-muted">Chỉ xuất tên, giới tính, ngày sinh, Chi/Nhánh, đời thứ và quan hệ đã ghi; không đưa email, số điện thoại hoặc hồ sơ riêng tư vào file CSV.</p><div className="fa-actions"><button type="button" className="fa-primary" onClick={() => { const current = getFamilyAdminState(); const rows = [['fullName', 'gender', 'birthDate', 'branch', 'generation'], ...current.persons.filter((person) => !person.hidden && person.visibility !== 'private').map((person) => [person.fullName, person.gender, person.birthDate, current.branches.find((branch) => branch.id === person.branchId)?.name || '', String(person.generation)])]; downloadFile('person-family-admin.csv', rows.map((row) => row.map(csvEscape).join(',')).join('\r\n'), 'text/csv;charset=utf-8'); }}>Xuất Person CSV</button><button type="button" onClick={() => { const current = getFamilyAdminState(); const visible = new Set(current.persons.filter((person) => !person.hidden && person.visibility !== 'private').map((person) => person.id)); const rows = [['type', 'from', 'to', 'since'], ...current.relations.filter((relation) => visible.has(relation.fromId) && visible.has(relation.toId)).map((relation) => [relation.type, current.persons.find((person) => person.id === relation.fromId)?.fullName || '', current.persons.find((person) => person.id === relation.toId)?.fullName || '', relation.since])]; downloadFile('quan-he-family-admin.csv', rows.map((row) => row.map(csvEscape).join(',')).join('\r\n'), 'text/csv;charset=utf-8'); }}>Xuất quan hệ CSV</button></div></div></>}

    {view === 'audit' && <div className="fa-panel"><h2>Nhật ký trong trình duyệt</h2><p className="fa-muted">Nhật ký này không thay thế AuditLog ở máy chủ.</p>{data.audit.length ? <ul className="fa-audit-list">{data.audit.map((item) => <li key={item.id}><span>{item.action}</span><time>{new Date(item.at).toLocaleString('vi-VN')}</time></li>)}</ul> : <p>Chưa có thao tác.</p>}</div>}
  </section>;
};

export default FamilyAdminModule;
