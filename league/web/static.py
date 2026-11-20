"""Static files for the web process, through WhiteNoise.

WhiteNoise hands Django an open file to read in a loop. Django under ASGI can't do that without
blocking the event loop, so for every static file it warns ("StreamingHttpResponse must consume
synchronous iterators...") and reads the whole file in a thread before sending any of it. Under
ASGI this middleware streams the same file a block at a time instead, each read in a thread.
WhiteNoise itself (6.12) has no async path.

The player web UI's build (`WEB_DIST`, served under /static/web/) names every file under assets/
by its content already, so those are cached for good, beside the files collectstatic hashes.

It also finds files in DEBUG on Windows, where Django's finder misses them in a prefixed static
directory (the web UI's build is under "web").
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from typing import IO, Any

from django.contrib.staticfiles import finders
from django.core.handlers.asgi import ASGIRequest
from django.http import HttpRequest
from whitenoise.middleware import WhiteNoiseFileResponse, WhiteNoiseMiddleware

BLOCK_SIZE = 64 * 1024
# Under the static URL: Vite's hashed output (its `build.assetsDir`).
WEB_ASSETS = "web/assets/"


async def _read_blocks(file: IO[bytes]) -> AsyncIterator[bytes]:
    # The response closes the file when it's done (FileResponse registered its close).
    while block := await asyncio.to_thread(file.read, BLOCK_SIZE):
        yield block


class AsgiWhiteNoiseMiddleware(WhiteNoiseMiddleware):
    @staticmethod
    def serve(static_file: Any, request: HttpRequest) -> WhiteNoiseFileResponse:
        response: WhiteNoiseFileResponse = WhiteNoiseMiddleware.serve(static_file, request)
        file = response.file_to_stream
        if isinstance(request, ASGIRequest) and file is not None:
            response.streaming_content = _read_blocks(file)
        return response

    def immutable_file_test(self, path: str, url: str) -> bool:
        """Cache for good what collectstatic hashed, and the web UI's own hashed assets."""
        if url.startswith(f"{self.static_prefix}{WEB_ASSETS}"):
            return True
        return bool(super().immutable_file_test(path, url))

    def candidate_paths_for_url(self, url: str) -> Iterator[str]:
        yield from super().candidate_paths_for_url(url)
        # DEBUG reads straight from the finders. For a prefixed directory Django's finder checks
        # the path starts with "web" + os.sep, so on Windows the URL's forward slashes never
        # match it: ask again with the platform's separator.
        if os.sep != "/" and self.use_finders and url.startswith(self.static_prefix):
            path = finders.find(url[len(self.static_prefix) :].replace("/", os.sep))
            if isinstance(path, str):
                yield path
