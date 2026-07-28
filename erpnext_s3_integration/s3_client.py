import os

import frappe
from frappe import _
from frappe.utils.password import get_decrypted_password


def _load_boto3():
	"""Import boto3 lazily so Desk boot is not blocked by optional S3 dependencies."""
	try:
		import boto3
		from botocore.exceptions import ClientError
	except Exception:
		frappe.throw(
			_(
				"S3 dependencies could not be loaded. Please verify the boto3/OpenSSL environment before using S3 features."
			),
			exc=frappe.ValidationError,
		)

	return boto3, ClientError


class S3Client:
	def __init__(self):
		self.settings = frappe.get_single("S3 Integration Settings")
		self._client = None
		self.setup_client()

	@property
	def client(self):
		"""Expose the underlying boto3 client for internal callers like backup cleanup."""
		return self._client

	def get_password(self, fieldname):
		# frappe.get_single doesn't decrypt passwords automatically by default in all contexts
		if not self.settings.get(fieldname):
			return None
		try:
			return get_decrypted_password("S3 Integration Settings", "S3 Integration Settings", fieldname)
		except frappe.exceptions.SecretNotFoundError:
			return self.settings.get(fieldname)
		except Exception:
			return self.settings.get(fieldname)

	def setup_client(self):
		boto3, _ = _load_boto3()
		aws_access_key_id = (
			self.settings.aws_access_key_id
			or frappe.conf.get("s3_access_key_id")
			or os.getenv("AWS_ACCESS_KEY_ID")
		)
		aws_secret_access_key = (
			self.get_password("aws_secret_access_key")
			or frappe.conf.get("s3_secret_access_key")
			or os.getenv("AWS_SECRET_ACCESS_KEY")
		)
		region_name = (
			self.settings.region_name
			or frappe.conf.get("s3_region")
			or os.getenv("AWS_DEFAULT_REGION")
			or os.getenv("AWS_REGION")
		)
		endpoint_url = (
			self.settings.endpoint_url
			or frappe.conf.get("s3_endpoint_url")
			or os.getenv("AWS_ENDPOINT_URL")
		)

		if not (aws_access_key_id and aws_secret_access_key):
			frappe.throw(_("AWS Credentials are required to initialize the S3 client."))

		self.bucket_name = (
			self.settings.bucket_name
			or frappe.conf.get("s3_bucket")
			or os.getenv("AWS_S3_BUCKET")
		)
		if not self.bucket_name:
			frappe.throw(_("AWS Bucket Name is required."))

		use_path_style = (
			bool(self.settings.use_path_style)
			if self.settings.get("use_path_style") is not None
			else bool(frappe.conf.get("s3_use_path_style") or (os.getenv("AWS_S3_USE_PATH_STYLE") == "1"))
		)

		config = boto3.session.Config(signature_version="s3v4")
		if use_path_style:
			config = boto3.session.Config(signature_version="s3v4", s3={"addressing_style": "path"})

		client_kwargs = {
			"service_name": "s3",
			"aws_access_key_id": aws_access_key_id,
			"aws_secret_access_key": aws_secret_access_key,
			"config": config,
		}

		if region_name:
			client_kwargs["region_name"] = region_name
		if endpoint_url:
			client_kwargs["endpoint_url"] = endpoint_url

		self._client = boto3.client(**client_kwargs)

	def test_connection(self):
		_, client_error = _load_boto3()
		try:
			# Trying to list a bounded number of objects is a good way to verify bucket access
			self._client.list_objects_v2(Bucket=self.bucket_name, MaxKeys=1)
			return True, "Connection successful! Bucket is accessible."
		except client_error as e:
			frappe.log_error(message=frappe.get_traceback(), title="S3 Test Connection Error")
			return False, f"Connection Failed: {e}"
		except Exception as e:
			frappe.log_error(message=frappe.get_traceback(), title="S3 Test Connection Failed")
			return False, f"Connection Failed: {e!s}"

	def upload_fileobj(self, fileobj, key, content_type=None, is_public=False):
		_, client_error = _load_boto3()
		extra_args = {}
		if content_type:
			extra_args["ContentType"] = content_type
		# AWS S3 ACLs are being deprecated, but some MinIO instances might use them.
		if is_public:
			extra_args["ACL"] = "public-read"

		try:
			self._client.upload_fileobj(fileobj, self.bucket_name, key, ExtraArgs=extra_args)
			return True
		except client_error as e:
			error_code = (e.response or {}).get("Error", {}).get("Code")
			# Buckets with Object Ownership "Bucket owner enforced" reject ACLs.
			# Retry once without ACL so uploads still succeed.
			if error_code == "AccessControlListNotSupported" and "ACL" in extra_args:
				try:
					fileobj.seek(0)
				except Exception:
					pass
				extra_args.pop("ACL", None)
				self._client.upload_fileobj(fileobj, self.bucket_name, key, ExtraArgs=extra_args)
				return True
			frappe.log_error(message=frappe.get_traceback(), title=f"S3 Upload Failed for {key}")
			raise frappe.ValidationError(f"Could not upload file to S3: {e}")
		except Exception as e:
			frappe.log_error(message=frappe.get_traceback(), title=f"S3 Upload Failed for {key}")
			raise frappe.ValidationError(f"Could not upload file to S3: {e}")

	def delete_object(self, key):
		try:
			self._client.delete_object(Bucket=self.bucket_name, Key=key)
			return True
		except Exception:
			frappe.log_error(message=frappe.get_traceback(), title=f"S3 Delete Failed for {key}")
			# We don't raise here, so file deletion won't be blocked if S3 fails
			return False

	def generate_presigned_url(self, key, expires_in=3600):
		try:
			url = self._client.generate_presigned_url(
				"get_object",
				Params={"Bucket": self.bucket_name, "Key": key},
				ExpiresIn=expires_in,
			)
			return url
		except Exception:
			frappe.log_error(
				message=frappe.get_traceback(),
				title=f"S3 URL Generation Failed for {key}",
			)
			return None

	def download_as_stream(self, key):
		try:
			response = self._client.get_object(Bucket=self.bucket_name, Key=key)
			return response["Body"]
		except Exception:
			frappe.log_error(message=frappe.get_traceback(), title=f"S3 Downoad Failed for {key}")
			frappe.throw(f"File {key} not found on S3 or could not be streamed.")
