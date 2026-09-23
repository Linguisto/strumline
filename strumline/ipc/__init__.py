"""IPC framing contract — versioned binary protocol over Unix-domain sockets."""

from strumline.ipc.codec import (
    IPC_MAX_FRAME_BYTES,
    PROTOCOL_VERSION,
    EmptyFrameError,
    FrameTooLargeError,
    IPCError,
    MalformedEnvelopeError,
    TruncatedFrameError,
    UnknownVersionError,
    decode_envelope_body,
    encode_frame,
    read_frame,
)

__all__ = [
    "IPC_MAX_FRAME_BYTES",
    "PROTOCOL_VERSION",
    "EmptyFrameError",
    "FrameTooLargeError",
    "IPCError",
    "MalformedEnvelopeError",
    "TruncatedFrameError",
    "UnknownVersionError",
    "decode_envelope_body",
    "encode_frame",
    "read_frame",
]
