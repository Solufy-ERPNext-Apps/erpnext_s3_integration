import os

import frappe


def create_dummy():
	# Create dummy local file
	file_path = frappe.get_site_path("public", "files", "dummy_local.txt")
	with open(file_path, "w") as f:
		f.write("test content")

	doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": "dummy_local.txt",
			"file_url": "/files/dummy_local.txt",
			"is_private": 0,
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()  # nosemgrep
	print("Created dummy file doc:", doc.name)
