"""Local-only static onboarding page for the pending-live SSH pack (M3 slice 2).

This module is a pure file writer. It never opens a network connection,
starts a child process, retrieves a URL, or runs JavaScript: the page is
static HTML with inline CSS, meant to be opened from disk (``file://``) by
the operator who owns the pack. It is an onboarding checklist foundation,
not a public service and not a live proof. The full host-key body is never
rendered; only the key type is shown (compare the pinned value in
STATUS.json).
"""

from __future__ import annotations

import html
from pathlib import Path

from llm_research_os.execution.errors import NativeSshError
from llm_research_os.execution.native_ssh import (
    NativeSshTarget,
    authorized_keys_fragment,
    ssh_config_fragment,
)

ONBOARDING_PAGE_NAME = "ONBOARDING.html"


def write_onboarding_page(
    output: Path,
    target: NativeSshTarget,
    *,
    project_id: str,
    source: str,
) -> str:
    """Render the static onboarding page into an existing pack directory."""

    if type(target) is not NativeSshTarget:
        raise NativeSshError("ssh onboarding target is invalid", code="ssh-target-invalid")
    if not isinstance(output, Path):
        raise NativeSshError("ssh onboarding output is invalid", code="ssh-output-invalid")
    if output.is_symlink():
        raise NativeSshError("ssh onboarding output is invalid", code="ssh-output-invalid")
    if not output.is_dir():
        raise NativeSshError("ssh onboarding output is invalid", code="ssh-output-invalid")
    page = output / ONBOARDING_PAGE_NAME
    page.write_text(
        _render_page(target, project_id=project_id, source=source),
        encoding="utf-8",
    )
    return ONBOARDING_PAGE_NAME


def _render_page(target: NativeSshTarget, *, project_id: str, source: str) -> str:
    host = html.escape(target.host, quote=True)
    user = html.escape(target.user, quote=True)
    workdir = html.escape(target.workdir, quote=True)
    profile = html.escape(target.profile, quote=True)
    project = html.escape(project_id, quote=True)
    origin = html.escape(source, quote=True)
    key_type = html.escape(target.host_key.split(":", 1)[0], quote=True)
    config = html.escape(ssh_config_fragment(target), quote=False)
    authorized = html.escape(authorized_keys_fragment(target.profile), quote=False)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Native SSH onboarding (pending-live) — local checklist</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 46rem;
  padding: 0 1rem; color: #1a1a1a; }}
.banner {{ border: 2px solid #8a6d00; background: #fff8e1; padding: 1rem; }}
pre {{ background: #f4f4f4; padding: 1rem; overflow-x: auto; }}
table {{ border-collapse: collapse; }} td, th {{ border: 1px solid #999;
  padding: 0.25rem 0.5rem; text-align: left; }}
footer {{ margin-top: 2rem; font-size: 0.85rem; color: #555; }}
</style>
</head>
<body>
<div class="banner" role="note">
<strong>Local pending-live checklist.</strong> This page never contacts a host,
runs no script, and proves no second machine. Live steps stay pending until a
researcher provisions one. It is not a public service.
</div>
<h1>Native SSH onboarding (pending-live)</h1>
<h2>Status</h2>
<table>
<tr><th>Field</th><th>Value</th></tr>
<tr><td>Transport</td><td>ssh-pending</td></tr>
<tr><td>Live status</td><td>pending-live</td></tr>
<tr><td>Second host</td><td>not-provisioned</td></tr>
<tr><td>Profile</td><td>{profile}</td></tr>
<tr><td>Host</td><td>{host}</td></tr>
<tr><td>Port</td><td>{target.port}</td></tr>
<tr><td>User</td><td>{user}</td></tr>
<tr><td>Workdir</td><td>{workdir}</td></tr>
<tr><td>Host key type</td><td>{key_type}</td></tr>
<tr><td>Project</td><td>{project}</td></tr>
<tr><td>Source</td><td>{origin}</td></tr>
</table>
<h2>Steps</h2>
<details open>
<summary>1. Generate a dedicated key on the operator machine</summary>
<pre>ssh-keygen -t ed25519 -f ~/.ssh/researchos_native_ed25519 -C researchos-native</pre>
<p>Never copy the private key into this pack or the repository.</p>
</details>
<details>
<summary>2. Pin the host key before first use</summary>
<pre>ssh-keyscan -t ed25519 -p {target.port} {host} | tee known_hosts.native</pre>
<p>Compare the output with the pinned <code>hostKey</code> in STATUS.json.
Only the key type is shown here. Abort on mismatch.</p>
</details>
<details>
<summary>3. Provision the isolated workdir and restricted key prefix</summary>
<p>Append <code>authorized_keys.fragment</code> for the dedicated public key
only. Keep the <code>command=</code> prefix and all <code>no-*</code> options.</p>
<pre>{authorized}</pre>
</details>
<details>
<summary>4. Copy the client fragment and connect once in batch mode</summary>
<pre>{config}</pre>
<pre>ssh -F ssh_config.fragment researchos-native true</pre>
</details>
<details>
<summary>5. Run acceptance, then stop</summary>
<p>SSH transport execution stays <code>ssh-transport-not-implemented</code>.
<code>researchos native run --transport ssh</code> must fail closed. Do not
treat onboarding as a live run.</p>
</details>
<footer>Generated locally by the pack writer. Open from disk only; this page
makes no network requests and collects nothing.</footer>
</body>
</html>
"""
