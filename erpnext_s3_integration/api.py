import frappe
from frappe import _
from werkzeug.wrappers import Response
from werkzeug.wsgi import wrap_file


@frappe.whitelist(allow_guest=True)  # nosemgrep
def get_file():
	"""Serves files from S3. Routed internally via utils.before_request"""
	s3_key = frappe.form_dict.get("key")
	if not s3_key:
		raise frappe.PageDoesNotExistError()

	settings = frappe.get_single("S3 Integration Settings")
	if not settings.enable_attachments_s3:
		frappe.throw(_("S3 Attachments are disabled"), frappe.PermissionError)

	# Security: verify they have access to the File DOC
	file_doc = frappe.db.get_value(
		"File", {"file_url": f"/s3/{s3_key}"}, ["name", "is_private"], as_dict=True
	)

	if not file_doc:
		raise frappe.DoesNotExistError()

	if file_doc.is_private and not frappe.session.user:
		raise frappe.PermissionError()

	# If stream_from_s3 is enabled, stream it directly, otherwise return presigned URL redirect
	from erpnext_s3_integration.s3_client import S3Client

	s3_client = S3Client()

	if settings.stream_from_s3:
		try:
			stream = s3_client.download_as_stream(s3_key)
			response = Response(wrap_file(frappe.request.environ, stream), direct_passthrough=True)
			# You could get content-type from S3 response if you pass it back from download_as_stream
			# or from the File doc
			mime_type = frappe.db.get_value("File", file_doc.name, "mime_type")
			if mime_type:
				response.headers["Content-Type"] = mime_type

			return response
		except Exception as e:
			frappe.log_error(f"Error streaming file from S3: {e}")
			raise frappe.DoesNotExistError()
	else:
		# Return a temporary redirect to the S3 URL
		url = s3_client.generate_presigned_url(s3_key, expires_in=3600)
		if not url:
			raise frappe.DoesNotExistError()

		frappe.local.response["type"] = "redirect"
		frappe.local.response["location"] = url
