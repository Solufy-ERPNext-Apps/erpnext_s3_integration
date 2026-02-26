## ERPNext S3 Integration

A production-ready custom Frappe app that integrates AWS S3 with ERPNext to handle file attachments and system backups.

### Features
* **File Attachments to S3**: Automatically upload new `File` attachments to an S3 bucket instead of the local filesystem.
* **Stream or Redirect**: View private and public files stored on S3 directly within the UI, using either short-lived pre-signed URLs or direct streaming proxy.
* **Deletion Sync**: Automatically delete objects from S3 when the `File` document is deleted in ERPNext.
* **Database & File Backups to S3**: Sync scheduled internal Frappe backups (Database & Files) to your S3 bucket seamlessly.
* **MinIO Support**: Compatible with self-hosted S3-compatible object storage like MinIO by configuring custom Endpoint URLs and Path Style Addressing.
* **Migration Tool**: Easily migrate existing locally stored files to S3 with a background process.

### Installation

Run these commands from your Frappe bench folder:

```bash
# Get the app
bench get-app https://github.com/your-repo/erpnext_s3_integration

# Install app on your site
bench --site [your-site-name] install-app erpnext_s3_integration
```

> [!NOTE]
> The app depends on the `boto3` Python library, which is automatically installed during `bench get-app`.

### Configuration

1. Log into your ERPNext instance as an Administrator.
2. Navigate to **S3 Integration Settings** (accessible via the Awesomebar).
3. Provide your S3 Credentials (`Access Key ID`, `Secret Access Key`, `Region Name`, `Bucket Name`).
4. (Optional) Provide an `Endpoint URL` and check `Use Path Style` if you use an S3-compatible service like MinIO.
5. Select the features you want to enable in the "Feature Toggles" and "Backups" sections.
6. Click **Save**.
7. Use the **Test Connection** button to verify your configuration.

### File Migrations
To migrate existing files that are stored on the local Frappe filesystem to S3:
1. Go to **S3 Integration Settings**.
2. Under the *Attachments Migration* section, ensure S3 File integration is enabled.
3. Click the **Migrate Existing Files** button. 
4. The migration will run in the background. You can check the *Background Jobs* list or wait for the system notification indicating completion.

### License
MIT
