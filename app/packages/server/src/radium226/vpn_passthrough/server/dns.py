from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from ._run import run
from .namespace import Namespace


class DNS:
    @staticmethod
    @asynccontextmanager
    async def setup(namespace: Namespace, nameservers: list[str] | None = None) -> AsyncIterator[None]:
        if nameservers is None:
            nameservers = ["1.1.1.1"]
        resolv_file_path = namespace.directory / "resolv.conf"
        resolv_file_path.write_text(
            "# Created by VPN PassThrough\n\n"
            + "".join(f"nameserver {ns}\n" for ns in nameservers)
        )

        # Use only files + dns for hosts resolution — strips mdns/resolve/myhostname
        # which could bypass the VPN tunnel and leak DNS queries to the host.
        nsswitch_file_path = namespace.directory / "nsswitch.conf"
        nsswitch_file_path.write_text(
            "# Created by VPN PassThrough\n\n"
            "passwd:   files\n"
            "group:    files\n"
            "shadow:   files\n"
            "hosts:    files dns\n"
            "networks: files\n"
            "protocols: files\n"
            "services: files\n"
        )

        # Ensure /etc/resolv.conf exists as a real file (or valid symlink target) on the
        # HOST before bind-mounting inside the namespace.  We must NOT unlink from within
        # a namespace subprocess: /etc is a shared filesystem, so unlink() there would
        # delete the host's file too (mount namespaces only isolate mount operations, not
        # raw filesystem calls).
        etc_resolv = Path("/etc/resolv.conf")
        if etc_resolv.is_symlink() and not etc_resolv.exists():
            # Broken symlink: remove it and leave a real file so mount --bind has a target.
            etc_resolv.unlink()
            etc_resolv.touch()
        elif not etc_resolv.exists():
            etc_resolv.touch()

        # /etc/nsswitch.conf is always a regular file, no symlink handling needed.
        etc_nsswitch = Path("/etc/nsswitch.conf")
        if not etc_nsswitch.exists():
            etc_nsswitch.touch()

        # mount --bind follows symlinks on its own, so no special handling is needed for
        # the normal case (/etc/resolv.conf -> /run/systemd/resolve/stub-resolv.conf).
        # The resulting mount entries live in the namespace's private mount table.
        await run(
            ["mount", "--bind", str(resolv_file_path.resolve()), "/etc/resolv.conf"],
            check=True,
            preexec_fn=namespace.enter,
        )
        await run(
            ["mount", "--bind", str(nsswitch_file_path.resolve()), "/etc/nsswitch.conf"],
            check=True,
            preexec_fn=namespace.enter,
        )

        try:
            yield
        finally:
            resolv_file_path.unlink(missing_ok=True)
            nsswitch_file_path.unlink(missing_ok=True)
