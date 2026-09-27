CREATE TABLE "users" (
  "user_id" uuid PRIMARY KEY,
  "firebase_uid" varchar(255) UNIQUE NOT NULL,
  "email" varchar(255) UNIQUE NOT NULL,
  "display_name" varchar(255) NOT NULL,
  "phone" varchar(255) NOT NULL,
  "status" varchar(255) NOT NULL,
  "first_login_required" boolean NOT NULL,
  "created_at" timestamptz NOT NULL
);

CREATE TABLE "roles" (
  "role_id" uuid PRIMARY KEY,
  "code" varchar(255) UNIQUE NOT NULL,
  "name" varchar(255) NOT NULL
);

CREATE TABLE "permissions" (
  "permission_id" uuid PRIMARY KEY,
  "code" varchar(255) UNIQUE NOT NULL,
  "module" varchar(255) NOT NULL
);

CREATE TABLE "role_permissions" (
  "role_id" uuid,
  "permission_id" uuid,
  PRIMARY KEY ("role_id", "permission_id")
);

CREATE TABLE "user_roles" (
  "user_role_id" uuid PRIMARY KEY,
  "user_id" uuid NOT NULL,
  "role_id" uuid NOT NULL,
  "clan_id" uuid,
  "granted_by" uuid,
  "revoked_at" timestamptz
);

CREATE TABLE "member_accounts" (
  "member_account_id" uuid PRIMARY KEY,
  "user_id" uuid NOT NULL,
  "person_id" uuid NOT NULL,
  "clan_id" uuid NOT NULL,
  "status" varchar(255) NOT NULL,
  "linked_at" timestamptz NOT NULL
);

CREATE TABLE "account_invitations" (
  "invitation_id" uuid PRIMARY KEY,
  "user_id" uuid,
  "clan_id" uuid NOT NULL,
  "person_id" uuid,
  "token_hash" varchar(255) UNIQUE NOT NULL,
  "purpose" varchar(255) NOT NULL,
  "expires_at" timestamptz NOT NULL,
  "used_at" timestamptz
);

CREATE TABLE "family_admin_assignments" (
  "assignment_id" uuid PRIMARY KEY,
  "user_id" uuid NOT NULL,
  "clan_id" uuid NOT NULL,
  "branch_id" uuid,
  "assigned_by" uuid NOT NULL,
  "revoked_at" timestamptz
);

CREATE TABLE "business_registrations" (
  "registration_id" uuid PRIMARY KEY,
  "requested_plan_id" uuid NOT NULL,
  "representative_name" varchar(255) NOT NULL,
  "representative_email" varchar(255) NOT NULL,
  "clan_name" varchar(255) NOT NULL,
  "status" varchar(255) NOT NULL,
  "tracking_code_hash" varchar(255) UNIQUE NOT NULL,
  "reviewed_by" uuid,
  "reviewed_at" timestamptz,
  "rejection_reason" text,
  "created_at" timestamptz NOT NULL
);

CREATE TABLE "registration_status_history" (
  "history_id" uuid PRIMARY KEY,
  "registration_id" uuid NOT NULL,
  "from_status" varchar(255),
  "to_status" varchar(255) NOT NULL,
  "changed_by" uuid,
  "reason" text,
  "changed_at" timestamptz NOT NULL
);

CREATE TABLE "clans" (
  "clan_id" uuid PRIMARY KEY,
  "registration_id" uuid,
  "clan_code" varchar(255) UNIQUE NOT NULL,
  "name" varchar(255) NOT NULL,
  "status" varchar(255) NOT NULL,
  "activated_at" timestamptz,
  "created_at" timestamptz NOT NULL
);

CREATE TABLE "clan_profiles" (
  "clan_id" uuid PRIMARY KEY,
  "origin_place" varchar(255) NOT NULL,
  "history" text,
  "founder_person_id" uuid,
  "public_description" text,
  "updated_at" timestamptz NOT NULL
);

CREATE TABLE "clan_ownerships" (
  "ownership_id" uuid PRIMARY KEY,
  "clan_id" uuid NOT NULL,
  "user_id" uuid NOT NULL,
  "started_at" timestamptz NOT NULL,
  "ended_at" timestamptz,
  "transfer_id" uuid
);

CREATE TABLE "ownership_transfers" (
  "transfer_id" uuid PRIMARY KEY,
  "clan_id" uuid NOT NULL,
  "from_user_id" uuid NOT NULL,
  "to_user_id" uuid NOT NULL,
  "approved_by" uuid,
  "status" varchar(255) NOT NULL,
  "reason" text,
  "created_at" timestamptz NOT NULL
);

