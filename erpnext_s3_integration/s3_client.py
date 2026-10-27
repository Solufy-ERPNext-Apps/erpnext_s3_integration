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
		aws_access_key_id = self.settings.aws_access_key_id
		aws_secret_access_key = self.get_password("aws_secret_access_key")
		region_name = self.settings.region_name
		endpoint_url = self.settings.endpoint_url

		if not (aws_access_key_id and aws_secret_access_key):
			frappe.throw(_("AWS Credentials are required to initialize the S3 client."))

		self.bucket_name = self.settings.bucket_name
		if not self.bucket_name:
			frappe.throw(_("AWS Bucket Name is required."))

		config = boto3.session.Config(signature_version="s3v4")
		if self.settings.use_path_style:
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
		_, ClientError = _load_boto3()
		try:
			# Trying to list a bounded number of objects is a good way to verify bucket access
			self._client.list_objects_v2(Bucket=self.bucket_name, MaxKeys=1)
			return True, "Connection successful! Bucket is accessible."
		except ClientError as e:
			frappe.log_error(message=frappe.get_traceback(), title="S3 Test Connection Error")
			return False, f"Connection Failed: {e}"
		except Exception as e:
			frappe.log_error(message=frappe.get_traceback(), title="S3 Test Connection Failed")
			return False, f"Connection Failed: {e!s}"

	def upload_fileobj(self, fileobj, key, content_type=None, is_public=False):
		_, ClientError = _load_boto3()
		extra_args = {}
		if content_type:
			extra_args["ContentType"] = content_type
		# AWS S3 ACLs are being deprecated, but some MinIO instances might use them.
		if is_public:
			extra_args["ACL"] = "public-read"

		try:
			position = fileobj.tell()
		except (AttributeError, OSError):
			position = None

		# The SDK closes upload bodies; the caller owns the original stream.
		stream = _UploadStream(fileobj)
		try:
			try:
				self._client.upload_fileobj(stream, self.bucket_name, key, ExtraArgs=extra_args)
			except ClientError as error:
				error_code = (error.response or {}).get("Error", {}).get("Code")
				if error_code != "AccessControlListNotSupported" or "ACL" not in extra_args:
					raise
				if position is None:
					raise ValueError("Cannot retry the S3 upload because its source stream cannot be rewound.")
				fileobj.seek(position)
				extra_args.pop("ACL")
				self._client.upload_fileobj(stream, self.bucket_name, key, ExtraArgs=extra_args)
			return True
		except Exception as error:
			frappe.log_error(message=frappe.get_traceback(), title=f"S3 Upload Failed for {key}")
			raise frappe.ValidationError(f"Could not upload file to S3: {error}") from error

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


class _UploadStream:
	"""Let managed transfers close their wrapper without closing the caller's file."""

	def __init__(self, source):
		self.source = source

	def __getattr__(self, name):
		return getattr(self.source, name)

	def close(self):
		pass
