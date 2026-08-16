"""Async wrapper around the `paperclip` CLI.

Paperclip ships a real command-line client, so that is the integration surface —
there is no guessed HTTP endpoint anywhere in this module. Everything here shells
out to the binary the operator installed and parses its documented output:

* `paperclip search -s <source> -n <k> "<query>"` prints a result id like
  `[s_33c33ac5]`.
* `paperclip results <id> --save <path>` writes a CSV with a stable header:
  `title,authors,id,source,date,url,abstract`.
* `paperclip cat /proteins/<accession>/meta.json` returns UniProt metadata.

Three things this wrapper exists to handle, all of them observed against the
real CLI rather than imagined:

1. **Some calls hang.** A `proteins` semantic search and `head` on a protein's
   `content.lines` both ran past 120s in testing. Every invocation therefore has
   a hard timeout and the process is killed on expiry.
2. **Partial failure is normal.** One source timing out must not lose the other
   three, so callers get per-source results and per-source errors.
3. **Repeated identical queries.** A disk cache keyed by the argument vector
   keeps a demo fast and reproducible, and records `cache_hit` in provenance so
   a reader can tell a fresh call from a replayed one.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import CACHE_DIR

#: `Found 20 papers  [s_33c33ac5]`. Observed ids are hex, but the pattern stays
#: permissive so a change in their alphabet degrades into a normal result rather
#: than a spurious "no result id" error.
RESULT_ID = re.compile(r"\[([sm]_[0-9a-z]+)\]", re.IGNORECASE)

#: The documented CSV columns from `paperclip results --save`.
EXPECTED_COLUMNS = {"title", "authors", "id", "source", "date", "url", "abstract"}


class PaperclipError(RuntimeError):
    """A paperclip invocation failed, timed out, or returned nothing usable."""


@dataclass
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


@dataclass
class SearchHit:
    title: str
    authors: str
    doc_id: str
    source: str
    date: str
    url: str
    abstract: str
    rank: int
    query: str
    paperclip_source: str

    def citation_url(self) -> str:
        """Paperclip's canonical citation URL for this document.

        Documented format: https://paperclip.gxl.ai/citations/{papers|fda|trials}/<doc_id>
        """
        family = "papers"
        if self.doc_id.startswith("fda_"):
            family = "fda"
        elif self.doc_id.startswith("tri_") or self.doc_id.startswith("NCT"):
            family = "trials"
        return f"https://paperclip.gxl.ai/citations/{family}/{self.doc_id}"

    def best_url(self) -> str:
        return self.url or self.citation_url()


@dataclass
class SourceOutcome:
    """What happened for one source. Either hits, or an error — never both silently."""

    source: str
    query: str
    hits: list[SearchHit] = field(default_factory=list)
    error: str | None = None
    cache_hit: bool = False
    duration_ms: int = 0


@dataclass
class Probe:
    """Cached capability check so `status()` never shells out on the hot path."""

    available: bool
    version: str | None
    account: str | None
    server: str | None
    reachable: bool
    detail: str
    checked_at: float


class PaperclipCLI:
    def __init__(
        self,
        binary: str | None = None,
        *,
        timeout_s: float = 90.0,
        cache_ttl_s: int = 86400,
        api_key: str = "",
        cache_dir: Path | None = None,
    ) -> None:
        self._explicit_binary = binary or ""
        self.timeout_s = timeout_s
        self.cache_ttl_s = cache_ttl_s
        self.api_key = api_key
        self.cache_dir = cache_dir or (CACHE_DIR / "paperclip")
        self._probe: Probe | None = None
        self._probe_lock = asyncio.Lock()

    # -- discovery --------------------------------------------------------

    def resolve_binary(self) -> str | None:
        if self._explicit_binary:
            return self._explicit_binary if Path(self._explicit_binary).exists() else None
        found = shutil.which("paperclip")
        if found:
            return found
        # The installer puts it here and this is not always on a service's PATH.
        fallback = Path.home() / ".local" / "bin" / "paperclip"
        return str(fallback) if fallback.exists() else None

    @property
    def installed(self) -> bool:
        return self.resolve_binary() is not None

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.api_key:
            env["PAPERCLIP_API_KEY"] = self.api_key
        # Keep the CLI non-interactive; it otherwise offers a browser sign-in.
        env.setdefault("NO_COLOR", "1")
        env.setdefault("TERM", "dumb")
        return env

    # -- process ----------------------------------------------------------

    async def run(self, args: list[str], *, timeout_s: float | None = None) -> CommandResult:
        binary = self.resolve_binary()
        if binary is None:
            raise PaperclipError("paperclip CLI is not installed or not on PATH")

        limit = timeout_s if timeout_s is not None else self.timeout_s
        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            binary,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            env=self._env(),
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=limit)
        except TimeoutError:
            # Observed in practice: `-s proteins` search and `head` on a protein
            # both hang. Kill rather than leak the child.
            process.kill()
            with_suppressed = asyncio.shield(process.communicate())
            try:
                await asyncio.wait_for(with_suppressed, timeout=5)
            except (TimeoutError, ProcessLookupError):
                pass
            return CommandResult(
                args=args,
                returncode=-1,
                stdout="",
                stderr=f"timed out after {limit:g}s",
                duration_ms=int((time.monotonic() - started) * 1000),
                timed_out=True,
            )

        return CommandResult(
            args=args,
            returncode=process.returncode if process.returncode is not None else -1,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    # -- cache ------------------------------------------------------------

    def _cache_path(self, key_parts: list[str]) -> Path:
        digest = hashlib.sha256("\x00".join(key_parts).encode("utf-8")).hexdigest()[:24]
        return self.cache_dir / f"{digest}.json"

    def _cache_read(self, key_parts: list[str]) -> Any | None:
        if self.cache_ttl_s <= 0:
            return None
        path = self._cache_path(key_parts)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if time.time() - payload.get("_cached_at", 0) > self.cache_ttl_s:
            return None
        return payload.get("data")

    def _cache_write(self, key_parts: list[str], data: Any) -> None:
        if self.cache_ttl_s <= 0:
            return
        path = self._cache_path(key_parts)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"_cached_at": time.time(), "_key": key_parts, "data": data}),
                encoding="utf-8",
            )
        except OSError:
            # A cache that cannot be written is not an error worth failing on.
            pass

    # -- capability probe --------------------------------------------------

    async def probe(self, *, force: bool = False, ttl_s: float = 300.0) -> Probe:
        async with self._probe_lock:
            cached = self._probe
            if cached and not force and (time.time() - cached.checked_at) < ttl_s:
                return cached

            binary = self.resolve_binary()
            if binary is None:
                probe = Probe(
                    available=False,
                    version=None,
                    account=None,
                    server=None,
                    reachable=False,
                    detail="paperclip CLI not found on PATH or in ~/.local/bin.",
                    checked_at=time.time(),
                )
                self._probe = probe
                return probe

            version_result = await self.run(["--version"], timeout_s=25)
            version = None
            if version_result.ok:
                match = re.search(r"version\s+([\w.\-]+)", version_result.stdout)
                version = match.group(1) if match else version_result.stdout.strip()

            config_result = await self.run(["config"], timeout_s=40)
            account = server = None
            reachable = False
            if config_result.ok:
                text = config_result.stdout
                auth = re.search(r"Auth:\s*[✓✔]\s*(\S+)", text)
                account = auth.group(1) if auth else None
                srv = re.search(r"Server:\s*(\S+)", text)
                server = srv.group(1) if srv else None
                reachable = "server reachable" in text

            if account and reachable:
                detail = f"Signed in as {account}; server reachable."
            elif account:
                detail = f"Signed in as {account}, but the server did not report reachable."
            elif version:
                detail = (
                    "CLI installed but not authenticated. Run `paperclip login`, or set "
                    "PAPERCLIP_API_KEY for non-interactive auth."
                )
            else:
                detail = f"CLI found at {binary} but did not respond to --version."

            probe = Probe(
                available=bool(version) and bool(account) and reachable,
                version=version,
                account=account,
                server=server,
                reachable=reachable,
                detail=detail,
                checked_at=time.time(),
            )
            self._probe = probe
            return probe

    # -- search ------------------------------------------------------------

    async def search(
        self,
        source: str,
        query: str,
        *,
        limit: int = 6,
        timeout_s: float | None = None,
        extra_args: list[str] | None = None,
    ) -> SourceOutcome:
        """One search against one source. Never raises — returns the error."""
        args = ["search", "-s", source, "-n", str(limit), *(extra_args or []), query]
        key = ["search", source, query, str(limit), *(extra_args or [])]

        cached = self._cache_read(key)
        if cached is not None:
            return SourceOutcome(
                source=source,
                query=query,
                hits=[SearchHit(**hit) for hit in cached],
                cache_hit=True,
            )

        result = await self.run(args, timeout_s=timeout_s)
        if not result.ok:
            reason = result.stderr.strip() or result.stdout.strip() or "unknown error"
            return SourceOutcome(
                source=source,
                query=query,
                error=f"{'timeout' if result.timed_out else 'failed'}: {reason[:300]}",
                duration_ms=result.duration_ms,
            )

        match = RESULT_ID.search(result.stdout)
        if match is None:
            head = result.stdout.strip().splitlines()[:1]
            return SourceOutcome(
                source=source,
                query=query,
                error=f"no result id in output: {(head[0] if head else '')[:200]}",
                duration_ms=result.duration_ms,
            )

        try:
            hits = await self._export(match.group(1), query, source, timeout_s=timeout_s)
        except PaperclipError as exc:
            return SourceOutcome(
                source=source, query=query, error=str(exc), duration_ms=result.duration_ms
            )

        self._cache_write(key, [hit.__dict__ for hit in hits])
        return SourceOutcome(source=source, query=query, hits=hits, duration_ms=result.duration_ms)

    async def _export(
        self, result_id: str, query: str, source: str, *, timeout_s: float | None
    ) -> list[SearchHit]:
        """`paperclip results <id> --save <csv>` — the documented export path."""
        with tempfile.TemporaryDirectory(prefix="bioforge-paperclip-") as tmp:
            destination = Path(tmp) / "results.csv"
            result = await self.run(
                ["results", result_id, "--save", str(destination)], timeout_s=timeout_s
            )
            if not result.ok:
                raise PaperclipError(
                    f"export failed: {(result.stderr or result.stdout).strip()[:200]}"
                )
            if not destination.exists():
                raise PaperclipError("export reported success but wrote no file")

            with destination.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                columns = set(reader.fieldnames or [])
                missing = EXPECTED_COLUMNS - columns
                if missing:
                    # The CLI changed its contract; say so rather than guessing.
                    raise PaperclipError(
                        f"unexpected CSV columns from paperclip; missing {sorted(missing)}"
                    )
                return [
                    SearchHit(
                        title=(row.get("title") or "").strip(),
                        authors=(row.get("authors") or "").strip(),
                        doc_id=(row.get("id") or "").strip(),
                        source=(row.get("source") or "").strip(),
                        date=(row.get("date") or "").strip(),
                        url=(row.get("url") or "").strip(),
                        abstract=(row.get("abstract") or "").strip(),
                        rank=index,
                        query=query,
                        paperclip_source=source,
                    )
                    for index, row in enumerate(reader, start=1)
                ]

    # -- protein VFS --------------------------------------------------------

    async def protein_meta(
        self, accession: str, *, timeout_s: float | None = 45.0
    ) -> dict[str, Any] | None:
        """Read `/proteins/<accession>/meta.json`.

        Direct VFS access, because the `-s proteins` *search* was observed to
        time out while this returns in well under a second.
        """
        key = ["protein_meta", accession]
        cached = self._cache_read(key)
        if cached is not None:
            return cached

        result = await self.run(["cat", f"/proteins/{accession}/meta.json"], timeout_s=timeout_s)
        if not result.ok:
            return None
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            # The CLI appends a timing footer on some commands; take the object.
            start = result.stdout.find("{")
            end = result.stdout.rfind("}")
            if start == -1 or end == -1:
                return None
            try:
                payload = json.loads(result.stdout[start : end + 1])
            except json.JSONDecodeError:
                return None
        payload.pop("_timing", None)
        self._cache_write(key, payload)
        return payload

    # -- fan-out ------------------------------------------------------------

    async def search_many(
        self, plans: list[tuple[str, str, int]], *, timeout_s: float | None = None
    ) -> list[SourceOutcome]:
        """Run (source, query, limit) triples concurrently.

        Concurrency is the point: four sequential searches against a remote
        service is most of a demo's runtime budget.
        """
        return list(
            await asyncio.gather(
                *(
                    self.search(source, query, limit=limit, timeout_s=timeout_s)
                    for source, query, limit in plans
                )
            )
        )
