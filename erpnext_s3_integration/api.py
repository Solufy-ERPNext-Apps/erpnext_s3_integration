import mimetypes

import frappe
from frappe.website.page_renderers.base_renderer import BaseRenderer
from werkzeug.utils import redirect
from werkzeug.wrappers import Response
from werkzeug.wsgi import wrap_file


class S3FileRenderer(BaseRenderer):
	"""Serve `/s3/<key>` paths; the key stays in the path so `&`, `?` and `%` survive."""

	def can_render(self):
		return self.path.startswith("s3/")

	def render(self):
		# Path resolution strips a trailing ".html", so read the key from the raw request path.
		request = getattr(frappe.local, "request", None)
		path = request.path.strip("/") if request else self.path
		return get_file_response(path.removeprefix("s3/"))


@frappe.whitelist(allow_guest=True)  # nosemgrep
def get_file():
	"""Serve an S3 file by `key`; kept for links created before `/s3/` paths were rendered directly."""
	return get_file_response(frappe.form_dict.get("key"))


def get_file_response(s3_key):
	"""Return the S3 file as a stream or a presigned-URL redirect after checking File read permission."""
	if not s3_key:
		raise frappe.PageDoesNotExistError()

	file_names = frappe.get_all("File", filters={"file_url": f"/s3/{s3_key}"}, pluck="name")
	if not file_names:
		raise frappe.DoesNotExistError()

	for file_name in file_names:
		file_doc = frappe.get_doc("File", file_name)
		if file_doc.is_downloadable():
			break
	else:
		raise frappe.PermissionError()

	from erpnext_s3_integration.s3_client import S3Client

	s3_client = S3Client()
	if frappe.get_single("S3 Integration Settings").stream_from_s3:
		stream = s3_client.download_as_stream(s3_key)
		response = Response(wrap_file(frappe.request.environ, stream), direct_passthrough=True)
		response.headers["Content-Type"] = (
			mimetypes.guess_type(file_doc.file_name or "")[0] or "application/octet-stream"
		)
		return response

	url = s3_client.generate_presigned_url(s3_key, expires_in=3600)
	if not url:
		raise frappe.DoesNotExistError()
	return redirect(url, code=302)