CREATE TABLE "subscription_plans" (
  "plan_id" uuid PRIMARY KEY,
  "code" varchar(255) UNIQUE NOT NULL,
  "name" varchar(255) NOT NULL,
  "price" numeric(18,2) NOT NULL,
  "max_members" integer NOT NULL,
  "max_admins" integer NOT NULL,
  "storage_mb" integer NOT NULL,
  "features" jsonb NOT NULL,
  "status" varchar(255) NOT NULL
);

CREATE TABLE "clan_subscriptions" (
  "subscription_id" uuid PRIMARY KEY,
  "clan_id" uuid NOT NULL,
  "plan_id" uuid NOT NULL,
  "starts_at" timestamptz NOT NULL,
  "ends_at" timestamptz NOT NULL,
  "status" varchar(255) NOT NULL
);

CREATE TABLE "subscription_changes" (
  "change_id" uuid PRIMARY KEY,
  "subscription_id" uuid NOT NULL,
  "old_plan_id" uuid,
  "new_plan_id" uuid NOT NULL,
  "change_type" varchar(255) NOT NULL,
  "changed_by" uuid NOT NULL,
  "changed_at" timestamptz NOT NULL
);

CREATE TABLE "payments" (
  "payment_id" uuid PRIMARY KEY,
  "subscription_id" uuid NOT NULL,
  "amount" numeric(18,2) NOT NULL,
  "currency" varchar(255) NOT NULL,
  "provider_ref" varchar(255),
  "status" varchar(255) NOT NULL,
  "paid_at" timestamptz
);

CREATE TABLE "email_delivery_logs" (
  "email_id" uuid PRIMARY KEY,
  "registration_id" uuid,
  "user_id" uuid,
  "invitation_id" uuid,
  "recipient_email" varchar(255) NOT NULL,
  "email_type" varchar(255) NOT NULL,
  "status" varchar(255) NOT NULL,
  "provider_message_id" varchar(255),
  "attempt_count" integer NOT NULL,
  "sent_at" timestamptz,
  "error_message" text
);

CREATE TABLE "branches" (
  "branch_id" uuid PRIMARY KEY,
  "clan_id" uuid NOT NULL,
  "parent_branch_id" uuid,
  "name" varchar(255) NOT NULL,
  "status" varchar(255) NOT NULL
);

CREATE TABLE "persons" (
  "person_id" uuid PRIMARY KEY,
  "clan_id" uuid NOT NULL,
  "branch_id" uuid,
  "full_name" varchar(255) NOT NULL,
  "gender" varchar(255),
  "birth_date" date,
  "death_date" date,
  "is_living" boolean,
  "biography" text,
  "status" varchar(255) NOT NULL,
  "created_by" uuid
);

CREATE TABLE "person_aliases" (
  "alias_id" uuid PRIMARY KEY,
  "person_id" uuid NOT NULL,
  "alias" varchar(255) NOT NULL,
  "alias_type" varchar(255) NOT NULL
);

CREATE TABLE "person_contacts" (
  "contact_id" uuid PRIMARY KEY,
  "person_id" uuid NOT NULL,
  "email" varchar(255),
  "phone" varchar(255),
  "address" text
);

CREATE TABLE "person_professional_profiles" (
  "profile_id" uuid PRIMARY KEY,
  "person_id" uuid UNIQUE NOT NULL,
  "occupation" varchar(255),
  "expertise" text,
  "interests" text
);

CREATE TABLE "relationships" (
  "relationship_id" uuid PRIMARY KEY,
  "clan_id" uuid NOT NULL,
  "from_person_id" uuid NOT NULL,
  "to_person_id" uuid NOT NULL,
  "relationship_type" varchar(255) NOT NULL,
  "parent_type" varchar(255),
  "started_on" date,
  "ended_on" date,
  "status" varchar(255) NOT NULL,
  "created_by" uuid NOT NULL
);

CREATE TABLE "person_closure" (
  "ancestor_id" uuid,
  "descendant_id" uuid,
  "depth" integer NOT NULL,
  PRIMARY KEY ("ancestor_id", "descendant_id")
);

CREATE TABLE "person_merge_history" (
  "merge_id" uuid PRIMARY KEY,
  "source_person_id" uuid NOT NULL,
  "target_person_id" uuid NOT NULL,
  "merged_by" uuid NOT NULL,
  "merged_at" timestamptz NOT NULL
);

