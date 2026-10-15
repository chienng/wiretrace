"""Oversized bodies are replaced without being held decoded."""

from __future__ import annotations

import gzip
import zlib

import brotli
import zstandard
from mitmproxy.test import tflow

from cli.bodies import HAR_LIMIT, PLACEHOLDER, trim_oversized


def _message(flow, raw: bytes, encoding: str | None):
    flow.response.headers["Content-Type"] = "text/plain"
    if encoding:
        flow.response.headers["Content-Encoding"] = encoding
    flow.response.raw_content = raw
    return flow


def _gzip(data: bytes) -> bytes:
    return gzip.compress(data)


def _deflate(data: bytes) -> bytes:
    return zlib.compress(data)


def _raw_deflate(data: bytes) -> bytes:
    packer = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    return packer.compress(data) + packer.flush()


def _br(data: bytes) -> bytes:
    return brotli.compress(data, quality=1)


def _zstd(data: bytes) -> bytes:
    return zstandard.ZstdCompressor(level=1).compress(data)


ENCODERS = {"gzip": _gzip, "deflate": _deflate, "br": _br, "zstd": _zstd}


def test_bombs_are_replaced_and_the_encoding_is_removed():
    payload = b"X" * (HAR_LIMIT + 1)
    for name, encode in ENCODERS.items():
        flow = _message(tflow.tflow(resp=True), encode(payload), name)
        trim_oversized(flow)
        assert flow.response.raw_content == PLACEHOLDER.encode(), name
        assert "content-encoding" not in flow.response.headers, name
        assert flow.response.headers["content-length"] == str(len(PLACEHOLDER))


def test_raw_deflate_bomb_is_replaced():
    flow = _message(tflow.tflow(resp=True), _raw_deflate(b"Y" * (HAR_LIMIT + 1)), "deflate")
    trim_oversized(flow)
    assert flow.response.raw_content == PLACEHOLDER.encode()
    assert "content-encoding" not in flow.response.headers


def test_an_under_limit_body_is_unchanged():
    raw = _gzip(b"hello")
    flow = _message(tflow.tflow(resp=True), raw, "gzip")
    trim_oversized(flow)
    assert flow.response.raw_content == raw
    assert flow.response.headers["content-encoding"] == "gzip"


def test_a_body_at_the_limit_is_kept():
    raw = b"Z" * HAR_LIMIT
    flow = _message(tflow.tflow(resp=True), raw, None)
    trim_oversized(flow)
    assert flow.response.raw_content == raw
    assert "content-encoding" not in flow.response.headers


def test_an_uncompressed_body_over_the_limit_is_replaced():
    flow = _message(tflow.tflow(resp=True), b"Z" * (HAR_LIMIT + 1), None)
    trim_oversized(flow)
    assert flow.response.raw_content == PLACEHOLDER.encode()


def test_a_body_that_does_not_decode_is_kept():
    flow = _message(tflow.tflow(resp=True), b"not gzip at all", "gzip")
    trim_oversized(flow)
    assert flow.response.raw_content == b"not gzip at all"
    assert flow.response.headers["content-encoding"] == "gzip"


def test_the_request_body_is_trimmed_too():
    flow = tflow.tflow(resp=True)
    flow.request.headers["Content-Encoding"] = "gzip"
    flow.request.raw_content = _gzip(b"Q" * (HAR_LIMIT + 1))
    trim_oversized(flow)
    assert flow.request.raw_content == PLACEHOLDER.encode()
    assert "content-encoding" not in flow.request.headers
    assert flow.response.raw_content is not None
