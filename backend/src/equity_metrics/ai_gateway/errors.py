"""Gateway failure modes, separated by whether a retry can help."""


class GatewayError(Exception):
    """Base class for failures the gateway raises to its caller."""

    code = "gateway_error"


class ProviderConfigurationError(GatewayError):
    """The configured provider cannot be built, e.g. a missing credential."""

    code = "provider_not_configured"


class TransientProviderError(GatewayError):
    """A provider failure that a bounded retry may resolve."""

    code = "provider_unavailable"


class ProviderFailureError(GatewayError):
    """A provider failure no retry will fix, such as a rejected request."""

    code = "provider_failed"


class GatewayTimeoutError(GatewayError):
    """The provider call or the whole answer exceeded its time budget."""

    code = "timeout"


class ToolIterationLimitError(GatewayError):
    """The tool loop hit its fixed iteration ceiling without an answer."""

    code = "tool_loop_exhausted"
