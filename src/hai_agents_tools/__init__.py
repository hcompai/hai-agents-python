"""Prebuilt custom tools for the hai-agents SDK.

The generic plumbing (:class:`hai_agents.Tool`, :func:`hai_agents.tool`,
:func:`hai_agents.as_tools`) ships with the generated ``hai_agents`` package. This
package holds the prebuilt tools built on top of it, one module per
tool (``otp``, ...), re-exported here.
"""

from .otp import (
    OTP_TOOL_DESCRIPTION,
    OTP_TOOL_INPUT_SCHEMA,
    OTP_TOOL_NAME,
    OtpHandler,
    OtpRequest,
    extract_otp,
    imap_otp_handler,
    otp_tool,
)

__all__ = [
    "OTP_TOOL_DESCRIPTION",
    "OTP_TOOL_INPUT_SCHEMA",
    "OTP_TOOL_NAME",
    "OtpHandler",
    "OtpRequest",
    "extract_otp",
    "imap_otp_handler",
    "otp_tool",
]
