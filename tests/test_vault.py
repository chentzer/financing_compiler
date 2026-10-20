import json
import shutil
import subprocess
from pathlib import Path

import pytest

from fincomp import vault as V

PW = {"tng": "made-up-1", "aeon_credit": "made-up-2"}


def test_round_trip_and_format():
    blob = V.seal(PW, "123456")
    assert set(blob) == {"v", "kdf", "iterations", "salt", "iv", "data"}
    assert blob["kdf"] == "PBKDF2-SHA256" and blob["iterations"] == 600_000
    assert "made-up" not in json.dumps(blob)  # nothing readable leaves the device
    assert V.open_vault(blob, "123456") == PW


def test_wrong_pin():
    with pytest.raises(V.WrongPin):
        V.open_vault(V.seal(PW, "123456"), "654321")


def test_salted_fresh_each_new_pin_and_iv_each_save():
    a, b = V.seal(PW, "123456"), V.seal(PW, "123456")
    assert a["salt"] != b["salt"]  # same PIN, different salt: no precomputed attacks
    assert a["data"] != b["data"]
    again = V.seal(PW, "123456", salt=V.salt_of(a))  # re-save under the same PIN
    assert again["salt"] == a["salt"] and again["iv"] != a["iv"]


ROOT = Path(__file__).resolve().parents[1]
NODE_SCRIPT = r"""
const v = await import(process.argv[1]);
const [mode, pin, input] = process.argv.slice(2);
if (mode === 'seal') {
  const salt = v.newSalt();
  const key = await v.deriveKey(pin, salt);
  console.log(JSON.stringify(await v.seal(JSON.parse(input), key, salt)));
} else {
  const blob = JSON.parse(input);
  const key = await v.deriveKey(pin, v.saltOf(blob), blob.iterations);
  console.log(JSON.stringify(await v.open(blob, key)));
}
"""


def node(mode: str, pin: str, data: str) -> str:
    vault_ts = (ROOT / "web" / "src" / "data" / "vault.ts").as_uri()
    out = subprocess.run(
        ["node", "--input-type=module", "-e", NODE_SCRIPT, vault_ts, mode, pin, data],
        capture_output=True, text=True, timeout=60,
    )
    if out.returncode != 0:
        pytest.skip(f"this Node can't run vault.ts: {out.stderr.strip()[:120]}")
    return out.stdout.strip()


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_web_app_and_cli_read_each_others_vault():
    from_web = json.loads(node("seal", "246810", json.dumps(PW)))
    assert V.open_vault(from_web, "246810") == PW
    from_cli = V.seal(PW, "246810")
    assert json.loads(node("open", "246810", json.dumps(from_cli))) == PW
