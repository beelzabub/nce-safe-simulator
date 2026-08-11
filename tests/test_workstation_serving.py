"""Tests for serving the app from a development workstation over HTTPS.

The workstation has no DNS name of its own — it is reached by its Elastic IP —
so it needs a different bring-up from the live site. Two failures here are
silent rather than loud, and both are what these tests pin:

- ``redeploy.sh`` publishes no ports by design (Caddy owns 80/443 and reaches
  the app over the Docker network). Run on a box that never had a first-time
  bring-up, it used to create an app container reachable from nothing and then
  print "Live at https://nce-safe-sim.com" — a live site on another machine.
  "Caddy untouched" and "Caddy absent" printed identically.
- A TLS client connecting to a bare IP sends no SNI, because the extension
  carries a name and an address literal has none. Without ``default_sni`` Caddy
  matches no site, presents no certificate, and aborts the handshake before any
  HTTP — so dropping that one line breaks HTTPS on the box completely.
"""
import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REDEPLOY = REPO_ROOT / "scripts" / "redeploy.sh"
DEPLOY_LOCAL = REPO_ROOT / "scripts" / "deploy-local.sh"
CADDYFILE_WS = REPO_ROOT / "deploy" / "Caddyfile.workstation"
CADDYFILE_LIVE = REPO_ROOT / "deploy" / "Caddyfile"


def _stub(tmp_path, name, body):
    """Drop a fake executable on PATH and return an env that finds it first."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    exe = bindir / name
    exe.write_text("#!/bin/sh\n" + body + "\n")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    env = dict(os.environ)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    return env


class TestRedeployRequiresAReverseProxy:
    """redeploy.sh must refuse to run where nothing can serve what it deploys."""

    def test_aborts_when_no_caddy_container_exists(self, tmp_path):
        # `docker inspect caddy` failing is exactly how a box that never had a
        # first-time bring-up looks.
        env = _stub(tmp_path, "docker", "exit 1")
        result = subprocess.run(
            [str(REDEPLOY)], capture_output=True, text=True,
            env=env, cwd=str(REPO_ROOT),
        )
        assert result.returncode == 1
        assert "no 'caddy' container" in result.stderr
        # It has to say what to run instead, in both topologies.
        assert "deploy-local.sh" in result.stderr
        assert "--workstation" in result.stderr

    def test_aborts_before_building_the_image(self, tmp_path):
        """The guard is worthless at the bottom: a full build then a refusal.

        Ordering is the whole point, so assert the build never started rather
        than just that the exit code was non-zero.
        """
        marker = tmp_path / "build-ran"
        env = _stub(
            tmp_path, "docker",
            f'case "$1" in build) touch {marker} ;; esac\nexit 1',
        )
        result = subprocess.run(
            [str(REDEPLOY)], capture_output=True, text=True,
            env=env, cwd=str(REPO_ROOT),
        )
        assert result.returncode == 1
        assert not marker.exists(), "redeploy.sh built an image before refusing"


class TestWorkstationCaddyfile:
    """The bare-IP TLS config, whose failure mode is a dead handshake."""

    def test_sets_default_sni(self):
        # Without this, https://<ip>/ fails for curl and every browser alike.
        assert "default_sni" in CADDYFILE_WS.read_text()

    def test_uses_an_internal_ca_not_public_acme(self):
        text = CADDYFILE_WS.read_text()
        assert "tls internal" in text
        # A public issuer here would need 443 reachable by the CA's validators
        # on every renewal, which the admin-CIDR security group forbids. Check
        # directives only — the comments discuss ACME precisely to explain why
        # it is not used.
        directives = [
            line for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        assert not any("acme" in line.lower() for line in directives)

    def test_proxies_to_the_app_container_over_the_docker_network(self):
        assert "reverse_proxy nce-safe-sim:8080" in CADDYFILE_WS.read_text()

    def test_restricts_access_by_source_cidr(self):
        text = CADDYFILE_WS.read_text()
        assert "remote_ip" in text and "403" in text

    def test_live_site_config_is_left_alone(self):
        """The live box shares this repo — its Caddyfile must stay public-ACME."""
        text = CADDYFILE_LIVE.read_text()
        assert "nce-safe-sim.com" in text
        assert "tls internal" not in text


class TestDeployLocalWorkstationMode:
    def test_fails_clearly_when_the_public_ip_cannot_be_found(self, tmp_path):
        """No IMDS and no override is a stop, not a box serving on ''."""
        env = _stub(tmp_path, "curl", "exit 1")
        env.pop("NCE_SITE_ADDR", None)
        result = subprocess.run(
            [str(DEPLOY_LOCAL), "--workstation"], capture_output=True, text=True,
            env=env, cwd=str(REPO_ROOT),
        )
        assert result.returncode == 1
        assert "public IP" in result.stderr
        assert "NCE_SITE_ADDR" in result.stderr

    def test_workstation_mode_serves_the_workstation_caddyfile(self):
        text = DEPLOY_LOCAL.read_text()
        assert "deploy/Caddyfile.workstation" in text

    def test_workstation_mode_publishes_only_443(self):
        """:80 exists only to answer public ACME challenges, which this box has
        none of — leaving it published would open a port the SG then has to
        justify. The live default keeps :80, so assert on the override the
        workstation branch installs rather than on the file as a whole.
        """
        text = DEPLOY_LOCAL.read_text()
        assert "CADDY_PORTS=(-p 80:80 -p 443:443)" in text, "live default changed"
        assert "CADDY_PORTS=(-p 443:443)" in text, "workstation override missing"
        # The override must come after the default, or it never takes effect.
        assert text.index("CADDY_PORTS=(-p 443:443)") > text.index(
            "CADDY_PORTS=(-p 80:80 -p 443:443)"
        )
