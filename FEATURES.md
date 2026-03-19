# Feature List

## Core Storage

- Upload new ERPNext attachments directly to S3-compatible storage.
- Preserve ERPNext file access through `/s3/...` application routes.
- Read S3-backed files without requiring a local file copy.
- Support public and private file handling through the existing `File` workflow.

## Delivery Options

- Stream files through ERPNext.
- Generate pre-signed S3 URLs for direct object access.
- Keep existing S3-backed files accessible even after new S3 uploads are disabled.

## Migration

- Migrate existing local attachments to S3 in the background.
- Skip already migrated files.
- Skip external web URLs during migration.
- Preserve deterministic S3 object keys based on ERPNext file metadata.

## Backup Sync

- Upload database backups to S3.
- Upload public and private file backups to S3.
- Trigger manual backup creation and sync from settings.
- Run scheduled sync using a CRON expression.
- Organize backups by site and date prefix in the bucket.
- Optionally remove local backup files after successful upload.
- Optionally delete older S3 backups based on retention days.

## S3 Compatibility

- Work with AWS S3.
- Support S3-compatible providers such as MinIO.
- Support custom endpoint URLs.
- Support path-style addressing.
- Support configurable folder prefixes for attachments and backups.

## Administration

- Settings-driven configuration through ERPNext.
- Connection test from the settings form.
- Background processing for migration and backup operations.
- Sync logging through the `S3 Sync Log` doctype.

Maintained by Solufy  
Contact: sahil@solufy.in
