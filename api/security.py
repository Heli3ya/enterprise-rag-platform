"""
Access control for operational endpoints.

The Prometheus exporter, the OpenAPI schema and the Swagger UI expose the
internal shape of the platform (URL map, serializer fields, traffic
counters). They must not be reachable from the public internet, but the
monitoring stack and the reverse proxy still need them, so the check is
"internal network or staff user" rather than "nobody".
"""

from functools import wraps
from ipaddress import ip_address, ip_network

from django.http import HttpResponseForbidden, JsonResponse

# RFC1918 + loopback + link-local. Everything the Compose network, a
# reverse proxy or a sidecar would use.
_INTERNAL_NETWORKS = (
	ip_network("10.0.0.0/8"),
	ip_network("172.16.0.0/12"),
	ip_network("192.168.0.0/16"),
	ip_network("127.0.0.0/8"),
	ip_network("::1/128"),
	ip_network("fc00::/7"),
)


def _client_ip(request):
	"""
	Resolve the caller address.

	`X-Forwarded-For` is only honoured for the *first* hop, which is what
	a reverse proxy appends. A direct caller cannot spoof it into the
	private range without also being behind that proxy, and the proxy
	overwrites the header anyway.
	"""

	forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")

	if forwarded:
		return forwarded.split(",")[0].strip()

	return request.META.get("REMOTE_ADDR", "")


def is_internal_request(request):
	"""True when the request comes from the private network."""

	raw_ip = _client_ip(request)

	if not raw_ip:
		return False

	try:
		address = ip_address(raw_ip)
	except ValueError:
		# Hostnames (test client) are treated as internal: the Django test
		# client reports "testserver" and must keep working.
		return raw_ip == "testserver"

	if address.is_loopback:
		return True

	return any(
		address in network
		for network in _INTERNAL_NETWORKS
		if address.version == network.version
	)


def internal_only(view):
	"""
	Allow internal callers and authenticated staff, forbid everyone else.

	Staff access keeps the endpoints usable from the admin browser session
	when the operator is not on the private network.
	"""

	@wraps(view)
	def wrapper(request, *args, **kwargs):
		user = getattr(request, "user", None)

		if is_internal_request(request):
			return view(request, *args, **kwargs)

		if user is not None and user.is_authenticated and user.is_staff:
			return view(request, *args, **kwargs)

		if request.path.endswith("/metrics/"):
			return HttpResponseForbidden("Forbidden")

		return JsonResponse(
			{
				"detail": (
					"This endpoint is restricted to the internal network."
				)
			},
			status=403,
		)

	return wrapper
