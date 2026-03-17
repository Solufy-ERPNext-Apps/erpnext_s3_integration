import frappe


def test_set_value():
	try:
		frappe.db.set_value("File", "Home", {"_s3_uploaded_key": "test_key"})
		print("Set value succeeded!")
	except Exception as e:
		print(f"Exception type: {type(e).__name__}")
		print(f"Set value failed: {e}")


if __name__ == "__main__":
	test_set_value()