CREATE TABLE "change_requests" (
  "request_id" uuid PRIMARY KEY,
  "clan_id" uuid NOT NULL,
  "requester_id" uuid NOT NULL,
  "person_id" uuid,
  "relationship_id" uuid,
  "request_type" varchar(255) NOT NULL,
  "proposed_data" jsonb NOT NULL,
  "status" varchar(255) NOT NULL,
  "created_at" timestamptz NOT NULL
);

CREATE TABLE "request_reviews" (
  "review_id" uuid PRIMARY KEY,
  "request_id" uuid NOT NULL,
  "reviewer_id" uuid NOT NULL,
  "decision" varchar(255) NOT NULL,
  "reason" text,
  "reviewed_at" timestamptz NOT NULL
);

CREATE TABLE "inter_clan_requests" (
  "inter_request_id" uuid PRIMARY KEY,
  "source_clan_id" uuid NOT NULL,
  "target_clan_id" uuid NOT NULL,
  "requester_id" uuid NOT NULL,
  "source_person_id" uuid,
  "target_person_id" uuid,
  "status" varchar(255) NOT NULL,
  "reviewed_by" uuid
);

CREATE TABLE "inter_clan_links" (
  "link_id" uuid PRIMARY KEY,
  "request_id" uuid NOT NULL,
  "clan_a_id" uuid NOT NULL,
  "clan_b_id" uuid NOT NULL,
  "status" varchar(255) NOT NULL,
  "linked_at" timestamptz NOT NULL
);

CREATE TABLE "inter_clan_shared_policies" (
  "policy_id" uuid PRIMARY KEY,
  "link_id" uuid NOT NULL,
  "owner_clan_id" uuid NOT NULL,
  "data_scope" varchar(255) NOT NULL,
  "visibility" varchar(255) NOT NULL,
  "can_export" boolean NOT NULL
);

CREATE TABLE "death_anniversaries" (
  "anniversary_id" uuid PRIMARY KEY,
  "clan_id" uuid NOT NULL,
  "person_id" uuid NOT NULL,
  "lunar_day" integer NOT NULL,
  "lunar_month" integer,
  "reminder_days" integer NOT NULL,
  "created_by" uuid NOT NULL
);

CREATE TABLE "anniversary_follows" (
  "follow_id" uuid PRIMARY KEY,
  "anniversary_id" uuid NOT NULL,
  "user_id" uuid NOT NULL,
  "reminder_enabled" boolean NOT NULL
);

CREATE TABLE "events" (
  "event_id" uuid PRIMARY KEY,
  "clan_id" uuid NOT NULL,
  "title" varchar(255) NOT NULL,
  "event_type" varchar(255) NOT NULL,
  "starts_at" timestamptz NOT NULL,
  "location" text,
  "status" varchar(255) NOT NULL,
  "created_by" uuid NOT NULL
);

CREATE TABLE "event_participants" (
  "participant_id" uuid PRIMARY KEY,
  "event_id" uuid NOT NULL,
  "user_id" uuid NOT NULL,
  "person_id" uuid,
  "status" varchar(255) NOT NULL
);

CREATE TABLE "funds" (
  "fund_id" uuid PRIMARY KEY,
  "clan_id" uuid NOT NULL,
  "name" varchar(255) NOT NULL,
  "visibility" varchar(255) NOT NULL,
  "status" varchar(255) NOT NULL
);

CREATE TABLE "fund_categories" (
  "category_id" uuid PRIMARY KEY,
  "clan_id" uuid NOT NULL,
  "name" varchar(255) NOT NULL,
  "kind" varchar(255) NOT NULL
);

CREATE TABLE "fund_transactions" (
  "transaction_id" uuid PRIMARY KEY,
  "fund_id" uuid NOT NULL,
  "category_id" uuid,
  "amount" numeric(18,2) NOT NULL,
  "direction" varchar(255) NOT NULL,
  "occurred_on" date NOT NULL,
  "created_by" uuid NOT NULL,
  "description" text
);

CREATE TABLE "contributions" (
  "contribution_id" uuid PRIMARY KEY,
  "transaction_id" uuid UNIQUE NOT NULL,
  "person_id" uuid,
  "user_id" uuid,
  "contributor_name" varchar(255),
  "receipt_document_id" uuid
);

CREATE TABLE "document_categories" (
  "category_id" uuid PRIMARY KEY,
  "clan_id" uuid NOT NULL,
  "name" varchar(255) NOT NULL
);

