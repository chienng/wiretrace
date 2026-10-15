"""Bounded decompression of captured bodies.

The window shows at most a few mebibytes of a body. A HAR must not expand a
compression bomb: `trim_oversized` counts the decoded size in chunks and, past
the limit, replaces the body without ever holding the decoded bytes.

brotli and zstandard are imported only when a body uses them, so `wiretrace
doctor` still runs when those packages are not installed.
"""

from __future__ import annotations

import io
import zlib

CHUNK_BYTES = 1 << 20
HAR_LIMIT = 16 << 20
PLACEHOLDER = "Wiretrace: body left out, it decodes to more than 16 MiB."

_IDENTITY = ("", "identity", "none")


def _decompressor(encoding: str):
    """A function `(raw, limit) -> output` that stops once `limit` bytes are out; None if not supported."""
    if encoding == "gzip":
        return lambda raw, limit: zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw, limit)
    if encoding == "deflate":
        def deflate(raw: bytes, limit: int) -> bytes:
            try:
                return zlib.decompressobj().decompress(raw, limit)
            except zlib.error:
                return zlib.decompressobj(-zlib.MAX_WBITS).decompress(raw, limit)
        return deflate
    if encoding == "br":
        import brotli
        return lambda raw, limit: brotli.Decompressor().process(raw, output_buffer_limit=limit)
    if encoding == "zstd":
        import zstandard
        return lambda raw, limit: zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw)).read(limit)
    return None


def _zlib_size(raw: bytes, wbits: int, limit: int) -> int:
    """Decoded size, counting at most `limit` + 1 bytes.

    `decompress` can consume every input byte and still hold output back, so an
    empty feed is tried until the stream ends or the count stops.
    """
    stop = limit + 1
    decoder = zlib.decompressobj(wbits)
    total = 0
    pending = raw
    while total < stop:
        chunk = decoder.decompress(pending, min(CHUNK_BYTES, stop - total))
        total += len(chunk)
        pending = decoder.unconsumed_tail
        if decoder.eof or (not pending and not chunk):
            break
    return total


def decoded_size(encoding: str, raw: bytes, known: int, limit: int) -> int:
    """The decoded size, counted in chunks up to `limit`, so a compression bomb is never held in memory.

    Past `limit` the returned size is a lower bound (`limit` or just above it).
    """
    if encoding in ("gzip", "deflate"):
        attempts = [16 + zlib.MAX_WBITS] if encoding == "gzip" else [zlib.MAX_WBITS, -zlib.MAX_WBITS]
        for wbits in attempts:
            try:
                return _zlib_size(raw, wbits, limit)
            except zlib.error:
                continue
        return known
    if encoding == "zstd":
        import zstandard
        reader = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw))
        total = 0
        stop = limit + 1
        while total < stop and (chunk := reader.read(min(CHUNK_BYTES, stop - total))):
            total += len(chunk)
        return total
    if encoding == "br":
        import brotli
        decoder = brotli.Decompressor()
        stop = limit + 1
        total = len(decoder.process(raw, output_buffer_limit=min(CHUNK_BYTES, stop)))
        while not decoder.is_finished() and total < stop:
            chunk = decoder.process(b"", output_buffer_limit=min(CHUNK_BYTES, stop - total))
            if not chunk:
                break
            total += len(chunk)
        return total
    return known


def bounded_content(message, max_bytes: int, count_limit: int) -> tuple[bytes, int, bool]:
    """Up to `max_bytes` of the decoded body, its size, and whether it was cut.

    A body that does not decode is returned as it travelled.
    """
    raw = message.raw_content or b""
    encoding = message.headers.get("content-encoding", "").strip().lower()
    if encoding in _IDENTITY:
        return raw[:max_bytes], len(raw), len(raw) > max_bytes
    decompress = _decompressor(encoding)
    if decompress is None:
        return raw[:max_bytes], len(raw), len(raw) > max_bytes
    try:
        data = decompress(raw, max_bytes + 1)
    except Exception:
        # As mitmproxy's get_content(strict=False): an undecodable body is shown as it travelled.
        return raw[:max_bytes], len(raw), len(raw) > max_bytes
    if len(data) <= max_bytes:
        return data, len(data), False
    # Past count_limit the size is a lower bound.
    return data[:max_bytes], decoded_size(encoding, raw, len(data), count_limit), True


def _decoded_length(encoding: str, raw: bytes, limit: int) -> int | None:
    """How many bytes `raw` decodes to, counting at most `limit` + 1. None if it does not decode."""
    if encoding in ("gzip", "deflate"):
        attempts = [16 + zlib.MAX_WBITS] if encoding == "gzip" else [zlib.MAX_WBITS, -zlib.MAX_WBITS]
        for wbits in attempts:
            try:
                return _zlib_size(raw, wbits, limit)
            except zlib.error:
                continue
        return None
    if encoding == "zstd":
        try:
            import zstandard
            reader = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw))
            total = 0
            stop = limit + 1
            while total < stop and (chunk := reader.read(min(CHUNK_BYTES, stop - total))):
                total += len(chunk)
            return total
        except Exception:
            return None
    if encoding == "br":
        try:
            import brotli
            decoder = brotli.Decompressor()
            stop = limit + 1
            total = len(decoder.process(raw, output_buffer_limit=min(CHUNK_BYTES, stop)))
            while not decoder.is_finished() and total < stop:
                chunk = decoder.process(b"", output_buffer_limit=min(CHUNK_BYTES, stop - total))
                if not chunk:
                    break
                total += len(chunk)
            return total
        except Exception:
            return None
    return None


def _replace(message) -> None:
    message.headers.pop("content-encoding", None)
    message.raw_content = PLACEHOLDER.encode()
    if "transfer-encoding" not in message.headers:
        message.headers["content-length"] = str(len(message.raw_content))


def _trim_message(message, limit: int) -> None:
    raw = message.raw_content
    if not raw:
        return
    encoding = message.headers.get("content-encoding", "").strip().lower()
    if encoding in _IDENTITY:
        if len(raw) > limit:
            _replace(message)
        return
    size = _decoded_length(encoding, raw, limit)
    # None: the body does not decode, so it stays as it travelled.
    if size is not None and size > limit:
        _replace(message)


def trim_oversized(flow, limit: int = HAR_LIMIT) -> None:
    """Replace each request or response body that decodes to more than `limit` bytes.

    The decoded bytes are counted in chunks and never kept. `Content-Encoding` is
    removed only when a body is replaced.
    """
    for message in (getattr(flow, "request", None), getattr(flow, "response", None)):
        if message is not None:
            _trim_message(message, limit)
