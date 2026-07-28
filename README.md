# ERPNext S3 Integration

ERPNext S3 Integration is a Frappe app by Solufy that stores ERPNext attachments and backups in S3-compatible object storage.

It supports AWS S3 and compatible providers such as MinIO, keeps existing S3-backed files accessible inside ERPNext, and provides a settings-driven workflow for file migration and backup sync.

## Features

- Store new ERPNext `File` attachments in S3 instead of the local filesystem.
- Open S3-backed files inside ERPNext through a secure application route.
- Support both direct streaming and pre-signed URL redirects for file delivery.
- Preview PDFs and safe raster images inline while downloading active or unknown file types.
- Migrate existing local attachments to S3 in the background.
- Sync database and file backups to S3.
- Schedule backup sync using a CRON expression from the settings doctype.
- Optionally delete S3 objects when the related ERPNext `File` record is deleted.
- Optionally remove local backup files after successful S3 upload.
- Support custom bucket prefixes for both attachments and backups.
- Support S3-compatible endpoints with path-style addressing for MinIO and similar providers.

For a concise GitHub feature summary, see [FEATURES.md](FEATURES.md).

## Requirements

- Frappe / ERPNext v16 bench
- Python 3.14+
- An S3-compatible bucket
- Valid access credentials for the target bucket

## Installation

Run the following from your bench directory:

```bash
bench get-app https://github.com/solufy/erpnext_s3_integration
bench --site <your-site> install-app erpnext_s3_integration
bench migrate && bench restart
```

If you are installing from a local app path or a private repository, use your normal `bench get-app` flow and then install the app on the target site.

## Dependencies

This app requires:

- `boto3`
- `croniter`

If your environment does not install Python dependencies automatically, run:

```bash
bench pip install -r apps/erpnext_s3_integration/requirements.txt
bench restart
```

## Setup

1. Open **S3 Integration Settings** in ERPNext.
2. Enter the S3 connection details:
   - `AWS Access Key ID`
   - `AWS Secret Access Key`
   - `Region Name`
   - `Bucket Name`
   - `Endpoint URL` if you are using MinIO or another S3-compatible service
   - `Use Path Style` if required by your storage provider
3. Optionally set `Folder Prefix` to keep all objects under a dedicated root path.
4. Save the document.
5. Click `Test Connection`.

### Environment Variables & `site_config.json` Fallback

If credentials are not explicitly set in **S3 Integration Settings** DocType, the app automatically falls back to `site_config.json` or Environment Variables (ideal for Docker, Kubernetes Secrets, HashiCorp Vault, AWS Secrets Manager, Doppler, Infisical, or GitOps pipelines):

* **Environment Variables**:
  * `AWS_ACCESS_KEY_ID`
  * `AWS_SECRET_ACCESS_KEY`
  * `AWS_DEFAULT_REGION` / `AWS_REGION`
  * `AWS_S3_BUCKET`
  * `AWS_ENDPOINT_URL` (optional)
  * `AWS_S3_USE_PATH_STYLE` (`1` or `true`, optional)

  `Use Path Style` is a Frappe Check field, so its default `0` has no distinct
  "unset" state. An enabled value in Desk takes priority. When it is disabled,
  the app falls back to `s3_use_path_style` and then
  `AWS_S3_USE_PATH_STYLE`, allowing environment-only deployments to opt in.

* **`site_config.json`**:
  ```json
  {
    "s3_access_key_id": "your-access-key",
    "s3_secret_access_key": "your-secret-key",
    "s3_region": "us-east-1",
    "s3_bucket": "your-bucket-name",
    "s3_endpoint_url": "https://s3.us-east-1.amazonaws.com",
    "s3_use_path_style": false
  }
  ```

### Security Enhancements & Object Ownership (ACLs)

> **Important Security Note**: By default, `Use Public Read ACL` is **disabled (`0`)**. Objects uploaded to S3 are stored as private, requiring proxy streaming or pre-signed URLs. This aligns with modern AWS S3 security standards (`BucketOwnerEnforced` with Block Public Access enabled).

If your environment (e.g. legacy MinIO setup) requires public read ACLs on public attachments:
1. Enable `Use Public Read ACL` in **S3 Integration Settings** (managed strictly from Desk UI).
2. Ensure your IAM user has `s3:PutObjectAcl` permissions and your bucket allows Object ACLs (`BucketOwnerPreferred` or ACLs enabled).

## Attachment Storage Setup

To store new attachments in S3:

1. Enable `Enable Attachments S3`.
2. Choose whether files should be streamed through ERPNext or served with pre-signed URLs using `Stream From S3`.
3. Optionally enable `Delete From S3 On File Delete`.
4. Save the settings.

From that point onward, newly uploaded ERPNext attachments are stored in S3.

### Upload API

The app intercepts normal Frappe `File` creation; clients do not need an
S3-specific upload endpoint. Desk, mobile, and SPA clients can keep using
Frappe's authenticated multipart endpoint:

```http
POST /api/method/upload_file
Authorization: token <api-key>:<api-secret>
Content-Type: multipart/form-data
```

Multipart fields:

