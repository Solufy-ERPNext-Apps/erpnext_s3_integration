import os

import frappe
from frappe import _
from frappe.utils import cint

from erpnext_s3_integration.file_hooks import generate_s3_key
from erpnext_s3_integration.s3_client import S3Client


@frappe.whitelist()
def start_migration(only_unmigrated: bool = True):
	frappe.only_for("System Manager")

	settings = frappe.get_single("S3 Integration Settings")
	if not settings.enable_attachments_s3:
		frappe.throw(_("S3 Attachments must be enabled to start migration."))

	# Enqueue the background job
	frappe.enqueue(
		"erpnext_s3_integration.migration.run_migration",
		queue="long",
		timeout=3600,
		only_unmigrated=only_unmigrated,
	)

	return "Migration started in background. You will receive an Email/System Notification upon completion."


def run_migration(only_unmigrated):
	only_unmigrated = bool(cint(only_unmigrated))
	settings = frappe.get_single("S3 Integration Settings")
	s3_client = S3Client()

	files = frappe.get_all(
		"File",
		filters={"is_folder": 0},
		fields=[
			"name",
			"file_url",
			"is_private",
			"content_hash",
			"file_name",
			"attached_to_doctype",
			"creation",
		],
	)

	success_count = 0
	failed_count = 0
	skipped_count = 0
	total_files = len(files)

	if not total_files:
		message = "Migration completed.\nSuccessfully Migrated: 0\nSkipped: 0\nFailed: 0"
		print(message)
		frappe.log_error(message, "S3 Migration Summary")
		return

	for i, f in enumerate(files):
		try:
			# Skip external links and already S3-backed rows.
			# Existing migration operates on locally stored files only.
			if f.file_url and f.file_url.startswith("/s3/"):
				skipped_count += 1
				continue
			if f.file_url and (f.file_url.startswith("http://") or f.file_url.startswith("https://")):
				skipped_count += 1
				continue

			# Needs migration
			doc = frappe.get_doc("File", f.name)

			# Ensure local file exists
			local_path = doc.get_full_path()
			if not os.path.exists(local_path):
				# File is missing locally
				frappe.log_error(f"Migration: File missing locally for {doc.name}: {local_path}")
				failed_count += 1
				continue

			# Generate S3 key
			s3_key = generate_s3_key(doc, settings)

			# Upload to S3
			is_public = not doc.is_private
			with open(local_path, "rb") as fileobj:  # nosemgrep
				s3_client.upload_fileobj(fileobj, s3_key, doc.get("mime_type"), is_public)

			# Update URL and metadata
			frappe.db.set_value(
				"File",
				doc.name,
				{
					"file_url": f"/s3/{s3_key}",
				},
				update_modified=False,
			)

			# Optionally remove local file here if desired, but safest to leave for manual cleanup
			# os.remove(local_path)

			success_count += 1
			print(f"Migrated {f.file_name}")
		except Exception as e:
			print(f"Error migrating {f.file_name}: {e}")
			frappe.log_error(
				message=frappe.get_traceback(),
				title=f"Migration Error for File {f.name}",
			)
			failed_count += 1

		frappe.publish_progress(
			(i + 1) * 100 / total_files,
			title="Migrating files to S3",
			description=f"Processed {i + 1}/{total_files}",
		)

	# Final summary
	message = f"Migration completed.<br>Successfully Migrated: {success_count}<br>Skipped: {skipped_count}<br>Failed: {failed_count}"
	print(message.replace("<br>", "\n"))
	frappe.log_error(message, "S3 Migration Summary")
