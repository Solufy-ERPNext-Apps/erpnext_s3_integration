import frappe
from werkzeug.wrappers import Response
from werkzeug.wsgi import wrap_file


@frappe.whitelist(allow_guest=True)  # nosemgrep
def get_file():
	"""Serves files from S3. Routed internally via utils.before_request"""
	s3_key = frappe.form_dict.get("key")
	if not s3_key:
		raise frappe.PageDoesNotExistError()

	settings = frappe.get_single("S3 Integration Settings")

	# Security: verify file exists in DB
	file_name = frappe.db.get_value("File", {"file_url": f"/s3/{s3_key}"}, "name")
	if not file_name:
		raise frappe.DoesNotExistError()

	file_obj = frappe.get_doc("File", file_name)

	# Guest check: reject guests on private files explicitly
	if file_obj.is_private and (not frappe.session.user or frappe.session.user == "Guest"):
		raise frappe.PermissionError()

	# Permission check: verify current user has read permission on the File document
	if not file_obj.is_downloadable():
		raise frappe.PermissionError()

	# If stream_from_s3 is enabled, stream it directly, otherwise return presigned URL redirect
	from erpnext_s3_integration.s3_client import S3Client, resolve_content_headers

	s3_client = S3Client()
	stored_content_type = file_obj.get("mime_type")
	if not isinstance(stored_content_type, str):
		stored_content_type = None
	content_type, content_disposition = resolve_content_headers(
		file_obj.file_name or s3_key, stored_content_type
	)

	if settings.stream_from_s3:
		try:
			stream = s3_client.download_as_stream(s3_key)
			response = Response(wrap_file(frappe.request.environ, stream), direct_passthrough=True)

			response.headers["Content-Type"] = content_type
			response.headers["Content-Disposition"] = content_disposition
			return response
		except Exception as e:
			frappe.log_error(f"Error streaming file from S3: {e}")
			raise frappe.DoesNotExistError()
	else:
		# Return a temporary redirect to the S3 URL
		url = s3_client.generate_presigned_url(
			s3_key,
			expires_in=3600,
			filename=file_obj.file_name or s3_key,
			content_type=content_type,
		)
		if not url:
			raise frappe.DoesNotExistError()

		frappe.local.response["type"] = "redirect"
		frappe.local.response["location"] = url
