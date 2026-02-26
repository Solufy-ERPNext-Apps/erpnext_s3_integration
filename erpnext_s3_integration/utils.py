import frappe


def before_request(*args, **kwargs):
    path = frappe.request.path.lstrip("/")
    if path.startswith("s3/"):
        from erpnext_s3_integration.api import get_file

        return get_file()
