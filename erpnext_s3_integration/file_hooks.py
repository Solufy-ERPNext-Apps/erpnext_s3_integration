import io
import os

import frappe
from frappe.utils import get_files_path
from unidecode import unidecode


def generate_s3_key(file_doc, settings):
	"""Generates a deterministic S3 key mirroring native Frappe paths."""
	folder_prefix = settings.get("folder_prefix") or ""
	if folder_prefix and not folder_prefix.endswith("/"):
		folder_prefix += "/"

	# If this is an existing file being migrated, its file_url will simply be a local path like /files/x.png
	file_url = getattr(file_doc, "file_url", None)
	if file_url and file_url.startswith("/") and not file_url.startswith("/s3/"):
		base_path = file_url.lstrip("/")
	else:
		# Construct native-style path for brand new files
		filename = unidecode(file_doc.file_name).replace(" ", "_") if file_doc.file_name else "unnamed_file"
		identifier = (
			f"{file_doc.content_hash}-{filename}" if getattr(file_doc, "content_hash", None) else filename
		)

		if file_doc.is_private:
			base_path = f"private/{identifier}"
		else:
			base_path = f"public/{identifier}"

	return f"{folder_prefix}{base_path}"


def before_insert(file_doc, method):
	"""Intercept file insertion to upload to S3."""
	print(f"Hook fired for: {file_doc.file_name}")
	settings = frappe.get_single("S3 Integration Settings")
	if not settings.enable_attachments_s3:
		print("S3 disabled")
		return

	# Only intercept if it's a new upload with content
	if (
		hasattr(file_doc, "is_file_path") and file_doc.is_file_path() and not frappe.flags.in_test
	) or getattr(file_doc, "is_folder", False):
		print("Is file path or is folder")
		return

	# If no content was provided during insert but they uploaded a file, Frappe triggers `save_file`
	# Which writes to disk. We need to handle this by checking if the content exists.
	content = file_doc.get_content()
	if not content and not frappe.flags.in_test:
		print("No content")
		return

	print("Proceeding to upload")
	from erpnext_s3_integration.s3_client import S3Client

	try:
		s3_client = S3Client()

		# Generate the predictable S3 key
		s3_key = generate_s3_key(file_doc, settings)

		# Upload the file
		is_public = not file_doc.is_private
		content_stream = io.BytesIO(content) if isinstance(content, bytes) else io.BytesIO(content.encode())
		s3_client.upload_fileobj(content_stream, s3_key, file_doc.get("mime_type"), is_public)

		# We must configure Frappe to not look for this locally.
		# Setting file_url to point to S3 route or a specific custom URL scheme.
		# Using a custom scheme so Frappe doesn't try to validate the local path
		file_doc.file_url = f"/s3/{s3_key}"

		# Store the S3 Key in custom field or just rely on file_url
		# Here we add a dynamic attribute to pass it to after_insert/on_update if needed
		file_doc._s3_uploaded_key = s3_key

		# Clean up content from memory so Frappe doesn't save it locally (in some routes)
		# File storage logic in Frappe looks at file_doc.content.
		file_doc.content = None

	except Exception as e:
		frappe.throw(f"Error uploading file to S3: {e}")


def on_trash(file_doc, method):
	"""Handle deletion from S3."""
	settings = frappe.get_single("S3 Integration Settings")
	if not settings.enable_attachments_s3 or not settings.delete_from_s3_on_file_delete:
		return

	if not file_doc.file_url or not file_doc.file_url.startswith("/s3/"):
		return

	s3_key = file_doc.file_url.replace("/s3/", "", 1)

	from erpnext_s3_integration.s3_client import S3Client

	s3_client = S3Client()
	s3_client.delete_object(s3_key)