CREATE TABLE "documents" (
  "document_id" uuid PRIMARY KEY,
  "clan_id" uuid NOT NULL,
  "category_id" uuid,
  "title" varchar(255) NOT NULL,
  "storage_key" varchar(255) NOT NULL,
  "mime_type" varchar(255) NOT NULL,
  "visibility" varchar(255) NOT NULL,
  "status" varchar(255) NOT NULL,
  "uploaded_by" uuid NOT NULL
);

CREATE TABLE "person_documents" (
  "person_id" uuid,
  "document_id" uuid,
  PRIMARY KEY ("person_id", "document_id")
);

CREATE TABLE "event_documents" (
  "event_id" uuid,
  "document_id" uuid,
  PRIMARY KEY ("event_id", "document_id")
);

CREATE TABLE "document_access_policies" (
  "policy_id" uuid PRIMARY KEY,
  "document_id" uuid NOT NULL,
  "role_id" uuid NOT NULL,
  "can_view" boolean NOT NULL,
  "can_download" boolean NOT NULL
);

CREATE TABLE "worship_spaces" (
  "space_id" uuid PRIMARY KEY,
  "clan_id" uuid NOT NULL,
  "title" varchar(255) NOT NULL,
  "visibility" varchar(255) NOT NULL,
  "created_by" uuid NOT NULL
);

CREATE TABLE "worship_persons" (
  "worship_person_id" uuid PRIMARY KEY,
  "space_id" uuid NOT NULL,
  "person_id" uuid NOT NULL,
  "altar_position" integer
);

CREATE TABLE "worship_artifacts" (
  "artifact_id" uuid PRIMARY KEY,
  "space_id" uuid NOT NULL,
  "document_id" uuid,
  "title" varchar(255) NOT NULL,
  "artifact_type" varchar(255) NOT NULL
);

CREATE TABLE "media_360_items" (
  "media_id" uuid PRIMARY KEY,
  "clan_id" uuid NOT NULL,
  "document_id" uuid NOT NULL,
  "title" varchar(255) NOT NULL
);

CREATE TABLE "three_d_items" (
  "model_id" uuid PRIMARY KEY,
  "clan_id" uuid NOT NULL,
  "document_id" uuid NOT NULL,
  "model_format" varchar(255) NOT NULL
);

CREATE TABLE "memorial_messages" (
  "message_id" uuid PRIMARY KEY,
  "space_id" uuid NOT NULL,
  "person_id" uuid,
  "author_id" uuid NOT NULL,
  "content" text NOT NULL,
  "status" varchar(255) NOT NULL
);

CREATE TABLE "virtual_incense" (
  "incense_id" uuid PRIMARY KEY,
  "space_id" uuid NOT NULL,
  "person_id" uuid,
  "user_id" uuid NOT NULL,
  "offered_at" timestamptz NOT NULL
);

CREATE TABLE "clan_privacy_settings" (
  "clan_id" uuid PRIMARY KEY,
  "public_level" varchar(255) NOT NULL,
  "inter_clan_level" varchar(255) NOT NULL,
  "fund_level" varchar(255) NOT NULL
);

CREATE TABLE "person_visibility_settings" (
  "person_id" uuid PRIMARY KEY,
  "basic_level" varchar(255) NOT NULL,
  "contact_level" varchar(255) NOT NULL,
  "relationship_level" varchar(255) NOT NULL
);

CREATE TABLE "ai_consents" (
  "consent_id" uuid PRIMARY KEY,
  "person_id" uuid NOT NULL,
  "user_id" uuid NOT NULL,
  "purpose" varchar(255) NOT NULL,
  "granted" boolean NOT NULL,
  "changed_at" timestamptz NOT NULL
);

CREATE TABLE "ai_jobs" (
  "job_id" uuid PRIMARY KEY,
  "clan_id" uuid NOT NULL,
  "requested_by" uuid NOT NULL,
  "job_type" varchar(255) NOT NULL,
  "status" varchar(255) NOT NULL,
  "created_at" timestamptz NOT NULL
);

CREATE TABLE "ai_suggestions" (
  "suggestion_id" uuid PRIMARY KEY,
  "job_id" uuid NOT NULL,
  "person_id" uuid,
  "proposed_data" jsonb NOT NULL,
  "status" varchar(255) NOT NULL,
  "created_at" timestamptz NOT NULL
);

CREATE TABLE "ai_suggestion_reviews" (
  "review_id" uuid PRIMARY KEY,
  "suggestion_id" uuid NOT NULL,
  "reviewer_id" uuid NOT NULL,
  "decision" varchar(255) NOT NULL,
  "reviewed_at" timestamptz NOT NULL
);

