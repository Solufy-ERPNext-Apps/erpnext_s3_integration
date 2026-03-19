# User Guide

## Overview

ERPNext S3 Integration lets you store ERPNext attachments and backups in S3-compatible object storage such as AWS S3 or MinIO.

This guide is written for system administrators and ERPNext users who manage storage, backups, and file migration.

## What This App Does

- Stores new ERPNext attachments in S3.
- Opens S3-backed files from within ERPNext.
- Migrates existing local files to S3.
- Syncs database and file backups to S3.
- Supports scheduled backup sync using a CRON expression.

## Before You Start

Make sure you have:

- A working ERPNext / Frappe site with this app installed
- Access to **S3 Integration Settings**
- A valid S3 bucket or S3-compatible storage
- The following credentials:
  - Access Key ID
  - Secret Access Key
  - Region Name
  - Bucket Name
- An endpoint URL if you are using MinIO or another S3-compatible provider

## Open S3 Integration Settings

1. Log in as a user with System Manager access.
2. Search for **S3 Integration Settings** from the Awesome Bar.
3. Open the settings document.

## Connection Settings

Fill in the following fields:

- `AWS Access Key ID`: Access key for the target bucket
- `AWS Secret Access Key`: Secret key for the target bucket
- `Region Name`: AWS region or provider region
- `Bucket Name`: Destination bucket name
- `Endpoint URL`: Required for MinIO and some S3-compatible providers
- `Use Path Style`: Enable this when your provider requires path-style bucket access
- `Folder Prefix`: Optional root prefix for all files stored by the app

After entering the values:

1. Save the document.
2. Click `Test Connection`.
3. Confirm that the connection status changes to `Configured & Connected`.

## Attachment Storage

Use this section when you want new ERPNext attachments to be stored in S3 instead of the local filesystem.

### Enable Attachment Storage

1. Open **S3 Integration Settings**.
2. Enable `Enable Attachments S3`.
3. Choose how files should be served:
   - Enable `Stream From S3` to stream files through ERPNext
   - Disable `Stream From S3` to use pre-signed S3 URLs
4. Optionally enable `Delete From S3 On File Delete`.
5. Save the document.

### What Happens After Enabling

- New file uploads are stored in S3.
- ERPNext stores the file path as a `/s3/...` URL in the `File` record.
- Files remain accessible from ERPNext using the app route.

## Existing File Migration

Use this option if your ERPNext site already has attachments stored locally and you want to move them to S3.

### Start the Migration

1. Open **S3 Integration Settings**.
2. Confirm `Enable Attachments S3` is enabled.
3. Enable `Migrate Only Unmigrated` if you want to skip files that already point to S3.
4. Click `Migrate Existing Files`.

### How Migration Works

- The migration runs in the background.
- Local files are uploaded to S3.
- The related ERPNext `File` records are updated to use `/s3/...` URLs.
- External links such as `http://` and `https://` are skipped.

### Important Notes

- Keep your S3 settings active during migration.
- If a local file is already missing from disk, that file cannot be migrated.
- Disabling `Enable Attachments S3` stops new uploads from going to S3, but existing `/s3/...` files still require valid S3 credentials to open.

## Backup Sync

Use this section to send ERPNext backups to S3.

### Enable Backup Sync

1. Open **S3 Integration Settings**.
2. Enable `Enable Backups S3`.
3. Choose the backup types you want:
   - Database backups
   - File backups
4. Set `Backup Folder Prefix` if you want backups in a separate S3 path.
5. Enter a `Backup CRON Expression`.
6. Choose whether to enable `Create New Backup Before Sync`.
7. Choose whether to enable `Keep Local Backups`.
8. Save the document.

### Manual Backup Sync

To force an immediate backup and upload:

1. Open **S3 Integration Settings**.
2. Click `Take Backup and Sync`.

### Scheduled Backup Sync

When the scheduler is running:

- The app checks the CRON expression.
- It uploads new backup files to S3 when the next scheduled time is reached.
- If retention days are configured, it can also remove older backup objects from S3.

## File Access Behavior

The app supports two file delivery modes.

### Stream From S3

When `Stream From S3` is enabled:

- Files are served through ERPNext.
- Users access files without being redirected to the storage provider.

### Pre-signed URL

When `Stream From S3` is disabled:

- ERPNext generates a temporary download URL.
- The user is redirected to S3 for the file download.

## Recommended Setup

For most production sites:

- Enable `Enable Attachments S3`
- Use a dedicated `Folder Prefix`
- Test file upload with one sample attachment
- Enable backup sync after attachment storage is verified
- Keep local backups enabled initially until backup uploads are confirmed

## Troubleshooting

### Test Connection Fails

Check:

- Access key and secret key
- Bucket name
- Region name
- Endpoint URL
- Path-style setting for MinIO or custom S3 providers
- Bucket permissions

### File Does Not Open

Check:

- The `File` record has a `/s3/...` URL
- S3 credentials are still configured
- The object exists in the bucket
- The selected delivery mode is correct for your environment

### Migration Skips or Fails for Some Files

Possible reasons:

- The file was already migrated
- The file is an external URL, not a local attachment
- The local file no longer exists on disk
- S3 upload failed because of credentials, permissions, or endpoint configuration

### Backup Sync Does Not Run

Check:

- `Enable Backups S3` is enabled
- The scheduler is running
- The CRON expression is valid
- The bench has `croniter` installed
- The site can create backups normally

## Validation Checklist

Use this checklist after setup:

- `Test Connection` succeeds
- A new attachment is uploaded and stored with a `/s3/...` URL
- An existing migrated file opens successfully
- Manual backup sync uploads backup files to S3
- Scheduled backup sync runs at the expected time

## Support

Maintained by Solufy

- Company: Solufy
- Email: sahil@solufy.in
