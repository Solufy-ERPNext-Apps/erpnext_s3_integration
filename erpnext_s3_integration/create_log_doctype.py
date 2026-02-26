import frappe


def create_log_doctype():
	if not frappe.db.exists("DocType", "S3 Sync Log"):
		doc = frappe.get_doc(
			{
				"doctype": "DocType",
				"module": "ERPNext S3 Integration",
				"custom": 0,
				"name": "S3 Sync Log",
				"naming_rule": "Expression",
				"autoname": "format:S3L-{YYYY}-{MM}-{####}",
				"fields": [
					{
						"fieldname": "status",
						"fieldtype": "Select",
						"options": "Success\nFailed",
						"label": "Status",
						"in_list_view": 1,
					},
					{"fieldname": "message", "fieldtype": "Code", "label": "Message"},
				],
				"permissions": [
					{
						"role": "System Manager",
						"read": 1,
						"write": 1,
						"create": 1,
						"delete": 1,
					}
				],
			}
		)
		doc.insert(ignore_permissions=True)
		frappe.db.commit()  # nosemgrep