CREATE TABLE "ai_conversations" (
  "conversation_id" uuid PRIMARY KEY,
  "clan_id" uuid NOT NULL,
  "user_id" uuid NOT NULL,
  "started_at" timestamptz NOT NULL
);

CREATE TABLE "ai_messages" (
  "message_id" uuid PRIMARY KEY,
  "conversation_id" uuid NOT NULL,
  "sender" varchar(255) NOT NULL,
  "content" text NOT NULL,
  "created_at" timestamptz NOT NULL
);

CREATE TABLE "notifications" (
  "notification_id" uuid PRIMARY KEY,
  "clan_id" uuid,
  "type" varchar(255) NOT NULL,
  "title" varchar(255) NOT NULL,
  "body" text NOT NULL,
  "created_at" timestamptz NOT NULL
);

CREATE TABLE "user_notifications" (
  "notification_id" uuid,
  "user_id" uuid,
  "read_at" timestamptz,
  PRIMARY KEY ("notification_id", "user_id")
);

CREATE TABLE "notification_preferences" (
  "preference_id" uuid PRIMARY KEY,
  "user_id" uuid NOT NULL,
  "type" varchar(255) NOT NULL,
  "email_enabled" boolean NOT NULL,
  "in_app_enabled" boolean NOT NULL
);

CREATE TABLE "violation_reports" (
  "report_id" uuid PRIMARY KEY,
  "clan_id" uuid,
  "reporter_id" uuid NOT NULL,
  "target_type" varchar(255) NOT NULL,
  "target_id" uuid NOT NULL,
  "reason" text NOT NULL,
  "status" varchar(255) NOT NULL,
  "handled_by" uuid
);

CREATE TABLE "audit_logs" (
  "log_id" uuid PRIMARY KEY,
  "clan_id" uuid,
  "actor_id" uuid,
  "action" varchar(255) NOT NULL,
  "entity_type" varchar(255) NOT NULL,
  "entity_id" uuid,
  "old_data" jsonb,
  "new_data" jsonb,
  "occurred_at" timestamptz NOT NULL
);

CREATE TABLE "import_jobs" (
  "job_id" uuid PRIMARY KEY,
  "clan_id" uuid NOT NULL,
  "file_document_id" uuid,
  "created_by" uuid NOT NULL,
  "status" varchar(255) NOT NULL,
  "created_at" timestamptz NOT NULL
);

CREATE TABLE "import_errors" (
  "error_id" uuid PRIMARY KEY,
  "job_id" uuid NOT NULL,
  "row_number" integer NOT NULL,
  "field_name" varchar(255),
  "message" text NOT NULL
);

CREATE TABLE "export_jobs" (
  "job_id" uuid PRIMARY KEY,
  "clan_id" uuid NOT NULL,
  "requested_by" uuid NOT NULL,
  "output_document_id" uuid,
  "status" varchar(255) NOT NULL
);

CREATE TABLE "backup_jobs" (
  "job_id" uuid PRIMARY KEY,
  "clan_id" uuid,
  "requested_by" uuid NOT NULL,
  "backup_type" varchar(255) NOT NULL,
  "storage_key" varchar(255),
  "status" varchar(255) NOT NULL
);

CREATE TABLE "restore_jobs" (
  "job_id" uuid PRIMARY KEY,
  "backup_job_id" uuid NOT NULL,
  "requested_by" uuid NOT NULL,
  "status" varchar(255) NOT NULL,
  "started_at" timestamptz NOT NULL
);

CREATE TABLE "registration_attachments" (
  "attachment_id" uuid PRIMARY KEY,
  "registration_id" uuid NOT NULL,
  "file_name" varchar(255) NOT NULL,
  "storage_key" text NOT NULL,
  "mime_type" varchar(100) NOT NULL,
  "uploaded_at" timestamptz NOT NULL
);

CREATE TABLE "email_delivery_attempts" (
  "attempt_id" uuid PRIMARY KEY,
  "email_id" uuid NOT NULL,
  "attempt_number" integer NOT NULL,
  "status" varchar(30) NOT NULL,
  "provider_message_id" varchar(255),
  "error_message" text,
  "attempted_at" timestamptz NOT NULL
);

CREATE TABLE "relationship_evidence" (
  "evidence_id" uuid PRIMARY KEY,
  "relationship_id" uuid NOT NULL,
  "document_id" uuid NOT NULL,
  "added_by" uuid NOT NULL,
  "created_at" timestamptz NOT NULL
);

CREATE TABLE "scheduled_reminders" (
  "reminder_id" uuid PRIMARY KEY,
  "anniversary_id" uuid,
  "event_id" uuid,
  "recipient_user_id" uuid NOT NULL,
  "notification_id" uuid,
  "scheduled_at" timestamptz NOT NULL,
  "delivered_at" timestamptz,
  "status" varchar(30) NOT NULL
);

