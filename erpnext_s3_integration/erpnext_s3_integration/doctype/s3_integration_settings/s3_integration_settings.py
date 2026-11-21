import frappe
from frappe import _
from frappe.model.document import Document


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

		self.validate_backup_cron_expression()

	def validate_backup_cron_expression(self):
		from croniter import croniter

		if self.backup_cron_expression and not croniter.is_valid(self.backup_cron_expression):
			frappe.throw(_("Backup CRON Expression {0} is not valid.").format(self.backup_cron_expression))


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

	from erpnext_s3_integration.backup_hooks import enqueue_backup_and_sync

	enqueue_backup_and_sync(create_backup=True)
	return "Backup and Sync job enqueued successfully."
