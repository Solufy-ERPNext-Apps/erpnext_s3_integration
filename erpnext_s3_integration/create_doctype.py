import frappe


def create_s3_integration_settings():
    doctype_name = "S3 Integration Settings"
    if frappe.db.exists("DocType", doctype_name):
        print(f"{doctype_name} already exists. Skipping.")
        return

    doc = frappe.get_doc(
        {
            "doctype": "DocType",
            "name": doctype_name,
            "module": "ERPNext S3 Integration",
            "custom": 0,
            "issingle": 1,
            "actions": [],
            "links": [],
            "fields": [
                {
                    "fieldname": "s3_credentials_section",
                    "fieldtype": "Section Break",
                    "label": "S3 Credentials",
                },
                {
                    "fieldname": "aws_access_key_id",
                    "fieldtype": "Data",
                    "label": "AWS Access Key ID",
                },
                {
                    "fieldname": "aws_secret_access_key",
                    "fieldtype": "Password",
                    "label": "AWS Secret Access Key",
                },
                {
                    "fieldname": "region_name",
                    "fieldtype": "Data",
                    "label": "Region Name",
                },
                {
                    "fieldname": "bucket_name",
                    "fieldtype": "Data",
                    "label": "Bucket Name",
                },
                {"fieldname": "cb_advanced", "fieldtype": "Column Break"},
                {
                    "fieldname": "folder_prefix",
                    "fieldtype": "Data",
                    "label": "Folder Prefix",
                    "description": "Base prefix for all uploads (e.g. erpnext)",
                },
                {
                    "fieldname": "endpoint_url",
                    "fieldtype": "Data",
                    "label": "Endpoint URL",
                    "description": "For MinIO or custom S3 endpoints",
                },
                {
                    "fieldname": "use_path_style",
                    "fieldtype": "Check",
                    "label": "Use Path Style",
                },
                {
                    "fieldname": "sb_actions",
                    "fieldtype": "Section Break",
                    "label": "Actions",
                },
                {
                    "fieldname": "test_connection",
                    "fieldtype": "Button",
                    "label": "Test Connection",
                },
                {
                    "fieldname": "status",
                    "fieldtype": "Data",
                    "label": "Status",
                    "read_only": 1,
                },
                {
                    "fieldname": "feature_toggles_section",
                    "fieldtype": "Section Break",
                    "label": "Feature Toggles",
                },
                {
                    "fieldname": "enable_attachments_s3",
                    "fieldtype": "Check",
                    "label": "Enable S3 for file attachments",
                },
                {
                    "fieldname": "stream_from_s3",
                    "fieldtype": "Check",
                    "label": "Stream file content from S3 when viewing/downloading",
                    "depends_on": "eval:doc.enable_attachments_s3",
                },
                {
                    "fieldname": "delete_from_s3_on_file_delete",
                    "fieldtype": "Check",
                    "label": "Delete from S3 when File is deleted",
                    "depends_on": "eval:doc.enable_attachments_s3",
                },
                {"fieldname": "cb_backups", "fieldtype": "Column Break"},
                {
                    "fieldname": "enable_backups_s3",
                    "fieldtype": "Check",
                    "label": "Enable S3 for backups",
                },
                {
                    "fieldname": "migration_section",
                    "fieldtype": "Section Break",
                    "label": "Attachments Migration",
                    "depends_on": "eval:doc.enable_attachments_s3",
                },
                {
                    "fieldname": "migrate_existing_files",
                    "fieldtype": "Button",
                    "label": "Migrate Existing Files",
                },
                {
                    "fieldname": "migrate_only_unmigrated",
                    "fieldtype": "Check",
                    "label": "Only migrate files not already on S3",
                    "default": "1",
                },
                {
                    "fieldname": "backups_section",
                    "fieldtype": "Section Break",
                    "label": "Backups",
                    "depends_on": "eval:doc.enable_backups_s3",
                },
                {
                    "fieldname": "upload_db_backup",
                    "fieldtype": "Check",
                    "label": "Upload DB Backup",
                },
                {
                    "fieldname": "upload_files_backup",
                    "fieldtype": "Check",
                    "label": "Upload Files Backup",
                },
                {
                    "fieldname": "backup_folder_prefix",
                    "fieldtype": "Data",
                    "label": "Backup Folder Prefix",
                    "default": "backups",
                },
                {
                    "fieldname": "keep_local_backups",
                    "fieldtype": "Check",
                    "label": "Keep Local Backups",
                    "default": "1",
                    "description": "If disabled, local backup files will be deleted after successful S3 upload.",
                },
            ],
            "permissions": [
                {
                    "role": "System Manager",
                    "read": 1,
                    "write": 1,
                    "create": 1,
                    "delete": 0,
                    "submit": 0,
                }
            ],
        }
    )

    doc.insert()
    print(f"DocType '{doctype_name}' created successfully.")


if __name__ == "__main__":
    create_s3_integration_settings()