CREATE UNIQUE INDEX ON "email_delivery_attempts" ("email_id", "attempt_number");

CREATE UNIQUE INDEX ON "relationship_evidence" ("relationship_id", "document_id");

COMMENT ON TABLE "scheduled_reminders" IS 'Exactly one of anniversary_id or event_id; enforce by SQL CHECK.';

ALTER TABLE "role_permissions" ADD FOREIGN KEY ("role_id") REFERENCES "roles" ("role_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "role_permissions" ADD FOREIGN KEY ("permission_id") REFERENCES "permissions" ("permission_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "user_roles" ADD FOREIGN KEY ("user_id") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "user_roles" ADD FOREIGN KEY ("role_id") REFERENCES "roles" ("role_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "user_roles" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "user_roles" ADD FOREIGN KEY ("granted_by") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "member_accounts" ADD FOREIGN KEY ("user_id") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "member_accounts" ADD FOREIGN KEY ("person_id") REFERENCES "persons" ("person_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "member_accounts" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "account_invitations" ADD FOREIGN KEY ("user_id") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "account_invitations" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "account_invitations" ADD FOREIGN KEY ("person_id") REFERENCES "persons" ("person_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "family_admin_assignments" ADD FOREIGN KEY ("user_id") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "family_admin_assignments" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "family_admin_assignments" ADD FOREIGN KEY ("branch_id") REFERENCES "branches" ("branch_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "family_admin_assignments" ADD FOREIGN KEY ("assigned_by") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "business_registrations" ADD FOREIGN KEY ("requested_plan_id") REFERENCES "subscription_plans" ("plan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "business_registrations" ADD FOREIGN KEY ("reviewed_by") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "registration_status_history" ADD FOREIGN KEY ("registration_id") REFERENCES "business_registrations" ("registration_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "registration_status_history" ADD FOREIGN KEY ("changed_by") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "clans" ADD FOREIGN KEY ("registration_id") REFERENCES "business_registrations" ("registration_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "clan_profiles" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "clan_profiles" ADD FOREIGN KEY ("founder_person_id") REFERENCES "persons" ("person_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "clan_ownerships" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "clan_ownerships" ADD FOREIGN KEY ("user_id") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "clan_ownerships" ADD FOREIGN KEY ("transfer_id") REFERENCES "ownership_transfers" ("transfer_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "ownership_transfers" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "ownership_transfers" ADD FOREIGN KEY ("from_user_id") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "ownership_transfers" ADD FOREIGN KEY ("to_user_id") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "ownership_transfers" ADD FOREIGN KEY ("approved_by") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "clan_subscriptions" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "clan_subscriptions" ADD FOREIGN KEY ("plan_id") REFERENCES "subscription_plans" ("plan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "subscription_changes" ADD FOREIGN KEY ("subscription_id") REFERENCES "clan_subscriptions" ("subscription_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "subscription_changes" ADD FOREIGN KEY ("old_plan_id") REFERENCES "subscription_plans" ("plan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "subscription_changes" ADD FOREIGN KEY ("new_plan_id") REFERENCES "subscription_plans" ("plan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "subscription_changes" ADD FOREIGN KEY ("changed_by") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "payments" ADD FOREIGN KEY ("subscription_id") REFERENCES "clan_subscriptions" ("subscription_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "email_delivery_logs" ADD FOREIGN KEY ("registration_id") REFERENCES "business_registrations" ("registration_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "email_delivery_logs" ADD FOREIGN KEY ("user_id") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "email_delivery_logs" ADD FOREIGN KEY ("invitation_id") REFERENCES "account_invitations" ("invitation_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "branches" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "branches" ADD FOREIGN KEY ("parent_branch_id") REFERENCES "branches" ("branch_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "persons" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "persons" ADD FOREIGN KEY ("branch_id") REFERENCES "branches" ("branch_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "persons" ADD FOREIGN KEY ("created_by") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "person_aliases" ADD FOREIGN KEY ("person_id") REFERENCES "persons" ("person_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "person_contacts" ADD FOREIGN KEY ("person_id") REFERENCES "persons" ("person_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "person_professional_profiles" ADD FOREIGN KEY ("person_id") REFERENCES "persons" ("person_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "relationships" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "relationships" ADD FOREIGN KEY ("from_person_id") REFERENCES "persons" ("person_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "relationships" ADD FOREIGN KEY ("to_person_id") REFERENCES "persons" ("person_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "relationships" ADD FOREIGN KEY ("created_by") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "person_closure" ADD FOREIGN KEY ("ancestor_id") REFERENCES "persons" ("person_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "person_closure" ADD FOREIGN KEY ("descendant_id") REFERENCES "persons" ("person_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "person_merge_history" ADD FOREIGN KEY ("source_person_id") REFERENCES "persons" ("person_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "person_merge_history" ADD FOREIGN KEY ("target_person_id") REFERENCES "persons" ("person_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "person_merge_history" ADD FOREIGN KEY ("merged_by") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "change_requests" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "change_requests" ADD FOREIGN KEY ("requester_id") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "change_requests" ADD FOREIGN KEY ("person_id") REFERENCES "persons" ("person_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "change_requests" ADD FOREIGN KEY ("relationship_id") REFERENCES "relationships" ("relationship_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "request_reviews" ADD FOREIGN KEY ("request_id") REFERENCES "change_requests" ("request_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "request_reviews" ADD FOREIGN KEY ("reviewer_id") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "inter_clan_requests" ADD FOREIGN KEY ("source_clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "inter_clan_requests" ADD FOREIGN KEY ("target_clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "inter_clan_requests" ADD FOREIGN KEY ("requester_id") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "inter_clan_requests" ADD FOREIGN KEY ("source_person_id") REFERENCES "persons" ("person_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "inter_clan_requests" ADD FOREIGN KEY ("target_person_id") REFERENCES "persons" ("person_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "inter_clan_requests" ADD FOREIGN KEY ("reviewed_by") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "inter_clan_links" ADD FOREIGN KEY ("request_id") REFERENCES "inter_clan_requests" ("inter_request_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "inter_clan_links" ADD FOREIGN KEY ("clan_a_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "inter_clan_links" ADD FOREIGN KEY ("clan_b_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "inter_clan_shared_policies" ADD FOREIGN KEY ("link_id") REFERENCES "inter_clan_links" ("link_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "inter_clan_shared_policies" ADD FOREIGN KEY ("owner_clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "death_anniversaries" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "death_anniversaries" ADD FOREIGN KEY ("person_id") REFERENCES "persons" ("person_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "death_anniversaries" ADD FOREIGN KEY ("created_by") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "anniversary_follows" ADD FOREIGN KEY ("anniversary_id") REFERENCES "death_anniversaries" ("anniversary_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "anniversary_follows" ADD FOREIGN KEY ("user_id") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "events" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "events" ADD FOREIGN KEY ("created_by") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "event_participants" ADD FOREIGN KEY ("event_id") REFERENCES "events" ("event_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "event_participants" ADD FOREIGN KEY ("user_id") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "event_participants" ADD FOREIGN KEY ("person_id") REFERENCES "persons" ("person_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "funds" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "fund_categories" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "fund_transactions" ADD FOREIGN KEY ("fund_id") REFERENCES "funds" ("fund_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "fund_transactions" ADD FOREIGN KEY ("category_id") REFERENCES "fund_categories" ("category_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "fund_transactions" ADD FOREIGN KEY ("created_by") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "contributions" ADD FOREIGN KEY ("transaction_id") REFERENCES "fund_transactions" ("transaction_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "contributions" ADD FOREIGN KEY ("person_id") REFERENCES "persons" ("person_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "contributions" ADD FOREIGN KEY ("user_id") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "contributions" ADD FOREIGN KEY ("receipt_document_id") REFERENCES "documents" ("document_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "document_categories" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "documents" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "documents" ADD FOREIGN KEY ("category_id") REFERENCES "document_categories" ("category_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "documents" ADD FOREIGN KEY ("uploaded_by") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "person_documents" ADD FOREIGN KEY ("person_id") REFERENCES "persons" ("person_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "person_documents" ADD FOREIGN KEY ("document_id") REFERENCES "documents" ("document_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "event_documents" ADD FOREIGN KEY ("event_id") REFERENCES "events" ("event_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "event_documents" ADD FOREIGN KEY ("document_id") REFERENCES "documents" ("document_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "document_access_policies" ADD FOREIGN KEY ("document_id") REFERENCES "documents" ("document_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "document_access_policies" ADD FOREIGN KEY ("role_id") REFERENCES "roles" ("role_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "worship_spaces" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "worship_spaces" ADD FOREIGN KEY ("created_by") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "worship_persons" ADD FOREIGN KEY ("space_id") REFERENCES "worship_spaces" ("space_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "worship_persons" ADD FOREIGN KEY ("person_id") REFERENCES "persons" ("person_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "worship_artifacts" ADD FOREIGN KEY ("space_id") REFERENCES "worship_spaces" ("space_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "worship_artifacts" ADD FOREIGN KEY ("document_id") REFERENCES "documents" ("document_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "media_360_items" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "media_360_items" ADD FOREIGN KEY ("document_id") REFERENCES "documents" ("document_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "three_d_items" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "three_d_items" ADD FOREIGN KEY ("document_id") REFERENCES "documents" ("document_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "memorial_messages" ADD FOREIGN KEY ("space_id") REFERENCES "worship_spaces" ("space_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "memorial_messages" ADD FOREIGN KEY ("person_id") REFERENCES "persons" ("person_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "memorial_messages" ADD FOREIGN KEY ("author_id") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "virtual_incense" ADD FOREIGN KEY ("space_id") REFERENCES "worship_spaces" ("space_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "virtual_incense" ADD FOREIGN KEY ("person_id") REFERENCES "persons" ("person_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "virtual_incense" ADD FOREIGN KEY ("user_id") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "clan_privacy_settings" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "person_visibility_settings" ADD FOREIGN KEY ("person_id") REFERENCES "persons" ("person_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "ai_consents" ADD FOREIGN KEY ("person_id") REFERENCES "persons" ("person_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "ai_consents" ADD FOREIGN KEY ("user_id") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "ai_jobs" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "ai_jobs" ADD FOREIGN KEY ("requested_by") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "ai_suggestions" ADD FOREIGN KEY ("job_id") REFERENCES "ai_jobs" ("job_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "ai_suggestions" ADD FOREIGN KEY ("person_id") REFERENCES "persons" ("person_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "ai_suggestion_reviews" ADD FOREIGN KEY ("suggestion_id") REFERENCES "ai_suggestions" ("suggestion_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "ai_suggestion_reviews" ADD FOREIGN KEY ("reviewer_id") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "ai_conversations" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "ai_conversations" ADD FOREIGN KEY ("user_id") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "ai_messages" ADD FOREIGN KEY ("conversation_id") REFERENCES "ai_conversations" ("conversation_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "notifications" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "user_notifications" ADD FOREIGN KEY ("notification_id") REFERENCES "notifications" ("notification_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "user_notifications" ADD FOREIGN KEY ("user_id") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "notification_preferences" ADD FOREIGN KEY ("user_id") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "violation_reports" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "violation_reports" ADD FOREIGN KEY ("reporter_id") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "violation_reports" ADD FOREIGN KEY ("handled_by") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "audit_logs" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "audit_logs" ADD FOREIGN KEY ("actor_id") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "import_jobs" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "import_jobs" ADD FOREIGN KEY ("file_document_id") REFERENCES "documents" ("document_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "import_jobs" ADD FOREIGN KEY ("created_by") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "import_errors" ADD FOREIGN KEY ("job_id") REFERENCES "import_jobs" ("job_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "export_jobs" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "export_jobs" ADD FOREIGN KEY ("requested_by") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "export_jobs" ADD FOREIGN KEY ("output_document_id") REFERENCES "documents" ("document_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "backup_jobs" ADD FOREIGN KEY ("clan_id") REFERENCES "clans" ("clan_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "backup_jobs" ADD FOREIGN KEY ("requested_by") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "restore_jobs" ADD FOREIGN KEY ("backup_job_id") REFERENCES "backup_jobs" ("job_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "restore_jobs" ADD FOREIGN KEY ("requested_by") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "registration_attachments" ADD FOREIGN KEY ("registration_id") REFERENCES "business_registrations" ("registration_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "email_delivery_attempts" ADD FOREIGN KEY ("email_id") REFERENCES "email_delivery_logs" ("email_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "relationship_evidence" ADD FOREIGN KEY ("relationship_id") REFERENCES "relationships" ("relationship_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "relationship_evidence" ADD FOREIGN KEY ("document_id") REFERENCES "documents" ("document_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "relationship_evidence" ADD FOREIGN KEY ("added_by") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "scheduled_reminders" ADD FOREIGN KEY ("anniversary_id") REFERENCES "death_anniversaries" ("anniversary_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "scheduled_reminders" ADD FOREIGN KEY ("event_id") REFERENCES "events" ("event_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "scheduled_reminders" ADD FOREIGN KEY ("recipient_user_id") REFERENCES "users" ("user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "scheduled_reminders" ADD FOREIGN KEY ("notification_id") REFERENCES "notifications" ("notification_id") DEFERRABLE INITIALLY IMMEDIATE;
