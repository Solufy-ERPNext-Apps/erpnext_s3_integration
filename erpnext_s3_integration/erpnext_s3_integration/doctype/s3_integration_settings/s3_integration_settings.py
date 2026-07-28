import frappe
from frappe import _
from frappe.model.document import Document


class S3IntegrationSettings(Document):
	def validate(self):
		if self.enable_attachments_s3 or self.enable_backups_s3:
			from erpnext_s3_integration.s3_client import resolve_s3_config

			config = resolve_s3_config(self)
			missing = []
			if not config.get("aws_access_key_id"):
				missing.append(_("AWS Access Key ID"))
			if not config.get("aws_secret_access_key"):
				missing.append(_("AWS Secret Access Key"))
			if not config.get("region_name"):
				missing.append(_("Region Name"))
			if not config.get("bucket_name"):
				missing.append(_("Bucket Name"))

			if missing:
				frappe.throw(
					_(
						"The following S3 configuration values are required (from DocType, site_config.json, or environment): {0}"
					).format(", ".join(missing))
				)


@frappe.whitelist()
def test_s3_connection():
	frappe.only_for("System Manager")
	try:
		from erpnext_s3_integration.s3_client import S3Client

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
