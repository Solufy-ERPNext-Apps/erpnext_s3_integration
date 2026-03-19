import frappe
from frappe import _
from frappe.model.document import Document

from erpnext_s3_integration.s3_client import S3Client


class S3IntegrationSettings(Document):
	def validate(self):
		if self.enable_attachments_s3 or self.enable_backups_s3:
			required_fields = ["aws_access_key_id", "region_name", "bucket_name"]
			missing = []
			for field in required_fields:
				if not self.get(field):
					missing.append(self.meta.get_field(field).label)

			if not self.get_password("aws_secret_access_key"):
				missing.append("AWS Secret Access Key")

			if missing:
				frappe.throw(
					f"The following fields are required when S3 Integration features are enabled: {', '.join(missing)}"
				)


@frappe.whitelist()
def test_s3_connection():
	frappe.only_for("System Manager")
	try:
		client = S3Client()
		success, msg = client.test_connection()

		return {"success": success, "message": msg}
	except Exception as e:
		return {"success": False, "message": str(e)}


@frappe.whitelist()
def take_backup_and_sync():
	frappe.only_for("System Manager")

	settings = frappe.get_single("S3 Integration Settings")
	if not settings.enable_backups_s3:
		frappe.throw(_("S3 Backups are currently disabled in Settings."))

	frappe.enqueue(
		"erpnext_s3_integration.erpnext_s3_integration.doctype.s3_integration_settings.s3_integration_settings.run_backup_and_sync",
		queue="long",
		timeout=1500,
	)
	return "Backup and Sync job enqueued successfully."


def run_backup_and_sync():
	import frappe.utils.backups

	from erpnext_s3_integration.backup_hooks import after_backup

	try:
		settings = frappe.get_single("S3 Integration Settings")

		frappe.utils.backups.backup(with_files=settings.upload_files_backup)

		# Call the after_backup hook to sync
		after_backup()

	except Exception:
		frappe.log_error(message=frappe.get_traceback(), title="Manual S3 Backup Sync Failed")
