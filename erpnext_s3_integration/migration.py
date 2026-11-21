import os

import frappe
from frappe import _

from erpnext_s3_integration.backup_hooks import log_s3_sync
from erpnext_s3_integration.file_hooks import S3_URL_PREFIX, generate_s3_key, get_content_type

ATTACH_FIELDTYPES = ("Attach", "Attach Image")


@frappe.whitelist()
def start_migration():
	frappe.only_for("System Manager")

	settings = frappe.get_single("S3 Integration Settings")
	if not settings.enable_attachments_s3:
		frappe.throw(_("S3 Attachments must be enabled to start migration."))

	frappe.enqueue("erpnext_s3_integration.migration.run_migration", queue="long", timeout=3600)
	return _("Migration started in background. The summary will be added to S3 Sync Log.")


def get_local_file_urls():
	return frappe.get_all(
		"File",
		filters={"is_folder": 0},
		or_filters=[["file_url", "like", "/files/%"], ["file_url", "like", "/private/files/%"]],
		pluck="file_url",
		distinct=True,
		order_by="file_url",
	)


def run_migration():
	"""Upload every local file to S3 once and point all records that use it at the S3 URL."""
	from erpnext_s3_integration.s3_client import S3Client

	settings = frappe.get_single("S3 Integration Settings")
	s3_client = S3Client()
	file_urls = get_local_file_urls()
	failed_urls = []

	for index, file_url in enumerate(file_urls, start=1):
		try:
			migrate_file_url(s3_client, settings, file_url)
			frappe.db.commit()  # nosemgrep
		except Exception:
			frappe.db.rollback()
			frappe.log_error(message=frappe.get_traceback(), title=f"S3 Migration Error for {file_url}")
			failed_urls.append(file_url)

		frappe.publish_progress(
			index * 100 / len(file_urls),
			title="Migrating files to S3",
			description=f"Processed {index}/{len(file_urls)}",
		)

	log_s3_sync(
		"Failed" if failed_urls else "Success",
		f"File migration finished. Migrated: {len(file_urls) - len(failed_urls)}, Failed: {len(failed_urls)}"
		+ "".join(f"\n{file_url}" for file_url in failed_urls),
	)


def migrate_file_url(s3_client, settings, file_url):
	files = frappe.get_all(
		"File",
		filters={"file_url": file_url},
		fields=["name", "attached_to_doctype", "attached_to_name", "attached_to_field"],
	)
	file_doc = frappe.get_doc("File", files[0].name)
	local_path = file_doc.get_full_path()
	if not os.path.exists(local_path):
		raise FileNotFoundError(f"File is missing locally: {local_path}")

	s3_key = generate_s3_key(file_doc, settings)
	with open(local_path, "rb") as fileobj:  # nosemgrep
		s3_client.upload_fileobj(fileobj, s3_key, get_content_type(file_doc), not file_doc.is_private)

	s3_url = f"{S3_URL_PREFIX}{s3_key}"
	frappe.db.set_value("File", {"file_url": file_url}, "file_url", s3_url, update_modified=False)
	for file in files:
		update_attach_fields(file, file_url, s3_url)


def update_attach_fields(file, old_url, new_url):
	"""Point the attached document's Attach fields that hold `old_url` at `new_url`."""
	doctype, name = file.attached_to_doctype, file.attached_to_name
	if not (doctype and name and frappe.db.exists("DocType", doctype)):
		return

	meta = frappe.get_meta(doctype)
	if file.attached_to_field:
		fieldnames = [file.attached_to_field] if meta.has_field(file.attached_to_field) else []
	else:
		fieldnames = [field.fieldname for field in meta.fields if field.fieldtype in ATTACH_FIELDTYPES]

	for fieldname in fieldnames:
		if not meta.issingle:
			frappe.db.set_value(
				doctype, {"name": name, fieldname: old_url}, fieldname, new_url, update_modified=False
			)
		elif frappe.db.get_single_value(doctype, fieldname) == old_url:
			frappe.db.set_single_value(doctype, fieldname, new_url, update_modified=False)
