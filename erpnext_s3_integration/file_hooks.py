import io
import mimetypes

import frappe
from unidecode import unidecode

S3_URL_PREFIX = "/s3/"


def generate_s3_key(file_doc, settings):
	"""Reuse the key of an S3 file, mirror a local file's path, or build a new unguessable key."""
	file_url = file_doc.get("file_url") or ""
	if file_url.startswith(S3_URL_PREFIX):
		return file_url.removeprefix(S3_URL_PREFIX)

	folder_prefix = settings.get("folder_prefix") or ""
	if folder_prefix and not folder_prefix.endswith("/"):
		folder_prefix += "/"

	if file_url.startswith("/"):
		return f"{folder_prefix}{file_url.lstrip('/')}"

	file_name = unidecode(file_doc.file_name).replace(" ", "_") if file_doc.file_name else "unnamed_file"
	visibility = "private" if file_doc.is_private else "public"
	return f"{folder_prefix}{visibility}/{frappe.generate_hash(length=10)}-{file_name}"


def get_content_type(file_doc):
	return file_doc.get("content_type") or mimetypes.guess_type(file_doc.file_name or "")[0]


def write_file(file_doc):
	"""`write_file` hook: store new file content on S3 instead of the local disk."""
	settings = frappe.get_single("S3 Integration Settings")
	if not settings.enable_attachments_s3:
		return file_doc.save_file_on_filesystem()

	from erpnext_s3_integration.s3_client import S3Client

	content = file_doc._content
	if isinstance(content, str):
		content = content.encode()
	file_doc._content = content
	file_doc.check_content()

	s3_key = generate_s3_key(file_doc, settings)
	with io.BytesIO(content) as content_stream:
		S3Client().upload_fileobj(
			content_stream, s3_key, get_content_type(file_doc), is_public=not file_doc.is_private
		)

	file_doc.file_url = f"{S3_URL_PREFIX}{s3_key}"
	return {"file_name": file_doc.file_name, "file_url": file_doc.file_url}


def delete_file_data_content(file_doc, only_thumbnail=False):
	"""`delete_file_data_content` hook: delete the S3 object once no File record uses it."""
	file_url = file_doc.file_url or ""
	if not file_url.startswith(S3_URL_PREFIX):
		return file_doc.delete_file_from_filesystem(only_thumbnail=only_thumbnail)

	if only_thumbnail or not frappe.get_single("S3 Integration Settings").delete_from_s3_on_file_delete:
		return

	if frappe.db.exists("File", {"file_url": file_url, "name": ("!=", file_doc.name)}):
		return

	from erpnext_s3_integration.s3_client import S3Client

	s3_key = file_url.removeprefix(S3_URL_PREFIX)
	# A rolled-back insert has no commit to wait for.
	if file_doc.flags.new_file:
		S3Client().delete_object(s3_key)
	else:
		frappe.db.after_commit.add(lambda: S3Client().delete_object(s3_key))