- `file`: file body
- `is_private`: `1` for private files, `0` for public files
- `doctype` and `docname`: optional attachment target
- `fieldname`: optional attachment field

Example:

```bash
curl -X POST "https://erp.example.com/api/method/upload_file" \
  -H "Authorization: token API_KEY:API_SECRET" \
  -F "file=@invoice.pdf" \
  -F "is_private=1" \
  -F "doctype=Sales Invoice" \
  -F "docname=ACC-SINV-2026-00001"
```

Server-side code can continue using Frappe's file manager:

```python
from frappe.utils.file_manager import save_file

file_doc = save_file(
    "invoice.pdf",
    pdf_bytes,
    "Sales Invoice",
    "ACC-SINV-2026-00001",
    is_private=1,
)
```

`file_doc.file_url` is stored as `/s3/<object-key>`. Applications should retain
and open that URL instead of constructing an S3 URL or calling
`S3Client.upload_fileobj()` directly.

### Object Keys and Uniqueness

New object keys mirror Frappe's public/private layout:

```text
<folder-prefix>/<public|private>/<content-hash>-<normalized-file-name>
```

When Frappe has not populated `content_hash`, the normalized `file_name` is
used. Frappe may already add a conflict-avoiding suffix to that name.

The app does **not** currently add a UUID. `content_hash` is Frappe's MD5-based
content identifier for deduplication and naming, not a security digest or random
identifier. Callers must treat the returned `file_url` as the canonical
location.

### Download and Preview API

Open the `file_url` returned by Frappe:

```http
GET /s3/private/files/invoice.pdf
```

The route resolves internally to:

```http
GET /api/method/erpnext_s3_integration.api.get_file?key=private/files/invoice.pdf
```

Before returning content, the app loads the matching `File` document, rejects
Guest access to private files, and requires `File.is_downloadable()`.

- With `Stream From S3` enabled, Frappe proxies the object bytes.
- With it disabled, Frappe redirects to a presigned S3 URL valid for one hour.
- PDFs and matching safe raster image types are served with `inline`.
- HTML, SVG, unknown types, and MIME/extension mismatches use `attachment`.
- Presigned response-header overrides provide preview behavior for legacy
  objects that were stored as `application/octet-stream`.

Custom Frappe authentication hooks remain compatible. If a JWT or other bearer
hook validates the request and establishes `frappe.session.user` before the
method runs, the same `File.is_downloadable()` authorization applies. The S3
app does not independently interpret JWT claims or bypass Frappe permissions.

For browser `fetch()` or XHR access to a presigned URL, allow the application
origin in the bucket CORS policy. Normal navigation and native mobile clients
do not use browser CORS in the same way.

## Existing File Migration

To migrate existing files already stored on disk:

1. Open **S3 Integration Settings**.
2. Ensure `Enable Attachments S3` is enabled.
3. Enable `Migrate Only Unmigrated` if you want to skip rows already pointing to S3.
4. Click `Migrate Existing Files`.

The migration runs as a background job. It uploads local files to S3 and updates the corresponding `File.file_url` to the `/s3/...` route used by the app.

## Backup Sync Setup

To send ERPNext backups to S3:

1. Enable `Enable Backups S3`.
2. Choose whether to upload database backups, file backups, or both.
3. Set `Backup Folder Prefix` if you want backups stored separately from attachments.
4. Set `Backup CRON Expression`.
5. Choose whether to create a fresh backup before sync.
6. Choose whether to keep local backups after upload.
7. Save the settings.

The scheduler checks the CRON expression and uploads backup files to S3 when the next run time is due.

You can also trigger an immediate manual sync from the settings form with `Take Backup and Sync`.

## Behavior Notes

- Disabling `Enable Attachments S3` stops new uploads from being redirected to S3.
- Existing files that already point to `/s3/...` remain accessible as long as the S3 credentials are still configured.
- External file URLs such as `http://` and `https://` are skipped by the migration tool.
- The app uses a `File` override so ERPNext can read S3-backed files without expecting them on local disk.

## Project Structure

- [hooks.py](erpnext_s3_integration/hooks.py) registers file hooks, scheduler hooks, redirects, and the `File` override.
- [file_hooks.py](erpnext_s3_integration/file_hooks.py) handles upload interception, key generation, and delete sync.
- [api.py](erpnext_s3_integration/api.py) serves S3-backed files through ERPNext.
- [migration.py](erpnext_s3_integration/migration.py) migrates existing local files to S3.
- [backup_hooks.py](erpnext_s3_integration/backup_hooks.py) syncs backups and handles retention cleanup.
- [s3_client.py](erpnext_s3_integration/s3_client.py) wraps S3 client setup, upload, delete, and URL generation.

## Verification Checklist

- `Test Connection` succeeds.
- A newly uploaded attachment gets a `/s3/...` URL in the `File` record.
- Opening an existing S3-backed file works from ERPNext.
- Manual backup sync uploads the expected backup artifacts.
- Scheduled backup sync runs with the configured CRON expression.

## Support

Maintained by Solufy.

- Company: Solufy Pvy. Ltd.
- Email: sahil@solufy.in

## License

MIT
