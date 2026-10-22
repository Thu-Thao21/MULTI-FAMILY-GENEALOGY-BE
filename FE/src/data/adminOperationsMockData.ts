export type AuditLevel = 'info' | 'warning' | 'security' | 'error';
export type AuditStatus = 'success' | 'failed';

export interface AuditLogRecord {
  id: string;
  timestamp: string;
  user: string;
  action: string;
  module: string;
  ip: string;
  device: string;
  status: AuditStatus;
  level: AuditLevel;
  detail: string;
}

export const auditLogMockData: AuditLogRecord[] = [];

export type BackupStatus = 'success' | 'processing' | 'failed';

export interface BackupRecord {
  id: string;
  name: string;
  type: 'Full' | 'Incremental' | 'Manual';
  createdAt: string;
  size: string;
  status: BackupStatus;
  createdBy: string;
}

export const backupMockData: BackupRecord[] = [];
