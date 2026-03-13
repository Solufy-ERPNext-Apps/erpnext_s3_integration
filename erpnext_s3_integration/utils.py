import frappe


def before_request(*args, **kwargs):
	path = frappe.request.path.lstrip("/")
	if path.startswith("s3/"):
		# Rewrite the underlying WSGI environment to redirect the flow into our API endpoint
		frappe.local.request.environ["PATH_INFO"] = "/api/method/erpnext_s3_integration.api.get_file"
		frappe.form_dict.key = path[3:]

		# Werkzeug caches the `path` property natively. Frappe accesses request.path *before*
		# triggering these hooks, which caches the old /s3/ value in memory.
		# We must clear this cache to force Frappe to read the new injected PATH_INFO.
		frappe.local.request.__dict__.pop("path", None)
