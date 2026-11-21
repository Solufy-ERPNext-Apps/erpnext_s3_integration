app_name = "erpnext_s3_integration"
app_title = "ERPNext S3 Integration"
app_publisher = "Solufy"
app_description = "S3-based storage for File attachments and backups"
app_email = "sahil@solufy.in"
app_license = "mit"

write_file = "erpnext_s3_integration.file_hooks.write_file"
delete_file_data_content = "erpnext_s3_integration.file_hooks.delete_file_data_content"

scheduler_events = {"all": ["erpnext_s3_integration.backup_hooks.scheduled_backup_and_sync"]}

extend_doctype_class = {"File": "erpnext_s3_integration.overrides.file.CustomFile"}

website_redirects = [
	{"source": r"/s3/(.*)", "target": r"/api/method/erpnext_s3_integration.api.get_file?key=\1"}
]
