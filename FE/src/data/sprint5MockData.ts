export type ProposalStatus = 'pending' | 'approved' | 'rejected';

export interface ProposalRecord {
  id: string;
  proposerName: string;
  proposerInitial: string;
  targetName: string;
  type: 'profile' | 'relationship';
  relationship: string;
  currentValue: string;
  proposedValue: string;
  reason: string;
  status: ProposalStatus;
  createdAt: string;
  adminNote?: string;
}

export const proposalMockData: ProposalRecord[] = [];

export interface MemorialRecord {
  id: string;
  name: string;
  initial: string;
  generation: number;
  deathDate: string;
  memorialDate: string;
  lunarDate: string;
  relationship: string;
  reminder: boolean;
  notes: string;
}

export const memorialMockData: MemorialRecord[] = [];

export type EventStatus = 'upcoming' | 'ongoing' | 'completed' | 'cancelled';
export type RsvpStatus = 'confirmed' | 'pending' | 'declined';

export interface EventParticipant {
  id: string;
  name: string;
  initial: string;
  relationship: string;
  rsvp: RsvpStatus;
}

export interface FamilyEventRecord {
  id: string;
  title: string;
  type: 'anniversary' | 'gathering' | 'meeting' | 'tomb_cleaning';
  startDate: string;
  endDate?: string;
  location: string;
  organizer: string;
  description: string;
  status: EventStatus;
  participantsCount: number;
  participants: EventParticipant[];
}

export const eventMockData: FamilyEventRecord[] = [];

export type FundTransactionType = 'income' | 'expense';
export type FundTransactionStatus = 'confirmed' | 'pending';

export interface FundTransactionRecord {
  id: string;
  date: string;
  type: FundTransactionType;
  category: string;
  amount: number;
  description: string;
  performer: string;
  status: FundTransactionStatus;
  receiptUrl?: string;
}

export const fundTransactionMockData: FundTransactionRecord[] = [];

export type ArchiveFileType = 'image' | 'document' | 'video' | 'audio';

export interface ArchiveRecord {
  id: string;
  name: string;
  type: ArchiveFileType;
  category: string;
  uploadDate: string;
  fileSize: string;
  uploader: string;
  url: string;
  description: string;
}

export const archiveMockData: ArchiveRecord[] = [];
